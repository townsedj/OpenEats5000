#!/usr/bin/env python
# encoding: utf-8
"""
Salt density, which is worth its own file.

The defect these cover: FoodData Central has no kosher salt, so a kosher
line matches "Salt, table" and the generic portion lookup handed back table
salt's 6 g teaspoon -- flagged as arithmetic, so high confidence -- for a
salt that actually weighs 2.8. More than double the sodium, on the one
nutrient this app was asked to track.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from v1.household.models import Household
from v1.ingredient.models import Ingredient, IngredientGroup
from v1.nutrition import matching, salt
from v1.nutrition.models import Food, FoodNutrient, FoodPortion
from v1.recipe.models import Recipe


class VarietyTests(TestCase):
    def test_a_named_brand_is_recognised(self):
        self.assertEqual(
            salt.variety_from_text('Diamond Crystal kosher salt'),
            'kosher_diamond_crystal',
        )
        self.assertEqual(
            salt.variety_from_text('Morton kosher salt'), 'kosher_morton'
        )

    def test_unbranded_kosher_falls_to_the_denser_default(self):
        """
        Erring towards over-reporting sodium rather than under-reporting it,
        which is the safer direction for a number someone is watching.
        """
        self.assertEqual(salt.variety_from_text('kosher salt'), 'kosher_morton')
        self.assertEqual(salt.GRAMS_PER_TSP['kosher_morton'], 4.8)
        self.assertGreater(
            salt.GRAMS_PER_TSP['kosher_morton'],
            salt.GRAMS_PER_TSP['kosher_diamond_crystal'],
        )

    def test_coarse_and_flaky_salts_are_recognised(self):
        self.assertEqual(salt.variety_from_text('coarse salt'), 'coarse_sea')
        self.assertEqual(salt.variety_from_text('sea salt'), 'coarse_sea')
        self.assertEqual(salt.variety_from_text('Maldon sea salt'), 'flake_maldon')
        self.assertEqual(salt.variety_from_text('flaky salt'), 'flake_maldon')

    def test_plain_salt_says_nothing(self):
        """Which means the household's own salt should decide."""
        self.assertIsNone(salt.variety_from_text('salt'))
        self.assertIsNone(salt.variety_from_text('salt and pepper'))

    def test_table_salt_is_recognised_explicitly(self):
        self.assertEqual(salt.variety_from_text('table salt'), 'table')
        self.assertEqual(salt.variety_from_text('iodized salt'), 'table')


class DensityTests(TestCase):
    def test_table_salt_reproduces_usda_exactly(self):
        """
        The spoon ratios are taken from USDA's own portions, so the one
        variety it does publish must come out unchanged.
        """
        self.assertEqual(salt.grams_for(1, 'tsp', 'table'), 6.0)
        self.assertEqual(salt.grams_for(1, 'tbsp', 'table'), 18.0)
        self.assertAlmostEqual(salt.grams_for(1, 'cup', 'table'), 292.0)
        self.assertAlmostEqual(salt.grams_for(1, 'dash', 'table'), 0.4)

    def test_kosher_weighs_less_for_the_same_spoon(self):
        self.assertAlmostEqual(salt.grams_for(1, 'tsp', 'kosher_morton'), 4.8)
        self.assertAlmostEqual(
            salt.grams_for(1, 'tsp', 'kosher_diamond_crystal'), 2.8
        )

    def test_the_sodium_difference_is_the_point(self):
        """
        Same teaspoon, same substance, same sodium per gram -- and 1,200 mg
        between the two boxes.
        """
        per_gram = 387.6  # USDA's figure for salt, mg of sodium per gram
        table = salt.grams_for(1, 'tsp', 'table') * per_gram
        diamond = salt.grams_for(1, 'tsp', 'kosher_diamond_crystal') * per_gram

        self.assertAlmostEqual(table, 2325.6, places=0)
        self.assertAlmostEqual(diamond, 1085.3, places=0)
        self.assertGreater(table - diamond, 1200)

    def test_a_non_volume_unit_is_not_this_modules_business(self):
        """A gram of any salt is a gram; the generic path handles mass."""
        self.assertIsNone(salt.grams_for(100, 'g', 'kosher_morton'))
        self.assertIsNone(salt.grams_for(1, 'handful', 'table'))

    def test_no_quantity_means_no_answer(self):
        self.assertIsNone(salt.grams_for(0, 'tsp', 'table'))
        self.assertIsNone(salt.grams_for(None, 'tsp', 'table'))

    def test_an_unknown_variety_gives_no_answer(self):
        self.assertIsNone(salt.grams_for(1, 'tsp', 'himalayan_pink'))


class AssumptionTests(TestCase):
    def test_unbranded_kosher_with_no_setting_is_an_assumption(self):
        """
        Diamond Crystal and Morton are 70% apart, so picking one is a coin
        toss worth admitting to.
        """
        self.assertTrue(salt.is_assumed('kosher salt', None))
        self.assertTrue(salt.is_assumed('kosher salt', ''))

    def test_a_household_setting_settles_it(self):
        self.assertFalse(salt.is_assumed('kosher salt', 'kosher_morton'))

    def test_a_named_brand_settles_it(self):
        self.assertFalse(salt.is_assumed('Diamond Crystal kosher salt', None))

    def test_plain_salt_is_not_an_assumption_worth_flagging(self):
        self.assertFalse(salt.is_assumed('salt', None))


class ResolutionTests(TestCase):
    """The whole path, through the matcher's own gram resolution."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.recipe = Recipe.objects.create(
            title='Chili', author=self.user, household=self.household,
            servings=4, directions='Cook it.',
        )
        self.group = IngredientGroup.objects.create(recipe=self.recipe, title='')

        # USDA's only salt, with the portions it really publishes.
        self.salt_food = Food.objects.create(
            fdc_id=173468, description='Salt, table',
            data_type=Food.DataType.SR_LEGACY,
        )
        FoodNutrient.objects.create(
            food=self.salt_food, nutrient='sodium_mg', amount=38758.0
        )
        for unit, grams in [('tsp', 6.0), ('tbsp', 18.0), ('cup', 292.0),
                            ('dash', 0.4)]:
            FoodPortion.objects.create(
                food=self.salt_food, amount=1, measure_unit=unit,
                gram_weight=grams,
            )

    def line(self, title, quantity=1, measurement='tsp'):
        return Ingredient.objects.create(
            ingredient_group=self.group, title=title,
            numerator=quantity, denominator=1, measurement=measurement,
        )

    def resolve(self, ingredient):
        return matching.resolve_grams(
            self.salt_food, ingredient.quantity(), ingredient.measurement,
            ingredient=ingredient, household=self.household,
        )

    def test_kosher_salt_no_longer_takes_table_salts_density(self):
        """
        The regression. Before this, a kosher teaspoon resolved to 6.0g
        through the portion lookup and reported 2,325mg of sodium.
        """
        grams, source = self.resolve(self.line('kosher salt'))

        self.assertAlmostEqual(grams, 4.8)
        self.assertEqual(source, 'salt')

    def test_a_two_salt_kitchen_follows_the_recipes_wording(self):
        """
        The real case this is built for: Morton for meats, table salt for
        eggs and baking. Both boxes are in the cupboard, so the recipe's
        wording is what decides which one gets reached for -- it is not
        overridden by a single household setting, which is what an earlier
        version did.
        """
        self.household.default_salt = Household.Salt.TABLE
        self.household.kosher_salt = Household.KosherSalt.MORTON
        self.household.save()

        kosher, _ = self.resolve(self.line('kosher salt'))
        plain, _ = self.resolve(self.line('salt'))

        self.assertAlmostEqual(kosher, 4.8)
        self.assertAlmostEqual(plain, 6.0)

    def test_the_kosher_setting_picks_the_brand(self):
        self.household.kosher_salt = Household.KosherSalt.DIAMOND
        self.household.save()

        grams, _source = self.resolve(self.line('kosher salt'))

        self.assertAlmostEqual(grams, 2.8)

    def test_a_named_brand_beats_the_household_setting(self):
        """If the line says whose salt, that is not a guess to override."""
        self.household.kosher_salt = Household.KosherSalt.MORTON
        self.household.save()

        grams, _source = self.resolve(
            self.line('Diamond Crystal kosher salt')
        )

        self.assertAlmostEqual(grams, 2.8)

    def test_a_stated_variety_is_taken_as_read(self):
        """
        "sea salt" in the recipe is not answered by the default salt: the
        recipe said which kind.
        """
        self.household.default_salt = Household.Salt.TABLE
        self.household.save()

        grams, _source = self.resolve(self.line('coarse sea salt'))

        self.assertAlmostEqual(grams, 5.0)

    def test_plain_salt_falls_to_the_default(self):
        self.household.default_salt = Household.Salt.KOSHER_MORTON
        self.household.save()

        grams, source = self.resolve(self.line('salt'))

        self.assertAlmostEqual(grams, 4.8)
        self.assertEqual(source, 'salt')

    def test_plain_salt_with_nothing_set_is_table_salt(self):
        grams, source = self.resolve(self.line('salt'))

        self.assertAlmostEqual(grams, 6.0)
        self.assertEqual(source, 'salt')

    def test_a_mass_measurement_is_unaffected(self):
        """A gram of any salt is a gram."""
        grams, source = self.resolve(self.line('kosher salt', 10, 'g'))

        self.assertEqual((grams, source), (10.0, 'mass'))

    def test_a_dash_scales_with_the_variety(self):
        grams, _source = self.resolve(self.line('kosher salt', 1, 'dash'))

        # USDA's dash of table salt is 0.4g; kosher is lighter in the same
        # spoon.
        self.assertLess(grams, 0.4)
        self.assertAlmostEqual(grams, 0.4 / 6.0 * 4.8)

    def test_salted_butter_is_not_treated_as_salt(self):
        """
        is_salt() excludes it, so a tablespoon of butter must not be
        weighed as a tablespoon of salt.
        """
        butter = Food.objects.create(
            fdc_id=173410, description='Butter, salted',
            data_type=Food.DataType.SR_LEGACY,
        )
        FoodPortion.objects.create(
            food=butter, amount=1, measure_unit='tbsp', gram_weight=14.2
        )
        row = self.line('salted butter', 1, 'tbsp')

        grams, source = matching.resolve_grams(
            butter, row.quantity(), row.measurement,
            ingredient=row, household=self.household,
        )

        self.assertAlmostEqual(grams, 14.2)
        self.assertEqual(source, 'portion')

    def test_the_sodium_that_comes_out_is_the_whole_point(self):
        from v1.nutrition.compute import recipe_nutrition

        row = self.line('kosher salt', 1, 'tsp')
        row.food = self.salt_food
        row.grams, _source = self.resolve(row)
        row.save()

        per_serving = recipe_nutrition(self.recipe)['per_serving']

        # 4.8g of salt over 4 servings, at 387.58 mg/g.
        self.assertAlmostEqual(per_serving['sodium_mg'], 465.1, places=0)
        # Against what table salt's density would have reported.
        self.assertLess(per_serving['sodium_mg'], 6.0 * 387.58 / 4)
