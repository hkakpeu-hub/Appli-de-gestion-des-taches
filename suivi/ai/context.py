"""Construction du contexte transmis à l'IA : lecture seule, volume maîtrisé, sans clé ni secret."""
from __future__ import annotations

import json
from datetime import datetime

from ..core import rules
from ..core.metrics import compute_dashboard
from ..core.models import Task
from ..context import AppContext

MAX_TASKS = 250


def _task_dict(t: Task, today) -> dict:
    return {
        "id": t.id, "intitule": t.title, "projet": t.project_name, "responsable": t.assignee,
        "statut": t.status_label, "nature_statut": t.status_kind, "priorite": t.priority_label,
        "debut": t.start_date and t.start_date.isoformat(), "deadline": t.deadline and t.deadline.isoformat(),
        "jours_retard": rules.overdue_days(t, today) or None,
        "heure_debut": t.start_time and t.start_time.strftime("%H:%M"),
        "heure_fin": t.end_time and t.end_time.strftime("%H:%M"),
        "duree_estimee_min": t.est_minutes, "cree_le": t.created_at.date().isoformat(),
        "modifie_le": t.updated_at.date().isoformat(),
        "realise_le": t.completed_at and t.completed_at.date().isoformat(),
        "description": t.description[:300] or None,
    }


def build_context(ctx: AppContext, now: datetime | None = None) -> str:
    """JSON compact : synthèse chiffrée + tâches ouvertes (priorisées) + terminées récentes."""
    now = now or ctx.clock()
    today = now.date()
    tasks = ctx.tasks.all()
    dash = compute_dashboard(tasks, now, ctx.settings.all())
    active = sorted((t for t in tasks if t.is_active), key=lambda t: -rules.urgency_score(t, today))
    recent_done = sorted((t for t in tasks if t.status_kind == "done"),
                         key=lambda t: t.completed_at or t.updated_at, reverse=True)[:40]
    shown = active[:MAX_TASKS]
    data = {
        "date_du_jour": today.isoformat(),
        "synthese": {
            "total": dash.total, "terminees": dash.done, "en_cours": dash.in_progress, "a_faire": dash.todo,
            "bloquees": dash.blocked, "en_retard": dash.overdue, "echeance_aujourdhui": dash.due_today,
            "taux_avancement_pct": round(dash.progress * 100, 1),
        },
        "projets": [
            {"projet": p.name, "total": p.total, "ouvertes": p.active, "terminees": p.done,
             "en_retard": p.overdue, "bloquees": p.blocked, "indice_charge": p.score}
            for p in dash.projects
        ],
        "taches_ouvertes": [_task_dict(t, today) for t in shown],
        "taches_ouvertes_non_transmises": max(0, len(active) - len(shown)),
        "terminees_recemment": [_task_dict(t, today) for t in recent_done],
        "terminees_par_mois": dash.completed_series,
        "charge_par_semaine": [{"semaine": w, "taches": n, "minutes_estimees": m} for w, n, m in dash.workload_series],
    }
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
