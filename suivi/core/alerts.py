"""Moteur d'alertes.

Fonctionnement :
 1. ``evaluate`` calcule, de façon déterministe, les alertes qui devraient exister à l'instant ``now``
    (chacune identifiée par une clé de dédoublonnage) ;
 2. ``run`` insère les nouvelles (clé jamais vue), résout (masque) celles dont la condition a disparu
    (tâche terminée, deadline modifiée, créneau passé…), remet à zéro celles reportées dont le délai est écoulé ;
 3. l'interface ne notifie (toast Windows) que les alertes jamais notifiées -> aucune répétition à chaque
    actualisation, même après un redémarrage (l'état est en base).

Réémission : les retards, tâches non démarrées et blocages prolongés produisent une nouvelle alerte
tous les N jours (paramètres ``*_reemit_days``) ; les autres alertes ne sont émises qu'une fois par
échéance/créneau (si la deadline ou l'horaire change, la clé change et l'alerte peut être réémise).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from ..db import Database
from .models import KIND_BLOCKED, KIND_WAITING, Alert, Task, iso_datetime, to_date, to_datetime
from .rules import overdue_days
from .settings import Settings
from .tasks import BASE_SELECT, TaskService

LEVELS = {"critical": "Critique", "high": "Élevée", "medium": "Moyenne", "low": "Faible"}
LEVEL_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
LEVEL_COLORS = {"critical": "#DC2626", "high": "#EA580C", "medium": "#D97706", "low": "#2563EB"}

KIND_LABELS = {
    "overdue": "Tâche en retard",
    "due_today": "Échéance aujourd'hui",
    "soon": "Échéance proche",
    "not_started": "Tâche non démarrée",
    "stuck": "Bloquée / en attente depuis trop longtemps",
    "start_soon": "Début imminent",
    "end_soon": "Risque de dépassement de l'heure de fin",
    "end_over": "Heure de fin dépassée",
}


@dataclass
class Candidate:
    task: Task
    kind: str
    level: str
    key: str
    message: str


def _fd(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


class AlertEngine:
    def __init__(self, db: Database, tasks: TaskService, settings: Settings):
        self.db = db
        self.tasks = tasks
        self.settings = settings
        self._listeners: list = []

    def subscribe(self, cb) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    # ---------------------------------------------------------------- calcul
    def evaluate(self, tasks: list[Task], now: datetime) -> list[Candidate]:
        s = self.settings
        today = now.date()
        thresholds = sorted({int(x) for x in s.get("reminder_days")})
        positive = [t for t in thresholds if t > 0]
        out: list[Candidate] = []
        for t in tasks:
            if not t.is_active:
                continue
            ctx = f"Projet : {t.project_name or '—'} · Deadline : {_fd(t.deadline)} · Statut : {t.status_label}"
            if t.deadline is not None:
                left = (t.deadline - today).days
                if left < 0:
                    n = overdue_days(t, today)
                    bucket = (n - 1) // max(1, int(s.get("overdue_reemit_days")))
                    out.append(Candidate(t, "overdue", "critical", f"overdue:{t.id}:{t.deadline}:{bucket}",
                                         f"En retard de {_plural(n, 'jour')}. {ctx}"))
                elif left == 0:
                    if 0 in thresholds:
                        out.append(Candidate(t, "due_today", "high", f"today:{t.id}:{t.deadline}",
                                             f"Échéance aujourd'hui. {ctx}"))
                elif positive:
                    reached = [x for x in positive if left <= x]
                    if reached:
                        th = min(reached)
                        lvl = "high" if left <= 1 else ("medium" if left <= 3 else "low")
                        out.append(Candidate(t, "soon", lvl, f"soon:{t.id}:{t.deadline}:{th}",
                                             f"Échéance dans {_plural(left, 'jour')}. {ctx}"))
            if t.status_kind == "todo" and t.start_date is not None and t.start_date < today:
                n = (today - t.start_date).days
                bucket = (n - 1) // max(1, int(s.get("notstarted_reemit_days")))
                out.append(Candidate(t, "not_started", "medium", f"notstarted:{t.id}:{t.start_date}:{bucket}",
                                     f"Devait commencer le {_fd(t.start_date)} ({_plural(n, 'jour')}) mais n'est pas démarrée. {ctx}"))
            if t.status_kind in (KIND_BLOCKED, KIND_WAITING):
                limit = int(s.get("blocked_days" if t.status_kind == KIND_BLOCKED else "waiting_days"))
                age = (now - t.status_changed_at).days
                if age >= limit:
                    bucket = (age - limit) // max(1, int(s.get("stuck_reemit_days")))
                    out.append(Candidate(t, "stuck", "high" if t.status_kind == KIND_BLOCKED else "medium",
                                         f"stuck:{t.id}:{t.status_changed_at:%Y%m%d}:{bucket}",
                                         f"« {t.status_label} » depuis {_plural(age, 'jour')}. {ctx}"))
            if t.start_date == today and t.start_time is not None:
                start = datetime.combine(today, t.start_time)
                mins = (start - now).total_seconds() / 60
                if 0 <= mins <= int(s.get("start_reminder_minutes")) and t.status_kind == "todo":
                    out.append(Candidate(t, "start_soon", "high", f"startsoon:{t.id}:{today}:{t.start_time:%H%M}",
                                         f"Début prévu à {t.start_time:%H:%M} (dans {int(round(mins))} min). {ctx}"))
                if t.end_time is not None:
                    end = datetime.combine(today, t.end_time)
                    mins_end = (end - now).total_seconds() / 60
                    if now >= start and 0 < mins_end <= int(s.get("end_warning_minutes")):
                        out.append(Candidate(t, "end_soon", "high", f"endsoon:{t.id}:{today}:{t.end_time:%H%M}",
                                             f"Fin prévue à {t.end_time:%H:%M} (dans {int(round(mins_end))} min) : risque de dépassement. {ctx}"))
                    elif mins_end <= 0:
                        out.append(Candidate(t, "end_over", "critical", f"endover:{t.id}:{today}:{t.end_time:%H%M}",
                                             f"Heure de fin prévue ({t.end_time:%H:%M}) dépassée. {ctx}"))
        return out

    # ------------------------------------------------------------- exécution
    def run(self, now: Optional[datetime] = None) -> list[Alert]:
        """Met à jour les alertes. Retourne les alertes visibles jamais notifiées."""
        now = now or self.tasks.clock()
        if not self.settings.get("alerts_enabled"):
            return []
        stamp = iso_datetime(now)
        tasks = self.tasks.all()
        candidates = self.evaluate(tasks, now)
        keys = {c.key for c in candidates}
        changed = False
        with self.db.transaction() as c:
            # fin de report : l'alerte redevient non lue et sera renotifiée
            cur = c.execute(
                "UPDATE alerts SET snoozed_until=NULL, read_at=NULL, notified_at=NULL "
                "WHERE snoozed_until IS NOT NULL AND snoozed_until<=? AND resolved_at IS NULL", (stamp,))
            changed |= cur.rowcount > 0
            existing = {r["dedupe_key"]: r["resolved_at"] for r in c.execute("SELECT dedupe_key, resolved_at FROM alerts")}
            for cand in candidates:
                if cand.key in existing:
                    continue
                # une seule alerte active par (tâche, type) : la nouvelle remplace l'ancienne
                c.execute("UPDATE alerts SET resolved_at=? WHERE task_id=? AND kind=? AND resolved_at IS NULL",
                          (stamp, cand.task.id, cand.kind))
                c.execute(
                    "INSERT INTO alerts(task_id,kind,level,title,message,dedupe_key,created_at) VALUES (?,?,?,?,?,?,?)",
                    (cand.task.id, cand.kind, cand.level, cand.task.title, cand.message, cand.key, stamp),
                )
                changed = True
            # alertes dont la condition a disparu
            for r in c.execute("SELECT id, dedupe_key FROM alerts WHERE resolved_at IS NULL").fetchall():
                if r["dedupe_key"] not in keys:
                    c.execute("UPDATE alerts SET resolved_at=? WHERE id=?", (stamp, r["id"]))
                    changed = True
        if changed:
            self._notify()
        return [a for a in self.visible(now) if a.notified_at is None]

    # --------------------------------------------------------------- lecture
    def _alert_query(self, extra: str, params: list) -> list[Alert]:
        sql = f"""SELECT a.*, t.title AS task_title, t.deadline AS t_deadline, p.name AS project_name,
                         s.label AS status_label
                  FROM alerts a JOIN tasks t ON t.id=a.task_id
                  LEFT JOIN projects p ON p.id=t.project_id JOIN statuses s ON s.id=t.status_id
                  WHERE a.resolved_at IS NULL AND t.deleted_at IS NULL {extra}
                  ORDER BY CASE a.level WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                           a.created_at DESC"""
        return [
            Alert(
                id=r["id"], task_id=r["task_id"], kind=r["kind"], level=r["level"], title=r["title"],
                message=r["message"], created_at=to_datetime(r["created_at"]), read_at=to_datetime(r["read_at"]),
                snoozed_until=to_datetime(r["snoozed_until"]), notified_at=to_datetime(r["notified_at"]),
                task_title=r["task_title"], project_name=r["project_name"] or "", deadline=to_date(r["t_deadline"]),
                status_label=r["status_label"],
            )
            for r in self.db.conn.execute(sql, params)
        ]

    def visible(self, now: Optional[datetime] = None, include_read: bool = True) -> list[Alert]:
        stamp = iso_datetime(now or self.tasks.clock())
        extra = "AND (a.snoozed_until IS NULL OR a.snoozed_until<=?)"
        if not include_read:
            extra += " AND a.read_at IS NULL"
        return self._alert_query(extra, [stamp])

    def unread_count(self, now: Optional[datetime] = None) -> int:
        return len(self.visible(now, include_read=False))

    # --------------------------------------------------------------- actions
    def mark_notified(self, ids: list[int]) -> None:
        if not ids:
            return
        stamp = iso_datetime(self.tasks.clock())
        with self.db.transaction() as c:
            c.executemany("UPDATE alerts SET notified_at=? WHERE id=? AND notified_at IS NULL", [(stamp, i) for i in ids])

    def mark_read(self, alert_id: int, read: bool = True) -> None:
        stamp = iso_datetime(self.tasks.clock()) if read else None
        with self.db.transaction() as c:
            c.execute("UPDATE alerts SET read_at=? WHERE id=?", (stamp, alert_id))
        self._notify()

    def mark_all_read(self) -> None:
        stamp = iso_datetime(self.tasks.clock())
        with self.db.transaction() as c:
            c.execute("UPDATE alerts SET read_at=? WHERE read_at IS NULL AND resolved_at IS NULL", (stamp,))
        self._notify()

    def snooze(self, alert_id: int, until: datetime) -> None:
        """Reporte une alerte : masquée jusqu'à ``until`` puis de nouveau non lue et renotifiée."""
        stamp = iso_datetime(self.tasks.clock())
        with self.db.transaction() as c:
            c.execute("UPDATE alerts SET snoozed_until=?, read_at=? WHERE id=?", (iso_datetime(until), stamp, alert_id))
        self._notify()
