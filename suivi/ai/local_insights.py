"""Analyses rapides calculées localement (sans IA, sans Internet).

Elles servent de repli quand aucune IA n'est configurée et de base factuelle vérifiable.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..context import AppContext
from ..core import rules
from ..core.metrics import compute_dashboard

QUICK_QUESTIONS = {
    "Mes 5 tâches les plus urgentes": "top5",
    "Quelles actions traiter en priorité aujourd'hui ?": "today",
    "Projets les plus chargés / à risque": "projects",
    "Tâches sans évolution depuis longtemps": "stale",
    "Résumé de mon activité cette semaine": "week",
}


def _line(t, today) -> str:
    dl = t.deadline.strftime("%d/%m/%Y") if t.deadline else "sans deadline"
    late = rules.overdue_days(t, today)
    extra = f", {late} j de retard" if late else ""
    return f"• #{t.id} {t.title} — {t.project_name or 'sans projet'} · {t.status_label} · {t.priority_label} · {dl}{extra}"


def answer(ctx: AppContext, key: str, now: datetime | None = None) -> str:
    now = now or ctx.clock()
    today = now.date()
    tasks = ctx.tasks.all()
    active = [t for t in tasks if t.is_active]
    if key == "top5":
        top = sorted(active, key=lambda t: -rules.urgency_score(t, today))[:5]
        return "Les 5 tâches les plus urgentes (score = retard, échéance proche, priorité) :\n" + "\n".join(_line(t, today) for t in top)
    if key == "today":
        sel = [t for t in active if t.deadline == today or rules.is_overdue(t, today) and t.priority in ("high", "critical")
               or t.status_kind == "in_progress"]
        sel.sort(key=lambda t: -rules.urgency_score(t, today))
        return "À traiter en priorité aujourd'hui :\n" + ("\n".join(_line(t, today) for t in sel[:10]) or "Rien d'urgent.")
    if key == "projects":
        d = compute_dashboard(tasks, now, ctx.settings.all())
        rows = [f"• {p.name} — {p.active} ouvertes, {p.overdue} en retard, {p.blocked} bloquées, {p.done_ratio:.0%} terminées (indice {p.score:g})"
                for p in d.projects[:8]]
        return "Projets classés par indice de charge (retards ×3 + bloquées ×2 + ouvertes) :\n" + "\n".join(rows)
    if key == "stale":
        days = int(ctx.settings.get("stale_days"))
        sel = sorted((t for t in active if rules.is_stale(t, now, days)), key=lambda t: t.updated_at)[:10]
        return f"Tâches ouvertes sans mise à jour depuis {days} jours ou plus :\n" + (
            "\n".join(f"{_line(t, today)} (maj {t.updated_at:%d/%m/%Y})" for t in sel) or "Aucune.")
    if key == "week":
        start = now - timedelta(days=7)
        done = [t for t in tasks if t.status_kind == "done" and (t.completed_at or t.updated_at) >= start]
        created = [t for t in tasks if t.created_at >= start]
        return (f"Sur les 7 derniers jours : {len(done)} tâche(s) terminée(s), {len(created)} créée(s), "
                f"{sum(1 for t in active if rules.is_overdue(t, today))} en retard à ce jour.")
    return "Question inconnue."
