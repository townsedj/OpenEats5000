#!/usr/bin/env python
# encoding: utf-8
"""
Ingredient matching, with a stub in place of the model.

No test here reaches the API. That is not only about cost: a test that
depends on a model's answer tests the model, and what needs testing is the
machinery around it -- what gets retrieved, what gets overridden by
arithmetic, and what gets thrown away because the model was not entitled to
say it.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from v1.household.models import Household
from v1.ingredient.models import Ingredient, IngredientGroup
from v1.nutrition import matching
from v1.nutrition.models import (
    Food, FoodNutrient, FoodPortion, IngredientMatch,
)
from v1.recipe.models import Recipe


class StubMatch(object):
    """Stands in for one entry of the model's parsed output."""

    def __init__(self, index, fdc_id=None, grams=None, confidence='high',
                 note='', alternate_search=None):
        self.index = index
        self.fdc_id = fdc_id
        self.grams = grams
        self.confidence = confidence
        self.note = note
        self.alternate_search = alternate_search


class StubParsed(object):
    def __init__(self, matches):
        self.matches = matches


class StubResponse(object):
    def __init__(self, matches):
        self.parsed_output = StubParsed(matches)


class StubClient(object):
    """
    A client that returns canned answers and records what it was asked.

    Shaped like the real one only as far as the code under test uses it:
    client.messages.parse(...) -> an object with .parsed_output.

    Pass a list of lists to answer successive calls differently, which is
    how the retry pass gets tested.
    """

    def __init__(self, matches):
        if matches and isinstance(matches[0], list):
            self.rounds = list(matches)
        else:
            self.rounds = [matches]
        self.calls = []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.rounds) - 1)
        return StubResponse(self.rounds[index])


def make_food(fdc_id, description, portions=(), category='',
              data_type=Food.DataType.SR_LEGACY, **amounts):
    food = Food.objects.create(
        fdc_id=fdc_id, description=description,
        data_type=data_type, category=category,
    )
    for key, amount in amounts.items():
        FoodNutrient.objects.create(food=food, nutrient=key, amount=amount)
    for unit, modifier, grams in portions:
        FoodPortion.objects.create(
            food=food, amount=1, measure_unit=unit, modifier=modifier,
            gram_weight=grams,
        )
    return food


class RetrievalTests(TestCase):
    def setUp(self):
        self.onion = make_food(1, 'Onions, raw', kcal=40)
        self.rings = make_food(
            2, 'Onion rings, breaded, par fried, frozen, prepared, heated in oven',
            kcal=411,
        )
        self.soup = make_food(3, 'Soup, onion, dry, mix', kcal=310)
        self.beef = make_food(4, 'Beef, ground, 90% lean meat / 10% fat, raw', kcal=176)

    def test_the_plain_form_outranks_the_elaborate_one(self):
        """
        "Onions, raw" should beat onion rings for the word "onion". Both
        contain it; brevity is what separates them.
        """
        found = matching.candidates_for('white onion')

        self.assertEqual(found[0], self.onion)

    def test_every_word_counts_towards_the_score(self):
        found = matching.candidates_for('onion soup mix')

        self.assertEqual(found[0], self.soup)

    def test_knife_work_and_size_words_are_dropped(self):
        """
        "large" really does appear in descriptions ("Eggs, Grade A, Large"),
        so leaving it in would score eggs as highly as onions here.
        """
        self.assertEqual(matching.tokens('1 large onion, chopped'), ['onion'])

    def test_words_that_identify_the_food_are_kept(self):
        """
        The ones that look like noise and are not. Ground beef is a
        different food from a steak, whole wheat from wheat, and USDA
        distinguishes fresh basil from dried.
        """
        self.assertEqual(matching.tokens('ground sirloin'), ['ground', 'sirloin'])
        self.assertEqual(
            matching.tokens('whole wheat flour'), ['whole', 'wheat', 'flour']
        )
        self.assertEqual(matching.tokens('fresh basil'), ['fresh', 'basil'])

    def test_ground_beef_is_retrievable(self):
        """
        The regression this list caused: "ground" was treated as knife work,
        so "ground sirloin" retrieved nothing and was never even asked
        about -- the line silently went unmatched.
        """
        self.assertIn(self.beef, matching.candidates_for('ground sirloin'))

    def test_a_line_of_nothing_but_stopwords_still_retrieves(self):
        """Better to search on a weak word than to give up with nothing."""
        self.assertEqual(matching.tokens('large chopped'), ['large', 'chopped'])

    def test_an_unknown_ingredient_returns_no_candidates(self):
        self.assertEqual(matching.candidates_for('unobtainium'), [])

    def test_retrieval_is_capped(self):
        for index in range(30):
            make_food(100 + index, 'Onions, variety %s' % index, kcal=40)

        self.assertLessEqual(
            len(matching.candidates_for('onion')),
            matching.CANDIDATES_PER_LINE,
        )


class RankingTests(TestCase):
    """
    What gets into the twelve slots when no food contains every word.

    All of these were found by running a week of ordinary shopping through
    retrieval and reading the lists: the model can only pick from what it is
    offered, so a right answer ranked thirteenth is a wrong answer.
    """

    def test_a_rare_word_outranks_a_common_one(self):
        """
        Nothing in FoodData Central says both "ground" and "sirloin", so
        every candidate matched one word and brevity decided -- which filled
        all twelve slots with emu, ostrich, lamb and flaxseed, and offered
        not one beef. "sirloin" is the word carrying the meaning.
        """
        sirloin = make_food(1, 'Beef, top sirloin steak, raw', kcal=201)
        for index, animal in enumerate(
            ('Emu', 'Lamb', 'Veal', 'Pork', 'Bison', 'Turkey', 'Ostrich')
        ):
            make_food(10 + index, '%s, ground, raw' % animal, kcal=200)

        found = matching.candidates_for('ground sirloin')

        self.assertEqual(found[0], sirloin)

    def test_a_food_matching_every_word_still_wins(self):
        """
        Rarity is only a tiebreak. A description containing the whole line
        beats one containing the rare half of it, however rare that half is.
        """
        broth = make_food(1, 'Soup, chicken broth, canned', kcal=5)
        make_food(2, 'Fish broth', kcal=5)
        for index in range(8):
            make_food(10 + index, 'Chicken, cut %s, raw' % index, kcal=190)

        self.assertEqual(matching.candidates_for('chicken broth')[0], broth)

    def test_each_reading_of_the_line_keeps_some_slots(self):
        """
        "kosher salt" is the case that made this necessary. "kosher" is the
        rarer word, nothing contains both, and there are more than twelve
        kosher foods -- so ranking by rarity alone offered twelve pickles and
        pushed the one food the line meant out of the list entirely.
        """
        table = make_food(1, 'Salt, table', sodium_mg=38758)
        for index in range(13):
            make_food(10 + index, 'Pickles, kosher dill, variety %s' % index)
        for index in range(16):
            make_food(40 + index, 'Vegetable %s, cooked, with salt' % index)

        found = matching.candidates_for('kosher salt')

        self.assertIn(table, found)

    def test_the_food_itself_outranks_a_dish_that_shares_its_name(self):
        """
        USDA writes "FOOD, qualifier, qualifier", so what sits before the
        first comma is the food and the rest is detail. "Rice crackers" is a
        cracker; "Rice, white, long-grain" is rice, and is what "jasmine
        rice" means even though it is the longer description.
        """
        rice = make_food(1, 'Rice, white, long grain, raw', kcal=365)
        make_food(2, 'Rice crackers', kcal=416)
        make_food(3, 'Rice bran, crude', kcal=316)

        self.assertEqual(matching.candidates_for('jasmine rice')[0], rice)

    def test_baby_food_is_demoted(self):
        """
        "orange juice" offered seven baby foods out of twelve. They are real
        foods, so this is a tiebreak and not a filter: a line that means one
        says "babyfood", and then it matches on its own merit.
        """
        juice = make_food(
            1, 'Beverages, orange juice, canned', kcal=45,
            category='Fruits and Fruit Juices',
        )
        baby = make_food(
            2, 'Babyfood, juice, orange', kcal=45, category='Baby Foods',
        )

        found = matching.candidates_for('orange juice')

        self.assertEqual(found[0], juice)
        self.assertIn(baby, found)

    def test_a_line_that_names_a_demoted_food_still_finds_it(self):
        make_food(1, 'Beverages, orange juice, canned', kcal=45)
        baby = make_food(
            2, 'Babyfood, juice, orange', kcal=45, category='Baby Foods',
        )

        self.assertEqual(
            matching.candidates_for('babyfood orange juice')[0], baby
        )

    def test_the_fuller_of_two_identical_rows_is_offered_once(self):
        """
        Ninety descriptions are published by both SR Legacy and Foundation.
        Offering both spends two slots on one answer and asks the model to
        choose between two options that read the same. SR Legacy is kept
        because it carries the fuller record -- 29 nutrients against 13 to
        23, and usually more portions.
        """
        legacy = make_food(
            174030, 'Beef, ground, 90% lean meat / 10% fat, raw', kcal=176,
            data_type=Food.DataType.SR_LEGACY,
        )
        make_food(
            2514743, 'Beef, ground, 90% lean meat / 10% fat, raw', kcal=176,
            data_type=Food.DataType.FOUNDATION,
        )

        found = matching.candidates_for('ground beef')

        self.assertEqual(found, [legacy])

    def test_a_run_together_word_is_split(self):
        """
        Recipes write "breadcrumbs"; USDA writes "Bread crumbs, dry,
        grated". One word against two retrieved nothing, and a line with no
        candidates is never asked about -- it silently carries no nutrition.
        """
        crumbs = make_food(1, 'Bread, crumbs, dry, grated, plain', kcal=395)
        make_food(2, 'Bread, white, commercially prepared', kcal=270)
        make_food(3, 'Bread, rye', kcal=259)
        make_food(4, 'Cookie crumbs, chocolate', kcal=480)
        make_food(5, 'Pie crust crumbs, graham cracker', kcal=484)

        self.assertIn(crumbs, matching.candidates_for('breadcrumbs'))

    def test_a_split_is_not_invented(self):
        """
        Both halves have to be words the food table knows, or the word is
        left alone. Otherwise every unmatched word would be chopped up until
        some fragment hit something.
        """
        make_food(1, 'Bread, rye', kcal=259)

        self.assertEqual(matching.split_compound('unobtainium'), [])
        self.assertEqual(matching.candidates_for('unobtainium'), [])


class GramResolutionTests(TestCase):
    def setUp(self):
        self.onion = make_food(
            1, 'Onions, raw',
            portions=[('cup, chopped', '', 160.0), ('cup, sliced', '', 115.0),
                      ('large', '', 150.0)],
            kcal=40,
        )
        self.salt = make_food(
            2, 'Salt, table',
            portions=[('tsp', '', 6.0), ('tbsp', '', 18.0), ('dash', '', 0.4)],
            sodium_mg=38758,
        )

    def test_mass_units_are_arithmetic(self):
        self.assertEqual(matching.resolve_grams(self.onion, 200, 'g'), (200.0, 'mass'))
        self.assertAlmostEqual(
            matching.resolve_grams(self.onion, 1, 'lb')[0], 453.59237
        )
        self.assertAlmostEqual(
            matching.resolve_grams(self.onion, 4, 'oz')[0], 113.398, places=2
        )

    def test_a_recipe_word_maps_to_the_usda_abbreviation(self):
        """A recipe says "tablespoons"; USDA writes "tbsp"."""
        grams, source = matching.resolve_grams(self.salt, 2, 'tablespoons')

        self.assertEqual((grams, source), (36.0, 'portion'))

    def test_one_matching_portion_is_arithmetic(self):
        grams, source = matching.resolve_grams(self.salt, 1, 'tsp')

        self.assertEqual((grams, source), (6.0, 'portion'))

    def test_an_ambiguous_unit_is_left_to_judgement(self):
        """
        A cup of chopped onion is 160g and a cup of sliced is 115g -- a 28%
        spread. Picking one would be inventing precision; the model is given
        both and the line's own wording to decide from.
        """
        self.assertEqual(matching.resolve_grams(self.onion, 1, 'cup'), (None, None))

    def test_an_unknown_unit_is_left_to_judgement(self):
        self.assertEqual(
            matching.resolve_grams(self.onion, 2, 'handfuls'), (None, None)
        )

    def test_no_quantity_means_no_arithmetic(self):
        self.assertEqual(matching.resolve_grams(self.onion, 0, 'g'), (None, None))
        self.assertEqual(matching.resolve_grams(self.onion, None, 'g'), (None, None))

    def test_a_dash_of_salt_is_resolvable(self):
        """
        USDA does give salt a dash at 0.4g, so "a dash of kosher salt" is
        not unknowable -- it is 155mg of sodium rather than the 2,325mg a
        teaspoon would be.
        """
        grams, source = matching.resolve_grams(self.salt, 1, 'dash')

        self.assertEqual((grams, source), (0.4, 'portion'))


class ValidationTests(TestCase):
    """
    Recipe text is pasted in from the web, so what comes back is checked
    against what was sent rather than trusted.
    """

    def setUp(self):
        self.onion = make_food(1, 'Onions, raw', kcal=40)
        self.beef = make_food(2, 'Beef, ground, raw', kcal=250)
        self.lines = [{
            'index': 0,
            'title': 'onion',
            'quantity': 1,
            'measurement': 'whole',
            'candidates': [self.onion],
        }]

    def validate(self, *matches):
        return matching.validate(StubParsed(list(matches)), self.lines)

    def test_a_food_outside_the_candidates_is_refused(self):
        """
        The beef was never offered for this line. Accepting it would let a
        prompt injection, or just a confused answer, put any food anywhere.
        """
        accepted = self.validate(StubMatch(0, fdc_id=2, grams=100))

        self.assertIsNone(accepted[0]['fdc_id'])
        self.assertEqual(accepted[0]['confidence'], 'low')

    def test_a_food_in_the_candidates_is_accepted(self):
        accepted = self.validate(StubMatch(0, fdc_id=1, grams=110))

        self.assertEqual(accepted[0]['fdc_id'], 1)
        self.assertEqual(accepted[0]['grams'], 110)

    def test_an_unknown_line_index_is_dropped(self):
        accepted = self.validate(StubMatch(7, fdc_id=1, grams=100))

        self.assertEqual(accepted, {})

    def test_an_implausible_weight_is_dropped(self):
        """Twenty kilos of onion in one line is a parse failure, not a recipe."""
        accepted = self.validate(StubMatch(0, fdc_id=1, grams=500000))

        self.assertEqual(accepted[0]['fdc_id'], 1)
        self.assertIsNone(accepted[0]['grams'])

    def test_a_negative_weight_is_dropped(self):
        accepted = self.validate(StubMatch(0, fdc_id=1, grams=-5))

        self.assertIsNone(accepted[0]['grams'])

    def test_an_unrecognised_confidence_becomes_low(self):
        accepted = self.validate(
            StubMatch(0, fdc_id=1, grams=100, confidence='extremely sure')
        )

        self.assertEqual(accepted[0]['confidence'], 'low')

    def test_a_long_note_is_truncated(self):
        accepted = self.validate(
            StubMatch(0, fdc_id=1, grams=100, note='x' * 5000)
        )

        self.assertEqual(len(accepted[0]['note']), 200)


@override_settings(ANTHROPIC_API_KEY='not-used-by-the-stub')
class MatchRecipeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='top_secret'
        )
        self.household = Household.objects.create(name='Ours')
        self.recipe = Recipe.objects.create(
            title='Tasty Chili', author=self.user, household=self.household,
            servings=4, directions='Cook it.',
        )
        self.group = IngredientGroup.objects.create(recipe=self.recipe, title='')

        self.beef = make_food(
            1, 'Beef, ground, 90% lean meat / 10% fat, raw',
            portions=[('lb', '', 453.6)], kcal=176, protein_g=20,
        )
        self.onion = make_food(
            2, 'Onions, raw',
            portions=[('cup, chopped', '', 160.0), ('cup, sliced', '', 115.0)],
            kcal=40,
        )

    def line(self, title, numerator=1, denominator=1, measurement=''):
        return Ingredient.objects.create(
            ingredient_group=self.group, title=title,
            numerator=numerator, denominator=denominator,
            measurement=measurement,
        )

    def test_arithmetic_overrides_the_models_weight(self):
        """
        The central rule. The model guessed 999g for a pound of beef; a
        pound is 453.6g and that is not a matter of opinion.
        """
        self.line('ground sirloin', 1, 1, 'lb')
        client = StubClient([StubMatch(0, fdc_id=1, grams=999)])

        summary = matching.match_recipe(self.recipe, client=client)

        row = Ingredient.objects.get()
        self.assertEqual(row.food, self.beef)
        # The exact conversion, not USDA's rounded 453.6 "lb" portion: a
        # unit conversion is a constant and beats a published rounding.
        self.assertAlmostEqual(row.grams, 453.59237, places=4)
        self.assertEqual(summary['grams_from']['mass'], 1)
        self.assertEqual(summary['grams_from']['model'], 0)

    def test_the_models_weight_is_used_where_arithmetic_cannot_reach(self):
        """
        "1 cup onion" is genuinely ambiguous -- chopped is 160g, sliced
        115g -- so here the judgement is the answer.
        """
        self.line('onion', 1, 1, 'cup')
        client = StubClient([StubMatch(0, fdc_id=2, grams=160)])

        summary = matching.match_recipe(self.recipe, client=client)

        row = Ingredient.objects.get()
        self.assertEqual(row.grams, 160)
        self.assertEqual(summary['grams_from']['model'], 1)

    def test_a_match_is_recorded_as_automatic(self):
        self.line('ground sirloin', 1, 1, 'lb')
        client = StubClient([StubMatch(0, fdc_id=1, grams=453.6)])

        matching.match_recipe(self.recipe, client=client)

        row = Ingredient.objects.get()
        self.assertEqual(row.match_source, Ingredient.MatchSource.AUTO)
        self.assertEqual(row.match_confidence, 'high')

    def test_a_hand_corrected_line_is_left_alone(self):
        """
        The correction is the most reliable thing in the table, and
        overwriting it is exactly what the save path was fixed to stop.
        """
        row = self.line('ground sirloin', 1, 1, 'lb')
        row.food = self.onion          # deliberately wrong, but chosen by a person
        row.grams = 500
        row.match_source = Ingredient.MatchSource.MANUAL
        row.save()

        client = StubClient([StubMatch(0, fdc_id=1, grams=453.6)])
        summary = matching.match_recipe(self.recipe, client=client)

        row.refresh_from_db()
        self.assertEqual(row.food, self.onion)
        self.assertEqual(row.grams, 500)
        self.assertEqual(summary['considered'], 0)
        self.assertEqual(client.calls, [])

    def test_force_asks_again_even_when_the_cache_has_an_answer(self):
        """
        The cache is keyed by the ingredient's text, so without this, force
        hands back the very answer being rejected -- and its only effect is
        to overwrite a hand correction with that answer. Asking to redo a
        line has to mean asking again.
        """
        IngredientMatch.objects.create(
            text='ground sirloin', food=self.onion, confidence='high',
        )
        row = self.line('ground sirloin', 1, 1, 'lb')

        client = StubClient([StubMatch(0, fdc_id=1, grams=453.6)])
        summary = matching.match_recipe(self.recipe, client=client, force=True)

        row.refresh_from_db()
        self.assertEqual(row.food, self.beef)
        self.assertEqual(summary['from_cache'], 0)
        self.assertEqual(summary['from_model'], 1)
        self.assertTrue(client.calls)

    def test_force_redoes_a_hand_corrected_line(self):
        row = self.line('ground sirloin', 1, 1, 'lb')
        row.match_source = Ingredient.MatchSource.MANUAL
        row.food = self.onion
        row.save()

        client = StubClient([StubMatch(0, fdc_id=1, grams=453.6)])
        matching.match_recipe(self.recipe, client=client, force=True)

        row.refresh_from_db()
        self.assertEqual(row.food, self.beef)

    def test_an_already_matched_line_is_not_asked_about_again(self):
        row = self.line('ground sirloin', 1, 1, 'lb')
        row.food = self.beef
        row.grams = 453.6
        row.save()

        client = StubClient([])
        summary = matching.match_recipe(self.recipe, client=client)

        self.assertEqual(summary['considered'], 0)
        self.assertEqual(client.calls, [])

    def test_the_cache_answers_the_second_time(self):
        """
        "white onion" means the same food in every recipe that lists it, so
        the question is asked once.
        """
        self.line('onion', 1, 1, 'cup')
        client = StubClient([StubMatch(0, fdc_id=2, grams=160)])
        matching.match_recipe(self.recipe, client=client)

        self.assertEqual(IngredientMatch.objects.count(), 1)
        self.assertEqual(IngredientMatch.objects.get().food, self.onion)

        other = Recipe.objects.create(
            title='Soup', author=self.user, household=self.household,
            servings=2, directions='Cook it.',
        )
        group = IngredientGroup.objects.create(recipe=other, title='')
        Ingredient.objects.create(
            ingredient_group=group, title='onion',
            numerator=200, denominator=1, measurement='g',
        )

        second = StubClient([])
        summary = matching.match_recipe(other, client=second)

        self.assertEqual(summary['from_cache'], 1)
        self.assertFalse(summary['called_model'])
        self.assertEqual(second.calls, [])
        # And the grams are this recipe's own, not the cached line's.
        self.assertEqual(
            Ingredient.objects.get(ingredient_group=group).grams, 200
        )

    def test_a_remembered_non_match_is_not_asked_again(self):
        """
        "nothing fits this" is worth caching too, or every save re-asks the
        same unanswerable question.
        """
        self.line('ground sirloin', 1, 1, 'lb')
        client = StubClient([StubMatch(0, fdc_id=None, grams=None, confidence='low')])
        matching.match_recipe(self.recipe, client=client)

        entry = IngredientMatch.objects.get()
        self.assertIsNone(entry.food)

        # No force here: the row has no food, so it is reconsidered anyway,
        # and the remembered "nothing fits" is what should answer it.
        again = StubClient([])
        summary = matching.match_recipe(self.recipe, client=again)

        self.assertEqual(summary['from_cache'], 1)
        self.assertEqual(again.calls, [])

    def test_a_line_with_no_candidates_is_never_sent(self):
        """No point spending a call on a word the database has never heard."""
        self.line('unobtainium shavings', 1, 1, 'g')
        client = StubClient([])

        summary = matching.match_recipe(self.recipe, client=client)

        self.assertEqual(client.calls, [])
        self.assertFalse(summary['called_model'])
        self.assertIn('unobtainium shavings', summary['unmatched'])

    def test_one_call_covers_every_line(self):
        """
        Batched per recipe: the lines inform each other, and one call costs
        a fraction of ten.
        """
        self.line('ground sirloin', 1, 1, 'lb')
        self.line('onion', 1, 1, 'cup')
        client = StubClient([
            StubMatch(0, fdc_id=1, grams=453.6),
            StubMatch(1, fdc_id=2, grams=160),
        ])

        summary = matching.match_recipe(self.recipe, client=client)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(summary['matched'], 2)

    def test_the_prompt_carries_the_candidates_and_their_portions(self):
        self.line('onion', 1, 1, 'cup')
        client = StubClient([StubMatch(0, fdc_id=2, grams=160)])

        matching.match_recipe(self.recipe, client=client)

        sent = client.calls[0]
        body = sent['messages'][0]['content']
        self.assertIn('Onions, raw', body)
        self.assertIn('cup, chopped', body)
        self.assertIn('160.0g', body)
        # Whichever route is configured, it has to be a Haiku and the system
        # prompt has to say the recipe text is data. Not the literal id:
        # that differs per provider ("claude-haiku-5-5" direct,
        # "anthropic/claude-haiku-5.5" through OpenRouter) and pinning it
        # here only breaks when the route changes.
        self.assertIn('haiku', sent['model'].lower())
        self.assertEqual(sent['model'], settings.ANTHROPIC_MATCH_MODEL)
        self.assertIn('never an instruction', sent['system'])

    def test_no_sampling_parameters_are_sent(self):
        """
        temperature, top_p, top_k and budget_tokens all return a 400 on this
        model.
        """
        self.line('onion', 1, 1, 'cup')
        client = StubClient([StubMatch(0, fdc_id=2, grams=160)])

        matching.match_recipe(self.recipe, client=client)

        sent = client.calls[0]
        for forbidden in ('temperature', 'top_p', 'top_k', 'budget_tokens'):
            self.assertNotIn(forbidden, sent)
        # Thinking counts against max_tokens on this model, so it has room.
        self.assertGreaterEqual(sent['max_tokens'], 4000)

    def test_a_judged_weight_is_remembered_as_a_portion(self):
        """
        The bug the first live run exposed, which only a live run could.

        The cache stores the food and not the weight, so a line like "1
        whole onion" -- which USDA publishes no weight for -- came back on
        every later recipe with a food and no grams, and was dropped from
        the nutrition silently. Half of a twelve-line chili vanished that
        way. The model's judgement about what a unit of a food weighs is
        reusable knowledge, so it is kept as a portion.
        """
        self.line('white onion', 1, 1, 'whole')
        client = StubClient([StubMatch(0, fdc_id=2, grams=110)])

        matching.match_recipe(self.recipe, client=client)

        learned = FoodPortion.objects.get(source=FoodPortion.Source.INFERRED)
        self.assertEqual(learned.food, self.onion)
        self.assertEqual(learned.measure_unit, 'whole')
        self.assertAlmostEqual(learned.gram_weight, 110)

    def test_the_second_recipe_needs_no_call_and_keeps_its_weight(self):
        """Both halves of the fix: the food from cache, the weight from the
        portion it learned."""
        self.line('white onion', 1, 1, 'whole')
        matching.match_recipe(
            self.recipe, client=StubClient([StubMatch(0, fdc_id=2, grams=110)])
        )

        other = Recipe.objects.create(
            title='Soup', author=self.user, household=self.household,
            servings=2, directions='Cook it.',
        )
        group = IngredientGroup.objects.create(recipe=other, title='')
        Ingredient.objects.create(
            ingredient_group=group, title='white onion',
            numerator=2, denominator=1, measurement='whole',
        )

        silent = StubClient([])
        summary = matching.match_recipe(other, client=silent)

        self.assertEqual(silent.calls, [])
        self.assertEqual(summary['from_cache'], 1)
        self.assertEqual(summary['grams_from']['portion'], 1)
        # Two onions, not one.
        self.assertAlmostEqual(
            Ingredient.objects.get(ingredient_group=group).grams, 220
        )

    def test_a_weight_per_unit_is_stored_not_the_line_total(self):
        self.line('white onion', 3, 1, 'whole')
        client = StubClient([StubMatch(0, fdc_id=2, grams=330)])

        matching.match_recipe(self.recipe, client=client)

        learned = FoodPortion.objects.get(source=FoodPortion.Source.INFERRED)
        self.assertAlmostEqual(learned.gram_weight, 110)

    def test_a_measured_portion_is_preferred_over_an_inferred_one(self):
        """An inferred weight must never override USDA's own measurement."""
        FoodPortion.objects.create(
            food=self.onion, amount=1, measure_unit='whole',
            gram_weight=999, source=FoodPortion.Source.INFERRED,
        )
        FoodPortion.objects.create(
            food=self.onion, amount=1, measure_unit='whole',
            gram_weight=150, source=FoodPortion.Source.USDA,
        )

        grams, source = matching.resolve_grams(self.onion, 1, 'whole')

        self.assertAlmostEqual(grams, 150)
        self.assertEqual(source, 'portion')

    def test_mass_units_teach_nothing(self):
        """A gram is already arithmetic; there is no judgement to keep."""
        self.line('white onion', 200, 1, 'g')
        client = StubClient([StubMatch(0, fdc_id=2, grams=200)])

        matching.match_recipe(self.recipe, client=client)

        self.assertFalse(
            FoodPortion.objects.filter(source=FoodPortion.Source.INFERRED).exists()
        )

    def test_an_implausible_judged_weight_is_not_remembered(self):
        self.line('white onion', 1, 1, 'whole')
        client = StubClient([StubMatch(0, fdc_id=2, grams=0)])

        matching.match_recipe(self.recipe, client=client)

        self.assertFalse(
            FoodPortion.objects.filter(source=FoodPortion.Source.INFERRED).exists()
        )

    def test_every_gram_source_is_counted(self):
        """
        The regression from the first live run: 'salt' was added as a gram
        source but not to the summary's counters, so the run crashed on a
        KeyError after the API call was paid for and the rows were written.
        """
        for source in matching.GRAM_SOURCES:
            self.assertIn(source, matching.match_recipe(
                self.recipe, client=StubClient([])
            )['grams_from'])

    def test_a_salt_line_is_counted_under_salt(self):
        salt_food = make_food(
            3, 'Salt, table', portions=[('tsp', '', 6.0)], sodium_mg=38758
        )
        Ingredient.objects.create(
            ingredient_group=self.group, title='kosher salt',
            numerator=1, denominator=1, measurement='tsp',
        )
        client = StubClient([StubMatch(0, fdc_id=3, grams=6)])

        summary = matching.match_recipe(self.recipe, client=client)

        self.assertEqual(summary['grams_from']['salt'], 1)
        self.assertAlmostEqual(Ingredient.objects.get().grams, 4.8)

    def test_a_missing_answer_for_a_line_leaves_it_unmatched(self):
        self.line('ground sirloin', 1, 1, 'lb')
        self.line('onion', 1, 1, 'cup')
        client = StubClient([StubMatch(0, fdc_id=1, grams=453.6)])

        summary = matching.match_recipe(self.recipe, client=client)

        self.assertEqual(summary['matched'], 1)
        self.assertIn('onion', summary['unmatched'])

    def test_matching_makes_the_recipe_computable(self):
        """The point of all of it."""
        from v1.nutrition.compute import recipe_nutrition

        self.line('ground sirloin', 1, 1, 'lb')
        client = StubClient([StubMatch(0, fdc_id=1, grams=453.6)])
        matching.match_recipe(self.recipe, client=client)

        result = recipe_nutrition(self.recipe)

        # 453.6g at 176 kcal/100g over 4 servings.
        self.assertAlmostEqual(result['per_serving']['kcal'], 199.6, places=1)
        self.assertEqual(result['note']['confidence'], 'high')


@override_settings(ANTHROPIC_API_KEY='not-used-by-the-stub')
class RetryTests(TestCase):
    """
    The second pass, which is what makes real recipe wording work.

    Word matching cannot bridge a synonym or a typo. Against the real table,
    "ground sirloin" returns every ground meat except beef -- emu, flaxseed,
    lamb, veal, pork, bison, turkey, chicken, ostrich -- because beef's
    ground entries carry long percentage descriptions and lose the brevity
    tiebreak. A line misspelt "tomatos" returns tomatoseed oil. Both are
    answerable once the model gets to say what to search for instead.
    """

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

        # Reachable only by searching for "beef", never for "sirloin".
        self.beef = make_food(
            1, 'Beef, ground, 90% lean meat / 10% fat, raw', kcal=176
        )
        # A decoy that "sirloin" does retrieve, so the first pass has
        # something plausible-looking to reject.
        make_food(2, 'Lamb, ground, raw', kcal=282)

    def line(self, title, measurement='g', numerator=450):
        return Ingredient.objects.create(
            ingredient_group=self.group, title=title,
            numerator=numerator, denominator=1, measurement=measurement,
        )

    def test_a_suggested_search_term_rescues_the_line(self):
        self.line('ground sirloin')
        client = StubClient([
            [StubMatch(0, fdc_id=None, alternate_search='beef ground')],
            [StubMatch(0, fdc_id=1, grams=450, confidence='medium')],
        ])

        summary = matching.match_recipe(self.recipe, client=client)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(Ingredient.objects.get().food, self.beef)
        self.assertEqual(summary['retried'], 1)

    def test_the_retry_sees_candidates_from_the_new_term(self):
        self.line('ground sirloin')
        client = StubClient([
            [StubMatch(0, fdc_id=None, alternate_search='beef ground')],
            [StubMatch(0, fdc_id=1, grams=450)],
        ])

        matching.match_recipe(self.recipe, client=client)

        second = client.calls[1]['messages'][0]['content']
        self.assertIn('Beef, ground', second)
        # And it still knows what it is matching.
        self.assertIn('ground sirloin', second)

    def test_no_suggestion_means_no_second_call(self):
        """
        When the model judges the database simply will not have the food --
        a brand-name sauce, say -- there is nothing to search for again.
        """
        self.line('ground mystery paste')
        client = StubClient([StubMatch(0, fdc_id=None, alternate_search=None)])

        summary = matching.match_recipe(self.recipe, client=client)

        # It was asked once (the word "ground" retrieves candidates here)
        # and not asked twice.
        self.assertEqual(len(client.calls), 1)
        self.assertIn('ground mystery paste', summary['unmatched'])

    def test_a_suggestion_that_finds_nothing_means_no_second_call(self):
        self.line('ground sirloin')
        client = StubClient([
            [StubMatch(0, fdc_id=None, alternate_search='unobtainium')],
        ])

        matching.match_recipe(self.recipe, client=client)

        self.assertEqual(len(client.calls), 1)

    def test_the_retry_runs_only_once(self):
        """No loop: a second failure is the end of it."""
        self.line('ground sirloin')
        client = StubClient([
            [StubMatch(0, fdc_id=None, alternate_search='beef ground')],
            [StubMatch(0, fdc_id=None, alternate_search='beef ground')],
        ])

        summary = matching.match_recipe(self.recipe, client=client)

        self.assertEqual(len(client.calls), 2)
        self.assertIn('ground sirloin', summary['unmatched'])

    def test_a_retry_answer_is_validated_against_the_new_candidates(self):
        """A second answer is trusted no more than the first."""
        self.line('ground sirloin')
        client = StubClient([
            [StubMatch(0, fdc_id=None, alternate_search='beef ground')],
            # fdc_id 999 was never offered.
            [StubMatch(0, fdc_id=999, grams=450)],
        ])

        matching.match_recipe(self.recipe, client=client)

        self.assertIsNone(Ingredient.objects.get().food)

    def test_a_line_matched_first_time_is_not_retried(self):
        self.line('ground sirloin')
        client = StubClient([StubMatch(0, fdc_id=1, grams=450)])

        matching.match_recipe(self.recipe, client=client)

        self.assertEqual(len(client.calls), 1)


class MissingKeyTests(TestCase):
    @override_settings(ANTHROPIC_API_KEY=None)
    def test_a_missing_key_is_a_clear_error(self):
        with self.assertRaises(RuntimeError) as caught:
            matching.get_client()

        self.assertIn('ANTHROPIC_API_KEY', str(caught.exception))
