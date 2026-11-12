#!/usr/bin/env python
# encoding: utf-8

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from v1.household.models import Household, NutritionTarget
from v1.menu import views
from v1.menu.models import MenuItem
from v1.recipe.models import Recipe


class DayNutritionTests(TestCase):
    """
    Two people, one plan, separate goals -- read back a day at a time.
    """

    def setUp(self):
        self.factory = APIRequestFactory()

        self.me = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.spouse = User.objects.create_user(
            username='spouse', email='spouse@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.household.members.add(self.me, self.spouse)

        self.recipe = Recipe.objects.create(
            title='Tasty Chili', author=self.me, household=self.household,
            servings=4,
        )
        self.monday = datetime.date(2026, 11, 9)

        NutritionTarget.objects.create(
            user=self.me, kcal=2400, sodium_mg=2300,
            micro_targets={'iron_mg': 8},
        )
        NutritionTarget.objects.create(
            user=self.spouse, kcal=1900, sodium_mg=2300,
            micro_targets={'iron_mg': 18},
        )

    def plan_and_log(self, meal, estimate, portions, date=None):
        item = MenuItem.objects.create(
            household=self.household, author=self.me, recipe=self.recipe,
            date=date or self.monday, week_start=self.monday, meal=meal,
            est_nutrition=estimate,
        )
        view = views.MenuItemViewSet.as_view({'post': 'log'})
        request = self.factory.post(
            '/api/v1/menu/menu-item/%s/log/' % item.id,
            data={'logs': [
                {'user': user.id, 'servings': servings}
                for user, servings in portions
            ]},
            format='json',
        )
        request.user = self.me
        response = view(request, pk=item.id)
        assert response.status_code == 200, response.data
        return item

    def get(self, query=''):
        request = self.factory.get('/api/v1/menu/day-nutrition/%s' % query)
        request.user = self.me
        return views.DayNutritionView.as_view()(request)

    def test_a_whole_day_adds_up_per_person(self):
        """
        Breakfast, lunch and dinner, two people, different portions of each.
        """
        for meal in (MenuItem.Meal.BREAKFAST, MenuItem.Meal.LUNCH,
                     MenuItem.Meal.DINNER):
            self.plan_and_log(
                meal,
                {'kcal': 400, 'sodium_mg': 300, 'iron_mg': 2},
                [(self.me, 1), (self.spouse, 0.5)],
            )

        response = self.get()
        day = response.data['days'][0]

        self.assertEqual(day['date'], self.monday)
        by_user = {row['username']: row for row in day['people']}

        self.assertAlmostEqual(by_user['me']['totals']['kcal'], 1200)
        self.assertAlmostEqual(by_user['me']['totals']['sodium_mg'], 900)
        self.assertAlmostEqual(by_user['spouse']['totals']['kcal'], 600)
        # Micros come out of the JSON blob, summed the same way as columns.
        self.assertAlmostEqual(by_user['me']['totals']['iron_mg'], 6)
        self.assertAlmostEqual(by_user['spouse']['totals']['iron_mg'], 3)

    def test_each_person_is_measured_against_their_own_targets(self):
        """
        Same meals, different goals. 1,200 kcal is half of one target and
        nearly two thirds of the other, and iron differs more than twofold.
        """
        for meal in (MenuItem.Meal.BREAKFAST, MenuItem.Meal.LUNCH,
                     MenuItem.Meal.DINNER):
            self.plan_and_log(
                meal,
                {'kcal': 400, 'iron_mg': 2},
                [(self.me, 1), (self.spouse, 1)],
            )

        response = self.get()
        by_user = {
            row['username']: row for row in response.data['days'][0]['people']
        }

        self.assertAlmostEqual(by_user['me']['against_target']['kcal']['share'], 0.5)
        self.assertAlmostEqual(
            by_user['spouse']['against_target']['kcal']['share'], 1200 / 1900.0
        )
        self.assertAlmostEqual(
            by_user['me']['against_target']['iron_mg']['share'], 6 / 8.0
        )
        self.assertAlmostEqual(
            by_user['spouse']['against_target']['iron_mg']['share'], 6 / 18.0
        )

    def test_direction_travels_with_each_comparison(self):
        self.plan_and_log(
            MenuItem.Meal.DINNER, {'kcal': 400, 'sodium_mg': 1000},
            [(self.me, 1)],
        )

        response = self.get()
        rows = response.data['days'][0]['people'][0]['against_target']

        self.assertEqual(rows['sodium_mg']['direction'], 'ceiling')
        self.assertEqual(rows['kcal']['direction'], 'target')

    def test_the_day_says_how_many_meals_were_logged(self):
        """
        A day with one meal logged is not a 400 kcal day, and the number on
        its own would say exactly that.
        """
        self.plan_and_log(MenuItem.Meal.DINNER, {'kcal': 400}, [(self.me, 1)])

        response = self.get()
        note = response.data['days'][0]['people'][0]['note']

        self.assertEqual(note['logged_meals'], 1)

    def test_unquantified_salt_follows_the_meal_into_the_day(self):
        """
        The caveat is snapshotted with the numbers, so a day built from a
        recipe that could not account for its salt says so.
        """
        from v1.ingredient.models import Ingredient, IngredientGroup

        group = IngredientGroup.objects.create(recipe=self.recipe, title='')
        Ingredient.objects.create(
            ingredient_group=group, title='kosher salt'
        )

        self.plan_and_log(MenuItem.Meal.DINNER, {'kcal': 400}, [(self.me, 1)])

        response = self.get()
        note = response.data['days'][0]['people'][0]['note']

        self.assertTrue(note['salt_not_counted'])
        self.assertIn('kosher salt', note['unmatched'])

    def test_the_worst_confidence_of_the_day_is_the_days_confidence(self):
        from v1.ingredient.models import Ingredient, IngredientGroup
        from v1.nutrition.models import Food, FoodNutrient

        food = Food.objects.create(fdc_id=1, description='Beans')
        FoodNutrient.objects.create(food=food, nutrient='kcal', amount=127)

        # A fully matched recipe: high confidence.
        good = Recipe.objects.create(
            title='Beans', author=self.me, household=self.household, servings=2
        )
        good_group = IngredientGroup.objects.create(recipe=good, title='')
        Ingredient.objects.create(
            ingredient_group=good_group, title='beans', food=food, grams=200
        )

        # A half-matched one: medium at best.
        patchy_group = IngredientGroup.objects.create(recipe=self.recipe, title='')
        Ingredient.objects.create(
            ingredient_group=patchy_group, title='beans', food=food, grams=200
        )
        Ingredient.objects.create(ingredient_group=patchy_group, title='mystery')

        good_item = MenuItem.objects.create(
            household=self.household, author=self.me, recipe=good,
            date=self.monday, week_start=self.monday,
            meal=MenuItem.Meal.LUNCH,
        )
        for item in (good_item,):
            view = views.MenuItemViewSet.as_view({'post': 'log'})
            request = self.factory.post(
                '/api/v1/menu/menu-item/%s/log/' % item.id,
                data={'logs': [{'user': self.me.id, 'servings': 1}]},
                format='json',
            )
            request.user = self.me
            view(request, pk=item.id)

        self.plan_and_log(MenuItem.Meal.DINNER, None, [(self.me, 1)])

        response = self.get()
        note = response.data['days'][0]['people'][0]['note']

        self.assertEqual(note['logged_meals'], 2)
        self.assertEqual(note['confidence'], 'medium')

    def test_the_range_is_filtered(self):
        self.plan_and_log(
            MenuItem.Meal.DINNER, {'kcal': 400}, [(self.me, 1)],
            date=self.monday,
        )
        self.plan_and_log(
            MenuItem.Meal.DINNER, {'kcal': 400}, [(self.me, 1)],
            date=datetime.date(2026, 11, 23),
        )

        response = self.get('?from=2026-11-09&to=2026-11-15')

        self.assertEqual(len(response.data['days']), 1)
        self.assertEqual(response.data['days'][0]['date'], self.monday)

    def test_a_bad_date_is_a_400(self):
        response = self.get('?from=last-tuesday')

        self.assertEqual(response.status_code, 400)

    def test_another_household_sees_nothing(self):
        self.plan_and_log(MenuItem.Meal.DINNER, {'kcal': 400}, [(self.me, 1)])

        neighbour = User.objects.create_user(
            username='neighbour', email='n@example.com', password='top_secret'
        )
        Household.objects.create(name='Next door').members.add(neighbour)

        request = self.factory.get('/api/v1/menu/day-nutrition/')
        request.user = neighbour
        response = views.DayNutritionView.as_view()(request)

        self.assertEqual(response.data['days'], [])

    def test_anonymous_is_refused(self):
        request = self.factory.get('/api/v1/menu/day-nutrition/')
        response = views.DayNutritionView.as_view()(request)

        self.assertIn(response.status_code, (401, 403))
