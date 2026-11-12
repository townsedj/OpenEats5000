#!/usr/bin/env python
# encoding: utf-8

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

# Create a router and register our viewsets with it.
router = DefaultRouter()
router.register(r'menu-item', views.MenuItemViewSet, basename='menu-item')

urlpatterns = [
    path('', include(router.urls)),
    path(
        'day-nutrition/',
        views.DayNutritionView.as_view(),
        name='day_nutrition'
    ),
    path(
        'menu-stats/',
        views.MenuStatsViewSet.as_view(),
        name='menu_stats'
    ),
]
