from datetime import date, datetime, time, timedelta

import pytest

from suivi.core import planning
from suivi.core.events import EventInput
from suivi.core.metrics import compute_dashboard
from suivi.core.models import EventTemplate, TaskInput, ValidationError
from suivi.core.recurrence import RecurrenceInput
from suivi.core.tasks import TaskFilter

TODAY = date(2026, 10, 13)  # mardi


def culte_series(**kw):
    base = dict(title="Culte", kind="event", freq="weekly", weekdays=[6], start_date=TODAY, start_time=time(7), end_time=time(11),
                location="Salle principale",
                templates=[EventTemplate("Chanter"), EventTemplate("Danser"), EventTemplate("Prier"),
                           EventTemplate("Lecture biblique", "Marie")])
    base.update(kw)
    return RecurrenceInput(**base)


def test_events_are_not_tasks_and_do_not_affect_dashboard(ctx, make):
    before = compute_dashboard(ctx.tasks.all(), ctx.clock(), ctx.settings.all())
    ctx.recurrences.create(culte_series(templates=[]))
    assert ctx.tasks.all() == []  # aucun événement dans les tâches
    assert len(ctx.events.list()) >= 12
    d = compute_dashboard(ctx.tasks.all(), ctx.clock(), ctx.settings.all())
    assert (d.total, d.overdue, d.todo, d.progress) == (before.total, before.overdue, before.todo, before.progress)
    assert ctx.tasks.list(TaskFilter()) == [] and ctx.alerts.run() == []


def test_series_events_have_template_tasks_linked(ctx):
    ctx.recurrences.create(culte_series())
    events = ctx.events.list()
    first = events[0]
    assert first.date == date(2026, 10, 18) and first.start_time == time(7) and first.location == "Salle principale"
    linked = ctx.events.linked_tasks(first.id)
    assert sorted(t.title for t in linked) == ["Chanter", "Danser", "Lecture biblique", "Prier"]
    assert all(t.event_id == first.id and t.deadline == first.date and t.event_title == "Culte" for t in linked)
    assert [t.assignee for t in linked if t.title == "Lecture biblique"] == ["Marie"]
    assert (first.n_tasks, first.n_done) == (4, 0)
    ctx.tasks.complete([t for t in linked if t.title == "Chanter"][0].id)
    assert ctx.events.get(first.id).n_done == 1


def test_sync_idempotent_deleted_task_and_event_not_recreated(ctx):
    ctx.recurrences.create(culte_series())
    n_tasks, n_events = len(ctx.tasks.all()), len(ctx.events.list())
    assert ctx.recurrences.sync() == 0 and len(ctx.tasks.all()) == n_tasks
    ev = ctx.events.list()[0]
    danser = [t for t in ctx.events.linked_tasks(ev.id) if t.title == "Danser"][0]
    ctx.tasks.delete(danser.id)
    ev2 = ctx.events.list()[1]
    ctx.events.delete(ev2.id)
    ctx.recurrences.sync()
    assert "Danser" not in [t.title for t in ctx.events.linked_tasks(ev.id)]  # pas recréée
    assert ev2.id not in [e.id for e in ctx.events.list()] and len(ctx.events.list()) == n_events - 1


def test_template_tasks_created_one_week_ahead_by_default_then_roll_forward(ctx, clock):
    s = ctx.recurrences.create(culte_series())
    assert s.task_weeks == 1  # valeur par défaut : une semaine
    events = ctx.events.list()
    assert len(events) >= 12  # les événements sont créés 90 jours à l'avance
    with_tasks = [e for e in events if e.n_tasks]
    assert [e.date for e in with_tasks] == [date(2026, 10, 18)]  # seul le culte de la semaine a ses tâches
    assert len(ctx.tasks.all()) == 4  # pas de tâches futures qui encombrent les listes
    clock.now = datetime(2026, 10, 19, 9, 0)  # le lendemain du culte : le suivant (25/10) est dans la semaine
    ctx.recurrences.sync()
    assert len(ctx.tasks.all()) == 8
    assert ctx.recurrences.sync() == 0 and len(ctx.tasks.all()) == 8  # idempotent


def test_task_weeks_is_a_creation_parameter_and_can_shrink(ctx, clock):
    s = ctx.recurrences.create(culte_series(task_weeks=3))
    assert s.task_weeks == 3
    assert [e.date for e in ctx.events.list() if e.n_tasks] == [date(2026, 10, 18), date(2026, 10, 25), date(2026, 11, 1)]
    assert len(ctx.tasks.all()) == 12
    # on repasse à 1 semaine : les tâches intactes des semaines lointaines sont retirées, celles de la semaine restent
    ctx.recurrences.update(s.id, culte_series(task_weeks=1, templates=ctx.recurrences.templates(s.id)))
    assert [e.date for e in ctx.events.list() if e.n_tasks] == [date(2026, 10, 18)] and len(ctx.tasks.all()) == 4
    from suivi.core.recurrence import RecurrenceInput
    with pytest.raises(ValidationError):
        ctx.recurrences.create(culte_series(task_weeks=0))


def test_days_before_deadline(ctx):
    ctx.recurrences.create(culte_series(templates=[EventTemplate("Préparer la salle", "", 2)]))
    ev = ctx.events.list()[0]
    t = ctx.events.linked_tasks(ev.id)[0]
    assert t.deadline == ev.date - timedelta(days=2) == date(2026, 10, 16)


def test_one_off_event_with_tasks_and_manual_link(ctx, make):
    ev = ctx.events.create(EventInput("Mariage", date(2026, 11, 7), time(14), time(18)), new_tasks=[("Décoration", "Anne", 1), ("Musique",)])
    assert ev.series_id is None and ev.n_tasks == 2
    free = make("Réserver le traiteur")
    ctx.events.link(free.id, ev.id)
    linked = ctx.tasks.get(free.id)
    assert linked.event_id == ev.id and linked.deadline == ev.date  # prend la date de l'événement
    assert ctx.events.get(ev.id).n_tasks == 3
    assert any(h.field == "Événement" and h.new_value == "Mariage" for h in ctx.tasks.history(free.id))
    # TaskDialog/updates conservent le lien ; détacher le retire
    ctx.tasks.update(free.id, ctx.tasks.to_input(linked, priority="high"))
    assert ctx.tasks.get(free.id).event_id == ev.id
    ctx.events.link(free.id, None)
    assert ctx.tasks.get(free.id).event_id is None


def test_delete_event_detaches_or_deletes_tasks(ctx):
    a = ctx.events.create(EventInput("A", date(2026, 11, 1)), new_tasks=[("t1",), ("t2",)])
    b = ctx.events.create(EventInput("B", date(2026, 11, 2)), new_tasks=[("t3",)])
    ctx.events.delete(a.id)  # détache
    assert {t.title for t in ctx.tasks.all()} == {"t1", "t2", "t3"} and all(t.event_id is None for t in ctx.tasks.all() if t.title != "t3")
    ctx.events.delete(b.id, delete_tasks=True)
    assert {t.title for t in ctx.tasks.all()} == {"t1", "t2"}


def test_planning_event_blocks_busy_and_free(ctx, make):
    ctx.events.create(EventInput("Culte", date(2026, 10, 18), time(7), time(11)))
    ctx.events.create(EventInput("Sans heure", date(2026, 10, 18)))
    day = date(2026, 10, 18)
    eb = planning.event_blocks_for_day(ctx.events.list(), day)
    assert len(eb) == 1 and eb[0].minutes == 240  # l'événement sans horaire n'a pas de bloc
    make("Répétition chorale", start_date=day, start_time=time(9), end_time=time(10))
    tb = planning.blocks_for_day(ctx.tasks.all(), day)
    assert planning.find_overlaps(tb) == [] and not tb[0].overlaps  # tâche pendant l'événement : pas un conflit
    assert planning.busy_minutes(tb + eb) == 240
    slots = planning.free_slots(tb + eb, day, 6, 19, 30)
    assert slots[0][1].hour == 7 and slots[1][0].hour == 11


def test_update_series_refits_events_and_templates(ctx):
    s = ctx.recurrences.create(culte_series(task_weeks=3))
    ev = ctx.events.list()[1]
    done = [t for t in ctx.events.linked_tasks(ev.id) if t.title == "Prier"][0]
    ctx.tasks.complete(done.id)  # cet événement a été « touché »
    new = culte_series(task_weeks=3, title="Culte principal", start_time=time(8), end_time=time(12), weekdays=[6, 2],
                       templates=[EventTemplate("Chanter", id=ctx.recurrences.templates(s.id)[0].id),
                                  EventTemplate("Accueil", "Paul")])
    ctx.recurrences.update(s.id, new)
    events = ctx.events.list()
    assert any(e.date.weekday() == 2 for e in events)  # les mercredis apparaissent
    touched = ctx.events.get(ev.id)
    assert touched.title == "Culte principal" and touched.start_time == time(8)
    titles = {t.title for t in ctx.events.linked_tasks(events[0].id)}
    assert titles == {"Chanter", "Accueil"}  # Danser/Prier/Lecture retirés, Accueil ajouté
    assert "Prier" in {t.title for t in ctx.events.linked_tasks(ev.id)}  # tâche faite : conservée


def test_stop_event_series_keeps_touched(ctx):
    s = ctx.recurrences.create(culte_series())
    ev = ctx.events.list()[0]
    ctx.tasks.complete(ctx.events.linked_tasks(ev.id)[0].id)
    n = ctx.recurrences.stop(s.id)
    assert n >= 10
    assert [e.id for e in ctx.events.list()] == [ev.id]
    ctx.recurrences.delete(s.id)
    assert ctx.events.get(ev.id).series_id is None


def test_event_validation_and_migration_of_old_auto_close_series(ctx, tmp_path):
    with pytest.raises(ValidationError):
        ctx.events.create(EventInput("", date(2026, 11, 1)))
    with pytest.raises(ValidationError):
        ctx.events.create(EventInput("x", date(2026, 11, 1), time(11), time(9)))
    with pytest.raises(ValidationError):
        ctx.recurrences.create(culte_series(templates=[EventTemplate(" ")]))


def test_migration_v3_to_v4_converts_event_series(tmp_path):
    from suivi.db import database
    path = tmp_path / "v3.db"
    full = list(database.MIGRATIONS)
    database.MIGRATIONS[:] = full[:3]
    try:
        db = database.Database(path)
        c = db.conn
        c.execute("INSERT INTO recurrences(space_id,title,start_time,end_time,freq,interval,weekdays,start_date,auto_close,active,created_at)"
                  " VALUES (3,'Culte','07:00','11:00','weekly',1,'6','2026-10-18',1,1,'2026-10-01T00:00:00')")
        c.execute("INSERT INTO recurrences(space_id,title,freq,interval,weekdays,start_date,auto_close,active,created_at)"
                  " VALUES (1,'Rapport','weekly',1,'4','2026-10-16',0,1,'2026-10-01T00:00:00')")
        for sid, d in ((1, "2026-10-18"), (1, "2026-10-25"), (2, "2026-10-16")):
            c.execute("INSERT INTO tasks(title,created_at,status_id,priority,updated_at,status_changed_at,series_id,occurrence_date,space_id)"
                      " VALUES ('x','2026-10-01T00:00:00',1,'normal','2026-10-01T00:00:00','2026-10-01T00:00:00',?,?,?)", (sid, d, 3 if sid == 1 else 1))
        c.commit()
        db.close()
    finally:
        database.MIGRATIONS[:] = full
    from suivi.context import AppContext
    ctx = AppContext(path, tmp_path / "bk")
    try:
        kinds = {s.title: s.kind for s in ctx.recurrences.list(space_id=None)}
        assert kinds == {"Culte": "event", "Rapport": "task"}
        assert [(e.title, e.date.isoformat()) for e in ctx.events.list(space_id=None)] == [("Culte", "2026-10-18"), ("Culte", "2026-10-25")]
        assert [t.series_id is not None for t in ctx.tasks.all(space_id=None)] == [True]  # seules les tâches de la série « Rapport » restent
    finally:
        ctx.close()
