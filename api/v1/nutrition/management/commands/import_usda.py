#!/usr/bin/env python
# encoding: utf-8
"""
Load generic foods from a FoodData Central export.

Takes a path you have already downloaded and unzipped rather than fetching
anything itself: the downloads are tens of megabytes, the file names carry a
release date that changes, and an import that silently re-downloads is an
import you cannot reproduce.

Get the archives from https://fdc.nal.usda.gov/download-datasets and point
this command at either form:

    python manage.py import_usda ../data/FoodData_Central_sr_legacy_food_csv_2018-04
    python manage.py import_usda ../data/FoodData_Central_foundation_food_json_2026-10-29.json

A directory is read as a CSV export, a .json file as a JSON one. Which form
you need is not a matter of taste: the Foundation CSV package contains no
food.csv and no food_nutrient.csv -- only lab provenance -- so Foundation
has to come from its JSON, while SR Legacy ships complete CSVs and no JSON
is needed.

Branded foods are deliberately out of scope. They are label-derived, about
two million rows, and of uneven quality; a jar of sauce gets entered by hand
with the sodium off its own label, which is more accurate than a guess from
a database average.
"""

import csv
import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from v1.nutrition import nutrients
from v1.nutrition.models import Food, FoodNutrient, FoodPortion

# FDC publishes amounts per 100 g of edible portion. Nothing downstream
# works if that assumption changes.
PER_GRAMS = 100

# What the JSON calls a dataset, mapped to the CSV spelling the rest of the
# app already uses.
JSON_DATA_TYPES = {
    'Foundation': Food.DataType.FOUNDATION,
    'SR Legacy': Food.DataType.SR_LEGACY,
}


class NutrientCollector(object):
    """
    Gathers nutrient amounts, keeping the best USDA id for each nutrient.

    A food can carry two ids that both mean the same thing -- energy by
    Atwater general factors and by specific factors, say -- and they
    routinely disagree. Taking whichever appeared first in the file would
    make the import depend on document order. This keeps the id the registry
    ranks highest and records how often it had to choose.
    """

    def __init__(self):
        self.priority = nutrients.usda_priority()
        self.best = {}
        self.displaced = 0

    def offer(self, fdc_id, usda_id, amount):
        known = self.priority.get(usda_id)
        if known is None or amount is None:
            return

        key, rank = known
        slot = (fdc_id, key)
        existing = self.best.get(slot)
        if existing is None:
            self.best[slot] = (rank, amount)
        elif rank < existing[0]:
            self.best[slot] = (rank, amount)
            self.displaced += 1
        elif rank > existing[0]:
            self.displaced += 1

    def keys_seen(self):
        return {key for (_fdc_id, key) in self.best}

    def rows(self, by_fdc_id):
        rows = []
        for (fdc_id, key), (_rank, amount) in self.best.items():
            food = by_fdc_id.get(fdc_id)
            if food is not None:
                rows.append(
                    FoodNutrient(food=food, nutrient=key, amount=amount)
                )
        return rows


class Command(BaseCommand):
    help = 'Import generic foods from a FoodData Central CSV or JSON export.'

    def add_arguments(self, parser):
        parser.add_argument(
            'path',
            help='A directory holding food.csv, nutrient.csv and '
                 'food_nutrient.csv, or a FoodData Central .json file',
        )
        parser.add_argument(
            '--limit', type=int, default=None,
            help='Stop after this many foods. For a quick look at the data.',
        )

    def handle(self, *args, **options):
        path = options['path']
        # Honour --verbosity so a test, or a cron run, can keep quiet.
        self.quiet = options.get('verbosity', 1) < 1
        limit = options['limit']

        if os.path.isdir(path):
            foods, collector, portions = self.read_csv_export(path, limit)
        elif os.path.isfile(path) and path.lower().endswith('.json'):
            foods, collector, portions = self.read_json_export(path, limit)
        else:
            raise CommandError(
                '%s is neither a directory of CSVs nor a .json file.' % path
            )

        dropped = self.drop_foods_without_energy(foods, collector, portions)

        self.say('%s foods' % len(foods))
        if dropped:
            self.say(
                '%s foods skipped for having no energy value at all '
                '(see the command docstring)' % len(dropped)
            )
            for description in dropped[:8]:
                self.say('    - %s' % description)
            if len(dropped) > 8:
                self.say('    ... and %s more' % (len(dropped) - 8))
        self.say(
            '%s of the %s nutrients this app tracks are in the export'
            % (len(collector.keys_seen()), len(nutrients.KEYS))
        )
        if collector.displaced:
            self.say(
                '%s nutrient values set aside in favour of a preferred '
                'USDA id (energy is usually the reason)' % collector.displaced
            )

        self.write(foods, collector, portions)
        self.say(self.style.SUCCESS('Done.'))

    @staticmethod
    def drop_foods_without_energy(foods, collector, portions):
        """
        Discard foods that carry no energy value, in place.

        An explicit zero is kept -- salt and water really are zero calories,
        and a stored 0 is a measurement. This is only about foods with no
        energy row at all.

        Those cannot take part honestly in an app whose unit of account is a
        day's calories against a goal, and the ones FDC ships are the worst
        possible candidates for a fuzzy name match: Foundation's
        extra-virgin olive oil has one nutrient and no energy, its butter
        has twenty-one and no energy, and seventeen of them are dry beans
        analysed at zero moisture, which is not food as anyone eats it. SR
        Legacy covers every one of them with a complete row -- olive oil at
        884 kcal, butter at 717 -- so keeping the empty ones only gives a
        matcher a chance to pick the worse of two.
        """
        keep = {fdc_id for (fdc_id, key) in collector.best if key == 'kcal'}

        dropped = sorted(
            food.description
            for fdc_id, food in foods.items()
            if fdc_id not in keep
        )
        for fdc_id in [fdc_id for fdc_id in foods if fdc_id not in keep]:
            del foods[fdc_id]

        for slot in [slot for slot in collector.best if slot[0] not in keep]:
            del collector.best[slot]

        portions[:] = [
            (fdc_id, spec) for fdc_id, spec in portions if fdc_id in keep
        ]

        return dropped

    def write(self, foods, collector, portions):
        with transaction.atomic():
            Food.objects.bulk_create(
                list(foods.values()),
                update_conflicts=True,
                update_fields=['description', 'data_type', 'category'],
                unique_fields=['fdc_id'],
            )
            by_fdc_id = {
                food.fdc_id: food
                for food in Food.objects.filter(fdc_id__in=foods.keys())
            }

            rows = collector.rows(by_fdc_id)
            FoodNutrient.objects.filter(food__in=by_fdc_id.values()).delete()
            FoodNutrient.objects.bulk_create(rows, batch_size=5000)
            self.say('%s nutrient rows' % len(rows))

            built = [
                FoodPortion(food=by_fdc_id[fdc_id], **spec)
                for fdc_id, spec in portions
                if fdc_id in by_fdc_id
            ]
            FoodPortion.objects.filter(food__in=by_fdc_id.values()).delete()
            FoodPortion.objects.bulk_create(built, batch_size=5000)
            self.say('%s portion rows' % len(built))

    def say(self, message):
        if not self.quiet:
            self.stdout.write(message)

    # ------------------------------------------------------------------- JSON

    def read_json_export(self, path, limit):
        with open(path, encoding='utf-8-sig') as handle:
            document = json.load(handle)

        # The top-level key names the dataset: "FoundationFoods",
        # "SRLegacyFoods", "BrandedFoods"...
        entries = []
        for value in document.values():
            if isinstance(value, list):
                entries = value
                break

        foods = {}
        collector = NutrientCollector()
        portions = []

        for entry in entries:
            fdc_id = self._int(entry.get('fdcId'))
            if fdc_id is None:
                continue

            category = entry.get('foodCategory') or {}
            foods[fdc_id] = Food(
                fdc_id=fdc_id,
                description=(entry.get('description') or '')[:300],
                data_type=JSON_DATA_TYPES.get(entry.get('dataType'), '')[:40],
                category=(category.get('description') or '')[:150],
            )

            for row in entry.get('foodNutrients') or []:
                nutrient = row.get('nutrient') or {}
                collector.offer(
                    fdc_id,
                    self._int(nutrient.get('id')),
                    self._float(row.get('amount')),
                )

            for row in entry.get('foodPortions') or []:
                spec = self._json_portion(row)
                if spec is not None:
                    portions.append((fdc_id, spec))

            if limit and len(foods) >= limit:
                break

        return foods, collector, portions

    def _json_portion(self, row):
        gram_weight = self._float(row.get('gramWeight'))
        if not gram_weight:
            return None

        unit = row.get('measureUnit') or {}
        # Prefer the abbreviation: it is what SR Legacy writes ("tbsp",
        # "tsp"), so the two datasets end up speaking the same way.
        measure = unit.get('abbreviation') or unit.get('name') or ''
        modifier = row.get('modifier') or ''

        if measure in ('', 'undetermined'):
            measure = row.get('portionDescription') or ''
            if not measure:
                measure = modifier
                modifier = ''

        return dict(
            amount=self._float(row.get('amount'))
                   or self._float(row.get('value')) or 1,
            measure_unit=measure[:80],
            modifier=modifier[:200],
            gram_weight=gram_weight,
        )

    # -------------------------------------------------------------------- CSV

    def read_csv_export(self, path, limit):
        foods = self.read_foods(path, limit)
        nutrient_keys = self.read_nutrient_ids(path)

        collector = NutrientCollector()
        for row in self.rows_of(path, 'food_nutrient.csv'):
            fdc_id = self._int(row.get('fdc_id'))
            if fdc_id not in foods:
                continue
            usda_id = nutrient_keys.get(row.get('nutrient_id'))
            collector.offer(fdc_id, usda_id, self._float(row.get('amount')))

        return foods, collector, self.read_portions(path, foods)

    def rows_of(self, path, name, required=True):
        full = os.path.join(path, name)
        if not os.path.exists(full):
            if required:
                raise CommandError('%s is missing from %s' % (name, path))
            return
        # newline='' per the csv module; FDC exports are utf-8 with a BOM on
        # some releases, which utf-8-sig handles either way.
        with open(full, newline='', encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                yield row

    def read_foods(self, path, limit):
        categories = {
            row['id']: row.get('description', '')
            for row in self.rows_of(path, 'food_category.csv', required=False) or []
        }

        foods = {}
        for row in self.rows_of(path, 'food.csv'):
            fdc_id = self._int(row.get('fdc_id'))
            if fdc_id is None:
                continue
            foods[fdc_id] = Food(
                fdc_id=fdc_id,
                description=(row.get('description') or '')[:300],
                data_type=(row.get('data_type') or '')[:40],
                category=categories.get(row.get('food_category_id'), '')[:150],
            )
            if limit and len(foods) >= limit:
                break
        return foods

    def read_nutrient_ids(self, path):
        """
        The export's own nutrient row ids, mapped to USDA nutrient ids.

        nutrient.csv carries both `id` (1008 for energy) and `nutrient_nbr`
        (208 for the same thing). The registry speaks in ids, but older
        exports reference numbers, so both are accepted. The value here is
        the USDA id, not our key, so that NutrientCollector can still see
        which of two competing ids it was given.
        """
        wanted = nutrients.usda_priority()
        mapping = {}
        for row in self.rows_of(path, 'nutrient.csv'):
            for field in ('id', 'nutrient_nbr'):
                usda_id = self._int(row.get(field))
                if usda_id in wanted:
                    mapping[row['id']] = usda_id
                    break
        return mapping

    def read_portions(self, path, foods):
        units = {
            row['id']: row.get('name', '')
            for row in self.rows_of(path, 'measure_unit.csv', required=False) or []
        }

        portions = []
        for row in self.rows_of(path, 'food_portion.csv', required=False) or []:
            fdc_id = self._int(row.get('fdc_id'))
            if fdc_id not in foods:
                continue
            gram_weight = self._float(row.get('gram_weight'))
            if not gram_weight:
                continue

            unit = units.get(row.get('measure_unit_id'), '')
            modifier = (row.get('modifier') or '')
            # "undetermined" means the measure is not in the unit table, and
            # which column actually holds it depends on the dataset. SR
            # Legacy puts it in `modifier` for every one of its 14,449 rows
            # -- all of them unit id 9999, none of them with a
            # portion_description -- while Foundation and FNDDS use
            # portion_description. Checking only the latter left every SR
            # Legacy portion with no unit at all, which is most of them.
            if unit in ('', 'undetermined'):
                unit = (row.get('portion_description') or '')
                if not unit:
                    unit = modifier
                    # Taking it from `modifier` means it is the measure, not
                    # a qualifier of one, so do not store it twice.
                    modifier = ''

            portions.append((fdc_id, dict(
                amount=self._float(row.get('amount')) or 1,
                measure_unit=unit[:80],
                modifier=modifier[:200],
                gram_weight=gram_weight,
            )))
        return portions

    # ----------------------------------------------------------------- casting

    @staticmethod
    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
