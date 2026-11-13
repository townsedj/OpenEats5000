#!/usr/bin/env python
# encoding: utf-8
"""
Match recipe ingredients to USDA foods, from the command line.

Exists because it is how this gets exercised before any front end does:

    python manage.py match_ingredients --slug tasty-chili
    python manage.py match_ingredients --all --dry-run

Every run that reaches the model costs money -- a fraction of a penny per
recipe on Haiku, but real -- so --dry-run shows what would be asked without
asking, and the command says how many recipes it is about to send.
"""

from django.core.management.base import BaseCommand, CommandError

from v1.nutrition import matching
from v1.nutrition.compute import recipe_nutrition
from v1.recipe.models import Recipe


class Command(BaseCommand):
    help = 'Match recipe ingredients to USDA foods and resolve gram weights.'

    def add_arguments(self, parser):
        parser.add_argument('--slug', help='One recipe, by slug')
        parser.add_argument(
            '--all', action='store_true',
            help='Every recipe that still has unmatched ingredients',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show the lines and their candidates without calling the model',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Ask again about lines already matched, including ones set '
                 'by hand. Reaches past the cache, so it always costs a call.',
        )

    def handle(self, *args, **options):
        if options['slug']:
            recipes = list(Recipe.objects.filter(slug=options['slug']))
            if not recipes:
                raise CommandError('No recipe with slug %r' % options['slug'])
        elif options['all']:
            recipes = list(Recipe.objects.all())
        else:
            raise CommandError('Give --slug or --all.')

        if options['dry_run']:
            return self.dry_run(recipes, options['force'])

        self.stdout.write(
            'Matching %s recipe(s). Each one that needs the model is one '
            'API call.' % len(recipes)
        )

        for recipe in recipes:
            summary = matching.match_recipe(recipe, force=options['force'])
            if not summary['considered']:
                self.stdout.write('  %s: nothing to do' % recipe.title)
                continue

            self.stdout.write('')
            self.stdout.write('  %s' % recipe.title)
            self.stdout.write(
                '    %s lines, %s from cache, %s from the model, %s matched'
                % (
                    summary['considered'], summary['from_cache'],
                    summary['from_model'], summary['matched'],
                )
            )
            self.stdout.write(
                '    grams: %s by unit conversion, %s from a portion, '
                '%s judged, %s unknown' % (
                    summary['grams_from']['mass'],
                    summary['grams_from']['portion'],
                    summary['grams_from']['model'],
                    summary['grams_from']['none'],
                )
            )
            for title in summary['unmatched']:
                self.stdout.write('    unmatched: %s' % title)

            result = recipe_nutrition(recipe)
            note = result['note']
            self.stdout.write(
                '    nutrition: %s confidence, %s of %s lines carry calories'
                % (note['confidence'], note['with_energy'], note['total'])
            )
            if note['salt_not_counted']:
                self.stdout.write(
                    self.style.WARNING('    salt is not counted in the sodium')
                )
            per_serving = result['per_serving']
            if per_serving.get('kcal') is not None:
                self.stdout.write(
                    '    per serving: %.0f kcal, %.0fg protein, %.0fmg sodium'
                    % (
                        per_serving.get('kcal') or 0,
                        per_serving.get('protein_g') or 0,
                        per_serving.get('sodium_mg') or 0,
                    )
                )

    def dry_run(self, recipes, force):
        """What would be sent, and what arithmetic already settles."""
        for recipe in recipes:
            rows = matching.lines_to_match(recipe, force=force)
            self.stdout.write('')
            self.stdout.write('%s (%s lines to match)' % (recipe.title, len(rows)))
            for row in rows:
                candidates = matching.candidates_for(row.title)
                grams, source = matching.resolve_grams(
                    candidates[0] if candidates else None,
                    row.quantity(), row.measurement,
                    ingredient=row, household=recipe.household,
                )
                self.stdout.write('  %r  %s %s' % (
                    row.title, row.quantity(), row.measurement or '',
                ))
                if source:
                    self.stdout.write(
                        '     grams settled by %s: %.1f' % (source, grams)
                    )
                for food in candidates[:4]:
                    self.stdout.write('     candidate: %s' % food.description[:66])
                if not candidates:
                    self.stdout.write(
                        self.style.WARNING('     no candidates, will not be asked')
                    )
