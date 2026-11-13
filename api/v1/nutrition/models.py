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


class IngredientMatch(models.Model):
    """
    What an ingredient line was decided to mean, cached by its text.

    Two reasons this exists. It keeps the same question from being asked
    twice -- "white onion" means the same food in every recipe that ever
    lists it -- and it makes matching free and instant the second time,
    which matters because the alternative is an API call per recipe save.

    `food` is nullable on purpose: "nothing in the database fits this" is an
    answer worth remembering too, otherwise every save re-asks about the
    same unmatchable line.

    Not scoped to a household. This is a dictionary of what words mean, not
    anybody's data.
    """
    text = models.CharField(_('ingredient text'), max_length=250, unique=True)
    food = models.ForeignKey(
        Food, on_delete=models.CASCADE, related_name='matches',
        null=True, blank=True
    )
    confidence = models.CharField(_('confidence'), max_length=10, blank=True)
    model = models.CharField(
        _('model'), max_length=60, blank=True,
        help_text='which model decided, so a later one can redo the weak ones'
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['text']
        verbose_name_plural = 'ingredient matches'

    def __str__(self):
        return '%s -> %s' % (self.text, self.food or 'no match')


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
    :source: = where the weight came from. USDA publishes no weight for "1
               whole onion" or "1 can of beans", but the assistant can
               judge one, and that judgement is reusable knowledge about
               the food rather than a fact about one recipe. Recording it
               here turns the next occurrence into arithmetic -- and keeps
               it distinguishable from measured data, so an inferred weight
               can always be found, audited or deleted.
    """

    class Source(models.TextChoices):
        USDA = 'usda', _('published by USDA')
        INFERRED = 'inferred', _('inferred by the assistant')

    food = models.ForeignKey(Food, on_delete=models.CASCADE, related_name='portions')
    amount = models.FloatField(_('amount'), default=1)
    measure_unit = models.CharField(_('measure unit'), max_length=80, blank=True)
    modifier = models.CharField(_('modifier'), max_length=200, blank=True)
    gram_weight = models.FloatField(_('gram weight'))
    source = models.CharField(
        _('source'), max_length=10, choices=Source.choices, default=Source.USDA
    )

    class Meta:
        # Measured weights before inferred ones, so a USDA portion is always
        # preferred where both exist.
        ordering = ['food_id', 'source', 'id']

    def __str__(self):
        return '%s %s %s = %sg' % (
            self.amount, self.measure_unit, self.modifier, self.gram_weight
        )
