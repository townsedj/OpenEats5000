#!/usr/bin/env python
# encoding: utf-8

from django.urls import path

from . import views

# Paths are unchanged from the djangorestframework-jwt version; the front end
# has them hard-coded in web/modules/common/config.js.
urlpatterns = [
    path('obtain-auth-token/', views.ObtainAuthToken.as_view()),
    path('refresh-auth-token/', views.RefreshAuthToken.as_view()),
]
