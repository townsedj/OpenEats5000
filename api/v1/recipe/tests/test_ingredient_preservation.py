#!/usr/bin/env python
# encoding: utf-8

from django.contrib.auth.models import User
from django.test import TestCase

from v1.household.models import Household
from v1.ingredient.models import Ingredient
from v1.recipe.models import Recipe
from v1.recipe.save_recipe import SaveRecipe


class IngredientPreservationTests(TestCase):
    """
    Editing a recipe used to delete every ingredient row and recreate it.

    That was invisible while an Ingredient held nothing but what the form
    sent. It stops being invisible the moment ingredients carry a matched
    food, a gram weight and corrections to either -- a save would throw all
    of it away. These tests pin the rows down by primary key, which is the
    only thing that proves the row survived rather than being replaced by an
    identical one.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.household.members.add(self.user)

        self.recipe = self.save({
            'title': 'Tasty Chili',
            'directions': 'Cook it.',
            'servings': 8,
            'ingredient_groups': [
                {
                    'title': 'Veges',
                    'ingredients': [
                        {'title': 'white onion', 'numerator': 1, 'denominator': 1,
                         'measurement': 'whole'},
                        {'title': 'chili powder', 'numerator': 4, 'denominator': 1,
                         'measurement': 'tablespoons'},
                    ],
                },
                {
                    'title': 'Beef',
                    'ingredients': [
                        {'title': 'ground pork', 'numerator': 1, 'denominator': 1,
                         'measurement': 'pound'},
                    ],
                },
            ],
        })

    def save(self, data):
        return SaveRecipe(data, self.user, household=self.household).create()

    def update(self, data):
        return SaveRecipe(
            data, self.user, household=self.household
        ).update(Recipe.objects.get(pk=self.recipe.pk))

    def ids_by_title(self):
        return {
            row.title: row.id
            for row in Ingredient.objects.filter(ingredient_group__recipe=self.recipe)
        }

    def payload(self, groups):
        return {
            'title': 'Tasty Chili',
            'directions': 'Cook it.',
            'servings': 8,
            'ingredient_groups': groups,
        }

    def test_editing_the_title_keeps_every_ingredient_row(self):
        before = self.ids_by_title()

        self.update(self.payload([
            {
                'title': 'Veges',
                'ingredients': [
                    {'title': 'white onion', 'numerator': 1, 'denominator': 1,
                     'measurement': 'whole'},
                    {'title': 'chili powder', 'numerator': 4, 'denominator': 1,
                     'measurement': 'tablespoons'},
                ],
            },
            {
                'title': 'Beef',
                'ingredients': [
                    {'title': 'ground pork', 'numerator': 1, 'denominator': 1,
                     'measurement': 'pound'},
                ],
            },
        ]))

        self.assertEqual(self.ids_by_title(), before)

    def test_a_row_sent_with_its_id_is_updated_in_place(self):
        before = self.ids_by_title()

        self.update(self.payload([
            {
                'title': 'Veges',
                'ingredients': [
                    {'id': before['white onion'], 'title': 'red onion',
                     'numerator': 2, 'denominator': 1, 'measurement': 'whole'},
                    {'title': 'chili powder', 'numerator': 4, 'denominator': 1,
                     'measurement': 'tablespoons'},
                ],
            },
            {
                'title': 'Beef',
                'ingredients': [
                    {'title': 'ground pork', 'numerator': 1, 'denominator': 1,
                     'measurement': 'pound'},
                ],
            },
        ]))

        row = Ingredient.objects.get(pk=before['white onion'])
        self.assertEqual(row.title, 'red onion')
        self.assertEqual(row.numerator, 2)

    def test_renaming_a_group_keeps_its_ingredients(self):
        before = self.ids_by_title()

        self.update(self.payload([
            {
                'title': 'Veges',
                'ingredients': [
                    {'id': before['white onion'], 'title': 'white onion',
                     'numerator': 1, 'denominator': 1, 'measurement': 'whole'},
                    {'id': before['chili powder'], 'title': 'chili powder',
                     'numerator': 4, 'denominator': 1, 'measurement': 'tablespoons'},
                ],
            },
            {
                'title': 'Meat',  # was "Beef"
                'ingredients': [
                    {'id': before['ground pork'], 'title': 'ground pork',
                     'numerator': 1, 'denominator': 1, 'measurement': 'pound'},
                ],
            },
        ]))

        self.assertEqual(self.ids_by_title()['ground pork'], before['ground pork'])
        self.assertEqual(
            sorted(
                self.recipe.ingredient_groups.values_list('title', flat=True)
            ),
            ['Meat', 'Veges'],
        )

    def test_moving_an_ingredient_between_groups_keeps_its_row(self):
        """
        Matched by id across the whole recipe, not within one group, so a
        drag from one group to another keeps the food match underneath it.
        """
        before = self.ids_by_title()

        self.update(self.payload([
            {
                'title': 'Veges',
                'ingredients': [
                    {'id': before['chili powder'], 'title': 'chili powder',
                     'numerator': 4, 'denominator': 1, 'measurement': 'tablespoons'},
                ],
            },
            {
                'title': 'Beef',
                'ingredients': [
                    {'id': before['ground pork'], 'title': 'ground pork',
                     'numerator': 1, 'denominator': 1, 'measurement': 'pound'},
                    {'id': before['white onion'], 'title': 'white onion',
                     'numerator': 1, 'denominator': 1, 'measurement': 'whole'},
                ],
            },
        ]))

        row = Ingredient.objects.get(pk=before['white onion'])
        self.assertEqual(row.ingredient_group.title, 'Beef')

    def test_a_removed_ingredient_is_deleted(self):
        before = self.ids_by_title()

        self.update(self.payload([
            {
                'title': 'Veges',
                'ingredients': [
                    {'id': before['white onion'], 'title': 'white onion',
                     'numerator': 1, 'denominator': 1, 'measurement': 'whole'},
                ],
            },
            {
                'title': 'Beef',
                'ingredients': [
                    {'id': before['ground pork'], 'title': 'ground pork',
                     'numerator': 1, 'denominator': 1, 'measurement': 'pound'},
                ],
            },
        ]))

        self.assertFalse(
            Ingredient.objects.filter(pk=before['chili powder']).exists()
        )
        self.assertEqual(len(self.ids_by_title()), 2)

    def test_a_removed_group_is_deleted_with_its_ingredients(self):
        before = self.ids_by_title()

        self.update(self.payload([
            {
                'title': 'Veges',
                'ingredients': [
                    {'id': before['white onion'], 'title': 'white onion',
                     'numerator': 1, 'denominator': 1, 'measurement': 'whole'},
                    {'id': before['chili powder'], 'title': 'chili powder',
                     'numerator': 4, 'denominator': 1, 'measurement': 'tablespoons'},
                ],
            },
        ]))

        self.assertEqual(self.recipe.ingredient_groups.count(), 1)
        self.assertFalse(
            Ingredient.objects.filter(pk=before['ground pork']).exists()
        )

    def test_a_new_ingredient_is_created(self):
        before = self.ids_by_title()

        self.update(self.payload([
            {
                'title': 'Veges',
                'ingredients': [
                    {'id': before['white onion'], 'title': 'white onion',
                     'numerator': 1, 'denominator': 1, 'measurement': 'whole'},
                    {'id': before['chili powder'], 'title': 'chili powder',
                     'numerator': 4, 'denominator': 1, 'measurement': 'tablespoons'},
                    {'title': 'cumin', 'numerator': 1, 'denominator': 1,
                     'measurement': 'tablespoon'},
                ],
            },
            {
                'title': 'Beef',
                'ingredients': [
                    {'id': before['ground pork'], 'title': 'ground pork',
                     'numerator': 1, 'denominator': 1, 'measurement': 'pound'},
                ],
            },
        ]))

        after = self.ids_by_title()
        self.assertIn('cumin', after)
        self.assertEqual(after['white onion'], before['white onion'])

    def test_tags_are_only_changed_where_they_differ(self):
        recipe = self.save({
            'title': 'Another',
            'directions': 'Cook it.',
            'servings': 2,
            'tags': [{'title': 'quick'}, {'title': 'spicy'}],
            'ingredient_groups': [
                {'title': '', 'ingredients': [
                    {'title': 'salt', 'numerator': 1, 'denominator': 1},
                ]},
            ],
        })
        kept = recipe.tags.get(title='quick')

        SaveRecipe({
            'title': 'Another',
            'directions': 'Cook it.',
            'servings': 2,
            'tags': [{'title': 'quick'}, {'title': 'cheap'}],
            'ingredient_groups': [
                {'title': '', 'ingredients': [
                    {'title': 'salt', 'numerator': 1, 'denominator': 1},
                ]},
            ],
        }, self.user, household=self.household).update(recipe)

        self.assertEqual(
            sorted(recipe.tags.values_list('title', flat=True)),
            ['cheap', 'quick'],
        )
        self.assertEqual(recipe.tags.get(title='quick').pk, kept.pk)

    def test_a_caller_cannot_file_a_recipe_under_another_household(self):
        """
        `household` is a real model field, so _clean_data has to drop it or
        the generic "is this a model field" loop would keep whatever the
        client sent.
        """
        theirs = Household.objects.create(name='Next door')

        recipe = self.save({
            'title': 'Mine',
            'directions': 'Cook it.',
            'servings': 2,
            'household': theirs.id,
            'ingredient_groups': [
                {'title': '', 'ingredients': [
                    {'title': 'salt', 'numerator': 1, 'denominator': 1},
                ]},
            ],
        })

        self.assertEqual(recipe.household, self.household)
