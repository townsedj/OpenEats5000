#!/usr/bin/env python
# encoding: utf-8

from rest_framework import renderers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import News
from .serializers import NewsSerializer
from v1.common.permissions import IsAdminOrReadOnly


class NewsViewSet(viewsets.ModelViewSet):
    """
    This viewset automatically provides `list`, `create`, `retrieve`,
    `update` and `destroy` actions for THe homepage News items.
    """
    queryset = News.objects.all()
    serializer_class = NewsSerializer
    permission_classes = (IsAdminOrReadOnly,)

    # detail_route was removed in DRF 3.10; @action(detail=True) is the
    # replacement and keeps the same /entry/{pk}/title/ URL.
    @action(detail=True, renderer_classes=[renderers.StaticHTMLRenderer])
    def title(self, request, *args, **kwargs):
        entry = self.get_object()
        return Response(entry.content)
