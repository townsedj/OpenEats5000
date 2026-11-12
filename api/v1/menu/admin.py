#!/usr/bin/env python
# encoding: utf-8

from django.contrib import admin

from .models import MenuItem, ServingLog


class ServingLogInline(admin.TabularInline):
    model = ServingLog
    extra = 0


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'household', 'kind', 'date', 'week_start', 'status']
    list_filter = ['household', 'kind', 'status']
    search_fields = ['title', 'recipe__title']
    inlines = [ServingLogInline]


@admin.register(ServingLog)
class ServingLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'menu_item', 'servings', 'date']
    list_filter = ['user']
