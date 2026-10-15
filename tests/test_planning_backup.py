from datetime import date, datetime, time

import pytest

from suivi.core import planning
from suivi.core.tasks import TaskFilter

D = date(2026, 10, 13)


def test_overlaps_columns_and_free_slots(ctx, make):
    make("A", start_date=D, start_time=time(9), end_time=time(10, 30))
    make("B", start_date=D, start_time=time(10), end_time=time(11))
    make("C", start_date=D, start_time=time(14), end_time=time(15))
    make("Sans horaire", start_date=D)
    tasks = ctx.tasks.all()
    blocks = planning.blocks_for_day(tasks, D)
    assert [b.task.title for b in blocks] == ["A", "B", "C"]
    pairs = planning.find_overlaps(blocks)
    assert [(a.task.title, b.task.title) for a, b in pairs] == [("A", "B")]
    assert blocks[0].overlaps and blocks[1].overlaps and not blocks[2].overlaps
    assert {blocks[0].column, blocks[1].column} == {0, 1} and blocks[0].columns == 2
    assert planning.busy_minutes(blocks) == 180  # A∪B = 9h-11h (120 min, chevauchement compté une fois) + C 60 min
    slots = planning.free_slots(blocks, D, 8, 19, 30)
    assert slots == [
        (datetime(2026, 10, 13, 8), datetime(2026, 10, 13, 9)),
        (datetime(2026, 10, 13, 11), datetime(2026, 10, 13, 14)),
        (datetime(2026, 10, 13, 15), datetime(2026, 10, 13, 19)),
    ]
    assert [t.title for t in planning.unscheduled(tasks, D)] == ["Sans horaire"]


def test_forgotten_and_ended_late(ctx, make):
    make("Oubliée", start_date=D, start_time=time(8), end_time=time(9))
    make("Démarrée", start_date=D, start_time=time(8), end_time=time(9), kind="in_progress")
    make("Finie", start_date=D, start_time=time(8), end_time=time(9), kind="done")
    now = datetime(2026, 10, 13, 10)
    tasks = ctx.tasks.all()
    assert [t.title for t in planning.forgotten(tasks, now)] == ["Oubliée"]
    assert sorted(t.title for t in planning.ended_late(tasks, now)) == ["Démarrée", "Oubliée"]


def test_set_schedule_moves_task(ctx, make):
    t = make("Déplacée", start_date=D, start_time=time(9), end_time=time(10), deadline=D)
    t2 = ctx.tasks.set_schedule(t.id, date(2026, 10, 14), time(11), time(12))
    assert t2.start_date == date(2026, 10, 14) and t2.start_time == time(11) and t2.deadline == date(2026, 10, 14)


def test_backup_and_restore(ctx, make):
    make("Avant")
    path = ctx.backups.create("manuel")
    make("Après")
    assert len(ctx.tasks.all()) == 2
    ctx.restore_backup(path)
    assert [t.title for t in ctx.tasks.all()] == ["Avant"]
    assert any(b.reason == "restauration" for b in ctx.backups.list())  # filet de sécurité créé


def test_backup_rotation_and_auto(ctx, make, clock):
    from datetime import timedelta
    ctx.settings.set("backup_keep", 3)
    for i in range(5):
        clock.now += timedelta(hours=1)
        ctx.backups.create("auto")
    assert len(ctx.backups.list()) == 3
    assert ctx.backups.auto_if_due() is None  # trop récent (< 12 h)
    clock.now += timedelta(hours=13)
    assert ctx.backups.auto_if_due() is not None


def test_restore_rejects_invalid_file(ctx, tmp_path):
    bad = tmp_path / "taches_20260101_000000_manuel.db"
    bad.write_bytes(b"ceci n'est pas une base")
    with pytest.raises(Exception):
        ctx.restore_backup(bad)
