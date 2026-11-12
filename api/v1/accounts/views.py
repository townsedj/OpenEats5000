#!/usr/bin/env python
# encoding: utf-8

from rest_framework_simplejwt.views import (
    TokenObtainSlidingView,
    TokenRefreshSlidingView,
)

from .serializers import (
    OpenEatsTokenObtainSerializer,
    OpenEatsTokenRefreshSerializer,
)


class ObtainAuthToken(TokenObtainSlidingView):
    """ Log in: {username, password} -> {token, id} """
    serializer_class = OpenEatsTokenObtainSerializer


class RefreshAuthToken(TokenRefreshSlidingView):
    """ Refresh: {token} -> {token, id} """
    serializer_class = OpenEatsTokenRefreshSerializer
