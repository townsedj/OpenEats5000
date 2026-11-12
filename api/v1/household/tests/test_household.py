#!/usr/bin/env python
# encoding: utf-8

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from v1.household import views
from v1.household.models import Household, NutritionTarget, Profile


class HouseholdManagerTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.spouse = User.objects.create_user(
            username='spouse', email='spouse@example.com', password='top_secret'
        )

    def test_first_user_gets_a_household(self):
        household = Household.objects.for_user(self.me)

        self.assertEqual(Household.objects.count(), 1)
        self.assertIn(self.me, household.members.all())

    def test_second_user_joins_the_same_household(self):
        """
        The second account joins the house rather than getting one of its
        own. That is what should happen when the other person in the house
        logs in for the first time -- they should find the shared recipes
        and shopping list already there.
        """
        mine = Household.objects.for_user(self.me)
        theirs = Household.objects.for_user(self.spouse)

        self.assertEqual(mine, theirs)
        self.assertEqual(Household.objects.count(), 1)

    def test_existing_membership_is_respected(self):
        """Someone already in a second household stays in it."""
        other = Household.objects.create(name='Next door')
        other.members.add(self.spouse)
        Household.objects.for_user(self.me)

        self.assertEqual(Household.objects.for_user(self.spouse), other)

    def test_repeated_calls_do_not_pile_up_memberships(self):
        Household.objects.for_user(self.me)
        Household.objects.for_user(self.me)

        self.assertEqual(self.me.households.count(), 1)


class NutritionTargetTests(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )

    def test_only_the_targets_that_are_set_come_back(self):
        """
        Someone tracking protein and nothing else should not be shown four
        other numbers they never set.
        """
        target = NutritionTarget.objects.create(user=self.me, protein_g=150)

        self.assertEqual(target.as_dict(), {'protein_g': 150})

    def test_targets_are_whole_day_numbers(self):
        target = NutritionTarget.objects.create(
            user=self.me, kcal=2400, protein_g=180, carb_g=250, fat_g=80, fibre_g=30
        )

        self.assertEqual(
            target.as_dict(),
            {
                'kcal': 2400, 'protein_g': 180, 'carb_g': 250,
                'fat_g': 80, 'fibre_g': 30,
            },
        )


class HouseholdViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.me = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret',
            first_name='Me'
        )
        self.spouse = User.objects.create_user(
            username='spouse', email='spouse@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.household.members.add(self.me, self.spouse)

    def get(self, view, path):
        request = self.factory.get(path)
        request.user = self.me
        return view(request)

    def test_me_returns_both_members_with_their_settings(self):
        """One request the app can boot off: who is here and how they read."""
        Profile.objects.create(
            user=self.spouse, default_servings=1.5, show_nutrition=False
        )

        response = self.get(
            views.CurrentHouseholdView.as_view(), '/api/v1/household/me/'
        )

        self.assertEqual(response.data['user_id'], self.me.id)
        members = response.data['household']['members']
        self.assertEqual(len(members), 2)

        by_username = {member['username']: member for member in members}
        self.assertEqual(by_username['spouse']['default_servings'], 1.5)
        self.assertFalse(by_username['spouse']['show_nutrition'])
        # Never created a profile for this one; it comes back on the defaults
        # rather than as nulls.
        self.assertEqual(by_username['me']['default_servings'], 1)
        self.assertTrue(by_username['me']['show_nutrition'])

    def test_nutrition_target_is_created_on_first_read(self):
        """So the front end always has a row to PATCH."""
        response = self.get(
            views.NutritionTargetView.as_view(),
            '/api/v1/household/nutrition-target/',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['kcal'])
        self.assertTrue(NutritionTarget.objects.filter(user=self.me).exists())

    def test_targets_are_private_to_each_person(self):
        """
        Shared meals, separate goals. Patching mine must not touch theirs.
        """
        view = views.NutritionTargetView.as_view()
        request = self.factory.patch(
            '/api/v1/household/nutrition-target/',
            data={'kcal': 2400}, format='json'
        )
        request.user = self.me
        response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['kcal'], 2400)
        self.assertFalse(NutritionTarget.objects.filter(user=self.spouse).exists())

    def test_anonymous_is_refused(self):
        request = self.factory.get('/api/v1/household/me/')
        response = views.CurrentHouseholdView.as_view()(request)

        self.assertIn(response.status_code, (401, 403))


class TargetPresetViewTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.me = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.household.members.add(self.me)

    def post(self, payload, user=None):
        request = self.factory.post(
            '/api/v1/household/nutrition-target/preset/',
            data=payload, format='json',
        )
        request.user = user or self.me
        return views.TargetPresetView.as_view()(request)

    def test_preset_fills_the_blanks_and_reports_what_it_filled(self):
        response = self.post({'preset': 'female'})

        self.assertEqual(response.status_code, 200)
        self.assertIn('iron_mg', response.data['filled'])
        self.assertEqual(response.data['target']['fibre_g'], 25)
        self.assertEqual(response.data['target']['all_targets']['iron_mg'], 18)

    def test_an_unknown_preset_is_refused(self):
        response = self.post({'preset': 'guess'})

        self.assertEqual(response.status_code, 400)

    def test_an_unknown_nutrient_key_is_refused(self):
        """A typo in a target key must not silently vanish into the blob."""
        request = self.factory.patch(
            '/api/v1/household/nutrition-target/',
            data={'micro_targets': {'irn_mg': 18}}, format='json',
        )
        request.user = self.me
        response = views.NutritionTargetView.as_view()(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn('micro_targets', response.data)
