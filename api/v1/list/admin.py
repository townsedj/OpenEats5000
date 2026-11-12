#!/usr/bin/env python
# encoding: utf-8

from django.contrib import admin

from .models import GroceryList, GroceryItem
from .serializers import GroceryItemSerializer


class GroceryListInline(admin.TabularInline):
    model = GroceryItem
    ser = GroceryItemSerializer


class GroceryListAdmin(admin.ModelAdmin):
    list_display = ['title', 'household', 'author']
    list_filter = ['household', 'author']
    search_fields = ['author__username', 'title']
    ordering = ['author__username', 'title']


class GroceryItemAdmin(admin.ModelAdmin):
    list_display = ['list', 'title', 'aisle', 'completed']
    list_filter = ['list', 'completed']
    ordering = ['list', 'order']
    search_fields = ['title']


admin.site.register(GroceryList, GroceryListAdmin)
admin.site.register(GroceryItem, GroceryItemAdmin)
