#!/usr/bin/env python
# encoding: utf-8

from django.contrib import admin

from .models import Household, NutritionTarget, Profile


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ('name', 'default_salt', 'kosher_salt', 'created')
    filter_horizontal = ('members',)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'default_servings', 'show_nutrition')


@admin.register(NutritionTarget)
class NutritionTargetAdmin(admin.ModelAdmin):
    list_display = ('user', 'kcal', 'protein_g', 'carb_g', 'fat_g', 'fibre_g')
