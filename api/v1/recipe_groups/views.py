#!/usr/bin/env python
# encoding: utf-8

from django.db.models import Count
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from v1.household.models import Household
from v1.recipe_groups.models import Cuisine, Course, Tag
from v1.recipe.models import Recipe
from v1.recipe_groups import serializers
from v1.common.recipe_search import get_search_results


class HouseholdRecipes(object):
    """
    Shared helper: the recipes the caller is allowed to count.

    These endpoints exist to count recipes per group, so they have to be
    scoped the same way the recipe list is. They used to fall back to
    `public=True` for anonymous callers; there is no anonymous access and no
    `public` field any more.
    """

    def household_recipes(self):
        return Recipe.objects.filter(
            household=Household.objects.for_user(self.request.user)
        )


class CuisineViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions.

    Uses `slug` as the PK for any lookups.
    """
    queryset = Cuisine.objects.all()
    serializer_class = serializers.CuisineSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = 'slug'


class CuisineCountViewSet(HouseholdRecipes, viewsets.ModelViewSet):
    """
    How many of the household's recipes sit under each cuisine.
    """
    serializer_class = serializers.AggCuisineSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = 'slug'

    def get_queryset(self):
        query = self.household_recipes()
        filter_set = {}

        if 'course' in self.request.query_params:
            filter_set['course__in'] = Course.objects.filter(
                slug__in=self.request.query_params.get('course').split(',')
            )

        if 'search' in self.request.query_params:
            query = get_search_results(
                ['title', 'ingredient_groups__ingredients__title', 'tags__title'],
                query,
                self.request.query_params.get('search')
            ).distinct()

        query = query.filter(**filter_set)
        return Cuisine.objects.filter(recipe__in=query).annotate(
            total=Count('recipe', distinct=True)
        )


class CourseViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions.

    Uses `slug` as the PK for any lookups.
    """
    queryset = Course.objects.all()
    serializer_class = serializers.CourseSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = 'slug'


class CourseCountViewSet(HouseholdRecipes, viewsets.ModelViewSet):
    """
    How many of the household's recipes sit under each course.
    """
    serializer_class = serializers.AggCourseSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = 'slug'

    def get_queryset(self):
        query = self.household_recipes()
        filter_set = {}

        if 'cuisine' in self.request.query_params:
            filter_set['cuisine__in'] = Cuisine.objects.filter(
                slug__in=self.request.query_params.get('cuisine').split(',')
            )

        if 'search' in self.request.query_params:
            query = get_search_results(
                ['title', 'ingredient_groups__ingredients__title', 'tags__title'],
                query,
                self.request.query_params.get('search')
            ).distinct()

        query = query.filter(**filter_set)
        return Course.objects.filter(recipe__in=query).annotate(
            total=Count('recipe', distinct=True)
        )


class TagViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions.

    Uses `title` as the PK for any lookups.
    """
    queryset = Tag.objects.all()
    serializer_class = serializers.TagSerializer
    permission_classes = (IsAuthenticated,)
    lookup_field = 'title'
