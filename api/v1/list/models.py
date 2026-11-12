#!/usr/bin/env python
# encoding: utf-8

from django.db import models
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django_extensions.db.fields import AutoSlugField

from v1.household.models import Household


class GroceryList(models.Model):
    """
    The GroceryList is the core of list app.
    It offers a home to many GroceryItems.
    title = The name of the GroceryList.
    slug = The HTML safe name of the GroceryList.
    author = The User who created the GroceryList.
    household = The house that shares the GroceryList.
    pub_date = The date that the GroceryList was created on.
    """
    title = models.CharField(_("grocery list title"), max_length=250)
    slug = AutoSlugField(_('slug'), populate_from='title')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name='grocery_lists',
        null=True, blank=True
    )
    pub_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['pub_date']

    def __str__(self):
        return '%s' % self.title

    def item_count(self):
        """get the number of items in the list"""
        return GroceryItem.objects.filter(list=self).count()


class GroceryItem(models.Model):
    """
    The GroceryItem is an item on a GroceryList.
    list = The GroceryList that owns the GroceryItem.
    title = The name of the GroceryItem.
    completed = Whether or not the GroceryItem has been purchased or
                added to the users shopping cart in the supermarket.
    order = The order of the item in the GroceryList.
    menu_item = The planned meal this item was added for, if any. Lets the
                shopping screen group by meal and lets a cancelled meal
                take its ingredients off the list.
    aisle = Free text used to group the list for one trip round the shop.
            Not a foreign key on purpose: aisles differ per shop and are
            not worth a table.
    updated_at = Last change, so an offline client can reconcile its queue.
    """
    list = models.ForeignKey(GroceryList, on_delete=models.CASCADE, related_name='items')
    title = models.CharField(_("title"), max_length=550)
    completed = models.BooleanField(_("completed"), default=False)
    order = models.IntegerField(_("order"), default=0)
    menu_item = models.ForeignKey(
        'menu.MenuItem', on_delete=models.SET_NULL, related_name='grocery_items',
        null=True, blank=True
    )
    aisle = models.CharField(_("aisle"), max_length=100, blank=True)
    # Nullable because `loaddata` saves raw, which skips the pre_save that
    # fills an auto_now field in -- a non-null column makes every fixture
    # that predates this field unloadable. Any save through the ORM sets it.
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ['list_id', 'order', 'pk']

    def __str__(self):
        return '%s' % self.title
