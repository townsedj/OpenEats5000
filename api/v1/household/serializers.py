#!/usr/bin/env python
# encoding: utf-8

from rest_framework import serializers

from .models import Household, NutritionTarget, Profile


class CurrentHouseholdDefault:
    """
    Serializer default that fills in the requesting user's household.

    Used as a HiddenField default so household is never taken from the
    request body -- a client cannot write a row into someone else's house.
    """
    requires_context = True

    def __call__(self, serializer_field):
        request = serializer_field.context['request']
        return Household.objects.for_user(request.user)

    def __repr__(self):
        return '%s()' % self.__class__.__name__


class MemberSerializer(serializers.Serializer):
    """A person in the household, with the settings that affect shared screens."""
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    default_servings = serializers.FloatField(
        read_only=True, source='profile.default_servings'
    )
    show_nutrition = serializers.BooleanField(
        read_only=True, source='profile.show_nutrition'
    )


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('default_servings', 'show_nutrition')


class NutritionTargetSerializer(serializers.ModelSerializer):
    """ One person's whole-day targets. """
    # Columns and micro_targets flattened into one dict, which is the shape
    # a screen wants. Read-only: writes go to the real fields.
    all_targets = serializers.SerializerMethodField()

    class Meta:
        model = NutritionTarget
        fields = (
            'kcal', 'protein_g', 'carb_g', 'fat_g', 'fibre_g',
            'sodium_mg', 'satfat_g', 'micro_targets', 'all_targets',
        )

    def get_all_targets(self, obj):
        return obj.as_dict()

    def validate_micro_targets(self, value):
        """Refuse keys the app has no nutrient for, so typos do not vanish."""
        from v1.nutrition import nutrients

        if value is None:
            return value
        if not isinstance(value, dict):
            raise serializers.ValidationError('Expected an object.')

        unknown = sorted(set(value) - set(nutrients.KEYS))
        if unknown:
            raise serializers.ValidationError(
                'Unknown nutrients: %s' % ', '.join(unknown)
            )
        return value


class TargetPresetSerializer(serializers.Serializer):
    """
    Which population-level starting point to fill the blanks from.

    No sex is stored anywhere. The preset is picked once, the numbers are
    written down as this person's own, and from then on they are just
    numbers they can edit.
    """
    preset = serializers.ChoiceField(choices=('male', 'female'))


class HouseholdSerializer(serializers.ModelSerializer):
    members = MemberSerializer(many=True, read_only=True)

    class Meta:
        model = Household
        fields = ('id', 'name', 'members')
