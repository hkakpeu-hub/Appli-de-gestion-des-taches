"""Importation Excel (.xlsx / .xls) : analyse, prévisualisation, dédoublonnage, import transactionnel.

Principes
 - Les feuilles sont reconnues par leurs EN-TÊTES (pas par leur position), avec des synonymes
   (« Dead line », « Date butoire », « Commetaire(...) » -> commentaire, etc.).
 - Une feuille n'est proposée que si elle contient une colonne « action/intitulé » ET au moins une
   colonne de suivi (statut, deadline ou responsable) : les feuilles « Compétences » ou « WINNING »
   du classeur d'origine ne sont donc pas prises pour des tâches.
 - Aucune donnée n'est écrite pendant l'analyse. L'import réel est atomique (tout ou rien) et précédé
   d'une sauvegarde de la base.
 - Doublon = même intitulé + même date de début + même projet (insensible à la casse/aux accents).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Optional

from ..core.models import (
    KIND_BLOCKED, KIND_CANCELLED, KIND_DONE, KIND_IN_PROGRESS, KIND_TODO, KIND_WAITING,
    PRIORITIES, TaskInput, to_date,
)
from ..core.tasks import TaskService
from ..db import fold

log = logging.getLogger(__name__)

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "num": ("id", "num", "n", "no", "numero"),
    "title": ("action", "actions", "intitule", "tache", "titre", "intitule de la tache", "intitule de l action"),
    "start_date": ("dates", "date", "date de debut", "debut", "date de debut prevue", "date prevue"),
    "deadline": ("dead line", "deadline", "date butoire", "echeance", "date limite", "date d echeance"),
    "project": ("projet", "project"),
    "status": ("statut", "status", "etat"),
    "description": ("description", "details", "detail"),
    "comment": ("commentaire", "commentaires", "observation", "observations", "remarques"),
    "assignee": ("responsable", "assigne a", "assigne"),
    "start_time": ("heure de debut", "heure debut"),
    "end_time": ("heure de fin", "heure fin"),
    "priority": ("priorite",),
    "est_minutes": ("duree estimee", "duree estimee min"),
    "actual_minutes": ("duree reelle", "duree reelle min"),
    "created_at": ("date de creation", "creee le"),
    "completed_at": ("date de realisation", "realisee le", "date de cloture", "date de fin reelle"),
    "extra_date": ("date complementaire",),
}

STATUS_SYNONYMS: dict[str, str] = {
    "termine": KIND_DONE, "terminee": KIND_DONE, "fait": KIND_DONE, "faite": KIND_DONE, "done": KIND_DONE,
    "cloture": KIND_DONE, "clos": KIND_DONE, "realise": KIND_DONE, "realisee": KIND_DONE,
    "en cours": KIND_IN_PROGRESS, "encours": KIND_IN_PROGRESS, "demarre": KIND_IN_PROGRESS,
    "non dem": KIND_TODO, "non demarre": KIND_TODO, "non demarree": KIND_TODO, "a faire": KIND_TODO,
    "todo": KIND_TODO, "ouvert": KIND_TODO, "nouveau": KIND_TODO,
    "en attente": KIND_WAITING, "attente": KIND_WAITING, "suspendu": KIND_WAITING,
    "bloque": KIND_BLOCKED, "bloquee": KIND_BLOCKED,
    "annule": KIND_CANCELLED, "annulee": KIND_CANCELLED, "abandonne": KIND_CANCELLED,
}
PRIORITY_SYNONYMS = {
    "faible": "low", "basse": "low", "low": "low", "normal": "normal", "normale": "normal", "moyenne": "normal",
    "eleve": "high", "elevee": "high", "haute": "high", "high": "high", "critique": "critical", "critical": "critical",
    "urgent": "critical", "urgente": "critical",
}
DEFAULT_PROJECT_BY_SHEET = {"actions personnelles": "Personnel"}
DATE_PATTERNS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d"]


def norm_header(v) -> str:
    s = fold(v)
    s = re.sub(r"\(.*?\)", " ", s)  # « Commetaire(Difficultés, apprentissage) » -> « commetaire »
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def _match_header(h: str) -> Optional[str]:
    if not h:
        return None
    if h.startswith("comme") or h.startswith("observ"):
        return "comment"  # tolère les fautes (« Commetaire »)
    for key, syns in HEADER_SYNONYMS.items():
        if h in syns:
            return key
    return None


# --------------------------------------------------------------------------------- lecture du classeur
@dataclass
class RawSheet:
    name: str
    hidden: bool
    rows: list[list]


def read_workbook(path: Path) -> list[RawSheet]:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        try:
            import xlrd
        except ImportError as exc:  # pragma: no cover
            raise ValueError("La lecture des fichiers .xls nécessite le paquet « xlrd » (relancez install.bat).") from exc
        try:
            book = xlrd.open_workbook(str(path))
        except Exception as exc:
            raise ValueError(f"Fichier .xls illisible : {exc}") from exc
        sheets = []
        for sh in book.sheets():
            rows = []
            for r in range(sh.nrows):
                row = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    v = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        v = xlrd.xldate_as_datetime(v, book.datemode)
                    elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                        v = None
                    row.append(v)
                rows.append(row)
            sheets.append(RawSheet(sh.name, sh.visibility != 0, rows))
        return sheets
    if suffix not in (".xlsx", ".xlsm"):
        raise ValueError("Format non pris en charge : choisissez un fichier .xlsx ou .xls.")
    import openpyxl
    try:
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=False)
    except Exception as exc:
        raise ValueError(f"Impossible d'ouvrir le fichier Excel (est-il ouvert ailleurs ou corrompu ?) : {exc}") from exc
    sheets = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        sheets.append(RawSheet(ws.title, ws.sheet_state != "visible", rows))
    wb.close()
    return sheets


# --------------------------------------------------------------------------------------- structures
@dataclass
class SheetInfo:
    name: str
    hidden: bool
    header_row: Optional[int]  # index 0-based
    columns: dict[str, int]  # champ -> index de colonne
    data_rows: int = 0
    selected: bool = False
    default_project: str = ""
    skip_reason: str = ""


@dataclass
class ParsedRow:
    sheet: str
    row_no: int  # numéro de ligne Excel (1-based)
    data: Optional[TaskInput]
    state: str  # new | duplicate | update | invalid
    messages: list[str] = field(default_factory=list)
    existing_id: Optional[int] = None
    comment: str = ""
    key: str = ""

    @property
    def has_warning(self) -> bool:
        return bool(self.messages) and self.state in ("new", "update")


@dataclass
class ImportPreview:
    path: Path
    sheets: list[SheetInfo]
    rows: list[ParsedRow]

    def counts(self) -> dict[str, int]:
        c = {"new": 0, "duplicate": 0, "update": 0, "invalid": 0, "warnings": 0}
        for r in self.rows:
            c[r.state] += 1
            c["warnings"] += 1 if r.has_warning else 0
        return c


@dataclass
class ImportReport:
    imported: int = 0
    updated: int = 0
    ignored: int = 0
    rejected: int = 0
    warnings: int = 0
    backup: Optional[Path] = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.imported} importée(s), {self.updated} mise(s) à jour, "
                f"{self.ignored} ignorée(s) (doublons), {self.rejected} rejetée(s)")


# ---------------------------------------------------------------------------------- conversion de valeurs
def clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v or v.startswith("#"):  # vide ou erreur Excel (#REF!, #N/A…)
            return None
    return v


def parse_date(v) -> tuple[Optional[date], Optional[str]]:
    v = clean(v)
    if v is None:
        return None, None
    if isinstance(v, datetime):
        return v.date(), None
    if isinstance(v, date):
        return v, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < v < 80000:  # numéro de série Excel
            return (datetime(1899, 12, 30) + timedelta(days=float(v))).date(), None
        return None, f"date invalide « {v} »"
    s = str(v)
    for candidate in (s, s[:10]):
        for p in DATE_PATTERNS:
            try:
                return datetime.strptime(candidate, p).date(), None
            except ValueError:
                continue
    return None, f"date invalide « {s} »"


def parse_time(v) -> tuple[Optional[time], Optional[date], Optional[str]]:
    """Retourne (heure, date_si_la_cellule_contient_une_date, avertissement)."""
    v = clean(v)
    if v is None:
        return None, None, None
    if isinstance(v, time):
        return v.replace(second=0, microsecond=0), None, None
    if isinstance(v, datetime):
        if v.hour == 0 and v.minute == 0:  # date sans heure dans une colonne d'heure
            return None, v.date(), None
        return v.time().replace(second=0, microsecond=0), v.date(), None
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 1:
        total = round(v * 24 * 60)
        return time(total // 60 % 24, total % 60), None, None
    s = str(v).lower().replace("h", ":")
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})?", s)
    if m and int(m.group(1)) < 24 and int(m.group(2) or 0) < 60:
        return time(int(m.group(1)), int(m.group(2) or 0)), None, None
    return None, None, f"heure invalide « {v} »"


def parse_int(v) -> tuple[Optional[int], Optional[str]]:
    v = clean(v)
    if v is None:
        return None, None
    try:
        n = int(float(str(v).replace(",", ".")))
        return (n, None) if n >= 0 else (None, f"durée négative « {v} »")
    except ValueError:
        return None, f"durée invalide « {v} »"


def dup_key(title: str, start: Optional[date], project: str) -> str:
    return f"{fold(' '.join(title.split()))}|{start.isoformat() if start else ''}|{fold(' '.join((project or '').split()))}"


# ------------------------------------------------------------------------------------------- importeur
class ExcelImporter:
    def __init__(self, tasks: TaskService, backup: Optional[Callable[[], Path]] = None):
        self.tasks = tasks
        self.backup = backup

    # -- analyse des feuilles -----------------------------------------------
    def detect_sheet(self, sh: RawSheet) -> SheetInfo:
        info = SheetInfo(sh.name, sh.hidden, None, {})
        info.default_project = DEFAULT_PROJECT_BY_SHEET.get(fold(sh.name), "")
        for i, row in enumerate(sh.rows[:20]):
            cols: dict[str, int] = {}
            for j, cell in enumerate(row):
                key = _match_header(norm_header(clean(cell))) if clean(cell) is not None else None
                if key and key not in cols:
                    cols[key] = j
            has_track = any(k in cols for k in ("status", "deadline", "assignee"))
            if "title" in cols and has_track:
                info.header_row, info.columns = i, cols
                break
        if info.header_row is None:
            info.skip_reason = "aucune colonne « Action / Intitulé » + suivi reconnue"
            return info
        # colonne sans titre juste après les commentaires qui contient des dates (cas du fichier d'origine)
        if "extra_date" not in info.columns and "comment" in info.columns:
            j = info.columns["comment"] + 1
            hdr = sh.rows[info.header_row]
            blank_header = j >= len(hdr) or clean(hdr[j]) is None
            body = [r[j] for r in sh.rows[info.header_row + 1:] if j < len(r) and clean(r[j]) is not None]
            if blank_header and body and all(isinstance(x, (datetime, date)) for x in body):
                info.columns["extra_date"] = j
        info.data_rows = sum(
            1 for r in sh.rows[info.header_row + 1:] if self._cell(r, info.columns.get("title")) is not None
        )
        info.selected = info.data_rows > 0
        if "project" not in info.columns and not info.default_project:
            info.default_project = sh.name
        return info

    @staticmethod
    def _cell(row, idx):
        if idx is None or idx >= len(row):
            return None
        return clean(row[idx])

    # -- prévisualisation -----------------------------------------------------
    def preview(self, path: Path, update_existing: bool = False, sheets_override: Optional[dict] = None) -> ImportPreview:
        path = Path(path)
        raw = read_workbook(path)
        infos = [self.detect_sheet(s) for s in raw]
        # classeur issu d'un export de l'application : on n'importe que la feuille complète (l'autre en est le doublon)
        names = {fold(i.name) for i in infos}
        if "toutes les donnees" in names:
            for i in infos:
                if fold(i.name) != "toutes les donnees":
                    i.selected = False
        for i in infos:  # feuilles masquées : proposées mais non cochées par défaut si vides
            if i.header_row is None:
                i.selected = False
        preview = ImportPreview(path, infos, [])
        self.reparse(preview, raw, update_existing, sheets_override)
        return preview

    def reparse(self, preview: ImportPreview, raw: Optional[list[RawSheet]] = None, update_existing: bool = False,
                sheets_override: Optional[dict] = None) -> None:
        """(Re)calcule les lignes selon les feuilles cochées / projets par défaut / option de mise à jour."""
        raw = raw or read_workbook(preview.path)
        by_name = {s.name: s for s in raw}
        existing = self._existing_index()
        seen: dict[str, str] = {}
        preview.rows = []
        for info in preview.sheets:
            if not info.selected or info.header_row is None:
                continue
            sh = by_name[info.name]
            for idx in range(info.header_row + 1, len(sh.rows)):
                row = sh.rows[idx]
                if all(clean(c) is None for c in row):
                    continue
                pr = self._parse_row(info, row, idx + 1)
                self._classify(pr, existing, seen, update_existing)
                preview.rows.append(pr)

    def _existing_index(self) -> dict[str, tuple]:
        index = {}
        for t in self.tasks.all(include_deleted=True):
            index.setdefault(dup_key(t.title, t.start_date, t.project_name), t)
        return index

    def _parse_row(self, info: SheetInfo, row: list, row_no: int) -> ParsedRow:
        cols = info.columns
        msgs: list[str] = []
        g = lambda k: self._cell(row, cols.get(k))  # noqa: E731
        title = g("title")
        if title is None:
            return ParsedRow(info.name, row_no, None, "invalid", ["intitulé manquant"])
        title = " ".join(str(title).split())
        data = TaskInput(title=title, source=f"Excel:{info.name}")

        data.start_date, w = parse_date(g("start_date")); w and msgs.append(f"début : {w}")
        data.deadline, w = parse_date(g("deadline")); w and msgs.append(f"deadline : {w}")
        data.extra_date, w = parse_date(g("extra_date")); w and msgs.append(f"date complémentaire : {w}")
        created, w = parse_date(g("created_at")); w and msgs.append(f"création : {w}")
        completed, w = parse_date(g("completed_at")); w and msgs.append(f"réalisation : {w}")
        data.created_at = datetime.combine(created or data.start_date, time()) if (created or data.start_date) else None
        data.completed_at = datetime.combine(completed, time()) if completed else None

        # heures (une cellule d'heure contenant une simple date est interprétée comme une échéance)
        for fld in ("start_time", "end_time"):
            t, d, w = parse_time(g(fld))
            w and msgs.append(f"{fld.replace('_', ' ')} : {w}")
            if d is not None and t is None:
                if data.deadline is None:
                    data.deadline = d
                    msgs.append("une date figure dans la colonne d'heure : interprétée comme deadline")
                elif data.start_date is None:
                    data.start_date = d
                    msgs.append("une date figure dans la colonne d'heure : interprétée comme date de début")
            else:
                setattr(data, fld, t)
        if data.start_time and data.end_time and data.end_time <= data.start_time:
            msgs.append("heure de fin ≤ heure de début : horaires ignorés")
            data.start_time = data.end_time = None
        if (data.start_time or data.end_time) and not data.start_date:
            data.start_date = data.deadline or data.created_at and data.created_at.date()
            if not data.start_date:
                msgs.append("horaires sans date : horaires ignorés")
                data.start_time = data.end_time = None
        if data.start_date and data.deadline and data.deadline < data.start_date:
            msgs.append("deadline antérieure à la date de début (conservée telle quelle)")

        data.est_minutes, w = parse_int(g("est_minutes")); w and msgs.append(w)
        data.actual_minutes, w = parse_int(g("actual_minutes")); w and msgs.append(w)
        data.description = str(g("description") or "")
        data.assignee = str(g("assignee") or "")
        data.project_name = str(g("project") or info.default_project or "")

        pr_raw = g("priority")
        if pr_raw is not None:
            p = PRIORITY_SYNONYMS.get(fold(pr_raw))
            if p in PRIORITIES:
                data.priority = p
            else:
                msgs.append(f"priorité inconnue « {pr_raw} » (Normal retenu)")

        raw_status = g("status")
        data.status_id, w = self._map_status(raw_status)
        w and msgs.append(w)
        if data.completed_at is not None and self.tasks.statuses.get(data.status_id).kind != KIND_DONE:
            data.completed_at = None
        return ParsedRow(info.name, row_no, data, "new", msgs, comment=str(g("comment") or ""),
                         key=dup_key(title, data.start_date, data.project_name))

    def _map_status(self, raw) -> tuple[int, Optional[str]]:
        svc = self.tasks.statuses
        if raw is None:
            return svc.first_of_kind(KIND_TODO).id, None
        label = str(raw).strip()
        exact = svc.by_label(label)
        if exact:
            return exact.id, None
        key = re.sub(r"^\s*\d+\s*[-–.)]\s*", "", fold(label)).strip()  # « 1-Terminé » -> « termine »
        kind = STATUS_SYNONYMS.get(key)
        if kind:
            return svc.first_of_kind(kind).id, None
        return svc.first_of_kind(KIND_TODO).id, f"statut inconnu « {label} » (« À faire » retenu)"

    def _classify(self, pr: ParsedRow, existing: dict, seen: dict, update_existing: bool) -> None:
        if pr.state == "invalid":
            return
        if pr.key in seen:
            pr.state = "duplicate"
            pr.messages.append(f"doublon d'une ligne précédente du fichier ({seen[pr.key]})")
            return
        seen[pr.key] = f"{pr.sheet} l.{pr.row_no}"
        ex = existing.get(pr.key)
        if ex is None:
            return
        pr.existing_id = ex.id
        pr.state = "duplicate"
        pr.messages.append("déjà présente dans l'application")
        if update_existing:
            d = pr.data
            diffs = []
            if d.status_id != ex.status_id:
                diffs.append("statut")
            if d.deadline and d.deadline != ex.deadline:
                diffs.append("deadline")
            if d.description and d.description != ex.description:
                diffs.append("description")
            if d.assignee and d.assignee != ex.assignee:
                diffs.append("responsable")
            if d.extra_date and d.extra_date != ex.extra_date:
                diffs.append("date complémentaire")
            if pr.comment and pr.comment not in {c.body for c in self.tasks.comments(ex.id)}:
                diffs.append("commentaire")
            if diffs:
                pr.state = "update"
                pr.messages[-1] = "déjà présente : mise à jour de " + ", ".join(diffs)

    # -- import réel -----------------------------------------------------------
    def commit(self, preview: ImportPreview) -> ImportReport:
        report = ImportReport()
        todo = [r for r in preview.rows if r.state in ("new", "update")]
        report.rejected = sum(1 for r in preview.rows if r.state == "invalid")
        report.ignored = sum(1 for r in preview.rows if r.state == "duplicate")
        report.warnings = sum(1 for r in preview.rows if r.has_warning)
        if not todo:
            return report
        if self.backup:
            report.backup = self.backup()  # sauvegarde avant toute écriture
        try:
            with self.tasks.batch(), self.tasks.db.transaction():
                for pr in todo:
                    if pr.state == "new":
                        t = self.tasks.create(pr.data, history=False, strict=False, completed_default_now=False)
                        if pr.comment:
                            self._add_comment(t.id, pr.comment, pr.data.created_at)
                        self.tasks.log_event(t.id, t.title, "imported", "Fichier", "", f"{preview.path.name} · {pr.sheet} l.{pr.row_no}")
                        report.imported += 1
                    else:
                        self._apply_update(pr)
                        report.updated += 1
        except Exception as exc:  # rollback déjà fait par transaction()
            log.exception("Échec de l'import")
            report.errors.append(str(exc))
            report.imported = report.updated = 0
            raise ImportFailed(f"Import annulé, aucune donnée n'a été modifiée : {exc}", report) from exc
        return report

    def _add_comment(self, task_id: int, body: str, when: Optional[datetime]) -> None:
        from ..core.models import iso_datetime
        self.tasks.db.conn.execute(
            "INSERT INTO comments(task_id,body,created_at) VALUES (?,?,?)",
            (task_id, body, iso_datetime(when or self.tasks.clock())),
        )

    def _apply_update(self, pr: ParsedRow) -> None:
        ex = self.tasks.get(pr.existing_id)
        d = pr.data
        new = self.tasks.to_input(ex, status_id=d.status_id)
        if d.deadline:
            new.deadline = d.deadline
        if d.description:
            new.description = d.description
        if d.assignee:
            new.assignee = d.assignee
        if d.extra_date:
            new.extra_date = d.extra_date
        self.tasks.update(ex.id, new, strict=False)
        if pr.comment and pr.comment not in {c.body for c in self.tasks.comments(ex.id)}:
            self._add_comment(ex.id, pr.comment, d.created_at)


class ImportFailed(Exception):
    def __init__(self, message: str, report: ImportReport):
        super().__init__(message)
        self.report = report
