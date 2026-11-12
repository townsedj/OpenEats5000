#!/usr/bin/env python
# encoding: utf-8

import datetime

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils.dateparse import parse_date
from rest_framework import views, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from v1.common.permissions import IsHouseholdMember
from v1.household.models import Household, NutritionTarget
from v1.nutrition import compute
from v1.recipe.models import Recipe
from .estimates import refresh_estimate
from .models import MenuItem, ServingLog
from .serializers import LogMealSerializer, MenuItemSerializer, week_start_for


def snapshot_nutrition(menu_item, servings):
    """
    Scale a plan entry's per-serving estimate to one person's portion.

    Written into the ServingLog row rather than derived on read: editing a
    recipe must not rewrite what somebody ate weeks ago. Returns the column
    values, the micros blob and the caveat, all of which get snapshotted --
    a number whose caveat was lost is worse than no number.
    """
    portion = compute.scale(menu_item.est_nutrition, servings)
    columns, micros = compute.split_for_log(portion)
    columns['micros'] = micros
    columns['nutrition_note'] = getattr(menu_item, 'est_nutrition_note', None)
    return columns


class MenuItemViewSet(viewsets.ModelViewSet):
    """
    The household's plan: `list`, `create`, `retrieve`, `update`, `destroy`,
    plus `log` for recording what was actually eaten.

    Listing accepts `?from=YYYY-MM-DD&to=YYYY-MM-DD`, and `?meal=` to narrow
    to one slot of the day. Entries with no date are included in a range
    when their week overlaps it, because an undated entry is still planned
    for that week -- that is the "any day" tray.
    """
    serializer_class = MenuItemSerializer
    permission_classes = (IsHouseholdMember,)
    filterset_fields = ('recipe', 'date', 'week_start', 'meal', 'status', 'kind')

    def get_queryset(self):
        user = self.request.user
        if not user or user.is_anonymous:
            return MenuItem.objects.none()

        queryset = MenuItem.objects.filter(
            household=Household.objects.for_user(user)
        ).select_related(
            'recipe', 'cook'
        ).prefetch_related('logs__user')

        return self._filter_date_range(queryset)

    def _filter_date_range(self, queryset):
        start = self._query_date('from')
        end = self._query_date('to')
        if start is None and end is None:
            return queryset

        dated = Q(date__isnull=False)
        undated = Q(date__isnull=True)
        if start is not None:
            dated &= Q(date__gte=start)
            undated &= Q(week_start__gte=week_start_for(start))
        if end is not None:
            dated &= Q(date__lte=end)
            undated &= Q(week_start__lte=week_start_for(end))

        return queryset.filter(dated | undated)

    def _query_date(self, param):
        raw = self.request.query_params.get(param)
        if not raw:
            return None
        try:
            parsed = parse_date(raw)
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValidationError({param: 'Expected a date as YYYY-MM-DD.'})
        return parsed

    @action(detail=True, methods=['post', 'delete'], url_path='log')
    def log(self, request, pk=None):
        """
        POST   menu-item/{id}/log  -- both people's portions, in one write.
        DELETE menu-item/{id}/log  -- undo: drops the logs, replans the meal.

        One request per tap, so there is no half-logged meal to reconcile and
        undo is a single call.
        """
        menu_item = self.get_object()

        if request.method == 'DELETE':
            with transaction.atomic():
                menu_item.logs.all().delete()
                menu_item.status = MenuItem.Status.PLANNED
                menu_item.save(update_fields=['status'])
            return Response(self._represent(menu_item))

        serializer = LogMealSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        eaten_on = data.get('date') or menu_item.date or datetime.date.today()

        # Recompute before freezing: this is the write that becomes the
        # permanent record of what was eaten.
        refresh_estimate(menu_item, save=True)

        with transaction.atomic():
            for entry in data['logs']:
                ServingLog.objects.update_or_create(
                    menu_item=menu_item,
                    user_id=entry['user'],
                    defaults=dict(
                        servings=entry['servings'],
                        date=eaten_on,
                        logged_by=request.user,
                        **snapshot_nutrition(menu_item, entry['servings'])
                    ),
                )

            menu_item.status = MenuItem.Status.EATEN
            fields = ['status']
            if menu_item.date is None:
                # Logging an "any day" entry is what finally dates it.
                menu_item.date = eaten_on
                menu_item.week_start = week_start_for(eaten_on)
                fields += ['date', 'week_start']
            menu_item.save(update_fields=fields)

        return Response(self._represent(menu_item))

    def _represent(self, menu_item):
        menu_item.refresh_from_db()
        return MenuItemSerializer(
            menu_item, context=self.get_serializer_context()
        ).data


class DayNutritionView(views.APIView):
    """
    GET menu/day-nutrition/?from=YYYY-MM-DD&to=YYYY-MM-DD

    Each person's day against their own targets. One request covers both
    people and the whole range, because the screen that reads this shows a
    week at a time.

    Every day carries a note rather than a bare set of numbers. A day with
    two meals logged out of four is not a low-calorie day, and a day whose
    recipes could not account for their salt has a sodium figure that is
    wrong rather than merely low. Reporting those as plain totals would be
    the most confident way to mislead.
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        household = Household.objects.for_user(request.user)

        start = self._date('from')
        end = self._date('to')

        logs = ServingLog.objects.filter(
            menu_item__household=household
        ).select_related('user')
        if start is not None:
            logs = logs.filter(date__gte=start)
        if end is not None:
            logs = logs.filter(date__lte=end)

        targets = {
            target.user_id: target.as_dict()
            for target in NutritionTarget.objects.filter(
                user__in=household.members.all()
            )
        }

        by_day = {}
        for log in logs:
            by_day.setdefault(log.date, {}).setdefault(log.user, []).append(log)

        days = []
        for date in sorted(by_day, key=lambda value: (value is None, value)):
            people = []
            for user, user_logs in by_day[date].items():
                totals = compute.sum_logs(user_logs)
                people.append({
                    'user_id': user.id,
                    'username': user.get_username(),
                    'totals': totals,
                    'against_target': compute.compare(
                        totals, targets.get(user.id, {})
                    ),
                    'note': self._note(user_logs),
                })
            people.sort(key=lambda row: row['user_id'])
            days.append({'date': date, 'people': people})

        return Response({'days': days})

    @staticmethod
    def _note(logs):
        """The worst caveat among the meals that make up this day."""
        notes = [log.nutrition_note or {} for log in logs]
        ranking = {'high': 0, 'medium': 1, 'low': 2}
        confidences = [
            note.get('confidence') for note in notes if note.get('confidence')
        ]
        return {
            'logged_meals': len(logs),
            'confidence': max(
                confidences, key=lambda level: ranking.get(level, 2)
            ) if confidences else None,
            'salt_not_counted': any(
                note.get('salt_not_counted') for note in notes
            ),
            'unmatched': sorted({
                title
                for note in notes
                for title in note.get('unmatched') or []
            }),
        }

    def _date(self, param):
        raw = self.request.query_params.get(param)
        if not raw:
            return None
        try:
            parsed = parse_date(raw)
        except ValueError:
            parsed = None
        if parsed is None:
            raise ValidationError({param: 'Expected a date as YYYY-MM-DD.'})
        return parsed


class MenuStatsViewSet(views.APIView):
    """
    How often the household has cooked each recipe, and when it last did.

    Was unscoped: it reported every recipe on the install to every caller,
    the one endpoint with no owner filter at all. Now it answers for the
    caller's household only.
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        household = Household.objects.for_user(request.user)
        eaten = Q(menu_recipe__status=MenuItem.Status.EATEN)

        return Response(
            Recipe.objects.filter(
                household=household
            ).filter(
                eaten
            ).annotate(
                num_menuitems=Count('menu_recipe', filter=eaten, distinct=True),
                last_made=Max('menu_recipe__date', filter=eaten),
            ).values(
                'slug',
                'title',
                'num_menuitems',
                'last_made',
            ).order_by(
                '-last_made',
                'num_menuitems',
            )
        )
