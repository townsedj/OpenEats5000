#!/usr/bin/env python
# encoding: utf-8

from django.test import TestCase
from django.contrib.auth.models import User, AnonymousUser
from rest_framework.test import APIRequestFactory

from v1.common.testing import one_household
from v1.household.models import Household
from v1.list import views


class ListTests(TestCase):
    fixtures = ['test/users.json', 'test/lists.json', 'test/list_items.json']

    def setUp(self):
        self.factory = APIRequestFactory()
        # Both fixture users are in one house, which is the whole point of
        # the change these tests cover.
        self.household = one_household()

    def getResponse(self, user=None):
        view = views.GroceryListViewSet.as_view({'get': 'list'})
        request = self.factory.get('/api/v1/list/lists/')
        if user:
            request.user = user
        return view(request)

    def test_get_lists(self):
        """Check if we get the right data for a list"""
        response = self.getResponse(User.objects.get(pk=1))

        self.assertEqual(response.data.get('count'), 2)

        results = response.data.get('results')
        totals = {"test-list": 7, "another-test-list": 5}

        for item in results:
            self.assertEqual(totals[item.get('slug')], item.get('item_count'))

    def test_second_member_sees_the_same_lists(self):
        """
        The other person in the house sees the shared lists.

        This used to assert the opposite -- that user 2 got nothing back,
        because every list was filtered to `author=user`. That is the defect
        the household model removes: a grocery list the two of them shop
        from was only ever visible to whoever typed it in.
        """
        response = self.getResponse(User.objects.get(pk=2))

        self.assertEqual(response.data.get('count'), 2)

    def test_other_household_gets_nothing(self):
        """
        A member of a different household sees none of these lists.

        They have to be put in one explicitly: a brand new account joins the
        only household that exists, which is what should happen when the
        second person in the house first logs in.
        """
        outsider = User.objects.create_user(
            username='outsider', email='outsider@example.com', password='top_secret'
        )
        Household.objects.create(name='Next door').members.add(outsider)

        response = self.getResponse(outsider)

        self.assertEqual(response.data.get('results'), [])

    def test_anonymous_user_get_lists(self):
        """Anonymous callers are refused outright."""
        response = self.getResponse(AnonymousUser())

        self.assertEqual(response.status_code, 401)
