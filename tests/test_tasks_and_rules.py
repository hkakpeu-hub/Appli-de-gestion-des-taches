from datetime import date, datetime, time, timedelta

import pytest

from suivi.core import rules
from suivi.core.models import TaskInput, ValidationError
from suivi.core.tasks import TaskFilter

TODAY = date(2026, 10, 13)


def test_create_update_close_and_history(ctx, make):
    t = make("Rédiger le CR", project_name="Centaures", deadline=TODAY + timedelta(days=3), priority="high")
    assert t.status_kind == "todo" and t.project_name == "Centaures"
    # modification : deadline + priorité + statut
    data = ctx.tasks.to_input(t, deadline=TODAY + timedelta(days=5), priority="critical",
                              status_id=ctx.statuses.first_of_kind("in_progress").id)
    t2 = ctx.tasks.update(t.id, data)
    assert t2.status_kind == "in_progress" and t2.priority == "critical"
    # clôture
    t3 = ctx.tasks.complete(t.id)
    assert t3.status_kind == "done" and t3.completed_at is not None
    events = [h.event for h in ctx.tasks.history(t.id)]
    assert "created" in events and "deadline" in events and "priority" in events and "completed" in events
    # réouverture : la date de réalisation est effacée
    t4 = ctx.tasks.set_status(t.id, ctx.statuses.first_of_kind("todo").id)
    assert t4.completed_at is None


def test_update_without_change_logs_nothing(ctx, make):
    t = make("Rien")
    n = len(ctx.tasks.history(t.id))
    ctx.tasks.update(t.id, ctx.tasks.to_input(t))
    assert len(ctx.tasks.history(t.id)) == n


def test_persistence_after_restart(tmp_path, clock):
    from suivi.context import AppContext
    c1 = AppContext(tmp_path / "p.db", tmp_path / "bk", clock)
    c1.tasks.create(TaskInput(title="Persistante", project_name="P", deadline=TODAY))
    c1.close()
    c2 = AppContext(tmp_path / "p.db", tmp_path / "bk", clock)
    tasks = c2.tasks.all()
    assert [t.title for t in tasks] == ["Persistante"] and tasks[0].deadline == TODAY
    c2.close()


def test_overdue_rules(ctx, make):
    late = make("En retard", deadline=TODAY - timedelta(days=2))
    today = make("Aujourd'hui", deadline=TODAY)
    done = make("Finie", deadline=TODAY - timedelta(days=9), kind="done")
    cancelled = make("Annulée", deadline=TODAY - timedelta(days=9), kind="cancelled")
    nodl = make("Sans deadline")
    assert rules.is_overdue(late, TODAY) and rules.overdue_days(late, TODAY) == 2
    assert not rules.is_overdue(today, TODAY) and rules.is_due_today(today, TODAY)
    assert not rules.is_overdue(done, TODAY) and not rules.is_overdue(cancelled, TODAY)
    assert rules.has_no_deadline(nodl)
    ids = {t.id for t in ctx.tasks.list(TaskFilter(delay="any"), TODAY)}
    assert ids == {late.id}  # ni terminée ni annulée ni du jour


def test_late_start_and_delay_levels(ctx, make):
    t = make("Devait commencer", start_date=TODAY - timedelta(days=2), deadline=TODAY + timedelta(days=4))
    started = make("Démarrée", start_date=TODAY - timedelta(days=2), kind="in_progress")
    assert rules.is_late_start(t, TODAY) and not rules.is_late_start(started, TODAY)
    l1, l2, l3 = (make(f"R{n}", deadline=TODAY - timedelta(days=n)) for n in (2, 10, 30))
    got = lambda lvl: {x.id for x in ctx.tasks.list(TaskFilter(delay=lvl), TODAY)}  # noqa: E731
    assert got("light") == {l1.id} and got("moderate") == {l2.id} and got("severe") == {l3.id}


def test_validation_errors(ctx):
    with pytest.raises(ValidationError):
        ctx.tasks.create(TaskInput(title="  "))
    with pytest.raises(ValidationError):
        ctx.tasks.create(TaskInput(title="x", start_date=TODAY, deadline=TODAY - timedelta(days=1)))
    with pytest.raises(ValidationError):
        ctx.tasks.create(TaskInput(title="x", start_date=TODAY, start_time=time(10), end_time=time(9)))
    with pytest.raises(ValidationError):
        ctx.tasks.create(TaskInput(title="x", start_time=time(10)))  # horaires sans date
    # champs incomplets mais valides : pas d'horaire, pas de projet, pas de deadline
    assert ctx.tasks.create(TaskInput(title="Minimale")).project_name == ""


def test_search_is_accent_and_case_insensitive_and_covers_comments(ctx, make):
    t = make("Préparer la RÉUNION", description="Budget", assignee="Adama", project_name="Centaures")
    ctx.tasks.add_comment(t.id, "Voir avec Donald")
    s = lambda q: [x.id for x in ctx.tasks.list(TaskFilter(text=q))]  # noqa: E731
    assert s("reunion") == [t.id] and s("BUDGET") == [t.id] and s("adama") == [t.id]
    assert s("centaures") == [t.id] and s("donald") == [t.id] and s("introuvable") == []


def test_soft_delete_and_restore(ctx, make):
    t = make("À supprimer")
    ctx.tasks.delete(t.id)
    assert ctx.tasks.all() == [] and [x.id for x in ctx.tasks.deleted()] == [t.id]
    ctx.tasks.restore(t.id)
    assert len(ctx.tasks.all()) == 1
    ctx.tasks.delete(t.id)
    ctx.tasks.purge(t.id)
    assert ctx.tasks.deleted() == []


def test_filters_combined(ctx, make):
    a = make("A", project_name="P1", priority="high", assignee="X", deadline=TODAY)
    make("B", project_name="P2", priority="high", assignee="X", deadline=TODAY)
    make("C", project_name="P1", priority="low", assignee="X", deadline=TODAY)
    p1 = ctx.projects.by_name("P1").id
    res = ctx.tasks.list(TaskFilter(project_ids=[p1], priorities=["high"], assignee="x", date_from=TODAY, date_to=TODAY))
    assert [t.id for t in res] == [a.id]


def test_dashboard_updates_after_change(ctx, make):
    from suivi.core.metrics import compute_dashboard
    t = make("Un", deadline=TODAY - timedelta(days=1))
    calls = []
    ctx.tasks.subscribe(lambda: calls.append(1))
    d = compute_dashboard(ctx.tasks.all(), ctx.clock(), ctx.settings.all())
    assert d.overdue == 1 and d.done == 0
    ctx.tasks.complete(t.id)
    assert calls  # l'interface est notifiée
    d = compute_dashboard(ctx.tasks.all(), ctx.clock(), ctx.settings.all())
    assert d.overdue == 0 and d.done == 1 and d.progress == 1.0


def test_status_configuration(ctx):
    new = ctx.statuses.add("En revue", "in_progress", "#123456")
    assert new.label in [s.label for s in ctx.statuses.list()]
    with pytest.raises(ValidationError):
        ctx.statuses.add("en revue", "todo")  # doublon insensible à la casse
