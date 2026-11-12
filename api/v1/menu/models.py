#!/usr/bin/env python
# encoding: utf-8

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _

from v1.household.models import Household
from v1.recipe.models import Recipe


class MenuItem(models.Model):
    """
    One entry on the household's plan.

    This is the *plan*, not what anybody ate: see ServingLog for that. The
    two of them share a meal in different portions, so a single "servings
    eaten" here could never be right for both.

    A day holds several of these -- one per meal slot, and more than one in a
    slot where that is what is happening. Nothing is unique per day and slot
    on purpose.

    :household: = The house whose plan this entry is on.
    :author: = Who put it on the plan.
    :recipe: = The recipe to cook, if there is one. Null for the entries that
               keep a plan honest: leftovers, eating out, a reminder.
    :title: = Shown instead of the recipe title when there is no recipe, and
              as an override when there is ("Chili, double batch").
    :meal: = Which meal of the day. Stored as a small integer so the plan
             sorts into the order the day actually happens in; a text choice
             would sort breakfast, dinner, lunch, snack.
    :kind: = What sort of entry this is.
    :date: = The day it is planned for, or null for "this week, some day".
             A DateField, not a DateTimeField: a meal belongs to a day, not
             an instant, and storing an instant made the day shift by
             timezone.
    :week_start: = The Monday of the week this entry sits in. Always set,
                   including for undated entries, which is what lets the
                   plan screen show an "any day" tray per week.
    :status: = planned / eaten / skipped.
    :cook: = Who is cooking. Null means nobody has claimed it.
    :batch_servings: = Servings actually made, when that differs from the
                       recipe's own servings (a double batch for leftovers).
    :est_nutrition: = Cached per-serving estimate, so the plan screen does
                      not recompute a recipe's nutrition on every render.
    """

    class Meal(models.IntegerChoices):
        BREAKFAST = 1, _('breakfast')
        LUNCH = 2, _('lunch')
        DINNER = 3, _('dinner')
        SNACK = 4, _('snack')

    class Kind(models.TextChoices):
        COOK = 'cook', _('cook')
        LEFTOVER = 'leftover', _('leftovers')
        OUT = 'out', _('eating out')
        NOTE = 'note', _('note')

    class Status(models.TextChoices):
        PLANNED = 'planned', _('planned')
        EATEN = 'eaten', _('eaten')
        SKIPPED = 'skipped', _('skipped')

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name='menu_items',
        null=True, blank=True
    )
    author = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    recipe = models.ForeignKey(
        Recipe, on_delete=models.CASCADE, related_name='menu_recipe',
        null=True, blank=True
    )
    title = models.CharField(_('title'), max_length=250, blank=True)
    meal = models.PositiveSmallIntegerField(
        _('meal'), choices=Meal.choices, default=Meal.DINNER
    )
    kind = models.CharField(
        _('kind'), max_length=20, choices=Kind.choices, default=Kind.COOK
    )
    date = models.DateField(_('date'), null=True, blank=True)
    week_start = models.DateField(_('week start'), null=True, blank=True)
    status = models.CharField(
        _('status'), max_length=20, choices=Status.choices, default=Status.PLANNED
    )
    cook = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name='cooking',
        null=True, blank=True
    )
    batch_servings = models.FloatField(_('batch servings'), null=True, blank=True)
    est_nutrition = models.JSONField(_('estimated nutrition'), null=True, blank=True)
    # What the estimate above does not account for: unmatched ingredients,
    # and whether the recipe quantified its salt. Kept beside the numbers so
    # the two cannot be separated on the way to a screen.
    est_nutrition_note = models.JSONField(
        _('estimate note'), null=True, blank=True
    )

    class Meta:
        # Undated entries sort after the dated ones in their week, which is
        # where the "any day" tray sits on screen. Within a day, entries come
        # out in the order the day happens.
        ordering = ['week_start', 'date', 'meal', 'id']

    def display_title(self):
        """What to put on the card: the override, else the recipe's title."""
        if self.title:
            return self.title
        if self.recipe_id:
            return self.recipe.title
        return ''

    def servings(self):
        """How many servings this entry makes."""
        if self.batch_servings:
            return self.batch_servings
        if self.recipe_id:
            return self.recipe.servings
        return None

    def __str__(self):
        return '%s' % (self.display_title() or self.get_kind_display())


class ServingLog(models.Model):
    """
    What one person actually ate of one planned meal.

    One row per person per plan entry, so the two of them can take different
    portions of the same food -- which is the normal case for a shared lunch
    or dinner. A day's intake for one person is the sum of their rows for
    that date; the meal slot comes from the plan entry.

    The macro columns are *snapshots*, written at log time. They are not
    derived on read on purpose: correcting a recipe next month must not
    rewrite what somebody ate last month. They stay null until nutrition
    matching exists, and get backfilled then -- logging ships first.

    :menu_item: = The planned meal.
    :user: = Whose portion this is.
    :logged_by: = Who tapped the button. Either spouse can log for the other.
    :servings: = Portions of `menu_item` eaten.
    :date: = The day it was eaten, which can differ from the planned date.
    """
    menu_item = models.ForeignKey(
        MenuItem, on_delete=models.CASCADE, related_name='logs'
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='serving_logs'
    )
    logged_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name='+', null=True, blank=True
    )
    servings = models.FloatField(_('servings'), default=1)
    date = models.DateField(_('date'), null=True, blank=True)

    # Columns for the seven the app sums or filters on every render.
    # Everything else USDA gave goes in `micros` -- see
    # v1.nutrition.nutrients for why the split is where it is.
    kcal = models.FloatField(_('kcal'), null=True, blank=True)
    protein_g = models.FloatField(_('protein (g)'), null=True, blank=True)
    carb_g = models.FloatField(_('carbohydrate (g)'), null=True, blank=True)
    fat_g = models.FloatField(_('fat (g)'), null=True, blank=True)
    fibre_g = models.FloatField(_('fibre (g)'), null=True, blank=True)
    sodium_mg = models.FloatField(_('sodium (mg)'), null=True, blank=True)
    satfat_g = models.FloatField(_('saturated fat (g)'), null=True, blank=True)
    micros = models.JSONField(_('micronutrients'), null=True, blank=True)

    # Why the computed numbers above cannot be taken at face value: which
    # ingredients went unmatched, and whether the recipe quantified its
    # salt. Snapshotted with the rest, because a caveat that is lost is
    # worse than no number.
    nutrition_note = models.JSONField(_('nutrition note'), null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        # One row per person per planned meal. Eating the same recipe twice
        # means two MenuItems, which is also how the plan should read.
        unique_together = ('menu_item', 'user')
        ordering = ['date', 'id']

    def __str__(self):
        return '%s: %s x%s' % (
            self.user.get_username(), self.menu_item_id, self.servings
        )
