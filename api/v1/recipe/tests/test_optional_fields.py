#!/usr/bin/env python
# encoding: utf-8
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.exceptions import ParseError

from v1.recipe.models import Recipe
from v1.recipe.save_recipe import SaveRecipe


class OptionalRecipeFieldsTests(TestCase):
    """
    Cuisine, course, prep time and cook time used to be required, which meant
    four fields to fill before a pasted recipe would save. They are optional
    now; these tests keep them that way.
    """

    def setUp(self):
        self.author = User.objects.create_user('cook', password='nope')
        self.minimal = {
            'title': 'Beans on toast',
            'directions': 'Toast the bread. Heat the beans.',
            'servings': 2,
            'ingredient_groups': [{'title': '', 'ingredients': []}],
        }

    def test_validation_accepts_a_recipe_with_no_taxonomy_or_times(self):
        # SaveRecipe validates in its constructor and raises ParseError.
        SaveRecipe(dict(self.minimal), self.author)

    def test_title_is_still_required(self):
        without_title = dict(self.minimal)
        del without_title['title']
        with self.assertRaises(ParseError):
            SaveRecipe(without_title, self.author)

    def test_a_non_numeric_time_is_still_rejected(self):
        bad_time = dict(self.minimal, prep_time='soon')
        with self.assertRaises(ParseError):
            SaveRecipe(bad_time, self.author)

    def test_the_model_stores_nulls_for_all_four(self):
        recipe = Recipe.objects.create(
            title='Beans on toast',
            author=self.author,
            servings=2,
            directions='Toast the bread.',
        )
        recipe.refresh_from_db()
        self.assertIsNone(recipe.cuisine)
        self.assertIsNone(recipe.course)
        self.assertIsNone(recipe.prep_time)
        self.assertIsNone(recipe.cook_time)
        self.assertEqual(recipe.notes, '')
