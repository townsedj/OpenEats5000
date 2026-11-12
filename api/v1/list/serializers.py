#!/usr/bin/env python
# encoding: utf-8

from rest_framework import serializers
from .models import GroceryList, GroceryItem


class GroceryItemSerializer(serializers.ModelSerializer):
    """Generic Serializer for grocery items"""
    class Meta:
        model = GroceryItem
        fields = ('id', 'list', 'title', 'completed', 'order')


class GroceryListSerializer(serializers.ModelSerializer):
    """
    Generic Serializer for grocery lists.
    This Serializer will also return the username
    of the user that owns the list.
    """
    author = serializers.ReadOnlyField(source='author.username')

    class Meta:
        model = GroceryList
        fields = ('id', 'title', 'slug', 'pub_date', 'author', 'item_count')

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


class BulkGroceryItemSerializer(serializers.ModelSerializer):
    """ Used to perform bulk operations on the GroceryItem model. """

    class Meta:
        model = GroceryItem
        list_serializer_class = BulkGroceryItemListSerializer
        fields = ('id', 'list', 'title', 'completed', 'order')

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
