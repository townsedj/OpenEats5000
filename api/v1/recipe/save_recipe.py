#!/usr/bin/env python
# encoding: utf-8

from django.db.models import Count
from django.core.exceptions import FieldDoesNotExist
from rest_framework.exceptions import ParseError

from v1.recipe.models import Recipe, SubRecipe
from v1.recipe_groups.models import Tag, Course, Cuisine
from v1.ingredient.models import IngredientGroup, Ingredient


def normalise(title):
    """Key used to recognise the same group or ingredient across an edit."""
    return (title or '').strip().lower()


class Validators(object):
    def __init__(self, partial=False):
        self.partial = partial

    def required(self, item):
        if not self.partial:
            return None if item else "This item is required."
        return None

    def is_digit(self, item):
        # None is allowed outright: prep_time and cook_time are optional now,
        # so a missing value must not fail on int(None).
        if item is None:
            return None
        try:
            int(item)
        except:
            return "This item must be a number."
        return None


class SaveRecipe(Validators):
    def __init__(self, data, author, partial=False, household=None):
        super(SaveRecipe, self).__init__(partial=partial)

        # Extract the data from data for use in the saving process
        self.author = author
        self.household = household
        self.data = data

        # Remove bad fields from the data
        self._clean_data()

        # Check the data from any errors
        self._validate()

        # Remove the complex data objects from processing
        self.tags = self.data.pop('tags', None)
        self.course = self.data.pop('course', None)
        self.cuisine = self.data.pop('cuisine', None)
        self.subrecipes = self.data.pop('subrecipes', None)
        self.ingredients = self.data.pop('ingredient_groups', None)

    def _save_course(self):
        """
        Add the Course instance to the self.data dict for use when we save the recipe
        If the Course does not exist create a new one.
        """
        if self.course:
            # Lookup the course by ID. If the ID isn't there, lookup by title
            # if that isn't found, create it.
            if self.course.get('id'):
                self.data['course'] = Course.objects.get(id=self.course.get('id'))
            elif self.course.get('title'):
                self.data['course'], created = Course.objects.get_or_create(
                    title=self.course.get('title'),
                    defaults={'author': self.author},
                )

    def _save_cuisine(self):
        """
        Add the Cuisine instance to the self.data dict for use when we save the recipe.
        If the Cuisine does not exist create a new one.
        """
        if self.cuisine:
            # Lookup the cuisine by ID. If the ID isn't there, lookup by title
            # if that isn't found, create it.
            if self.cuisine.get('id'):
                self.data['cuisine'] = Cuisine.objects.get(id=self.cuisine.get('id'))
            elif self.cuisine.get('title'):
                self.data['cuisine'], created = Cuisine.objects.get_or_create(
                    title=self.cuisine.get('title'),
                    defaults={'author': self.author},
                )

    @staticmethod
    def _delete_recipe_groups():
            # Check to see if we have any Cuisines or Courses with no recipes associated with them.
            # Id we do, delete them.
            Cuisine.objects.all().annotate(total=Count('recipe', distinct=True)).filter(total=0).delete()
            Course.objects.all().annotate(total=Count('recipe', distinct=True)).filter(total=0).delete()

    def _save_tags(self, recipe):
        """
        Reconcile the posted tags with the ones already on the recipe.

        Only the difference is written. The old version removed every tag and
        added them all back, which churned the join table on every save.
        """
        if self.tags is None:
            return

        wanted = {}
        for tag in self.tags:
            title = (tag.get('title') or '').strip()
            if title:
                wanted[normalise(title)] = title

        existing = {normalise(tag.title): tag for tag in recipe.tags.all()}

        for key, tag in existing.items():
            if key not in wanted:
                recipe.tags.remove(tag)

        for key, title in wanted.items():
            if key not in existing:
                obj, created = Tag.objects.get_or_create(title=title)
                recipe.tags.add(obj)

    def _save_ingredient_data(self, recipe):
        """
        Reconcile the posted ingredient groups with the rows already there.

        This used to delete every group and every ingredient and recreate
        them from the payload. That was invisible while an Ingredient held
        nothing but what the form sent, but ingredients are about to carry a
        matched USDA food, a gram weight and manual corrections to both --
        and a save would then have silently thrown all of it away.

        Rows are matched by id when the client sends one, else by normalised
        title within the recipe, so an edit that only reorders a group or
        fixes its spelling keeps the ingredient rows underneath it.
        """
        if self.ingredients is None:
            return

        # Across the whole recipe, not per group: an ingredient dragged into
        # another group should keep its row, and its matched food with it.
        rows_by_id = {
            row.id: row
            for row in Ingredient.objects.filter(ingredient_group__recipe=recipe)
        }
        groups_by_title = {
            normalise(group.title): group
            for group in recipe.ingredient_groups.all()
        }

        kept_group_ids = []
        kept_ingredient_ids = []

        for payload in self.ingredients:
            title = payload.get('title')
            group = groups_by_title.get(normalise(title))
            if group is None:
                group = IngredientGroup.objects.create(recipe=recipe, title=title)
                groups_by_title[normalise(title)] = group
            elif group.title != title:
                group.title = title
                group.save(update_fields=['title'])
            kept_group_ids.append(group.id)

            kept_ingredient_ids += self._save_ingredients(
                group,
                payload.get('ingredients') or [],
                rows_by_id,
                already_kept=kept_ingredient_ids,
            )

        # Anything the payload no longer mentions goes.
        Ingredient.objects.filter(
            ingredient_group__recipe=recipe
        ).exclude(id__in=kept_ingredient_ids).delete()
        recipe.ingredient_groups.exclude(id__in=kept_group_ids).delete()

    @staticmethod
    def _save_ingredients(group, rows, rows_by_id, already_kept):
        """Update, create and keep track of one group's ingredient rows."""
        writable = {
            field.name for field in Ingredient._meta.get_fields()
            if getattr(field, 'concrete', False)
        } - {'id', 'ingredient_group'}

        # Rows of this group not yet claimed, by title, so an ingredient the
        # client sent without an id still finds its way home.
        unclaimed_by_title = {}
        for row in group.ingredients.all():
            if row.id not in already_kept:
                unclaimed_by_title.setdefault(normalise(row.title), []).append(row)

        kept = []
        for payload in rows:
            payload = dict(payload)
            row_id = payload.pop('id', None)

            ingredient = None
            if row_id is not None and str(row_id).isdigit():
                candidate = rows_by_id.get(int(row_id))
                if candidate is not None and candidate.id not in already_kept \
                        and candidate.id not in kept:
                    ingredient = candidate
            if ingredient is None:
                candidates = unclaimed_by_title.get(normalise(payload.get('title')), [])
                while candidates:
                    candidate = candidates.pop(0)
                    if candidate.id not in already_kept and candidate.id not in kept:
                        ingredient = candidate
                        break
            if ingredient is None:
                ingredient = Ingredient()

            for field, value in payload.items():
                if field in writable:
                    setattr(ingredient, field, value)
            ingredient.ingredient_group = group
            ingredient.save()
            kept.append(ingredient.id)

        return kept

    def _save_subrecipe_data(self, recipe):
        if self.subrecipes:
            for subrecipe in SubRecipe.objects.filter(parent_recipe=recipe):
                subrecipe.delete()

            for subrecipe in self.subrecipes:
                if subrecipe.get('title'):
                    child_recipe = Recipe.objects.filter(title=subrecipe.get('title', '')).first()
                    if recipe:
                        obj = SubRecipe.objects.create(
                            numerator=subrecipe.get('numerator', 0),
                            denominator=subrecipe.get('denominator', 1),
                            measurement=subrecipe.get('measurement', ''),
                            child_recipe=child_recipe,
                            parent_recipe=recipe
                        )
                        obj.save()

    def _clean_data(self):
        """
        Clean up the data before we try and save it into the Recipe model.
        Remove fields that are not part of the model or should not be saved.
        """
        # `household` is in this list for a reason: it is a real model field,
        # so the loop below would happily keep it and a caller could file a
        # recipe under another house. It comes from the request user only.
        for key in ['author', 'id', 'slug', 'household']:
            self.data.pop(key) if self.data.get(key) is not None else None
        keys = []
        for key, value in self.data.items():
            try:
                Recipe._meta.get_field(key)
            except FieldDoesNotExist:
                keys.append(key)
        for key in keys:
            self.data.pop(key)

    def _validate(self):
        fields = {
            "title": [self.required],
            "directions": [self.required],

            "servings": [self.required, self.is_digit],

            # Optional: a pasted recipe should save without them.
            "prep_time": [self.is_digit],
            "cook_time": [self.is_digit],

            "ingredient_groups": [self.required],
        }

        errors = {}
        for key, validators in fields.items():
            for validator in validators:
                error = validator(self.data.get(key))
                if error:
                    errors[key] = [error]
                    # Only send one error at a time
                    break

        if len(errors) > 0:
            raise ParseError(errors)

    def update(self, instance):
        """ Update and return a new `Recipe` instance, given the validated data """
        self._save_course()
        self._save_cuisine()
        for attr, value in self.data.items():
            setattr(instance, attr, value)
        # Saved before the related rows, not after: _save_ingredient_data now
        # reads the recipe's existing groups, so the instance has to be in the
        # database first.
        instance.save()
        self._save_ingredient_data(instance)
        self._save_subrecipe_data(instance)
        self._save_tags(instance)

        self._delete_recipe_groups()

        return instance

    def create(self):
        """ Create and return a new `Recipe` instance, given the validated data """
        self._save_course()
        self._save_cuisine()
        recipe = Recipe.objects.create(
            author=self.author,
            household=self.household,
            **self.data
        )
        self._save_ingredient_data(recipe)
        self._save_subrecipe_data(recipe)
        self._save_tags(recipe)
        self._delete_recipe_groups()

        return recipe
