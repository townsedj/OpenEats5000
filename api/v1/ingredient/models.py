#!/usr/bin/env python
# encoding: utf-8

from django.db import models
from django.utils.translation import gettext_lazy as _

from v1.recipe.models import Recipe


class IngredientGroup(models.Model):
    """
    Django Model to hold an Ingredient Groups.
    Ingredient Groups share a many to one relationship.
    Meaning each Recipe will have many Ingredient Groups.
    :title: = Title of the Ingredient Group (EX: Cheddar Biscuits)
    """
    title = models.CharField(_('title'), max_length=150, null=True, blank=True)
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='ingredient_groups')

    class Meta:
        ordering = ['id']
        unique_together = ('title', 'recipe')

    def __str__(self):
        return '%s' % self.title


class Ingredient(models.Model):
    """
    Django Model to hold an Ingredient.
    Ingredients share a many to one relationship.
    Meaning each Ingredient Group will have many Ingredients.
    :title: = Title of the Ingredient (EX: Flour)
    :numerator: = Numerator of the quantity expressed as a fraction
    :denominator: = Denominator of the quantity expressed as a fraction
    :measurement: = Measurement of the Ingredient (EX: Liters, Cups, Grams, tablespoons)
    :quantity: = Amount of the Ingredient Needed (EX: 200, 15, 2)
    :food: = The USDA food this line was matched to, which is what makes the
             recipe's nutrition computable.
    :grams: = What this line weighs, resolved from a FoodPortion or entered
              by hand. Nutrient amounts are per 100 g, so without grams a
              match is useless.
    :match_confidence: = How much to trust the match. Low-confidence lines
                         are what the recipe screen offers up for fixing.
    :match_source: = Whether a person corrected it. A manual match must
                     never be overwritten by a later automatic one -- and
                     this is the data that SaveRecipe used to delete and
                     recreate on every edit.
    """

    class Confidence(models.TextChoices):
        HIGH = 'high', _('high')
        MEDIUM = 'medium', _('medium')
        LOW = 'low', _('low')

    class MatchSource(models.TextChoices):
        AUTO = 'auto', _('matched automatically')
        MANUAL = 'manual', _('set by hand')

    title = models.CharField(_('title'), max_length=250)
    numerator = models.FloatField(_('numerator'), default=0)
    denominator = models.FloatField(_('denominator'), default=1)
    measurement = models.CharField(_('measurement'), max_length=200, blank=True, null=True)
    ingredient_group = models.ForeignKey(IngredientGroup, on_delete=models.CASCADE, related_name='ingredients', null=True)
    food = models.ForeignKey(
        'nutrition.Food', on_delete=models.SET_NULL, related_name='ingredients',
        null=True, blank=True
    )
    grams = models.FloatField(_('grams'), null=True, blank=True)
    match_confidence = models.CharField(
        _('match confidence'), max_length=10, choices=Confidence.choices, blank=True
    )
    match_source = models.CharField(
        _('match source'), max_length=10, choices=MatchSource.choices, blank=True
    )

    class Meta:
        ordering = ['id']

    def quantity(self):
        """The fraction as a number, or None when there is no quantity."""
        if not self.denominator:
            return None
        return self.numerator / self.denominator

    def is_salt(self):
        """
        Whether this line is salt, which sodium tracking turns on.

        Added salt is the dominant source of sodium in home cooking and
        recipes almost never quantify it -- "a dash of kosher salt" carries
        no weight at all, while a teaspoon of it is most of a day's limit.
        A recipe with unquantified salt has to say so rather than report a
        sodium figure that ignores it.
        """
        title = (self.title or '').strip().lower()
        return 'salt' in title and 'salted' not in title

    def __str__(self):
        return '%s' % self.title
