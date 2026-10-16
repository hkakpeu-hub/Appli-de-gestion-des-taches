from datetime import date, datetime, time, timedelta

import pytest

from suivi.core.models import ValidationError
from suivi.core.recurrence import RecurrenceInput, describe, occurrences
from suivi.core.tasks import TaskFilter

# mardi 13/10/2026 (clock de test : 09:00)
TODAY = date(2026, 10, 13)


def culte(**kw):
    base = dict(title="Culte", freq="weekly", weekdays=[6], start_date=TODAY, start_time=time(7), end_time=time(11))
    base.update(kw)
    return RecurrenceInput(**base)


def test_weekly_sunday_rule():
    ds = list(occurrences(culte(), TODAY, date(2026, 11, 8)))
    assert ds == [date(2026, 10, 18), date(2026, 10, 25), date(2026, 11, 1), date(2026, 11, 8)]
    assert all(d.weekday() == 6 for d in ds)
    assert describe(culte()) == "Toutes les semaines le dimanche, de 07:00 à 11:00"


def test_rule_variants():
    biweekly = RecurrenceInput(title="x", freq="weekly", interval=2, weekdays=[0, 3], start_date=date(2026, 10, 12))
    assert list(occurrences(biweekly, date(2026, 10, 12), date(2026, 11, 1))) == [
        date(2026, 10, 12), date(2026, 10, 15), date(2026, 10, 26), date(2026, 10, 29)]
    daily3 = RecurrenceInput(title="x", freq="daily", interval=3, start_date=TODAY)
    assert list(occurrences(daily3, TODAY, TODAY + timedelta(days=7))) == [TODAY, TODAY + timedelta(3), TODAY + timedelta(6)]
    monthly31 = RecurrenceInput(title="x", freq="monthly", month_day=31, start_date=date(2026, 1, 1))
    got = list(occurrences(monthly31, date(2026, 1, 1), date(2026, 4, 30)))
    assert got == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]  # dernier jour si mois court
    limited = RecurrenceInput(title="x", freq="daily", start_date=TODAY, count=3)
    assert len(list(occurrences(limited, TODAY, TODAY + timedelta(days=30)))) == 3
    ended = RecurrenceInput(title="x", freq="daily", start_date=TODAY, end_date=TODAY + timedelta(days=2))
    assert len(list(occurrences(ended, TODAY, TODAY + timedelta(days=30)))) == 3


def test_create_generates_real_tasks_in_planning(ctx):
    ctx.set_space(ctx.spaces.by_name("Kingdom").id)
    s = ctx.recurrences.create(culte(project_name="Culte du dimanche"))
    tasks = ctx.tasks.list(TaskFilter(sort="start"))
    assert 12 <= len(tasks) <= 14  # ~90 jours de dimanches
    assert all(t.series_id == s.id and t.start_time == time(7) and t.end_time == time(11) and t.start_date.weekday() == 6
               and t.deadline == t.start_date and t.project_name == "Culte du dimanche" for t in tasks)
    assert tasks[0].start_date == date(2026, 10, 18)
    from suivi.core import planning
    blocks = planning.blocks_for_day(ctx.tasks.all(), date(2026, 10, 18))
    assert len(blocks) == 1 and blocks[0].minutes == 240


def test_sync_is_idempotent_and_extends_horizon(ctx, clock):
    ctx.recurrences.create(culte())
    n = len(ctx.tasks.all())
    assert ctx.recurrences.sync() == 0 and len(ctx.tasks.all()) == n
    clock.now = datetime(2026, 12, 1, 9, 0)  # l'horizon glisse : de nouvelles occurrences apparaissent
    assert ctx.recurrences.sync() > 0
    assert max(t.start_date for t in ctx.tasks.all()) > date(2027, 1, 20)


def test_no_past_occurrences_and_deleted_not_recreated(ctx, make):
    past = culte(start_date=date(2026, 9, 1))  # série commencée il y a un mois
    s = ctx.recurrences.create(past)
    assert min(t.start_date for t in ctx.tasks.all()) >= TODAY  # pas de retards fabriqués
    first = ctx.tasks.list(TaskFilter(sort="start"))[0]
    ctx.tasks.delete(first.id)
    ctx.recurrences.sync()
    assert first.id not in [t.id for t in ctx.tasks.all()]
    assert len([t for t in ctx.tasks.all(include_deleted=True) if t.start_date == first.start_date]) == 1


def test_auto_close_events(ctx, clock):
    ctx.recurrences.create(culte(auto_close=True, weekdays=[1], start_date=TODAY))  # mardis
    today_task = [t for t in ctx.tasks.all() if t.start_date == TODAY][0]
    assert today_task.is_active  # 09:00 : le créneau 07-11 n'est pas terminé
    clock.now = datetime(2026, 10, 13, 11, 30)
    ctx.recurrences.sync()
    assert ctx.tasks.get(today_task.id).status_kind == "done"
    ctx.alerts.run()
    assert all(a.task_id != today_task.id for a in ctx.alerts.visible())  # pas de retard pour un événement
    nxt = [t for t in ctx.tasks.all() if t.start_date == date(2026, 10, 20)][0]
    assert nxt.is_active


def test_not_auto_closed_becomes_overdue(ctx, clock):
    ctx.recurrences.create(culte(auto_close=False, weekdays=[1]))
    clock.now = datetime(2026, 10, 14, 9, 0)
    ctx.recurrences.sync()
    today_task = [t for t in ctx.tasks.all() if t.start_date == TODAY][0]
    assert today_task.is_active
    ctx.alerts.run()
    assert any(a.kind == "overdue" and a.task_id == today_task.id for a in ctx.alerts.visible())


def test_update_regenerates_future_but_keeps_touched(ctx):
    s = ctx.recurrences.create(culte())
    touched = ctx.tasks.list(TaskFilter(sort="start"))[1]
    ctx.tasks.add_comment(touched.id, "Prédicateur invité")
    d = culte(start_time=time(8), end_time=time(12), title="Culte principal")
    ctx.recurrences.update(s.id, d)
    tasks = ctx.tasks.list(TaskFilter(sort="start"))
    by_id = {t.id: t for t in tasks}
    assert touched.id in by_id and by_id[touched.id].title == "Culte"  # occurrence commentée : conservée telle quelle
    others = [t for t in tasks if t.id != touched.id]
    assert others and all(t.title == "Culte principal" and t.start_time == time(8) for t in others)
    assert len([t for t in tasks if t.start_date == touched.start_date]) == 1  # pas de doublon


def test_stop_and_delete_series(ctx):
    s = ctx.recurrences.create(culte())
    ctx.tasks.complete(ctx.tasks.list(TaskFilter(sort="start"))[0].id)
    n = ctx.recurrences.stop(s.id)
    assert n > 5
    left = ctx.tasks.all()
    assert len(left) == 1 and left[0].status_kind == "done"  # l'occurrence traitée est conservée
    assert ctx.recurrences.list() == []
    ctx.recurrences.sync()
    assert len(ctx.tasks.all()) == 1  # série arrêtée : plus de génération
    ctx.recurrences.delete(s.id)
    assert ctx.tasks.all()[0].series_id is None


def test_validation(ctx):
    for bad in (culte(title=" "), culte(weekdays=[]), culte(interval=0), culte(start_time=None, end_time=time(9)),
                culte(start_time=time(11), end_time=time(7)), culte(end_date=TODAY - timedelta(days=1)), culte(count=0),
                culte(freq="monthly", month_day=40)):
        with pytest.raises(ValidationError):
            ctx.recurrences.create(bad)


def test_archived_project_does_not_break_sync(ctx):
    ctx.recurrences.create(culte(project_name="Ancien"))
    ctx.projects.set_archived(ctx.projects.by_name("Ancien").id, True)
    ctx.set_space(ctx.scope.space_id)
    assert ctx.recurrences.sync() == 0  # aucune erreur, aucune occurrence en double
    assert ctx.tasks.all() == []  # toujours masquées
