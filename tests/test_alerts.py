from datetime import date, datetime, time, timedelta

TODAY = date(2026, 10, 13)


def kinds(ctx, only_unread=False):
    return sorted((a.kind, a.task_title) for a in ctx.alerts.visible(include_read=not only_unread))


def test_alerts_before_and_after_deadline(ctx, make, clock):
    make("T", deadline=TODAY + timedelta(days=7))
    ctx.alerts.run()
    assert kinds(ctx) == [("soon", "T")]
    # J-3 : nouveau palier ; l'ancien (7 j) est remplacé
    clock.now = datetime(2026, 10, 17, 9, 0)
    new = ctx.alerts.run()
    assert [a.kind for a in new] == ["soon"] and len(ctx.alerts.visible()) == 1
    clock.now = datetime(2026, 10, 20, 8, 0)  # jour J
    assert [a.kind for a in ctx.alerts.run()] == ["due_today"]
    clock.now = datetime(2026, 10, 21, 8, 0)  # lendemain : retard
    out = ctx.alerts.run()
    assert [a.kind for a in out] == ["overdue"] and "1 jour" in out[0].message
    assert kinds(ctx) == [("overdue", "T")]


def test_no_overdue_alert_for_done_or_cancelled(ctx, make):
    make("Finie", deadline=TODAY - timedelta(days=5), kind="done")
    make("Annulée", deadline=TODAY - timedelta(days=5), kind="cancelled")
    assert ctx.alerts.run() == [] and ctx.alerts.visible() == []


def test_closing_a_task_resolves_its_alerts(ctx, make):
    t = make("À clore", deadline=TODAY - timedelta(days=1))
    ctx.alerts.run()
    assert ctx.alerts.unread_count() == 1
    ctx.tasks.complete(t.id)
    ctx.alerts.run()
    assert ctx.alerts.visible() == []


def test_no_repeated_notifications(ctx, make):
    make("Retard", deadline=TODAY - timedelta(days=3))
    first = ctx.alerts.run()
    assert len(first) == 1
    ctx.alerts.mark_notified([a.id for a in first])
    assert ctx.alerts.run() == [] and ctx.alerts.run() == []  # actualisations successives : rien de nouveau


def test_state_survives_restart(tmp_path, clock):
    from suivi.context import AppContext
    from suivi.core.models import TaskInput
    c = AppContext(tmp_path / "r.db", tmp_path / "bk", clock)
    c.tasks.create(TaskInput(title="R", deadline=TODAY - timedelta(days=1)))
    c.alerts.mark_notified([a.id for a in c.alerts.run()])
    c.close()
    c = AppContext(tmp_path / "r.db", tmp_path / "bk", clock)
    assert c.alerts.run() == []  # déjà notifiée avant le redémarrage
    assert c.alerts.unread_count() == 1
    c.close()


def test_overdue_reemission_next_day_and_configurable(ctx, make, clock):
    make("R", deadline=TODAY - timedelta(days=1))
    ctx.alerts.mark_notified([a.id for a in ctx.alerts.run()])
    clock.now = datetime(2026, 10, 14, 9, 0)  # changement de jour -> réémission quotidienne
    assert len(ctx.alerts.run()) == 1
    ctx.settings.set("overdue_reemit_days", 7)
    ctx.alerts.mark_notified([a.id for a in ctx.alerts.visible()])
    clock.now = datetime(2026, 10, 15, 9, 0)
    assert ctx.alerts.run() == []  # avec réémission hebdomadaire, pas de nouvelle alerte


def test_thresholds_configurable(ctx, make):
    ctx.settings.set("reminder_days", [2, 0])
    make("Dans 5 j", deadline=TODAY + timedelta(days=5))
    make("Dans 2 j", deadline=TODAY + timedelta(days=2))
    ctx.alerts.run()
    assert kinds(ctx) == [("soon", "Dans 2 j")]


def test_not_started_and_stuck(ctx, make, clock):
    make("Pas démarrée", start_date=TODAY - timedelta(days=1))
    b = make("Bloquée", kind="blocked")
    ctx.alerts.run()
    assert ("not_started", "Pas démarrée") in kinds(ctx)
    assert all(k != "stuck" for k, _ in kinds(ctx))  # bloquée depuis 0 jour
    clock.now = datetime(2026, 10, 17, 9, 0)  # 4 jours > seuil de 3
    ctx.alerts.run()
    assert ("stuck", "Bloquée") in kinds(ctx)
    ctx.settings.set("blocked_days", 10)
    ctx.alerts.run()
    assert ("stuck", "Bloquée") not in kinds(ctx)


def test_scheduled_start_and_end_alerts(ctx, make, clock):
    make("Réunion", start_date=TODAY, start_time=time(9, 20), end_time=time(10, 0))
    clock.now = datetime(2026, 10, 13, 9, 0)  # début dans 20 min (seuil 30)
    ctx.alerts.run()
    assert ("start_soon", "Réunion") in kinds(ctx)
    ctx.tasks.set_status(1, ctx.statuses.first_of_kind("in_progress").id)
    clock.now = datetime(2026, 10, 13, 9, 50)  # fin dans 10 min (seuil 15)
    ctx.alerts.run()
    assert ("end_soon", "Réunion") in kinds(ctx) and ("start_soon", "Réunion") not in kinds(ctx)
    clock.now = datetime(2026, 10, 13, 10, 5)  # fin dépassée
    ctx.alerts.run()
    assert kinds(ctx) == [("end_over", "Réunion")]


def test_snooze_and_read(ctx, make, clock):
    make("S", deadline=TODAY)
    a = ctx.alerts.run()[0]
    ctx.alerts.mark_notified([a.id])
    ctx.alerts.mark_read(a.id)
    assert ctx.alerts.unread_count() == 0
    ctx.alerts.snooze(a.id, clock.now + timedelta(hours=2))
    assert ctx.alerts.visible() == []
    clock.now += timedelta(hours=3)
    back = ctx.alerts.run()
    assert [x.id for x in back] == [a.id] and ctx.alerts.unread_count() == 1  # réapparaît, non lue, renotifiée
