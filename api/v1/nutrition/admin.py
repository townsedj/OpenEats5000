#!/usr/bin/env python
# encoding: utf-8

from django.contrib import admin

from .models import Food, FoodNutrient, FoodPortion


class FoodNutrientInline(admin.TabularInline):
    model = FoodNutrient
    extra = 0


class FoodPortionInline(admin.TabularInline):
    model = FoodPortion
    extra = 0


@admin.register(Food)
class FoodAdmin(admin.ModelAdmin):
    list_display = ['description', 'data_type', 'category', 'fdc_id']
    list_filter = ['data_type', 'category']
    search_fields = ['description', 'fdc_id']
    inlines = [FoodNutrientInline, FoodPortionInline]
