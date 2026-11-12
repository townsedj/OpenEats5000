#!/usr/bin/env python
# encoding: utf-8
"""
Keeping a plan entry's cached nutrition estimate in step with its recipe.

Lives in its own module so both the serializer and the log endpoint can use
it without importing each other.
"""

from v1.nutrition import compute


def refresh_estimate(menu_item, save=False):
    """
    Recompute a plan entry's per-serving estimate from its recipe.

    The cache is what stops the plan screen recomputing a recipe's nutrition
    for every card it draws. Entries with no recipe are left alone: their
    estimate came from the assistant or from a person, and there is nothing
    to recompute it from.

    Called when an entry is created or edited, and again just before a meal
    is logged -- which is the moment that matters, because logging freezes
    the numbers into the ServingLog for good. Between those two moments a
    card can show an estimate that predates an edit to its recipe, which is
    a cosmetic lag rather than a wrong record.
    """
    if not menu_item.recipe_id:
        return menu_item

    result = compute.recipe_nutrition(menu_item.recipe)
    computed = result['per_serving']

    if computed:
        menu_item.est_nutrition = computed
        menu_item.est_nutrition_note = result['note']
    elif menu_item.est_nutrition:
        # Nothing in the recipe matched a food, so recomputing would trade a
        # usable estimate -- from the assistant, or typed in by hand -- for
        # nothing at all. Keep the numbers, and say in the note that they did
        # not come from the ingredients.
        menu_item.est_nutrition_note = dict(result['note'], source='kept')
    else:
        menu_item.est_nutrition = None
        menu_item.est_nutrition_note = result['note']

    if save:
        menu_item.save(update_fields=['est_nutrition', 'est_nutrition_note'])

    return menu_item
