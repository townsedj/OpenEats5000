#!/usr/bin/env python
# encoding: utf-8
"""
Turning matched ingredients into numbers, and saying how much to trust them.

The second half is the point. Summing whatever happened to match and
presenting the total as the recipe's nutrition is the easy way to build
something confidently wrong: a chili whose beans and tomatoes matched but
whose pork did not will report about a third of its real protein, and look
no different from one that matched completely.

So every total travels with a note saying what was left out.
"""

from . import nutrients


def ingredient_amounts(ingredient):
    """
    What one ingredient line contributes, keyed by nutrient.

    Returns an empty dict when the line has no food or no weight -- USDA
    amounts are per 100 g, so a match without grams buys nothing.
    """
    if not ingredient.food_id or not ingredient.grams:
        return {}

    scale = ingredient.grams / 100.0
    return {
        row.nutrient: row.amount * scale
        for row in ingredient.food.nutrients.all()
        if row.nutrient in nutrients.BY_KEY
    }


def recipe_nutrition(recipe):
    """
    Per-serving nutrition for a recipe, with a note about its gaps.

    Shape:
        {
          'per_serving': {'kcal': 410.0, 'sodium_mg': 180.0, ...},
          'note': {
            'confidence': 'high' | 'medium' | 'low',
            'matched': 7, 'with_energy': 6, 'total': 9,
            'unmatched': ['cumin', 'chili powder'],
            'no_energy': ['olive oil'],
            'salt_not_counted': True,
          },
        }

    `per_serving` holds only the nutrients something actually contributed.
    An absent key means "not known", which is different from zero and has to
    stay different all the way to the screen.

    `matched` and `with_energy` are counted separately because a line can
    match a food and still contribute no calories. USDA has foods like that,
    and they are the worst ones to get wrong: its extra-virgin olive oil
    carries a single nutrient, saturated fat, with no energy and no total
    fat. Counting that line as matched would let a recipe lose two hundred
    calories of oil and still call itself high confidence.
    """
    lines = [
        ingredient
        for group in recipe.ingredient_groups.all()
        for ingredient in group.ingredients.all()
    ]

    totals = {}
    matched = 0
    with_energy = 0
    unmatched = []
    no_energy = []
    salt_not_counted = False

    for line in lines:
        amounts = ingredient_amounts(line)
        if amounts:
            matched += 1
            if amounts.get('kcal') is not None:
                with_energy += 1
            else:
                # Its other nutrients are still real, so they are kept --
                # but the calorie total is short and has to say so.
                no_energy.append(line.title)
            for key, value in amounts.items():
                totals[key] = totals.get(key, 0.0) + value
        else:
            unmatched.append(line.title)
            if line.is_salt():
                # A teaspoon of salt is roughly a whole day's sodium, so an
                # unquantified salt line matters more than any other gap.
                salt_not_counted = True

    servings = recipe.servings or 1
    per_serving = {key: value / servings for key, value in totals.items()}

    return {
        'per_serving': per_serving,
        'note': {
            'source': 'computed',
            'confidence': confidence_for(
                with_energy, len(lines), salt_not_counted
            ),
            'matched': matched,
            'with_energy': with_energy,
            'total': len(lines),
            'unmatched': unmatched,
            'no_energy': no_energy,
            'salt_not_counted': salt_not_counted,
        },
    }


def confidence_for(with_energy, total, salt_not_counted):
    """
    How much of the recipe we actually accounted for.

    Driven by calorie coverage rather than by how many lines found a food.
    Calories are what every other number gets checked against, so a line
    that matched a food carrying no energy is, for this purpose, no better
    than one that matched nothing.

    Unquantified salt caps confidence at medium however well everything else
    matched, because the sodium figure is then not merely low but wrong by
    more than the daily limit.
    """
    if not total:
        return 'low'

    share = with_energy / float(total)
    if share < 0.5:
        return 'low'
    if share == 1 and not salt_not_counted:
        return 'high'
    return 'medium'


def scale(per_serving, servings):
    """One person's portion of a per-serving estimate."""
    return {
        key: value * servings
        for key, value in (per_serving or {}).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def split_for_log(amounts):
    """
    Split a nutrient dict into ServingLog's columns and its `micros` blob.

    Returns (column_kwargs, micros). Columns that nothing contributed are
    set to None rather than 0, so "we do not know" survives the write.
    """
    columns = {
        key: amounts.get(key) for key in nutrients.COLUMN_KEYS
    }
    micros = {
        key: amounts[key] for key in nutrients.MICRO_KEYS if key in amounts
    }
    return columns, (micros or None)


def sum_logs(logs):
    """
    Add up ServingLog rows -- one person's day, or week.

    Reads the snapshot columns and the micros blob together so callers never
    have to know which nutrient lives where.
    """
    totals = {}
    for log in logs:
        for key in nutrients.COLUMN_KEYS:
            value = getattr(log, key, None)
            if value is not None:
                totals[key] = totals.get(key, 0.0) + value
        for key, value in (log.micros or {}).items():
            if value is not None and key in nutrients.BY_KEY:
                totals[key] = totals.get(key, 0.0) + value
    return totals


def compare(totals, targets):
    """
    A day's intake against that person's targets.

    Each entry carries the direction, because a ceiling and a floor read
    differently even at the same percentage: 95% of a sodium limit is a
    warning and 95% of a fibre target is a good day.
    """
    rows = {}
    for key, target in (targets or {}).items():
        nutrient = nutrients.BY_KEY.get(key)
        if nutrient is None or not target:
            continue
        amount = totals.get(key)
        rows[key] = {
            'label': nutrient.label,
            'unit': nutrient.unit,
            'direction': nutrient.direction,
            'daily': nutrient.daily,
            'amount': amount,
            'target': target,
            'share': (amount / target) if amount is not None else None,
        }
    return rows
