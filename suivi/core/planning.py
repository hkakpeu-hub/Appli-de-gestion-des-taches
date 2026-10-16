"""Planning : blocs horaires, chevauchements, créneaux libres, tâches oubliées."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from .models import KIND_TODO, Task
from .rules import planned_interval


@dataclass
class Block:
    task: Task
    start: datetime
    end: datetime
    column: int = 0  # colonne d'affichage en cas de chevauchement
    columns: int = 1
    overlaps: bool = False

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class EventBlock:
    """Créneau d'un événement (fond du planning ; ne compte pas dans les chevauchements de tâches)."""
    event: object
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def event_blocks_for_day(events, day: date) -> list[EventBlock]:
    out = []
    for e in events:
        iv = e.interval
        if e.date == day and iv:
            out.append(EventBlock(e, *iv))
    return sorted(out, key=lambda b: (b.start, b.end))


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def blocks_for_day(tasks: list[Task], day: date) -> list[Block]:
    blocks = []
    for t in tasks:
        if t.deleted_at is not None or t.status_kind == "cancelled":
            continue
        iv = planned_interval(t)
        if iv and iv[0].date() == day:
            blocks.append(Block(t, *iv))
    blocks.sort(key=lambda b: (b.start, b.end))
    assign_columns(blocks)
    return blocks


def assign_columns(blocks: list[Block]) -> None:
    """Détecte les chevauchements et répartit les blocs en colonnes côte à côte."""
    cluster: list[Block] = []
    cluster_end: Optional[datetime] = None

    def flush():
        if not cluster:
            return
        cols: list[datetime] = []
        for b in cluster:
            for i, end in enumerate(cols):
                if b.start >= end:
                    b.column, cols[i] = i, b.end
                    break
            else:
                b.column = len(cols)
                cols.append(b.end)
        for b in cluster:
            b.columns = len(cols)
            b.overlaps = len(cluster) > 1

    for b in blocks:
        if cluster_end is not None and b.start >= cluster_end:
            flush()
            cluster = []
            cluster_end = None
        # nettoyage : `cluster` est rebindé ci-dessus, on garde la référence locale
        cluster.append(b)
        cluster_end = b.end if cluster_end is None else max(cluster_end, b.end)
    flush()


def find_overlaps(blocks: list[Block]) -> list[tuple[Block, Block]]:
    pairs = []
    for i, a in enumerate(blocks):
        for b in blocks[i + 1:]:
            if b.start < a.end and a.start < b.end:
                pairs.append((a, b))
    return pairs


def free_slots(blocks: list[Block], day: date, work_start: int, work_end: int, min_minutes: int = 30) -> list[tuple[datetime, datetime]]:
    """Créneaux libres dans la journée de travail (durée minimale ``min_minutes``)."""
    cursor = datetime.combine(day, datetime.min.time()).replace(hour=work_start)
    limit = datetime.combine(day, datetime.min.time()).replace(hour=work_end) if work_end < 24 else datetime.combine(day + timedelta(days=1), datetime.min.time())
    slots = []
    for b in sorted(blocks, key=lambda b: b.start):
        if b.start > cursor and (b.start - cursor) >= timedelta(minutes=min_minutes):
            slots.append((cursor, min(b.start, limit)))
        cursor = max(cursor, b.end)
        if cursor >= limit:
            break
    if cursor < limit and (limit - cursor) >= timedelta(minutes=min_minutes):
        slots.append((cursor, limit))
    return [s for s in slots if s[0] < s[1]]


def busy_minutes(blocks: list[Block]) -> int:
    """Minutes occupées (union des créneaux : un chevauchement n'est compté qu'une fois)."""
    total = 0
    cursor: Optional[datetime] = None
    for b in sorted(blocks, key=lambda b: b.start):
        start = b.start if cursor is None else max(b.start, cursor)
        if b.end > start:
            total += int((b.end - start).total_seconds() // 60)
        cursor = b.end if cursor is None else max(cursor, b.end)
    return total


def unscheduled(tasks: list[Task], day: date) -> list[Task]:
    """Tâches actives prévues ce jour (début ou deadline) mais sans horaire."""
    return [
        t for t in tasks
        if t.is_active and t.start_time is None and (t.start_date == day or (t.start_date is None and t.deadline == day))
    ]


def forgotten(tasks: list[Task], now: datetime) -> list[Task]:
    """Tâches planifiées dont l'heure de début est passée alors qu'elles n'ont pas démarré."""
    out = []
    for t in tasks:
        iv = planned_interval(t)
        if t.is_active and t.status_kind == KIND_TODO and iv and iv[0] < now:
            out.append(t)
    return out


def ended_late(tasks: list[Task], now: datetime) -> list[Task]:
    """Tâches non terminées dont l'heure de fin prévue est dépassée."""
    out = []
    for t in tasks:
        iv = planned_interval(t)
        if t.is_active and iv and t.end_time is not None and iv[1] < now:
            out.append(t)
    return out
