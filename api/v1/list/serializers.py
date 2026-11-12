#!/usr/bin/env python
# encoding: utf-8

from rest_framework import serializers

from v1.household.models import Household
from v1.household.serializers import CurrentHouseholdDefault
from .models import GroceryList, GroceryItem


class HouseholdScopedItem:
    """
    Refuses to attach an item to a list or a planned meal outside the
    caller's household.

    Object permissions only run against rows that already exist, so without
    this a member could POST an item carrying another household's list id.
    """

    def _check_household(self, value, field):
        if value is None:
            return value
        household = Household.objects.for_user(self.context['request'].user)
        owner_id = getattr(value, 'household_id', None)
        if owner_id != household.id:
            # Same message either way: do not reveal whether the row exists.
            raise serializers.ValidationError('No such %s.' % field)
        return value

    def validate_list(self, value):
        return self._check_household(value, 'list')

    def validate_menu_item(self, value):
        return self._check_household(value, 'menu item')


class GroceryItemSerializer(HouseholdScopedItem, serializers.ModelSerializer):
    """Generic Serializer for grocery items"""
    class Meta:
        model = GroceryItem
        fields = (
            'id', 'list', 'title', 'completed', 'order',
            'menu_item', 'aisle', 'updated_at',
        )
        read_only_fields = ('updated_at',)


class GroceryListSerializer(serializers.ModelSerializer):
    """
    Generic Serializer for grocery lists.
    This Serializer will also return the username
    of the user that owns the list.
    """
    author = serializers.ReadOnlyField(source='author.username')
    # Never taken from the request body: a client cannot file a list under
    # somebody else's house.
    household = serializers.HiddenField(default=CurrentHouseholdDefault())

    class Meta:
        model = GroceryList
        fields = (
            'id', 'title', 'slug', 'pub_date', 'author', 'household', 'item_count',
        )

    def create(self, validated_data):
        # Create the Grocery List.
        # Use the log-in user as the author.
        grocery_list = GroceryList.objects.create(
            author=self.context['request'].user,
            **validated_data
        )

        return grocery_list


class BulkGroceryItemListSerializer(serializers.ListSerializer):
    """
    Pairs each object in the request with an existing row by its `id`.

    DRF's ListSerializer refuses to implement update() on purpose, because in
    general there is no way to know which input belongs to which instance. Here
    there is: the front end always sends the id next to the changed fields
    (see toggleAll and orderAll in web/modules/list/actions/ItemActions.js), so
    pairing on id is unambiguous.

    Replaces djangorestframework-bulk, which is unmaintained.
    """

    def update(self, instance, validated_data):
        items_by_id = {item.id: item for item in instance}

        updated = []
        for data in validated_data:
            item = items_by_id.get(data.pop('id', None))
            # Anything the caller does not own was filtered out of the queryset
            # before it got here, so an unknown id is silently skipped rather
            # than leaking whether the row exists.
            if item is not None:
                updated.append(self.child.update(item, data))

        return updated


class BulkGroceryItemSerializer(HouseholdScopedItem, serializers.ModelSerializer):
    """ Used to perform bulk operations on the GroceryItem model. """

    class Meta:
        model = GroceryItem
        list_serializer_class = BulkGroceryItemListSerializer
        fields = (
            'id', 'list', 'title', 'completed', 'order',
            'menu_item', 'aisle', 'updated_at',
        )
        read_only_fields = ('updated_at',)

    def to_internal_value(self, data):
        ret = super().to_internal_value(data)

        # `id` is read-only, so it never reaches validated_data on its own.
        # Bulk updates need it to pair input with rows, so put it back for
        # those methods only, keeping it unwritable on create.
        request = self.context.get('request')
        if request is not None and request.method in ('PUT', 'PATCH'):
            try:
                ret['id'] = int(data['id'])
            except (KeyError, TypeError, ValueError):
                raise serializers.ValidationError(
                    {'id': 'A numeric id is required for each item in a bulk update.'}
                )

        return ret
