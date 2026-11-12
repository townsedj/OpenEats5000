#!/usr/bin/env python
# encoding: utf-8

from rest_framework import viewsets

from .models import Ingredient, IngredientGroup
from .serializers import IngredientSerializer, IngredientGroupSerializer
from v1.common.permissions import IsHouseholdMember
from v1.household.models import Household


class IngredientGroupViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions for Ingredient Groups.
    """
    serializer_class = IngredientGroupSerializer
    permission_classes = (IsHouseholdMember,)
    household_path = 'recipe.household'
    filterset_fields = ('recipe',)

    def get_queryset(self):
        user = self.request.user
        if not user or user.is_anonymous:
            return IngredientGroup.objects.none()
        return IngredientGroup.objects.filter(
            recipe__household=Household.objects.for_user(user)
        )


class IngredientViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions for Ingredients.

    Was readable by any logged-in account and not writable at all: the old
    IsOwnerOrReadOnly looked for `obj.recipe.author`, which an Ingredient
    does not have, so every write raised.
    """
    serializer_class = IngredientSerializer
    permission_classes = (IsHouseholdMember,)
    household_path = 'ingredient_group.recipe.household'
    filterset_fields = ('ingredient_group', 'ingredient_group__recipe')

    def get_queryset(self):
        user = self.request.user
        if not user or user.is_anonymous:
            return Ingredient.objects.none()
        return Ingredient.objects.filter(
            ingredient_group__recipe__household=Household.objects.for_user(user)
        )
