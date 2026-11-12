#!/usr/bin/env python
# encoding: utf-8

from django.contrib.auth.models import User

from v1.household.models import Household
from v1.list.models import GroceryList
from v1.menu.models import MenuItem
from v1.recipe.models import Recipe


def one_household(name='Test Household'):
    """
    Put every user and every fixture row into a single household.

    The JSON fixtures predate household scoping, so their recipes, lists and
    menu items load with household=NULL and a scoped queryset cannot see
    them. Call this from setUp(), which runs after fixtures have loaded.

    Returns the household, whose `members` are every user in the database --
    which is the point: these tests now assert that both people can see the
    shared data, where they used to assert that only the author could.
    """
    household = Household.objects.create(name=name)
    household.members.add(*User.objects.all())

    Recipe.objects.update(household=household)
    GroceryList.objects.update(household=household)
    MenuItem.objects.update(household=household)

    return household
