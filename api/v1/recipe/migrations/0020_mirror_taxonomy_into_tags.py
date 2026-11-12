"""Mirror each recipe's cuisine and course titles into Tags.

Cuisine and Course were required one-to-many fields; for a two-person
household they are just two more tags with extra machinery. This copies the
titles across so nothing is lost, leaving the FKs in place (now nullable)
until the front end stops reading them.
"""
from django.db import migrations


def taxonomy_to_tags(apps, schema_editor):
    Recipe = apps.get_model('recipe', 'Recipe')
    Tag = apps.get_model('recipe_groups', 'Tag')

    for recipe in Recipe.objects.select_related('cuisine', 'course').iterator():
        titles = [
            group.title
            for group in (recipe.cuisine, recipe.course)
            if group is not None and group.title
        ]
        for title in titles:
            tag, _ = Tag.objects.get_or_create(title=title)
            recipe.tags.add(tag)


def noop(apps, schema_editor):
    """Tags are not removed on reverse: by then they may be deliberate."""


class Migration(migrations.Migration):

    dependencies = [
        ('recipe', '0019_recipe_notes_alter_recipe_cook_time_and_more'),
        ('recipe_groups', '0003_auto_20180129_1456'),
    ]

    operations = [
        migrations.RunPython(taxonomy_to_tags, noop),
    ]
