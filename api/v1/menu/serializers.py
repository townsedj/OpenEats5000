#!/usr/bin/env python
# encoding: utf-8

import datetime

from django.contrib.auth.models import User
from rest_framework import serializers

from v1.household.models import Household
from v1.household.serializers import CurrentHouseholdDefault
from v1.recipe.mixins import FieldLimiter
from v1.recipe.models import Recipe
from v1.recipe.serializers import MiniBrowseSerializer
from .estimates import refresh_estimate
from .models import MenuItem, ServingLog


def week_start_for(date):
    """The Monday of the week `date` falls in."""
    return date - datetime.timedelta(days=date.weekday())


class ServingLogSerializer(serializers.ModelSerializer):
    """ One person's portion of one planned meal. """
    username = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = ServingLog
        fields = (
            'id', 'user', 'username', 'servings', 'date',
            'kcal', 'protein_g', 'carb_g', 'fat_g', 'fibre_g',
            'sodium_mg', 'satfat_g', 'micros', 'nutrition_note',
        )
        # Every nutrient here is a snapshot the server wrote at log time.
        # A client can correct the portion; it cannot rewrite history.
        read_only_fields = (
            'kcal', 'protein_g', 'carb_g', 'fat_g', 'fibre_g',
            'sodium_mg', 'satfat_g', 'micros', 'nutrition_note',
        )


class MenuItemSerializer(FieldLimiter, serializers.ModelSerializer):
    """
    One plan entry, with everything a plan card shows.

    Deliberately fat: the plan screen renders weeks of days, each with
    several meals, and a card needs the recipe's thumbnail, one total time,
    the servings and both people's logs. Serialising those separately would
    mean a request per card.
    """
    recipe_data = MiniBrowseSerializer(read_only=True, source='recipe')
    logs = ServingLogSerializer(many=True, read_only=True)
    household = serializers.HiddenField(default=CurrentHouseholdDefault())
    author = serializers.HiddenField(default=serializers.CurrentUserDefault())
    display_title = serializers.ReadOnlyField()
    servings = serializers.ReadOnlyField()
    total_time = serializers.SerializerMethodField()
    cook_username = serializers.ReadOnlyField(source='cook.username')
    # `meal` goes over the wire as the integer that sorts the day; this is
    # the word to put on the screen.
    meal_label = serializers.CharField(source='get_meal_display', read_only=True)

    class Meta:
        model = MenuItem
        fields = [
            'id',
            'household',
            'author',
            'recipe',
            'recipe_data',
            'title',
            'display_title',
            'meal',
            'meal_label',
            'kind',
            'date',
            'week_start',
            'status',
            'cook',
            'cook_username',
            'batch_servings',
            'servings',
            'total_time',
            'est_nutrition',
            'est_nutrition_note',
            'logs',
        ]
        extra_kwargs = {
            'recipe': {'write_only': True},
            # Derived from the recipe, so a client cannot assert it. An entry
            # with no recipe keeps whatever estimate was put on it by hand or
            # by the assistant.
            'est_nutrition_note': {'read_only': True},
        }

    def create(self, validated_data):
        return refresh_estimate(super().create(validated_data), save=True)

    def update(self, instance, validated_data):
        return refresh_estimate(super().update(instance, validated_data), save=True)

    def get_total_time(self, obj):
        """
        Prep plus cook as one number, which is the only time anyone reads.

        Null when the recipe has neither, rather than a misleading 0.
        """
        if not obj.recipe_id:
            return None
        parts = [obj.recipe.prep_time, obj.recipe.cook_time]
        known = [part for part in parts if part is not None]
        return sum(known) if known else None

    def _household(self):
        return Household.objects.for_user(self.context['request'].user)

    def validate_recipe(self, value):
        if value is not None and value.household_id != self._household().id:
            raise serializers.ValidationError('No such recipe.')
        return value

    def validate_cook(self, value):
        if value is not None and not self._household().members.filter(pk=value.pk).exists():
            raise serializers.ValidationError('Not a member of this household.')
        return value

    def validate(self, attrs):
        # An entry has to have something to put on the card.
        recipe = attrs.get('recipe', getattr(self.instance, 'recipe', None))
        title = attrs.get('title', getattr(self.instance, 'title', ''))
        if not recipe and not title:
            raise serializers.ValidationError(
                {'title': 'An entry with no recipe needs a title.'}
            )

        # week_start is derived, never sent: every entry belongs to a week,
        # including the undated ones that make up the "any day" tray.
        date = attrs.get('date', getattr(self.instance, 'date', None))
        if date is not None:
            attrs['week_start'] = week_start_for(date)
        elif not attrs.get('week_start') and getattr(self.instance, 'week_start', None) is None:
            attrs['week_start'] = week_start_for(datetime.date.today())

        return attrs


class ServingLogInputSerializer(serializers.Serializer):
    """ One person's portion, as sent to menu-item/{id}/log. """
    user = serializers.IntegerField()
    servings = serializers.FloatField(min_value=0)


class LogMealSerializer(serializers.Serializer):
    """
    The whole "we ate it" tap: both people's portions in one request.

    One request per tap is the point. Two requests would mean two ways to
    half-succeed and a fiddly undo.
    """
    date = serializers.DateField(required=False, allow_null=True)
    logs = ServingLogInputSerializer(many=True)

    def validate_logs(self, value):
        if not value:
            raise serializers.ValidationError('Nothing to log.')

        household = Household.objects.for_user(self.context['request'].user)
        member_ids = set(household.members.values_list('id', flat=True))
        seen = set()
        for entry in value:
            if entry['user'] not in member_ids:
                raise serializers.ValidationError(
                    'User %s is not a member of this household.' % entry['user']
                )
            if entry['user'] in seen:
                raise serializers.ValidationError(
                    'More than one portion for user %s.' % entry['user']
                )
            seen.add(entry['user'])

        return value
