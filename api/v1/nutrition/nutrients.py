#!/usr/bin/env python
# encoding: utf-8
"""
The one registry of nutrients this app knows about.

Why a module and not a table: which way a nutrient points is a property of
the nutrient, not of the person. Sodium is a ceiling for everybody and iron
is a floor for everybody; only the *number* differs per person, and that
lives on NutritionTarget. Putting direction in the database would invite two
rows that disagree about what sodium is.

Three groups, and the difference matters:

* `column=True` -- has its own column on ServingLog and NutritionTarget,
  because the app sums or filters it on every render.
* `shown=True` -- appears on the nutrition screen.
* everything else is still stored, in the `micros` JSON snapshot, because a
  snapshot cannot be reconstructed after a recipe is edited. Storing a
  nutrient costs almost nothing; wanting it next year and not having it
  costs the whole history.

`daily=False` marks the nutrients that are only honest as a weekly trend.
Cooking losses are not modelled by summing raw ingredients -- heat destroys
vitamin C, water-soluble vitamins leach into water that gets poured away,
minerals concentrate as liquid evaporates. Matching "1 cup chopped broccoli"
to the raw entry rather than the steamed one moves vitamin C by roughly
half. Calories, protein and sodium can carry a daily figure. Vitamin A
cannot.

Default targets are US DRI / DGA figures for adults, offered as a starting
point to be edited, not as gospel. kcal and protein are deliberately absent
from the presets: both depend on body weight and activity, so a population
number would be a worse guess than no number at all.
"""

FLOOR = 'floor'        # aim to reach it
CEILING = 'ceiling'    # aim to stay under it
TARGET = 'target'      # aim near it


class Nutrient(object):
    __slots__ = (
        'key', 'usda_id', 'alternate_usda_ids', 'label', 'unit',
        'direction', 'column', 'shown', 'daily',
    )

    def __init__(self, key, usda_id, label, unit, direction,
                 alternate_usda_ids=(), column=False, shown=False, daily=True):
        self.key = key
        self.usda_id = usda_id
        self.alternate_usda_ids = alternate_usda_ids
        self.label = label
        self.unit = unit
        self.direction = direction
        self.column = column
        self.shown = shown
        self.daily = daily

    def __repr__(self):
        return '<Nutrient %s>' % self.key


# USDA ids are FoodData Central `nutrient.id` values, not the older
# `nutrient_nbr` ones (energy is id 1008, nbr 208).
NUTRIENTS = (
    # --- the five that were already here, on every card ---
    Nutrient('kcal', 1008, 'Calories', 'kcal', TARGET,
             # Most Foundation foods have no plain kcal row at all: energy
             # arrives as Atwater factors instead. Of 424 foods, 95 carry
             # 1008, 279 carry 2047 and 200 carry 2048 -- and where a food
             # has both, they usually disagree by around a tenth (gala
             # apples: 61.0 against 54.9). So the order here is a real
             # decision, not a fallback that never fires.
             #
             # 1008 first where it exists, then 2048 (specific factors,
             # tailored per food), then 2047 (the general 4/9/4 shortcut).
             # Specific factors are the finer calculation, and they are
             # also how SR Legacy's own energy figures were derived, which
             # keeps the two datasets comparable in one database.
             alternate_usda_ids=(2048, 2047),
             column=True, shown=True),
    Nutrient('protein_g', 1003, 'Protein', 'g', FLOOR, column=True, shown=True),
    Nutrient('carb_g', 1005, 'Carbs', 'g', TARGET, column=True, shown=True),
    Nutrient('fat_g', 1004, 'Fat', 'g', TARGET, column=True, shown=True),
    Nutrient('fibre_g', 1079, 'Fibre', 'g', FLOOR, column=True, shown=True),

    # --- promoted to columns: summed every render, and worth filtering by ---
    Nutrient('sodium_mg', 1093, 'Sodium', 'mg', CEILING, column=True, shown=True),
    Nutrient('satfat_g', 1258, 'Saturated fat', 'g', CEILING,
             column=True, shown=True),

    # --- shown on the nutrition screen, stored in the micros snapshot ---
    Nutrient('potassium_mg', 1092, 'Potassium', 'mg', FLOOR, shown=True),
    Nutrient('calcium_mg', 1087, 'Calcium', 'mg', FLOOR, shown=True),
    Nutrient('iron_mg', 1089, 'Iron', 'mg', FLOOR, shown=True),
    Nutrient('magnesium_mg', 1090, 'Magnesium', 'mg', FLOOR, shown=True),
    Nutrient('zinc_mg', 1095, 'Zinc', 'mg', FLOOR, shown=True),
    Nutrient('sugars_g', 2000, 'Sugars', 'g', CEILING, shown=True),
    Nutrient('vitamin_c_mg', 1162, 'Vitamin C', 'mg', FLOOR,
             shown=True, daily=False),
    Nutrient('folate_ug', 1177, 'Folate', 'ug', FLOOR, shown=True, daily=False),
    Nutrient('vitamin_b12_ug', 1178, 'Vitamin B12', 'ug', FLOOR,
             shown=True, daily=False),
    Nutrient('vitamin_a_ug', 1106, 'Vitamin A', 'ug', FLOOR,
             shown=True, daily=False),
    Nutrient('vitamin_d_ug', 1114, 'Vitamin D', 'ug', FLOOR,
             shown=True, daily=False),

    # --- stored but not shown ---
    # Cheap to keep and impossible to add later for meals already eaten. A
    # varied diet makes a deficiency in most of these vanishingly unlikely,
    # so on a screen they would read "fine" forever and cost attention for
    # nothing. Vitamin K is here because it only matters to someone on
    # warfarin; cholesterol because current guidance has largely moved to
    # saturated fat.
    Nutrient('phosphorus_mg', 1091, 'Phosphorus', 'mg', FLOOR, daily=False),
    Nutrient('selenium_ug', 1103, 'Selenium', 'ug', FLOOR, daily=False),
    Nutrient('copper_mg', 1098, 'Copper', 'mg', FLOOR, daily=False),
    Nutrient('manganese_mg', 1101, 'Manganese', 'mg', FLOOR, daily=False),
    Nutrient('vitamin_k_ug', 1185, 'Vitamin K', 'ug', FLOOR, daily=False),
    Nutrient('vitamin_e_mg', 1109, 'Vitamin E', 'mg', FLOOR, daily=False),
    Nutrient('cholesterol_mg', 1253, 'Cholesterol', 'mg', CEILING, daily=False),
    Nutrient('thiamin_mg', 1165, 'Thiamin', 'mg', FLOOR, daily=False),
    Nutrient('riboflavin_mg', 1166, 'Riboflavin', 'mg', FLOOR, daily=False),
    Nutrient('niacin_mg', 1167, 'Niacin', 'mg', FLOOR, daily=False),
    Nutrient('vitamin_b6_mg', 1175, 'Vitamin B6', 'mg', FLOOR, daily=False),
)

BY_KEY = {nutrient.key: nutrient for nutrient in NUTRIENTS}
KEYS = tuple(nutrient.key for nutrient in NUTRIENTS)

# The ones with a column of their own, in the order they read on a card.
COLUMN_KEYS = tuple(n.key for n in NUTRIENTS if n.column)
# Everything else goes in the `micros` JSON snapshot.
MICRO_KEYS = tuple(n.key for n in NUTRIENTS if not n.column)
SHOWN_KEYS = tuple(n.key for n in NUTRIENTS if n.shown)


def usda_priority():
    """
    Every USDA nutrient id this app reads, as id -> (key, rank).

    Rank 0 is the preferred id for that nutrient and higher numbers are
    progressively worse substitutes, so an import that meets two ids for the
    same nutrient can choose rather than taking whichever came first in the
    file. Energy is the case that makes this necessary -- see the kcal entry
    above.
    """
    mapping = {}
    for nutrient in NUTRIENTS:
        mapping.setdefault(nutrient.usda_id, (nutrient.key, 0))
        for rank, alternate in enumerate(nutrient.alternate_usda_ids, start=1):
            mapping.setdefault(alternate, (nutrient.key, rank))
    return mapping


def by_usda_id():
    """Every USDA nutrient id this app reads, mapped to its key."""
    return {
        usda_id: key for usda_id, (key, _rank) in usda_priority().items()
    }


# Population-level starting points, to be written into a person's targets
# once and then edited. Saturated fat is absent on purpose: the guideline is
# under 10% of calories, so it is derived from their own kcal target rather
# than being a flat number -- see derived_targets().
TARGET_PRESETS = {
    'male': {
        'fibre_g': 38,
        'sodium_mg': 2300,
        'potassium_mg': 3400,
        'calcium_mg': 1000,
        'iron_mg': 8,
        'magnesium_mg': 420,
        'zinc_mg': 11,
        'vitamin_c_mg': 90,
        'folate_ug': 400,
        'vitamin_b12_ug': 2.4,
        'vitamin_a_ug': 900,
        'vitamin_d_ug': 15,
    },
    'female': {
        'fibre_g': 25,
        'sodium_mg': 2300,
        'potassium_mg': 2600,
        'calcium_mg': 1000,
        # 18 mg rather than 8: the clearest reason targets are per person.
        'iron_mg': 18,
        'magnesium_mg': 320,
        'zinc_mg': 8,
        'vitamin_c_mg': 75,
        'folate_ug': 400,
        'vitamin_b12_ug': 2.4,
        'vitamin_a_ug': 700,
        'vitamin_d_ug': 15,
    },
}


def derived_targets(kcal):
    """
    The targets that are a share of someone's calories rather than a figure.

    Saturated fat under 10% of calories, at 9 kcal per gram.
    """
    if not kcal:
        return {}
    return {'satfat_g': round(kcal * 0.10 / 9)}
