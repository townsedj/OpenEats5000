#!/usr/bin/env python
# encoding: utf-8

from django.db import models
from django.utils.translation import gettext_lazy as _

from . import nutrients


class Food(models.Model):
    """
    A generic food from USDA FoodData Central.

    SR Legacy and Foundation only -- roughly eight thousand generic
    ingredients, public domain. Excellent for "white onion" and "ground
    pork"; it does not contain a single branded product, so a jar of pasta
    sauce has to be entered by hand. That was a deliberate choice: the
    Branded set is around two million label-derived rows of uneven quality.

    :fdc_id: = FoodData Central's own id, which is the natural key for
               re-importing without duplicating.
    :description: = USDA's description, kept verbatim so it can be matched
                    against and cited.
    """

    class DataType(models.TextChoices):
        SR_LEGACY = 'sr_legacy_food', _('SR Legacy')
        FOUNDATION = 'foundation_food', _('Foundation')

    fdc_id = models.IntegerField(_('FDC id'), unique=True)
    description = models.CharField(_('description'), max_length=300)
    data_type = models.CharField(
        _('data type'), max_length=40, choices=DataType.choices, blank=True
    )
    category = models.CharField(_('category'), max_length=150, blank=True)

    class Meta:
        ordering = ['description']
        indexes = [models.Index(fields=['description'])]

    def nutrient_amounts(self):
        """Per 100 g, keyed by registry key."""
        return {row.nutrient: row.amount for row in self.nutrients.all()}

    def __str__(self):
        return '%s' % self.description


class FoodNutrient(models.Model):
    """
    One nutrient of one food, per 100 g of edible portion.

    A row per nutrient rather than fifty columns: USDA publishes a long and
    uneven tail, most foods carry only some of it, and a column per nutrient
    would mean a migration every time this app learns to care about another
    one.

    `nutrient` holds a key from v1.nutrition.nutrients, not a USDA id, so
    the rest of the app never has to know what 1093 means.
    """
    food = models.ForeignKey(Food, on_delete=models.CASCADE, related_name='nutrients')
    nutrient = models.CharField(_('nutrient'), max_length=40)
    amount = models.FloatField(_('amount per 100g'))

    class Meta:
        unique_together = ('food', 'nutrient')
        ordering = ['food_id', 'nutrient']

    @property
    def unit(self):
        known = nutrients.BY_KEY.get(self.nutrient)
        return known.unit if known else ''

    def __str__(self):
        return '%s: %s %s' % (self.nutrient, self.amount, self.unit)


class FoodPortion(models.Model):
    """
    A household measure for a food, and what it weighs.

    This is what turns "1 cup, chopped" into grams, which is the only form
    the nutrient rows can be used in. Without these, every ingredient would
    have to be entered by weight.

    :amount: = 1, as in "1 cup"
    :measure_unit: = "cup"
    :modifier: = "chopped" -- which matters, because a cup of chopped onion
                 and a cup of sliced onion are different weights.
    """
    food = models.ForeignKey(Food, on_delete=models.CASCADE, related_name='portions')
    amount = models.FloatField(_('amount'), default=1)
    measure_unit = models.CharField(_('measure unit'), max_length=80, blank=True)
    modifier = models.CharField(_('modifier'), max_length=200, blank=True)
    gram_weight = models.FloatField(_('gram weight'))

    class Meta:
        ordering = ['food_id', 'id']

    def __str__(self):
        return '%s %s %s = %sg' % (
            self.amount, self.measure_unit, self.modifier, self.gram_weight
        )
