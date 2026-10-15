"""Calcul des indicateurs du tableau de bord (à partir des règles de ``rules``)."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import rules
from .models import KIND_BLOCKED, KIND_DONE, KIND_IN_PROGRESS, KIND_TODO, KINDS, Task
from .planning import week_start


@dataclass
class ProjectStat:
    name: str
    color: str
    total: int = 0
    done: int = 0
    cancelled: int = 0
    active: int = 0
    overdue: int = 0
    blocked: int = 0

    @property
    def done_ratio(self) -> float:
        base = self.total - self.cancelled
        return self.done / base if base > 0 else 0.0

    @property
    def score(self) -> float:
        """Indice de charge : retards pondérés x3, bloquées x2, actions encore ouvertes x1."""
        return self.overdue * 3 + self.blocked * 2 + self.active


@dataclass
class Dashboard:
    total: int = 0
    done: int = 0
    in_progress: int = 0
    todo: int = 0
    overdue: int = 0
    due_today: int = 0
    due_soon: int = 0
    blocked: int = 0
    waiting: int = 0
    cancelled: int = 0
    progress: float = 0.0
    overdue_tasks: list[Task] = field(default_factory=list)
    blocked_tasks: list[Task] = field(default_factory=list)
    late_start_tasks: list[Task] = field(default_factory=list)
    no_deadline_tasks: list[Task] = field(default_factory=list)
    stale_tasks: list[Task] = field(default_factory=list)
    upcoming_tasks: list[Task] = field(default_factory=list)
    today_tasks: list[Task] = field(default_factory=list)
    projects: list[ProjectStat] = field(default_factory=list)
    by_status: list[tuple[str, str, int]] = field(default_factory=list)  # (libellé, couleur, n)
    completed_series: list[tuple[str, int]] = field(default_factory=list)
    workload_series: list[tuple[str, int, int]] = field(default_factory=list)  # (semaine, nb tâches, minutes)


def completion_date(t: Task) -> date:
    """Date de clôture retenue : réalisation effective, sinon (données historiques sans date de
    réalisation) date de début, sinon date de création."""
    if t.completed_at:
        return t.completed_at.date()
    return t.start_date or t.created_at.date()


def completed_series(tasks: list[Task], today: date, granularity: str = "month", periods: int = 12) -> list[tuple[str, int]]:
    """Terminées par mois ou par semaine. ``periods=0`` : de la première clôture à aujourd'hui (24 mois max)."""
    counts: Counter = Counter()
    first: date | None = None
    for t in tasks:
        if t.status_kind == KIND_DONE:
            d = completion_date(t)
            first = d if first is None or d < first else first
            key = (d.year, d.month) if granularity == "month" else week_start(d)
            counts[key] += 1
    if periods == 0:
        if first is None:
            periods = 12
        elif granularity == "month":
            periods = min(24, max(6, (today.year - first.year) * 12 + today.month - first.month + 1))
        else:
            periods = min(26, max(8, (week_start(today) - week_start(first)).days // 7 + 1))
    out = []
    if granularity == "month":
        y, m = today.year, today.month
        keys = []
        for _ in range(periods):
            keys.append((y, m))
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        for k in reversed(keys):
            out.append((f"{k[1]:02d}/{k[0] % 100:02d}", counts.get(k, 0)))
    else:
        ws = week_start(today)
        for i in range(periods - 1, -1, -1):
            k = ws - timedelta(weeks=i)
            out.append((k.strftime("%d/%m"), counts.get(k, 0)))
    return out


def workload_series(tasks: list[Task], today: date, before: int = 2, after: int = 8) -> list[tuple[str, int, int]]:
    """Charge par semaine : tâches actives selon leur deadline (ou date de début à défaut)
    et minutes estimées. Seules les tâches datées sont comptées."""
    ws = week_start(today)
    buckets: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for t in tasks:
        if not t.is_active:
            continue
        d = t.deadline or t.start_date
        if d is None:
            continue
        k = week_start(d)
        buckets[k][0] += 1
        buckets[k][1] += t.est_minutes or 0
    out = []
    for i in range(-before, after + 1):
        k = ws + timedelta(weeks=i)
        n, mins = buckets.get(k, (0, 0))
        out.append((k.strftime("%d/%m"), n, mins))
    return out


def project_stats(tasks: list[Task], today: date) -> list[ProjectStat]:
    stats: dict[str, ProjectStat] = {}
    for t in tasks:
        name = t.project_name or "(Sans projet)"
        st = stats.setdefault(name, ProjectStat(name, t.project_color or "#94A3B8"))
        st.total += 1
        if t.status_kind == KIND_DONE:
            st.done += 1
        elif t.status_kind == "cancelled":
            st.cancelled += 1
        else:
            st.active += 1
            if rules.is_overdue(t, today):
                st.overdue += 1
            if t.status_kind == KIND_BLOCKED:
                st.blocked += 1
    return sorted(stats.values(), key=lambda s: (-s.score, -s.total, s.name.lower()))


def compute_dashboard(tasks: list[Task], now: datetime, settings: dict) -> Dashboard:
    today = now.date()
    d = Dashboard()
    live = [t for t in tasks if t.deleted_at is None]
    d.total = len(live)
    kinds = Counter(t.status_kind for t in live)
    d.done = kinds[KIND_DONE]
    d.in_progress = kinds[KIND_IN_PROGRESS]
    d.todo = kinds[KIND_TODO]
    d.blocked = kinds[KIND_BLOCKED]
    d.waiting = kinds["waiting"]
    d.cancelled = kinds["cancelled"]
    base = d.total - d.cancelled
    d.progress = d.done / base if base > 0 else 0.0

    by_label: dict[str, list] = {}
    for t in live:
        e = by_label.setdefault(t.status_label, [t.status_color, 0])
        e[1] += 1
    d.by_status = [(k, v[0], v[1]) for k, v in by_label.items()]

    up_days = int(settings["upcoming_days"])
    for t in live:
        if rules.is_overdue(t, today):
            d.overdue_tasks.append(t)
        if rules.is_due_today(t, today):
            d.due_today += 1
        if rules.is_due_soon(t, today, up_days):
            d.upcoming_tasks.append(t)
        if t.status_kind == KIND_BLOCKED:
            d.blocked_tasks.append(t)
        if rules.is_late_start(t, today):
            d.late_start_tasks.append(t)
        if rules.has_no_deadline(t):
            d.no_deadline_tasks.append(t)
        if rules.is_stale(t, now, int(settings["stale_days"])):
            d.stale_tasks.append(t)
        if t.is_active and (t.deadline == today or t.start_date == today):
            d.today_tasks.append(t)
    d.overdue = len(d.overdue_tasks)
    d.due_soon = len(d.upcoming_tasks)
    d.overdue_tasks.sort(key=lambda t: t.deadline)
    d.upcoming_tasks.sort(key=lambda t: t.deadline)
    d.stale_tasks.sort(key=lambda t: t.updated_at)
    d.late_start_tasks.sort(key=lambda t: t.start_date)
    d.projects = project_stats(live, today)
    d.completed_series = completed_series(live, today)
    d.workload_series = workload_series(live, today)
    return d
