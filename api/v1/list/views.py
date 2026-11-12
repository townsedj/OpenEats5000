#!/usr/bin/env python
# encoding: utf-8

from rest_framework import filters, generics, viewsets, status
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

from .models import GroceryList, GroceryItem
from .serializers import GroceryListSerializer, \
    GroceryItemSerializer, BulkGroceryItemSerializer
from .permissions import IsListOwner, IsItemOwner


class GroceryListViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions.
    """
    lookup_field = 'slug'
    serializer_class = GroceryListSerializer
    permission_classes = (IsListOwner,)

    def get_queryset(self):
        user = self.request.user
        if user and not user.is_anonymous:
            return GroceryList.objects.filter(
                Q(author=user) | Q(groceryshared__shared_to=user)
            )
        return GroceryList.objects.none()


class GroceryItemViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions.
    Allows filtering by GroceryList `list={list_id}`
    """
    serializer_class = GroceryItemSerializer
    permission_classes = (IsItemOwner,)
    filter_backends = (filters.SearchFilter, DjangoFilterBackend)
    filterset_fields = ('list',)

    def get_queryset(self):
        user = self.request.user
        if user and not user.is_anonymous:
            return GroceryItem.objects.filter(
                Q(list__author=user) | Q(list__groceryshared__shared_to=user)
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

    Every method works through get_queryset(), so a caller can only touch items
    on lists they own or that are shared with them.
    """
    serializer_class = BulkGroceryItemSerializer
    permission_classes = (IsItemOwner,)

    def get_queryset(self):
        user = self.request.user
        if user and not user.is_anonymous:
            return GroceryItem.objects.filter(
                Q(list__author=user) | Q(list__groceryshared__shared_to=user)
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
