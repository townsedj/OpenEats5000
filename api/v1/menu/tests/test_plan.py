#!/usr/bin/env python
# encoding: utf-8

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from v1.household.models import Household
from v1.menu import views
from v1.menu.models import MenuItem, ServingLog
from v1.recipe.models import Recipe


class PlanTestCase(TestCase):
    """Two people, one house, one recipe -- the shape this app is for."""

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
            servings=8, prep_time=20, cook_time=40,
        )

        self.monday = datetime.date(2026, 11, 9)

    def plan(self, **kwargs):
        defaults = dict(
            household=self.household,
            author=self.me,
            recipe=self.recipe,
            date=self.monday,
            week_start=self.monday,
            meal=MenuItem.Meal.DINNER,
        )
        defaults.update(kwargs)
        return MenuItem.objects.create(**defaults)

    def call(self, view, request):
        request.user = self.me
        return view(request)


class MealSlotTests(PlanTestCase):
    def test_a_day_holds_a_meal_at_a_time(self):
        """
        Breakfast, lunch and dinner all live on the same day, and come back
        in the order the day happens in -- not alphabetically, which is what
        a text choice would have given (breakfast, dinner, lunch).
        """
        self.plan(meal=MenuItem.Meal.DINNER, title='Chili')
        self.plan(meal=MenuItem.Meal.BREAKFAST, title='Porridge', recipe=None)
        self.plan(meal=MenuItem.Meal.LUNCH, title='Leftovers', recipe=None)
        self.plan(meal=MenuItem.Meal.SNACK, title='Apple', recipe=None)

        titles = [item.display_title() for item in MenuItem.objects.all()]

        self.assertEqual(titles, ['Porridge', 'Leftovers', 'Chili', 'Apple'])

    def test_two_entries_can_share_a_slot(self):
        """Nothing is unique per day and meal: a dinner can be two dishes."""
        self.plan(title='Chili')
        self.plan(title='Cornbread', recipe=None)

        self.assertEqual(
            MenuItem.objects.filter(date=self.monday, meal=MenuItem.Meal.DINNER).count(),
            2,
        )

    def test_meal_label_is_serialised_for_the_screen(self):
        """`meal` is the integer that sorts the day; the label is the word."""
        item = self.plan(meal=MenuItem.Meal.LUNCH)

        view = views.MenuItemViewSet.as_view({'get': 'retrieve'})
        request = self.factory.get('/api/v1/menu/menu-item/%s/' % item.id)
        request.user = self.me
        response = view(request, pk=item.id)

        self.assertEqual(response.data['meal'], MenuItem.Meal.LUNCH)
        self.assertEqual(response.data['meal_label'], 'lunch')


class PlanListTests(PlanTestCase):
    def test_week_start_is_derived_from_the_date(self):
        view = views.MenuItemViewSet.as_view({'post': 'create'})
        request = self.factory.post(
            '/api/v1/menu/menu-item/',
            data={
                'recipe': self.recipe.id,
                'date': '2026-11-12',  # a Thursday
                'meal': MenuItem.Meal.DINNER,
            },
            format='json',
        )
        response = self.call(view, request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['week_start'], '2026-11-09')

    def test_an_undated_entry_still_belongs_to_a_week(self):
        """
        The "any day" tray: an entry with no date is planned for a week, and
        pinning dinners to specific days is what makes plans wrong.
        """
        view = views.MenuItemViewSet.as_view({'post': 'create'})
        request = self.factory.post(
            '/api/v1/menu/menu-item/',
            data={'recipe': self.recipe.id, 'meal': MenuItem.Meal.DINNER},
            format='json',
        )
        response = self.call(view, request)

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['date'])
        self.assertIsNotNone(response.data['week_start'])

    def test_date_range_includes_undated_entries_of_the_same_week(self):
        dated = self.plan(date=self.monday)
        undated = self.plan(date=None, week_start=self.monday)
        other_week = self.plan(
            date=datetime.date(2026, 11, 23), week_start=datetime.date(2026, 11, 23)
        )

        view = views.MenuItemViewSet.as_view({'get': 'list'})
        request = self.factory.get(
            '/api/v1/menu/menu-item/?from=2026-11-09&to=2026-11-15'
        )
        response = self.call(view, request)

        ids = {row['id'] for row in response.data['results']}
        self.assertEqual(ids, {dated.id, undated.id})
        self.assertNotIn(other_week.id, ids)

    def test_a_bad_date_is_a_400_not_a_500(self):
        view = views.MenuItemViewSet.as_view({'get': 'list'})
        request = self.factory.get('/api/v1/menu/menu-item/?from=last-tuesday')
        response = self.call(view, request)

        self.assertEqual(response.status_code, 400)

    def test_card_carries_what_the_plan_screen_needs(self):
        item = self.plan()

        view = views.MenuItemViewSet.as_view({'get': 'list'})
        response = self.call(view, self.factory.get('/api/v1/menu/menu-item/'))

        card = response.data['results'][0]
        self.assertEqual(card['id'], item.id)
        self.assertEqual(card['display_title'], 'Tasty Chili')
        # Prep plus cook as one number, which is the only time anyone reads.
        self.assertEqual(card['total_time'], 60)
        self.assertEqual(card['servings'], 8)
        self.assertEqual(card['logs'], [])
        self.assertIn('photo_thumbnail', card['recipe_data'])

    def test_another_household_cannot_see_the_plan(self):
        self.plan()
        neighbour = User.objects.create_user(
            username='neighbour', email='n@example.com', password='top_secret'
        )
        Household.objects.create(name='Next door').members.add(neighbour)

        view = views.MenuItemViewSet.as_view({'get': 'list'})
        request = self.factory.get('/api/v1/menu/menu-item/')
        request.user = neighbour
        response = view(request)

        self.assertEqual(response.data['results'], [])

    def test_an_entry_needs_something_to_show(self):
        view = views.MenuItemViewSet.as_view({'post': 'create'})
        request = self.factory.post(
            '/api/v1/menu/menu-item/',
            data={'meal': MenuItem.Meal.DINNER, 'kind': MenuItem.Kind.NOTE},
            format='json',
        )
        response = self.call(view, request)

        self.assertEqual(response.status_code, 400)
        self.assertIn('title', response.data)

    def test_cannot_plan_another_household_recipe(self):
        theirs = Household.objects.create(name='Next door')
        their_recipe = Recipe.objects.create(
            title='Not ours', author=self.me, household=theirs, servings=2
        )

        view = views.MenuItemViewSet.as_view({'post': 'create'})
        request = self.factory.post(
            '/api/v1/menu/menu-item/',
            data={'recipe': their_recipe.id, 'date': '2026-11-12'},
            format='json',
        )
        response = self.call(view, request)

        self.assertEqual(response.status_code, 400)
        self.assertIn('recipe', response.data)


class LoggingTests(PlanTestCase):
    def post_log(self, item, payload, user=None):
        view = views.MenuItemViewSet.as_view({'post': 'log'})
        request = self.factory.post(
            '/api/v1/menu/menu-item/%s/log/' % item.id, data=payload, format='json'
        )
        request.user = user or self.me
        return view(request, pk=item.id)

    def test_one_request_logs_both_portions(self):
        """
        Different portions of the same food is the normal case for a shared
        lunch or dinner, which is why portions are rows of their own rather
        than a number on the plan entry.
        """
        item = self.plan()

        response = self.post_log(item, {
            'logs': [
                {'user': self.me.id, 'servings': 1.5},
                {'user': self.spouse.id, 'servings': 1},
            ],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ServingLog.objects.count(), 2)

        portions = dict(ServingLog.objects.values_list('user__username', 'servings'))
        self.assertEqual(portions, {'me': 1.5, 'spouse': 1})

        item.refresh_from_db()
        self.assertEqual(item.status, MenuItem.Status.EATEN)

    def test_either_person_can_log_for_the_other(self):
        item = self.plan()

        self.post_log(
            item,
            {'logs': [{'user': self.me.id, 'servings': 2}]},
            user=self.spouse,
        )

        log = ServingLog.objects.get()
        self.assertEqual(log.user, self.me)
        self.assertEqual(log.logged_by, self.spouse)

    def test_logging_again_corrects_the_portion(self):
        """One row per person per meal, so a correction is not a duplicate."""
        item = self.plan()

        self.post_log(item, {'logs': [{'user': self.me.id, 'servings': 1}]})
        self.post_log(item, {'logs': [{'user': self.me.id, 'servings': 2}]})

        self.assertEqual(ServingLog.objects.count(), 1)
        self.assertEqual(ServingLog.objects.get().servings, 2)

    def test_logging_an_undated_entry_dates_it(self):
        item = self.plan(date=None, week_start=self.monday)

        self.post_log(item, {
            'date': '2026-11-11',
            'logs': [{'user': self.me.id, 'servings': 1}],
        })

        item.refresh_from_db()
        self.assertEqual(item.date, datetime.date(2026, 11, 11))
        self.assertEqual(item.week_start, self.monday)

    def test_eaten_on_a_different_day_than_planned(self):
        item = self.plan(date=self.monday)

        self.post_log(item, {
            'date': '2026-11-11',
            'logs': [{'user': self.me.id, 'servings': 1}],
        })

        self.assertEqual(ServingLog.objects.get().date, datetime.date(2026, 11, 11))
        # The plan entry keeps the day it was planned for.
        item.refresh_from_db()
        self.assertEqual(item.date, self.monday)

    def test_macros_are_snapshotted_at_log_time(self):
        """
        Editing a recipe next month must not rewrite what somebody ate last
        month, so the numbers are copied into the row.
        """
        item = self.plan()
        item.est_nutrition = {'kcal': 500, 'protein_g': 40}
        item.save()

        self.post_log(item, {'logs': [{'user': self.me.id, 'servings': 1.5}]})

        log = ServingLog.objects.get()
        self.assertEqual(log.kcal, 750)
        self.assertEqual(log.protein_g, 60)
        # Nothing was estimated for these, and a guess of zero would be worse
        # than admitting we do not know.
        self.assertIsNone(log.carb_g)

        item.est_nutrition = {'kcal': 1, 'protein_g': 1}
        item.save()
        log.refresh_from_db()
        self.assertEqual(log.kcal, 750)

    def test_macros_stay_null_until_nutrition_exists(self):
        """Logging ships before nutrition does; portions are the real data."""
        item = self.plan()

        self.post_log(item, {'logs': [{'user': self.me.id, 'servings': 1}]})

        log = ServingLog.objects.get()
        self.assertIsNone(log.kcal)
        self.assertEqual(log.servings, 1)

    def test_undo_drops_the_logs_and_replans_the_meal(self):
        item = self.plan()
        self.post_log(item, {
            'logs': [
                {'user': self.me.id, 'servings': 1},
                {'user': self.spouse.id, 'servings': 1},
            ],
        })

        view = views.MenuItemViewSet.as_view({'delete': 'log'})
        request = self.factory.delete('/api/v1/menu/menu-item/%s/log/' % item.id)
        request.user = self.me
        response = view(request, pk=item.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ServingLog.objects.count(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, MenuItem.Status.PLANNED)

    def test_cannot_log_a_portion_for_someone_outside_the_household(self):
        item = self.plan()
        neighbour = User.objects.create_user(
            username='neighbour', email='n@example.com', password='top_secret'
        )
        Household.objects.create(name='Next door').members.add(neighbour)

        response = self.post_log(item, {
            'logs': [{'user': neighbour.id, 'servings': 1}],
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ServingLog.objects.count(), 0)

    def test_cannot_log_another_household_meal(self):
        item = self.plan()
        neighbour = User.objects.create_user(
            username='neighbour', email='n@example.com', password='top_secret'
        )
        Household.objects.create(name='Next door').members.add(neighbour)

        response = self.post_log(
            item, {'logs': [{'user': neighbour.id, 'servings': 1}]}, user=neighbour
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ServingLog.objects.count(), 0)

    def test_two_portions_for_one_person_is_rejected(self):
        item = self.plan()

        response = self.post_log(item, {
            'logs': [
                {'user': self.me.id, 'servings': 1},
                {'user': self.me.id, 'servings': 2},
            ],
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ServingLog.objects.count(), 0)

    def test_a_days_intake_is_the_sum_of_one_persons_portions(self):
        """
        What tracking a whole day against a goal rests on: every meal of the
        day contributes one row per person.
        """
        for meal in (MenuItem.Meal.BREAKFAST, MenuItem.Meal.LUNCH, MenuItem.Meal.DINNER):
            item = self.plan(meal=meal, est_nutrition={'kcal': 400})
            self.post_log(item, {
                'logs': [
                    {'user': self.me.id, 'servings': 1},
                    {'user': self.spouse.id, 'servings': 0.5},
                ],
            })

        mine = ServingLog.objects.filter(user=self.me, date=self.monday)
        theirs = ServingLog.objects.filter(user=self.spouse, date=self.monday)

        self.assertEqual(sum(log.kcal for log in mine), 1200)
        self.assertEqual(sum(log.kcal for log in theirs), 600)


class MenuStatsTests(PlanTestCase):
    def test_stats_are_scoped_to_the_household(self):
        """
        This endpoint had no owner filter at all: it reported every recipe on
        the install to every caller.
        """
        eaten = self.plan(status=MenuItem.Status.EATEN)

        theirs = Household.objects.create(name='Next door')
        neighbour = User.objects.create_user(
            username='neighbour', email='n@example.com', password='top_secret'
        )
        theirs.members.add(neighbour)
        their_recipe = Recipe.objects.create(
            title='Theirs', author=neighbour, household=theirs, servings=2
        )
        MenuItem.objects.create(
            household=theirs, author=neighbour, recipe=their_recipe,
            date=self.monday, week_start=self.monday,
            status=MenuItem.Status.EATEN,
        )

        request = self.factory.get('/api/v1/menu/menu-stats/')
        request.user = self.me
        response = views.MenuStatsViewSet.as_view()(request)

        titles = [row['title'] for row in response.data]
        self.assertEqual(titles, ['Tasty Chili'])
        self.assertEqual(response.data[0]['num_menuitems'], 1)
        self.assertEqual(response.data[0]['last_made'], eaten.date)

    def test_only_eaten_meals_count_as_made(self):
        self.plan(status=MenuItem.Status.PLANNED)

        request = self.factory.get('/api/v1/menu/menu-stats/')
        request.user = self.me
        response = views.MenuStatsViewSet.as_view()(request)

        self.assertEqual(list(response.data), [])
