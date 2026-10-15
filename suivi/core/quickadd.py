"""Saisie rapide : « Relancer Donald #Centaures !demain @Hermann » -> tâche prête à créer.

 - ``#projet``  : projet (les « _ » deviennent des espaces)
 - ``@nom``     : responsable
 - ``!date``    : deadline — aujourd'hui | auj | demain | +3j | jj/mm | jj/mm/aaaa
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from .models import TaskInput, ValidationError

TOKEN = re.compile(r"(?:(?<=\s)|^)([#@!])(\S+)")


def parse_date_token(tok: str, today: date) -> date:
    t = tok.lower().replace("'", "").replace("’", "")
    if t in ("aujourdhui", "auj", "today"):
        return today
    if t in ("demain", "dem"):
        return today + timedelta(days=1)
    m = re.fullmatch(r"\+(\d{1,3})j?", t)
    if m:
        return today + timedelta(days=int(m.group(1)))
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        y += 2000 if y < 100 else 0
        try:
            res = date(y, mo, d)
        except ValueError as exc:
            raise ValidationError(f"Date invalide : « {tok} ».") from exc
        if not m.group(3) and res < today:  # « 15/03 » saisi en décembre = année suivante
            res = date(y + 1, mo, d)
        return res
    raise ValidationError(f"Date non reconnue : « !{tok} » (essayez !demain, !+3j ou !25/12).")


def parse_quick(text: str, today: date, default_assignee: str = "") -> TaskInput:
    data = TaskInput(assignee=default_assignee)

    def repl(m: re.Match) -> str:
        kind, tok = m.group(1), m.group(2)
        if kind == "#":
            data.project_name = tok.replace("_", " ")
        elif kind == "@":
            data.assignee = tok.replace("_", " ")
        else:
            data.deadline = parse_date_token(tok, today)
        return ""

    data.title = " ".join(TOKEN.sub(repl, text).split())
    if not data.title:
        raise ValidationError("Saisissez l'intitulé de la tâche.")
    data.source = "Saisie rapide"
    return data
