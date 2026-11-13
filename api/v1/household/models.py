#!/usr/bin/env python
# encoding: utf-8

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _


class HouseholdManager(models.Manager):
    def for_user(self, user):
        """
        The household `user` belongs to, joining or creating one if needed.

        This is a single-household install: one family on a private network,
        with accounts created by an admin rather than by self-registration.
        So a new account joins the household that already exists instead of
        getting one of its own -- that is what should happen when the second
        person in the house logs in for the first time. If a second household
        is ever wanted, membership has to be set explicitly in the admin.
        """
        household = self.filter(members=user).first()
        if household is not None:
            return household

        household = self.first()
        if household is None:
            household = self.create(name=_('Household'))
        household.members.add(user)
        return household


class Household(models.Model):
    """
    The group of people who share recipes, a menu and a grocery list.

    Everything shared hangs off this; everything personal (portions,
    nutrition targets) hangs off User instead.
    """
    class Salt(models.TextChoices):
        TABLE = 'table', _('table salt (fine)')
        KOSHER_MORTON = 'kosher_morton', _('Morton kosher')
        KOSHER_DIAMOND = 'kosher_diamond_crystal', _('Diamond Crystal kosher')
        COARSE_SEA = 'coarse_sea', _('coarse sea salt')
        FLAKE = 'flake_maldon', _('flaky sea salt')

    class KosherSalt(models.TextChoices):
        MORTON = 'kosher_morton', _('Morton kosher')
        DIAMOND = 'kosher_diamond_crystal', _('Diamond Crystal kosher')

    name = models.CharField(_('name'), max_length=150)
    members = models.ManyToManyField(
        User, verbose_name=_('members'), related_name='households', blank=True
    )

    # Salt needs two settings, not one, because a kitchen usually has two
    # boxes and the recipe's wording decides which one gets reached for.
    #
    # Why any of this is stored at all: every salt is essentially pure
    # sodium chloride, so the sodium per gram is identical, but a teaspoon
    # of Diamond Crystal weighs 2.8g against table salt's 6.0g. A recipe
    # measured in spoons therefore carries up to twice the sodium depending
    # on which box it is, and FoodData Central has no kosher salt entry at
    # all to read it from.
    default_salt = models.CharField(
        _('default salt'), max_length=30, choices=Salt.choices, blank=True,
        default=Salt.TABLE,
        help_text='what a recipe means when it just says "salt"'
    )
    kosher_salt = models.CharField(
        _('kosher salt'), max_length=30, choices=KosherSalt.choices, blank=True,
        default=KosherSalt.MORTON,
        help_text='which box a recipe calling for kosher salt gets; the two '
                  'brands are 70% apart by volume'
    )
    created = models.DateTimeField(auto_now_add=True)

    objects = HouseholdManager()

    class Meta:
        ordering = ['id']

    def __str__(self):
        return '%s' % self.name


class Profile(models.Model):
    """
    Per-person settings that are nobody else's business.

    :default_servings: = the portion to predict when this person logs a meal
                         they have not eaten before.
    :show_nutrition: = off makes the app a plain planner for this person.
                       Their spouse's setting is unaffected.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    default_servings = models.FloatField(_('default servings'), default=1)
    show_nutrition = models.BooleanField(_('show nutrition'), default=True)

    @classmethod
    def for_user(cls, user):
        profile, _created = cls.objects.get_or_create(user=user)
        return profile

    def __str__(self):
        return '%s' % self.user.get_username()


class NutritionTarget(models.Model):
    """
    One person's daily targets.

    These are whole-day numbers and every comparison is a whole day against
    them: the plan covers breakfast, lunch, dinner and snacks, so the day is
    the unit that can actually be measured.

    (An earlier draft had a `dinner_fraction` and compared one dinner against
    a share of the day. That only made sense while dinner was the only meal
    the app knew about.)

    Any target left null is simply not shown, so one person can track
    protein alone and nothing else.
    """
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='nutrition_target'
    )
    kcal = models.IntegerField(_('daily kcal'), null=True, blank=True)
    protein_g = models.FloatField(_('daily protein (g)'), null=True, blank=True)
    carb_g = models.FloatField(_('daily carbohydrate (g)'), null=True, blank=True)
    fat_g = models.FloatField(_('daily fat (g)'), null=True, blank=True)
    fibre_g = models.FloatField(_('daily fibre (g)'), null=True, blank=True)
    sodium_mg = models.FloatField(_('daily sodium (mg)'), null=True, blank=True)
    satfat_g = models.FloatField(
        _('daily saturated fat (g)'), null=True, blank=True
    )
    # Targets for everything that does not have a column, keyed the same way
    # as the nutrient registry. A JSON blob rather than twenty columns, for
    # the same reason the food nutrients are rows.
    micro_targets = models.JSONField(_('micro targets'), null=True, blank=True)

    def as_dict(self):
        """
        Every target that is actually set, for comparing a day against.

        Nulls are left out rather than sent as zero: somebody tracking
        protein and sodium alone should not be shown eighteen other numbers
        they never asked for.
        """
        from v1.nutrition import nutrients

        targets = {}
        for key in nutrients.COLUMN_KEYS:
            value = getattr(self, key, None)
            if value is not None:
                targets[key] = value

        for key, value in (self.micro_targets or {}).items():
            if value is not None and key in nutrients.BY_KEY:
                targets[key] = value

        return targets

    def apply_preset(self, preset):
        """
        Fill in population-level starting points, leaving anything already
        set alone.

        No `sex` field is stored anywhere: the preset is chosen once, the
        numbers are written down as this person's own, and from then on they
        are just numbers they can edit.
        """
        from v1.nutrition import nutrients

        values = dict(nutrients.TARGET_PRESETS.get(preset, {}))
        values.update(nutrients.derived_targets(self.kcal))

        micro_targets = dict(self.micro_targets or {})
        changed = []

        for key, value in values.items():
            if key in nutrients.COLUMN_KEYS:
                if getattr(self, key, None) is None:
                    setattr(self, key, value)
                    changed.append(key)
            elif micro_targets.get(key) is None:
                micro_targets[key] = value
                changed.append(key)

        self.micro_targets = micro_targets
        self.save()
        return changed

    def __str__(self):
        return '%s' % self.user.get_username()
