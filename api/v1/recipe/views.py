#!/usr/bin/env python
# encoding: utf-8

import random

from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from v1.common.permissions import IsHouseholdMember
from v1.household.models import Household
from . import serializers
from .models import Recipe
from .save_recipe import SaveRecipe
from v1.recipe_groups.models import Cuisine, Course


class RecipeViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions.

    Recipes belong to a household, not to the person who typed them in, and
    there is no anonymous browsing: `Recipe.public` is gone along with the
    read-only-for-the-world mode it enabled. This install is reachable only
    on a private network by two people who share everything in it.
    """
    lookup_field = 'slug'
    serializer_class = serializers.RecipeSerializer
    permission_classes = (IsHouseholdMember,)
    filter_backends = (filters.SearchFilter, filters.OrderingFilter)
    search_fields = ('title', 'tags__title', 'ingredient_groups__ingredients__title')
    ordering_fields = ('pub_date', 'title', )

    def get_queryset(self):
        user = self.request.user
        if not user or user.is_anonymous:
            return Recipe.objects.none()

        filter_set = {'household': Household.objects.for_user(user)}

        if 'cuisine__slug' in self.request.query_params:
            filter_set['cuisine__in'] = Cuisine.objects.filter(
                slug__in=self.request.query_params.get('cuisine__slug').split(',')
            )

        if 'course__slug' in self.request.query_params:
            filter_set['course__in'] = Course.objects.filter(
                slug__in=self.request.query_params.get('course__slug').split(',')
            )

        return Recipe.objects.filter(**filter_set)

    def create(self, request, *args, **kwargs):
        return Response(
            serializers.RecipeSerializer(
                SaveRecipe(
                    request.data,
                    self.request.user,
                    household=Household.objects.for_user(self.request.user),
                ).create(),
                context=self.get_serializer_context(),
            ).data
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        return Response(
            serializers.RecipeSerializer(
                SaveRecipe(
                    request.data,
                    self.request.user,
                    partial=partial,
                    household=Household.objects.for_user(self.request.user),
                ).update(self.get_object()),
                context=self.get_serializer_context(),
            ).data
        )


class MiniBrowseViewSet(viewsets.mixins.ListModelMixin,
                        viewsets.GenericViewSet):
    """
    A random handful of the household's recipes, for the "what shall we
    cook" prompt.
    """
    serializer_class = serializers.MiniBrowseSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        user = self.request.user
        if not user or user.is_anonymous:
            return Recipe.objects.none()
        return Recipe.objects.filter(household=Household.objects.for_user(user))

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # Sample from the ids rather than ordering by random in the database:
        # the household has hundreds of recipes at most, and this keeps the
        # query portable.
        ids = list(queryset.values_list('id', flat=True))
        limit = min(int(request.query_params.get('limit', 4)), len(ids))
        self.queryset = Recipe.objects.filter(id__in=random.sample(ids, limit))

        return super(MiniBrowseViewSet, self).list(request, *args, **kwargs)
