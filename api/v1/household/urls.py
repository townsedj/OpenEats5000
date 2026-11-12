#!/usr/bin/env python
# encoding: utf-8

from django.urls import path

from . import views

urlpatterns = [
    path('me/', views.CurrentHouseholdView.as_view(), name='household_me'),
    path('profile/', views.ProfileView.as_view(), name='household_profile'),
    path(
        'nutrition-target/',
        views.NutritionTargetView.as_view(),
        name='household_nutrition_target'
    ),
    path(
        'nutrition-target/preset/',
        views.TargetPresetView.as_view(),
        name='household_target_preset'
    ),
]
