#!/usr/bin/env python
# encoding: utf-8
"""
Salt, which needs its own module for one reason: density.

Every salt here is essentially pure sodium chloride, so **sodium per gram is
the same for all of them** -- about 390 mg, and USDA measures its table salt
at 387.6. What differs enormously is how much salt a spoon holds, because
the crystals are different sizes. A teaspoon of fine table salt is about
6 g; the same spoon of flaky Diamond Crystal kosher holds under half that.

That matters more here than anywhere else in the app:

* FoodData Central has no kosher salt entry at all -- the only "kosher"
  foods in it are dill pickles -- so a kosher salt line matches
  "Salt, table" and would otherwise inherit table salt's density.
* "1 tsp kosher salt" would then compute as 2,325 mg of sodium when the
  truth is nearer 1,100. Not a rounding error: more than double.
* And the two common kosher brands differ from each other by about 70%, so
  knowing it is "kosher" is not enough to answer.

The ratios between spoon sizes are taken from USDA's own table salt
portions, so a table-salt line still comes out exactly as USDA says it
does, and only the per-teaspoon weight is swapped for the variety's.
"""

# Grams per level teaspoon. Approximate by nature -- crystal size varies
# with humidity and how the box was handled -- which is why the household
# can change it rather than being stuck with a constant.
GRAMS_PER_TSP = {
    'table': 6.0,                     # matches USDA's own portion exactly
    'kosher_morton': 4.8,
    'kosher_diamond_crystal': 2.8,
    'coarse_sea': 5.0,
    'flake_maldon': 2.3,
}

# What to assume when a recipe says "kosher" and the household has not said
# which box is in the cupboard. Morton is the denser of the two, so this
# errs towards over-reporting sodium rather than under-reporting it -- the
# safer direction for a number someone might be watching.
DEFAULT_KOSHER = 'kosher_morton'
DEFAULT_COARSE = 'coarse_sea'

# The kosher varieties, which are the ones a household setting has to
# disambiguate: "kosher salt" on its own does not say whose, and the two
# brands are about 70% apart by volume.
KOSHER_VARIETIES = frozenset(
    {'kosher_morton', 'kosher_diamond_crystal'}
)

# Brand names that settle the question on their own.
BRAND_WORDS = ('diamond crystal', 'morton', 'maldon')


def names_a_brand(text):
    """Whether the line says whose salt, rather than just what kind."""
    words = (text or '').lower()
    return any(brand in words for brand in BRAND_WORDS)

# Spoon sizes as multiples of a teaspoon, derived from USDA's table salt
# portions (tsp 6.0g, tbsp 18.0g, cup 292.0g, dash 0.4g) so that table salt
# reproduces USDA exactly and everything else scales by density.
VOLUME_IN_TSP = {
    'tsp': 1.0,
    'tbsp': 3.0,
    'cup': 292.0 / 6.0,
    'dash': 0.4 / 6.0,
    'pinch': 0.2 / 6.0,
}


def variety_from_text(text):
    """
    Which salt a recipe line is asking for, from its own words.

    Returns None when the line does not say, which means the household's
    usual salt should be used instead.
    """
    words = (text or '').lower()

    if 'diamond crystal' in words:
        return 'kosher_diamond_crystal'
    if 'morton' in words:
        return 'kosher_morton'
    # "flak" rather than "flake", so that "flaky salt" matches too -- there
    # is no "e" in "flaky".
    if 'maldon' in words or 'flak' in words:
        return 'flake_maldon'
    if 'kosher' in words:
        return DEFAULT_KOSHER
    if 'coarse' in words or 'sea salt' in words or 'rock salt' in words:
        return DEFAULT_COARSE
    if 'table salt' in words or 'fine salt' in words or 'iodized' in words:
        return 'table'
    return None


def grams_for(quantity, measurement, variety):
    """
    What a spoon of this salt weighs, or None if the unit is not a volume.

    Mass units are not handled here on purpose: the generic path already
    converts those correctly, because a gram of any salt is a gram.
    """
    if not quantity or quantity <= 0:
        return None

    unit = (measurement or '').strip().lower()
    multiple = VOLUME_IN_TSP.get(unit)
    if multiple is None:
        return None

    per_tsp = GRAMS_PER_TSP.get(variety)
    if per_tsp is None:
        return None

    return quantity * multiple * per_tsp


def is_assumed(text, kosher_setting):
    """
    Whether the figure rests on a guess about which box is in the cupboard.

    True when the line says "kosher" without naming a brand and the
    household has not said which it keeps, because Diamond Crystal and
    Morton are 70% apart and picking one is a coin toss worth admitting to.
    """
    words = (text or '').lower()
    if names_a_brand(words):
        return False
    if 'kosher' in words:
        return not kosher_setting
    return False
