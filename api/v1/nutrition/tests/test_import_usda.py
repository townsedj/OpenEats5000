#!/usr/bin/env python
# encoding: utf-8

import os
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from v1.nutrition.models import Food, FoodNutrient, FoodPortion

# A miniature FoodData Central export. Column names and the id-versus-number
# split are what the real files use; the rows are made up.
FOOD_CSV = '''"fdc_id","data_type","description","food_category_id","publication_date"
"169228","sr_legacy_food","Onions, raw","11","2019-04-01"
"167902","sr_legacy_food","Pork, ground, raw","10","2019-04-01"
"321360","foundation_food","Beans, kidney, raw","16","2021-10-28"
'''

FOOD_CATEGORY_CSV = '''"id","code","description"
"10","1000","Pork Products"
"11","1100","Vegetables and Vegetable Products"
"16","1600","Legumes and Legume Products"
'''

# `id` is what food_nutrient.csv points at; `nutrient_nbr` is the older
# number. 2047 is energy by Atwater general factors, which some Foundation
# foods carry instead of 1008.
NUTRIENT_CSV = '''"id","name","unit_name","nutrient_nbr","rank"
"1003","Protein","G","203","600"
"1008","Energy","KCAL","208","300"
"1079","Fiber, total dietary","G","291","1200"
"1087","Calcium, Ca","MG","301","5300"
"1089","Iron, Fe","MG","303","5400"
"1093","Sodium, Na","MG","307","5800"
"1258","Fatty acids, total saturated","G","606","9700"
"2047","Energy (Atwater General Factors)","KCAL","957","280"
"1062","Energy","kJ","268","400"
'''

FOOD_NUTRIENT_CSV = '''"id","fdc_id","nutrient_id","amount"
"1","169228","1008","40.0"
"2","169228","1093","4.0"
"3","169228","1079","1.7"
"4","167902","1008","263.0"
"5","167902","1003","16.9"
"6","167902","1093","61.0"
"7","167902","1258","8.0"
"8","321360","2047","337.0"
"9","321360","1089","8.2"
"10","321360","1087","143.0"
"11","169228","1062","167.0"
"12","169228","9999","1.0"
'''

MEASURE_UNIT_CSV = '''"id","name"
"1000","cup"
"1001","tbsp"
"9999","undetermined"
'''

FOOD_PORTION_CSV = '''"id","fdc_id","seq_num","amount","measure_unit_id","portion_description","modifier","gram_weight"
"1","169228","1","1.0","1000","","chopped","160.0"
"2","169228","2","1.0","1000","","sliced","115.0"
"3","167902","1","1.0","9999","1 patty","","113.0"
"4","321360","1","1.0","1000","","","184.0"
"5","321360","2","1.0","1000","","","
'''

# How SR Legacy actually writes portions: unit id 9999 for every row, no
# portion_description, and the measure itself sitting in `modifier`.
SR_STYLE_PORTION_CSV = '''"id","fdc_id","seq_num","amount","measure_unit_id","portion_description","modifier","gram_weight"
"1","169228","1","1.0","9999","","cup, chopped","160.0"
"2","169228","2","1.0","9999","","cup, sliced","115.0"
"3","167902","1","1.0","9999","","serving","34.0"
'''


def write_export(path, **overrides):
    files = {
        'food.csv': FOOD_CSV,
        'food_category.csv': FOOD_CATEGORY_CSV,
        'nutrient.csv': NUTRIENT_CSV,
        'food_nutrient.csv': FOOD_NUTRIENT_CSV,
        'measure_unit.csv': MEASURE_UNIT_CSV,
        'food_portion.csv': FOOD_PORTION_CSV,
    }
    files.update(overrides)
    for name, content in files.items():
        if content is None:
            continue
        with open(os.path.join(path, name), 'w', encoding='utf-8') as handle:
            handle.write(content)


class ImportUsdaTests(TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def run_import(self, **kwargs):
        call_command('import_usda', self.directory, verbosity=0, **kwargs)

    def test_foods_nutrients_and_portions_are_loaded(self):
        write_export(self.directory)
        self.run_import()

        self.assertEqual(Food.objects.count(), 3)

        onion = Food.objects.get(fdc_id=169228)
        self.assertEqual(onion.description, 'Onions, raw')
        self.assertEqual(onion.data_type, 'sr_legacy_food')
        self.assertEqual(onion.category, 'Vegetables and Vegetable Products')

    def test_usda_ids_become_registry_keys(self):
        """The rest of the app never has to know that 1093 means sodium."""
        write_export(self.directory)
        self.run_import()

        amounts = Food.objects.get(fdc_id=167902).nutrient_amounts()

        self.assertEqual(amounts['kcal'], 263.0)
        self.assertEqual(amounts['protein_g'], 16.9)
        self.assertEqual(amounts['sodium_mg'], 61.0)
        self.assertEqual(amounts['satfat_g'], 8.0)

    def test_atwater_energy_is_read_as_calories(self):
        """
        Foundation foods sometimes carry energy as Atwater factors rather
        than the plain kcal row, and a food with no calories is useless.
        """
        write_export(self.directory)
        self.run_import()

        amounts = Food.objects.get(fdc_id=321360).nutrient_amounts()

        self.assertEqual(amounts['kcal'], 337.0)
        self.assertEqual(amounts['iron_mg'], 8.2)

    def test_kilojoule_energy_is_not_mistaken_for_calories(self):
        """
        Nutrient 1062 is energy in kJ. Reading it as kcal would inflate
        every total more than fourfold.
        """
        write_export(self.directory)
        self.run_import()

        self.assertEqual(Food.objects.get(fdc_id=169228).nutrient_amounts()['kcal'], 40.0)

    def test_nutrients_outside_the_registry_are_skipped(self):
        write_export(self.directory)
        self.run_import()

        self.assertFalse(FoodNutrient.objects.filter(nutrient='9999').exists())
        # 11 rows in the file, minus the kJ row and the unknown one.
        self.assertEqual(FoodNutrient.objects.count(), 10)

    def test_portions_keep_their_modifier_and_weight(self):
        write_export(self.directory)
        self.run_import()

        onion = Food.objects.get(fdc_id=169228)
        weights = {
            portion.modifier: portion.gram_weight
            for portion in onion.portions.all()
        }

        self.assertEqual(weights, {'chopped': 160.0, 'sliced': 115.0})

    def test_an_undetermined_unit_falls_back_to_the_description(self):
        write_export(self.directory)
        self.run_import()

        portion = Food.objects.get(fdc_id=167902).portions.get()

        self.assertEqual(portion.measure_unit, '1 patty')

    def test_a_portion_with_no_weight_is_skipped(self):
        """A measure without grams cannot resolve anything."""
        write_export(self.directory)
        self.run_import()

        self.assertEqual(Food.objects.get(fdc_id=321360).portions.count(), 1)

    def test_reimporting_updates_rather_than_duplicates(self):
        """
        FDC publishes a new export every few months, and re-running this
        must not leave two of every food.
        """
        write_export(self.directory)
        self.run_import()

        write_export(self.directory, **{
            'food.csv': FOOD_CSV.replace('Onions, raw', 'Onions, raw, white'),
        })
        self.run_import()

        self.assertEqual(Food.objects.count(), 3)
        self.assertEqual(
            Food.objects.get(fdc_id=169228).description, 'Onions, raw, white'
        )
        self.assertEqual(FoodNutrient.objects.count(), 10)
        self.assertEqual(FoodPortion.objects.count(), 4)

    def test_limit_stops_early(self):
        write_export(self.directory)
        self.run_import(limit=2)

        self.assertEqual(Food.objects.count(), 2)

    def test_a_missing_directory_is_a_clean_error(self):
        with self.assertRaises(CommandError):
            call_command('import_usda', os.path.join(self.directory, 'nope'))

    def test_a_missing_required_file_is_a_clean_error(self):
        write_export(self.directory, **{'food.csv': None})

        with self.assertRaises(CommandError):
            self.run_import()

    def test_sr_legacy_style_portions_get_their_unit(self):
        """
        SR Legacy carries the measure in `modifier`, with unit id 9999 and
        no portion_description -- for every one of its 14,449 rows. Reading
        only portion_description left them all with no unit, which is what
        "1 cup" has to match against.
        """
        write_export(self.directory, **{'food_portion.csv': SR_STYLE_PORTION_CSV})
        self.run_import()

        onion = Food.objects.get(fdc_id=169228)
        units = sorted(
            portion.measure_unit for portion in onion.portions.all()
        )

        self.assertEqual(units, ['cup, chopped', 'cup, sliced'])
        # The measure is the unit, so it is not also left in the modifier.
        self.assertEqual(
            [portion.modifier for portion in onion.portions.all()], ['', '']
        )
        self.assertEqual(
            onion.portions.get(measure_unit='cup, chopped').gram_weight, 160.0
        )

    def test_a_determined_unit_keeps_its_modifier(self):
        """
        Where the unit table does resolve, `modifier` is a qualifier of the
        measure rather than the measure itself, and must survive.
        """
        write_export(self.directory)
        self.run_import()

        portion = Food.objects.get(fdc_id=169228).portions.get(modifier='chopped')

        self.assertEqual(portion.measure_unit, 'cup')
        self.assertEqual(portion.modifier, 'chopped')

    def test_portions_are_optional(self):
        """Foundation exports do not always ship food_portion.csv."""
        write_export(self.directory)
        os.remove(os.path.join(self.directory, 'food_portion.csv'))

        self.run_import()

        self.assertEqual(Food.objects.count(), 3)
        self.assertEqual(FoodPortion.objects.count(), 0)
