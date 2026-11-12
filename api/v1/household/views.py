#!/usr/bin/env python
# encoding: utf-8

from rest_framework import generics, views
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Household, NutritionTarget, Profile
from .serializers import (
    HouseholdSerializer,
    NutritionTargetSerializer,
    ProfileSerializer,
    TargetPresetSerializer,
)


class CurrentHouseholdView(views.APIView):
    """
    GET household/me/ -- everything the app needs to boot: who is logged in,
    who else is in the house, and their shared-screen settings.
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        household = Household.objects.for_user(request.user)
        # Make sure every member has a profile before serializing, so the
        # member rows never come back with nulls for settings that have
        # defaults.
        for member in household.members.all():
            Profile.for_user(member)

        return Response({
            'user_id': request.user.id,
            'household': HouseholdSerializer(
                household, context={'request': request}
            ).data,
        })


class ProfileView(generics.RetrieveUpdateAPIView):
    """ GET / PUT / PATCH household/profile/ -- the caller's own settings. """
    permission_classes = (IsAuthenticated,)
    serializer_class = ProfileSerializer

    def get_object(self):
        return Profile.for_user(self.request.user)


class NutritionTargetView(generics.RetrieveUpdateAPIView):
    """
    GET / PUT / PATCH household/nutrition-target/ -- the caller's own targets.

    Created empty on first read, so the front end always has a row to PATCH.
    """
    permission_classes = (IsAuthenticated,)
    serializer_class = NutritionTargetSerializer

    def get_object(self):
        target, _created = NutritionTarget.objects.get_or_create(user=self.request.user)
        return target


class TargetPresetView(views.APIView):
    """
    POST household/nutrition-target/preset/ {"preset": "female"}

    Fills in whatever the caller has not set yet from the US DRI figures,
    and leaves anything they have already chosen alone. Saturated fat comes
    out of their own calorie target rather than a flat number, so setting
    kcal first gets a better answer.

    The response says which fields it actually filled, so the screen can
    show what changed instead of silently rewriting the form.
    """
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = TargetPresetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target, _created = NutritionTarget.objects.get_or_create(user=request.user)
        filled = target.apply_preset(serializer.validated_data['preset'])

        return Response({
            'filled': sorted(filled),
            'target': NutritionTargetSerializer(target).data,
        })
