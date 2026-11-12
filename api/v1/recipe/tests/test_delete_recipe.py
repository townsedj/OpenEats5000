#!/usr/bin/env python
# encoding: utf-8

from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIRequestFactory
from v1.recipe import views
from v1.common.testing import one_household


class RecipeSerializerTests(TestCase):
    fixtures = [
        'test/users.json',
        'course_data.json',
        'cuisine_data.json',
        'ing_data.json',
        'recipe_data.json'
    ]

    def setUp(self):
        self.factory = APIRequestFactory()
        self.staff = User.objects.create_user(
            username='staff', email='staff@gmail.com', password='top_secret', is_superuser=True
        )
        # Fixtures predate household scoping, so the rows they load have
        # no household and a scoped queryset cannot see them.
        self.household = one_household()

    def test_simple_delete_recipe(self):
        """Test to make sure we have the right fields"""
        view = views.RecipeViewSet.as_view({'delete': 'destroy'})
        request = self.factory.delete('/api/v1/recipe/recipes/tasty-chili')
        request.user = self.staff
        response = view(request, slug='tasty-chili')

        self.assertEqual(response.status_code, 204)
