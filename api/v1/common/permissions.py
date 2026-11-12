#!/usr/bin/env python
# encoding: utf-8

from rest_framework import permissions


class IsHouseholdMember(permissions.BasePermission):
    """
    The one object permission for everything a household shares.

    Replaces IsListOwner, IsItemOwner, IsMenuItemOwner and IsOwnerOrReadOnly,
    which between them allowed only `obj.author == request.user` and so made
    shared data unreachable for whichever spouse had not created it. Two of
    them were also broken outright: IsItemOwner dereferenced
    `obj.list.groceryshared`, which is not a valid reverse accessor, and
    IsOwnerOrReadOnly looked for `obj.recipe.author` on models that have no
    `recipe`.

    A view declares how to get from one of its objects to a Household:

        class GroceryItemViewSet(viewsets.ModelViewSet):
            household_path = 'list.household'

    The default is 'household', which covers every model that holds the FK
    directly. Querysets must still be scoped: DRF never runs object
    permissions against a list endpoint.
    """
    household_path = 'household'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        household = obj
        path = getattr(view, 'household_path', self.household_path)
        for attr in path.split('.'):
            household = getattr(household, attr, None)
            if household is None:
                # An unassigned row belongs to no house, so no member of one
                # can reach it.
                return False

        return household.members.filter(pk=request.user.pk).exists()
