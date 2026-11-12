#!/usr/bin/env python
# encoding: utf-8

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase, RequestFactory

from v1.common.permissions import IsHouseholdMember
from v1.household.models import Household
from v1.list.models import GroceryItem, GroceryList


class HouseholdView(object):
    """Stands in for a viewset: all the permission reads off it is the path."""
    def __init__(self, household_path='household'):
        self.household_path = household_path


class IsHouseholdMemberTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.permission = IsHouseholdMember()

        self.household = Household.objects.create(name='Ours')
        self.me = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.spouse = User.objects.create_user(
            username='spouse', email='spouse@example.com', password='top_secret'
        )
        self.household.members.add(self.me, self.spouse)

        self.neighbour = User.objects.create_user(
            username='neighbour', email='neighbour@example.com', password='top_secret'
        )
        Household.objects.create(name='Theirs').members.add(self.neighbour)

        self.admin = User.objects.create_user(
            username='admin', email='admin@example.com', password='top_secret',
            is_superuser=True
        )

        self.list = GroceryList.objects.create(
            title='Shopping', author=self.me, household=self.household
        )
        self.item = GroceryItem.objects.create(list=self.list, title='Milk')
        self.orphan = GroceryList.objects.create(title='Nobody', author=self.me)

    def request_as(self, user, method='get'):
        request = getattr(self.factory, method)('/api/v1/list/lists/')
        request.user = user
        return request

    def test_member_who_did_not_create_the_row_still_has_access(self):
        """
        The spouse can read and write a list they did not create.

        This is the whole reason the permission exists: the three classes it
        replaces all compared `obj.author` to the caller, so shared data was
        only ever reachable by whoever typed it in.
        """
        view = HouseholdView()
        for method in ('get', 'post', 'put', 'delete'):
            request = self.request_as(self.spouse, method)
            self.assertTrue(
                self.permission.has_object_permission(request, view, self.list),
                '%s should be allowed for a household member' % method,
            )

    def test_other_household_is_refused(self):
        view = HouseholdView()
        request = self.request_as(self.neighbour)
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.list)
        )

    def test_nested_path(self):
        """A view can declare how to walk from its object to the household."""
        view = HouseholdView(household_path='list.household')
        request = self.request_as(self.spouse)
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.item)
        )

        request = self.request_as(self.neighbour)
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.item)
        )

    def test_row_with_no_household_is_refused(self):
        """An unassigned row belongs to no house, so no member can reach it."""
        view = HouseholdView()
        request = self.request_as(self.me)
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.orphan)
        )

    def test_superuser_sees_everything(self):
        view = HouseholdView()
        request = self.request_as(self.admin)
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.list)
        )
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.orphan)
        )

    def test_anonymous_is_refused_before_any_object_lookup(self):
        request = self.request_as(AnonymousUser())
        self.assertFalse(self.permission.has_permission(request, HouseholdView()))

    def test_authenticated_user_passes_the_view_level_check(self):
        request = self.request_as(self.me)
        self.assertTrue(self.permission.has_permission(request, HouseholdView()))
