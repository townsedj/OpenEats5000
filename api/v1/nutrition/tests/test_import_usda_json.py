#!/usr/bin/env python
# encoding: utf-8
"""
The JSON import path, which Foundation Foods needs.

Foundation's CSV package carries no food.csv and no food_nutrient.csv -- it
is lab provenance only -- so its food data can come from nowhere else.
"""

import json
import os
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from v1.nutrition.models import Food, FoodPortion
from v1.nutrition.tests.test_import_usda import write_export

# A miniature Foundation JSON export, shaped like the real one: nutrient
# definitions nested inline, energy as Atwater factors, measure units as
# objects carrying an abbreviation.
FOUNDATION_JSON = {
    'FoundationFoods': [
        {
            'foodClass': 'FinalFood',
            'fdcId': 2710824,
            'dataType': 'Foundation',
            'description': 'Apples, gala, with skin, raw',
            'foodCategory': {'description': 'Fruits and Fruit Juices'},
            'foodNutrients': [
                # Both Atwater rows, disagreeing by about a tenth -- which
                # is what the real export does for 194 of its 424 foods.
                {'nutrient': {'id': 2047, 'name': 'Energy (Atwater General)',
                              'unitName': 'kcal'}, 'amount': 61.0},
                {'nutrient': {'id': 2048, 'name': 'Energy (Atwater Specific)',
                              'unitName': 'kcal'}, 'amount': 54.9},
                {'nutrient': {'id': 1093, 'name': 'Sodium, Na',
                              'unitName': 'mg'}, 'amount': 1.0},
                {'nutrient': {'id': 1106, 'name': 'Vitamin A',
                              'unitName': 'ug'}, 'amount': None},
            ],
            'foodPortions': [
                {'amount': 1.0, 'value': 1.0, 'gramWeight': 182.0,
                 'measureUnit': {'id': 1000, 'name': 'cup',
                                 'abbreviation': 'cup'},
                 'modifier': 'sliced'},
                {'amount': 2.0, 'value': 2.0, 'gramWeight': 33.9,
                 'measureUnit': {'id': 1001, 'name': 'tablespoon',
                                 'abbreviation': 'tbsp'},
                 'modifier': ''},
            ],
        },
        {
            'fdcId': 2710825,
            'dataType': 'Foundation',
            'description': 'Hummus, commercial',
            'foodCategory': {'description': 'Legumes and Legume Products'},
            'foodNutrients': [
                # The plain kcal row, which has to beat both Atwater ones.
                {'nutrient': {'id': 1008, 'name': 'Energy',
                              'unitName': 'kcal'}, 'amount': 229.0},
                {'nutrient': {'id': 2047, 'name': 'Energy (Atwater General)',
                              'unitName': 'kcal'}, 'amount': 210.0},
                # Kilojoules, which must never be read as calories.
                {'nutrient': {'id': 1062, 'name': 'Energy',
                              'unitName': 'kJ'}, 'amount': 958.0},
            ],
            'foodPortions': [
                # No usable unit object: the measure is in the description.
                {'amount': 1.0, 'gramWeight': 28.0,
                 'measureUnit': {'id': 9999, 'name': 'undetermined',
                                 'abbreviation': 'undetermined'},
                 'portionDescription': '1 oz', 'modifier': ''},
            ],
        },
        {
            # Like Foundation's extra-virgin olive oil: one nutrient, no
            # energy at all. SR Legacy has the same food complete, so this
            # row can only ever make a recipe quietly wrong.
            'fdcId': 2710826,
            'dataType': 'Foundation',
            'description': 'Oil, olive, extra virgin',
            'foodNutrients': [
                {'nutrient': {'id': 1258, 'name': 'Fatty acids, total saturated',
                              'unitName': 'g'}, 'amount': 13.8},
            ],
            'foodPortions': [
                {'amount': 1.0, 'gramWeight': 13.5,
                 'measureUnit': {'id': 1001, 'name': 'tablespoon',
                                 'abbreviation': 'tbsp'},
                 'modifier': ''},
            ],
        },
        {
            # Zero calories as a measurement, not as a gap. Has to survive.
            'fdcId': 2710827,
            'dataType': 'Foundation',
            'description': 'Salt, table, iodized',
            'foodNutrients': [
                {'nutrient': {'id': 1008, 'name': 'Energy',
                              'unitName': 'kcal'}, 'amount': 0.0},
                {'nutrient': {'id': 1093, 'name': 'Sodium, Na',
                              'unitName': 'mg'}, 'amount': 38758.0},
            ],
            'foodPortions': [],
        },
    ]
}


class ImportUsdaJsonTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, 'foundation.json')
        with open(self.path, 'w', encoding='utf-8') as handle:
            json.dump(FOUNDATION_JSON, handle)

    def run_import(self, **kwargs):
        call_command('import_usda', self.path, verbosity=0, **kwargs)

    def test_foods_load_from_json(self):
        self.run_import()

        # Three of the four survive: the olive oil has no energy value.
        self.assertEqual(Food.objects.count(), 3)
        apple = Food.objects.get(fdc_id=2710824)
        self.assertEqual(apple.description, 'Apples, gala, with skin, raw')
        # The JSON says "Foundation"; the rest of the app speaks the CSV
        # spelling, so the two datasets stay comparable in one table.
        self.assertEqual(apple.data_type, 'foundation_food')
        self.assertEqual(apple.category, 'Fruits and Fruit Juices')

    def test_specific_atwater_energy_beats_general(self):
        """
        Where a food has both and no plain kcal row, specific factors win.

        A deliberate choice: the two disagree by around a tenth, so taking
        whichever appeared first in the file would make the calorie figure
        depend on document order.
        """
        self.run_import()

        self.assertEqual(
            Food.objects.get(fdc_id=2710824).nutrient_amounts()['kcal'], 54.9
        )

    def test_the_plain_kcal_row_beats_both_atwater_rows(self):
        self.run_import()

        self.assertEqual(
            Food.objects.get(fdc_id=2710825).nutrient_amounts()['kcal'], 229.0
        )

    def test_kilojoules_are_never_read_as_calories(self):
        """Reading nutrient 1062 as kcal would inflate every total fourfold."""
        self.run_import()

        amounts = Food.objects.get(fdc_id=2710825).nutrient_amounts()

        self.assertEqual(amounts['kcal'], 229.0)
        self.assertNotIn(958.0, amounts.values())

    def test_an_entry_with_no_amount_is_skipped(self):
        """Thirty Vitamin A entries in the real export have no amount."""
        self.run_import()

        self.assertNotIn(
            'vitamin_a_ug', Food.objects.get(fdc_id=2710824).nutrient_amounts()
        )

    def test_portions_prefer_the_unit_abbreviation(self):
        """So "tablespoon" lands as "tbsp", the way SR Legacy writes it."""
        self.run_import()

        apple = Food.objects.get(fdc_id=2710824)
        units = sorted(portion.measure_unit for portion in apple.portions.all())

        self.assertEqual(units, ['cup', 'tbsp'])
        cup = apple.portions.get(measure_unit='cup')
        self.assertEqual(cup.modifier, 'sliced')
        self.assertEqual(cup.gram_weight, 182.0)

    def test_an_undetermined_unit_falls_back_to_the_description(self):
        self.run_import()

        portion = Food.objects.get(fdc_id=2710825).portions.get()

        self.assertEqual(portion.measure_unit, '1 oz')

    def test_a_food_with_no_energy_value_is_skipped(self):
        """
        Fifty of the real export's 424 foods have no energy at all, and they
        are the worst possible fuzzy-match targets: extra-virgin olive oil
        with one nutrient, butter with twenty-one and no calories, dry beans
        analysed at zero moisture. SR Legacy has all of them complete, so
        keeping these only lets a matcher pick the worse of two.
        """
        self.run_import()

        self.assertFalse(Food.objects.filter(fdc_id=2710826).exists())
        # Its portion row goes with it rather than being orphaned.
        self.assertEqual(FoodPortion.objects.filter(food__fdc_id=2710826).count(), 0)

    def test_an_explicit_zero_is_kept(self):
        """
        Salt really is zero calories. A stored 0 is a measurement, not a
        gap, and the rule is about foods with no energy row at all.
        """
        self.run_import()

        salt = Food.objects.get(fdc_id=2710827)

        self.assertEqual(salt.nutrient_amounts()['kcal'], 0.0)
        self.assertEqual(salt.nutrient_amounts()['sodium_mg'], 38758.0)

    def test_reimporting_updates_rather_than_duplicates(self):
        self.run_import()
        self.run_import()

        self.assertEqual(Food.objects.count(), 3)
        self.assertEqual(FoodPortion.objects.count(), 3)

    def test_limit_stops_early(self):
        self.run_import(limit=1)

        self.assertEqual(Food.objects.count(), 1)

    def test_a_json_import_leaves_a_csv_one_alone(self):
        """
        Both datasets share one table, and loading one must not clear the
        rows of the other.
        """
        csv_directory = tempfile.mkdtemp()
        write_export(csv_directory)
        call_command('import_usda', csv_directory, verbosity=0)
        self.assertEqual(Food.objects.count(), 3)

        self.run_import()

        self.assertEqual(Food.objects.count(), 6)
        self.assertEqual(
            Food.objects.get(fdc_id=169228).nutrient_amounts()['kcal'], 40.0
        )

    def test_limit_counts_foods_read_not_foods_kept(self):
        """
        --limit stops reading early, so what it keeps depends on which of
        the first N had energy. Stated here so the number is not a surprise.
        """
        self.run_import(limit=3)

        self.assertEqual(Food.objects.count(), 2)

    def test_a_path_that_is_neither_csv_nor_json_is_refused(self):
        notes = os.path.join(self.directory, 'notes.txt')
        with open(notes, 'w', encoding='utf-8') as handle:
            handle.write('hello')

        with self.assertRaises(CommandError):
            call_command('import_usda', notes, verbosity=0)
