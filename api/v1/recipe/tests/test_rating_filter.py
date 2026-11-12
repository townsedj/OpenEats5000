#!/usr/bin/env python
# encoding: utf-8

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from v1.recipe import views
from v1.recipe.models import Recipe
from v1.rating.models import Rating


class RecipeRatingFilterTests(TestCase):
    """
    Covers RecipeViewSet.get_queryset()'s ?rating= path, which had no tests and
    used to return a Python list instead of a QuerySet. The list form silently
    disabled pagination and ordering, so the pagination assertions below are
    the regression guard.
    """

    fixtures = [
        'test/users.json',
        'course_data.json',
        'cuisine_data.json',
        'ing_data.json',
        'recipe_data.json'
    ]

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = views.RecipeViewSet.as_view({'get': 'list'})

    def get(self, query):
        request = self.factory.get('/api/v1/recipe/recipes/?' + query)
        return self.view(request)

    def test_unrated_recipes_count_as_zero(self):
        """ No ratings at all means an average of 0, as convert_rating_to_int did """
        response = self.get('rating=0')

        # A paginated response at all is the point: a list has no 'count'.
        self.assertEqual(response.data.get('count'), Recipe.objects.count())

    def test_filters_by_whole_number_average(self):
        """ A rated recipe moves out of the 0 bucket and into its own """
        recipe = Recipe.objects.get(slug='tasty-chili')
        author = User.objects.get(pk=1)
        # Average 4.5, which truncates to 4.
        Rating.objects.create(recipe=recipe, author=author, rating=4, comment='')
        Rating.objects.create(recipe=recipe, author=author, rating=5, comment='')

        total = Recipe.objects.count()

        response = self.get('rating=4')
        self.assertEqual(response.data.get('count'), 1)
        self.assertEqual(response.data['results'][0].get('slug'), 'tasty-chili')

        response = self.get('rating=0')
        self.assertEqual(response.data.get('count'), total - 1)

        # Several buckets at once, the way the browse filters send them.
        response = self.get('rating=0,4')
        self.assertEqual(response.data.get('count'), total)

    def test_unparseable_rating_matches_nothing(self):
        """ Junk in the query string must not 500 """
        response = self.get('rating=not-a-number')
        self.assertEqual(response.data.get('count'), 0)

    def test_rating_path_is_still_orderable(self):
        """ OrderingFilter applies, which it could not on a list """
        response = self.get('rating=0&ordering=title')

        titles = [row.get('title') for row in response.data['results']]
        self.assertEqual(titles, sorted(titles))
