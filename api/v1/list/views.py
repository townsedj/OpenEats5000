#!/usr/bin/env python
# encoding: utf-8

from rest_framework import filters, generics, viewsets, status
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from v1.common.permissions import IsHouseholdMember
from v1.household.models import Household
from .models import GroceryList, GroceryItem
from .serializers import GroceryListSerializer, \
    GroceryItemSerializer, BulkGroceryItemSerializer


class GroceryListViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions.

    Every list belongs to a household, and every member of that household
    can read and write it. There is no per-list sharing any more: the old
    GroceryShared model, and the `author == user` filter it tried to widen,
    are gone.
    """
    lookup_field = 'slug'
    serializer_class = GroceryListSerializer
    permission_classes = (IsHouseholdMember,)

    def get_queryset(self):
        user = self.request.user
        if user and not user.is_anonymous:
            return GroceryList.objects.filter(
                household=Household.objects.for_user(user)
            )
        return GroceryList.objects.none()


class GroceryItemViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions.
    Allows filtering by GroceryList `list={list_id}`
    """
    serializer_class = GroceryItemSerializer
    permission_classes = (IsHouseholdMember,)
    household_path = 'list.household'
    filter_backends = (filters.SearchFilter, DjangoFilterBackend)
    filterset_fields = ('list', 'completed', 'aisle', 'menu_item')

    def get_queryset(self):
        user = self.request.user
        if user and not user.is_anonymous:
            return GroceryItem.objects.filter(
                list__household=Household.objects.for_user(user)
            )
        return GroceryItem.objects.none()


class BulkGroceryItemViewSet(generics.GenericAPIView):
    """
    Bulk create, update and destroy for grocery items.

    Request and response shapes are unchanged from the djangorestframework-bulk
    version this replaces, because web/modules/list/ depends on them:

      POST   [{list, title, completed, order}, ...]  -> 201 + created items
      PUT    [{id, list, title, completed, order}, ...] -> 200 + updated items
      PATCH  [{id, <changed fields>}, ...]           -> 200 + updated items
      DELETE [id, id, ...]                           -> 204

    Every method works through get_queryset(), so a caller can only touch
    items on their own household's lists.
    """
    serializer_class = BulkGroceryItemSerializer
    permission_classes = (IsHouseholdMember,)
    household_path = 'list.household'

    def get_queryset(self):
        user = self.request.user
        if user and not user.is_anonymous:
            return GroceryItem.objects.filter(
                list__household=Household.objects.for_user(user)
            )
        return GroceryItem.objects.none()

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def put(self, request, *args, **kwargs):
        return self._bulk_update(request, partial=False)

    def patch(self, request, *args, **kwargs):
        return self._bulk_update(request, partial=True)

    def _bulk_update(self, request, partial):
        if not isinstance(request.data, list):
            return Response(
                {'detail': 'Expected a list of items.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        ids = [item.get('id') for item in request.data if isinstance(item, dict)]
        instances = list(self.get_queryset().filter(id__in=ids))

        serializer = self.get_serializer(
            instances, data=request.data, many=True, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, *args, **kwargs):
        try:
            ids = [int(pk) for pk in request.data]
        except (TypeError, ValueError):
            return Response(
                {'detail': 'Expected a list of item ids.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        self.get_queryset().filter(id__in=ids).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
