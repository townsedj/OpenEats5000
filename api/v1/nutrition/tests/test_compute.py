#!/usr/bin/env python
# encoding: utf-8

from django.contrib.auth.models import User
from django.test import TestCase

from v1.household.models import Household, NutritionTarget
from v1.ingredient.models import Ingredient, IngredientGroup
from v1.nutrition import compute, nutrients
from v1.nutrition.models import Food, FoodNutrient, FoodPortion
from v1.recipe.models import Recipe


def make_food(description, **amounts):
    """A USDA food with per-100g amounts, keyed by registry key."""
    food = Food.objects.create(
        fdc_id=abs(hash(description)) % 1000000,
        description=description,
        data_type=Food.DataType.SR_LEGACY,
    )
    for key, amount in amounts.items():
        FoodNutrient.objects.create(food=food, nutrient=key, amount=amount)
    return food


class RegistryTests(TestCase):
    def test_every_nutrient_has_a_unique_key(self):
        self.assertEqual(len(nutrients.KEYS), len(set(nutrients.KEYS)))

    def test_columns_and_micros_partition_the_registry(self):
        """
        Nothing may be in both, and nothing may be in neither -- otherwise a
        nutrient would be snapshotted twice or not at all.
        """
        columns = set(nutrients.COLUMN_KEYS)
        micros = set(nutrients.MICRO_KEYS)

        self.assertEqual(columns & micros, set())
        self.assertEqual(columns | micros, set(nutrients.KEYS))

    def test_sodium_is_a_ceiling_and_iron_is_a_floor(self):
        """Direction is what makes 95% of a target read well or badly."""
        self.assertEqual(nutrients.BY_KEY['sodium_mg'].direction, nutrients.CEILING)
        self.assertEqual(nutrients.BY_KEY['satfat_g'].direction, nutrients.CEILING)
        self.assertEqual(nutrients.BY_KEY['iron_mg'].direction, nutrients.FLOOR)
        self.assertEqual(nutrients.BY_KEY['fibre_g'].direction, nutrients.FLOOR)

    def test_vitamins_are_not_marked_safe_as_daily_numbers(self):
        """
        Cooking losses are not modelled, so a daily vitamin C figure would
        be false precision. Sodium and calories are fine daily.
        """
        self.assertFalse(nutrients.BY_KEY['vitamin_c_mg'].daily)
        self.assertFalse(nutrients.BY_KEY['vitamin_a_ug'].daily)
        self.assertTrue(nutrients.BY_KEY['sodium_mg'].daily)
        self.assertTrue(nutrients.BY_KEY['kcal'].daily)

    def test_energy_has_fallback_usda_ids(self):
        """Foundation foods sometimes carry Atwater energy rows instead."""
        mapping = nutrients.by_usda_id()

        self.assertEqual(mapping[1008], 'kcal')
        self.assertEqual(mapping[2047], 'kcal')
        self.assertEqual(mapping[1093], 'sodium_mg')


class IngredientAmountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.recipe = Recipe.objects.create(
            title='Test', author=self.user, household=self.household, servings=4
        )
        self.group = IngredientGroup.objects.create(recipe=self.recipe, title='')

    def test_amounts_scale_from_per_100g(self):
        onion = make_food('Onions, raw', kcal=40, sodium_mg=4, fibre_g=1.7)
        line = Ingredient.objects.create(
            ingredient_group=self.group, title='white onion',
            food=onion, grams=150,
        )

        amounts = compute.ingredient_amounts(line)

        self.assertAlmostEqual(amounts['kcal'], 60)
        self.assertAlmostEqual(amounts['sodium_mg'], 6)
        self.assertAlmostEqual(amounts['fibre_g'], 2.55)

    def test_a_match_without_grams_contributes_nothing(self):
        """
        USDA amounts are per 100 g, so a food without a weight is not a
        partial answer -- it is no answer.
        """
        onion = make_food('Onions, raw', kcal=40)
        line = Ingredient.objects.create(
            ingredient_group=self.group, title='white onion', food=onion
        )

        self.assertEqual(compute.ingredient_amounts(line), {})

    def test_an_unmatched_line_contributes_nothing(self):
        line = Ingredient.objects.create(
            ingredient_group=self.group, title='mystery', grams=100
        )

        self.assertEqual(compute.ingredient_amounts(line), {})

    def test_unknown_nutrient_rows_are_ignored(self):
        """A food carrying something the registry does not know is skipped."""
        food = make_food('Odd', kcal=100)
        FoodNutrient.objects.create(food=food, nutrient='unobtainium_mg', amount=9)
        line = Ingredient.objects.create(
            ingredient_group=self.group, title='odd', food=food, grams=100
        )

        self.assertEqual(compute.ingredient_amounts(line), {'kcal': 100})


class SaltTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.recipe = Recipe.objects.create(
            title='Test', author=self.user, household=self.household, servings=4
        )
        self.group = IngredientGroup.objects.create(recipe=self.recipe, title='')

    def line(self, title, **kwargs):
        return Ingredient.objects.create(
            ingredient_group=self.group, title=title, **kwargs
        )

    def test_salt_is_recognised(self):
        self.assertTrue(self.line('kosher salt').is_salt())
        self.assertTrue(self.line('salt').is_salt())
        self.assertTrue(self.line('Sea Salt, to taste').is_salt())

    def test_salted_and_unsalted_things_are_not_salt(self):
        """"Unsalted butter" is not a salt line, and must not raise the flag."""
        self.assertFalse(self.line('unsalted butter').is_salt())
        self.assertFalse(self.line('salted peanuts').is_salt())
        self.assertFalse(self.line('pepper').is_salt())


class RecipeNutritionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.recipe = Recipe.objects.create(
            title='Tasty Chili', author=self.user, household=self.household,
            servings=4,
        )
        self.group = IngredientGroup.objects.create(recipe=self.recipe, title='')

        self.pork = make_food(
            'Pork, ground', kcal=263, protein_g=17, sodium_mg=61, satfat_g=8,
            iron_mg=1, potassium_mg=287,
        )
        self.beans = make_food(
            'Beans, kidney', kcal=127, protein_g=9, sodium_mg=2, fibre_g=6.4,
            iron_mg=2.9, potassium_mg=403,
        )

    def line(self, title, **kwargs):
        return Ingredient.objects.create(
            ingredient_group=self.group, title=title, **kwargs
        )

    def test_totals_are_per_serving(self):
        self.line('ground pork', food=self.pork, grams=400)
        self.line('kidney beans', food=self.beans, grams=400)

        result = compute.recipe_nutrition(self.recipe)
        per_serving = result['per_serving']

        # 400 g of each is 4 x the per-100g figures, over 4 servings, so the
        # per-serving number is just the sum of the two per-100g numbers.
        self.assertAlmostEqual(per_serving['kcal'], 390)     # 263 + 127
        self.assertAlmostEqual(per_serving['protein_g'], 26)  # 17 + 9
        self.assertAlmostEqual(per_serving['sodium_mg'], 63)  # 61 + 2

    def test_a_fully_matched_recipe_is_high_confidence(self):
        self.line('ground pork', food=self.pork, grams=400)
        self.line('kidney beans', food=self.beans, grams=400)

        note = compute.recipe_nutrition(self.recipe)['note']

        self.assertEqual(note['confidence'], 'high')
        self.assertEqual(note['unmatched'], [])
        self.assertFalse(note['salt_not_counted'])

    def test_unmatched_ingredients_are_named(self):
        """
        A total that silently omits the pork looks identical to a complete
        one, which is the most confident way to be wrong.
        """
        self.line('ground pork', food=self.pork, grams=400)
        self.line('cumin')
        self.line('chili powder')

        note = compute.recipe_nutrition(self.recipe)['note']

        self.assertEqual(note['matched'], 1)
        self.assertEqual(note['total'], 3)
        self.assertEqual(note['unmatched'], ['cumin', 'chili powder'])
        self.assertEqual(note['confidence'], 'low')

    def test_unquantified_salt_caps_confidence_at_medium(self):
        """
        A teaspoon of salt is most of a day's sodium limit, so a recipe that
        did not quantify its salt has a sodium figure that is wrong, not
        merely low -- however well everything else matched.
        """
        self.line('ground pork', food=self.pork, grams=400)
        self.line('kidney beans', food=self.beans, grams=400)
        self.line('kosher salt')  # "a dash" -- no weight

        note = compute.recipe_nutrition(self.recipe)['note']

        self.assertTrue(note['salt_not_counted'])
        self.assertEqual(note['confidence'], 'medium')

    def test_a_missing_nutrient_is_absent_not_zero(self):
        """
        "We do not know" has to survive all the way to the screen, so a
        nutrient nothing contributed is left out rather than set to zero.
        """
        self.line('ground pork', food=self.pork, grams=400)

        per_serving = compute.recipe_nutrition(self.recipe)['per_serving']

        self.assertIn('kcal', per_serving)
        self.assertNotIn('vitamin_c_mg', per_serving)
        self.assertNotIn('fibre_g', per_serving)

    def test_a_food_with_no_calories_does_not_count_as_accounted_for(self):
        """
        The trap that USDA's energy-less foods set, and that any
        hand-entered food can set again.

        Foundation's extra-virgin olive oil carries one nutrient: saturated
        fat. Counting that line as matched let a recipe drop two hundred
        calories of oil and still call itself high confidence. Confidence
        now follows calorie coverage, not how many lines found a food.
        """
        oil = make_food('Oil, olive, extra virgin', satfat_g=13.8)
        self.line('ground pork', food=self.pork, grams=400)
        self.line('kidney beans', food=self.beans, grams=400)
        self.line('olive oil', food=oil, grams=27)

        result = compute.recipe_nutrition(self.recipe)
        note = result['note']

        # It did find a food, and its saturated fat is real and counted.
        self.assertEqual(note['matched'], 3)
        self.assertGreater(result['per_serving']['satfat_g'], 0)
        # But it contributed no calories, so it is not accounted for.
        self.assertEqual(note['with_energy'], 2)
        self.assertEqual(note['no_energy'], ['olive oil'])
        self.assertEqual(note['confidence'], 'medium')

    def test_a_zero_calorie_food_is_accounted_for(self):
        """
        Zero is a measurement. Salt is genuinely zero calories and must not
        be treated as a gap.
        """
        salt = make_food('Salt, table', kcal=0, sodium_mg=38758)
        self.line('ground pork', food=self.pork, grams=400)
        self.line('salt', food=salt, grams=6)

        note = compute.recipe_nutrition(self.recipe)['note']

        self.assertEqual(note['with_energy'], 2)
        self.assertEqual(note['no_energy'], [])
        self.assertEqual(note['confidence'], 'high')
        self.assertFalse(note['salt_not_counted'])

    def test_a_recipe_with_no_ingredients_is_low_confidence(self):
        result = compute.recipe_nutrition(self.recipe)

        self.assertEqual(result['per_serving'], {})
        self.assertEqual(result['note']['confidence'], 'low')


class SplitAndSumTests(TestCase):
    def test_split_puts_columns_and_micros_in_the_right_place(self):
        columns, micros = compute.split_for_log({
            'kcal': 400, 'sodium_mg': 600, 'iron_mg': 3, 'selenium_ug': 12,
        })

        self.assertEqual(columns['kcal'], 400)
        self.assertEqual(columns['sodium_mg'], 600)
        # Nothing contributed these, so they are None rather than 0.
        self.assertIsNone(columns['protein_g'])
        self.assertEqual(micros, {'iron_mg': 3, 'selenium_ug': 12})

    def test_split_returns_none_for_an_empty_micros_blob(self):
        columns, micros = compute.split_for_log({'kcal': 400})

        self.assertIsNone(micros)

    def test_scale_multiplies_a_portion(self):
        self.assertEqual(
            compute.scale({'kcal': 400, 'sodium_mg': 100}, 1.5),
            {'kcal': 600, 'sodium_mg': 150},
        )

    def test_scale_drops_non_numbers(self):
        """est_nutrition is JSON, so it can hold anything."""
        self.assertEqual(
            compute.scale({'kcal': 400, 'confidence': 'high', 'flag': True}, 2),
            {'kcal': 800},
        )


class CompareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )

    def test_comparison_carries_direction_and_share(self):
        target = NutritionTarget.objects.create(
            user=self.user, kcal=2400, sodium_mg=2300
        )

        rows = compute.compare({'kcal': 1200, 'sodium_mg': 2185}, target.as_dict())

        self.assertEqual(rows['sodium_mg']['direction'], nutrients.CEILING)
        self.assertAlmostEqual(rows['sodium_mg']['share'], 0.95)
        self.assertEqual(rows['kcal']['direction'], nutrients.TARGET)
        self.assertAlmostEqual(rows['kcal']['share'], 0.5)

    def test_targets_that_are_not_set_are_left_out(self):
        target = NutritionTarget.objects.create(user=self.user, protein_g=150)

        rows = compute.compare({'protein_g': 100, 'kcal': 2000}, target.as_dict())

        self.assertEqual(list(rows), ['protein_g'])

    def test_a_nutrient_with_a_target_but_no_intake_reports_none(self):
        """Different from zero: nothing was logged, rather than nothing eaten."""
        # Iron has no column of its own, so its target lives in the blob.
        target = NutritionTarget.objects.create(
            user=self.user, micro_targets={'iron_mg': 18}
        )

        rows = compute.compare({}, target.as_dict())

        self.assertIsNone(rows['iron_mg']['amount'])
        self.assertIsNone(rows['iron_mg']['share'])


class TargetPresetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )

    def test_presets_differ_where_the_dri_differs(self):
        """18 mg against 8 mg is the clearest reason targets are per person."""
        male = nutrients.TARGET_PRESETS['male']
        female = nutrients.TARGET_PRESETS['female']

        self.assertEqual(male['iron_mg'], 8)
        self.assertEqual(female['iron_mg'], 18)
        self.assertEqual(male['fibre_g'], 38)
        self.assertEqual(female['fibre_g'], 25)
        # Same for both.
        self.assertEqual(male['sodium_mg'], female['sodium_mg'])

    def test_preset_fills_blanks_and_leaves_choices_alone(self):
        target = NutritionTarget.objects.create(user=self.user, sodium_mg=1500)

        filled = target.apply_preset('female')

        target.refresh_from_db()
        # Already chosen 1500, so the 2300 default must not overwrite it.
        self.assertEqual(target.sodium_mg, 1500)
        self.assertNotIn('sodium_mg', filled)
        self.assertEqual(target.fibre_g, 25)
        self.assertEqual(target.micro_targets['iron_mg'], 18)

    def test_saturated_fat_is_derived_from_the_calorie_target(self):
        """Under 10% of calories, so a flat number would be wrong for anyone."""
        target = NutritionTarget.objects.create(user=self.user, kcal=2400)

        target.apply_preset('male')

        target.refresh_from_db()
        self.assertEqual(target.satfat_g, 27)

    def test_saturated_fat_is_left_unset_without_a_calorie_target(self):
        target = NutritionTarget.objects.create(user=self.user)

        target.apply_preset('male')

        target.refresh_from_db()
        self.assertIsNone(target.satfat_g)

    def test_all_targets_flattens_columns_and_micros(self):
        target = NutritionTarget.objects.create(user=self.user, kcal=2400)
        target.apply_preset('female')

        targets = target.as_dict()

        self.assertEqual(targets['kcal'], 2400)
        self.assertEqual(targets['iron_mg'], 18)
        self.assertEqual(targets['fibre_g'], 25)


class FoodPortionTests(TestCase):
    def test_a_portion_carries_its_modifier(self):
        """
        A cup of chopped onion and a cup of sliced onion are different
        weights, which is why the modifier is stored rather than dropped.
        """
        onion = make_food('Onions, raw', kcal=40)
        chopped = FoodPortion.objects.create(
            food=onion, amount=1, measure_unit='cup', modifier='chopped',
            gram_weight=160,
        )
        sliced = FoodPortion.objects.create(
            food=onion, amount=1, measure_unit='cup', modifier='sliced',
            gram_weight=115,
        )

        self.assertEqual(onion.portions.count(), 2)
        self.assertNotEqual(chopped.gram_weight, sliced.gram_weight)

    def test_nutrient_amounts_are_keyed_by_registry_key(self):
        onion = make_food('Onions, raw', kcal=40, sodium_mg=4)

        self.assertEqual(onion.nutrient_amounts(), {'kcal': 40, 'sodium_mg': 4})
