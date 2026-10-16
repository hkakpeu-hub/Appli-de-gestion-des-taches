"""Accès SQLite : connexion, migrations versionnées, transactions, sauvegarde/restauration."""
from __future__ import annotations

import logging
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

DEFAULT_STATUSES = [
    # (libellé, nature, couleur)
    ("À faire", "todo", "#64748B"),
    ("En cours", "in_progress", "#2563EB"),
    ("En attente", "waiting", "#D97706"),
    ("Bloquée", "blocked", "#DC2626"),
    ("Terminée", "done", "#16A34A"),
    ("Annulée", "cancelled", "#94A3B8"),
]

MIGRATIONS: list[str] = [
    # --- version 1 -----------------------------------------------------
    """
    CREATE TABLE projects(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        color TEXT,
        description TEXT,
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE statuses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL UNIQUE COLLATE NOCASE,
        kind TEXT NOT NULL,
        color TEXT NOT NULL,
        position INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        project_id INTEGER REFERENCES projects(id),
        description TEXT,
        assignee TEXT,
        created_at TEXT NOT NULL,
        start_date TEXT,
        deadline TEXT,
        status_id INTEGER NOT NULL REFERENCES statuses(id),
        priority TEXT NOT NULL DEFAULT 'normal',
        completed_at TEXT,
        start_time TEXT,
        end_time TEXT,
        est_minutes INTEGER,
        actual_minutes INTEGER,
        extra_date TEXT,
        source TEXT,
        updated_at TEXT NOT NULL,
        status_changed_at TEXT NOT NULL,
        deleted_at TEXT
    );
    CREATE INDEX ix_tasks_deadline ON tasks(deadline);
    CREATE INDEX ix_tasks_start ON tasks(start_date);
    CREATE INDEX ix_tasks_status ON tasks(status_id);
    CREATE INDEX ix_tasks_project ON tasks(project_id);
    CREATE TABLE comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX ix_comments_task ON comments(task_id);
    CREATE TABLE history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        task_title TEXT,
        event TEXT NOT NULL,
        field TEXT,
        old_value TEXT,
        new_value TEXT,
        at TEXT NOT NULL
    );
    CREATE INDEX ix_history_task ON history(task_id);
    CREATE INDEX ix_history_at ON history(at);
    CREATE TABLE alerts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        level TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        notified_at TEXT,
        read_at TEXT,
        snoozed_until TEXT,
        resolved_at TEXT
    );
    CREATE INDEX ix_alerts_task ON alerts(task_id);
    CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # --- version 2 : espaces (Travail / Personnel / Kingdom…), pièces jointes -----------------
    """
    CREATE TABLE spaces(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        icon TEXT NOT NULL DEFAULT '✔',
        color TEXT NOT NULL DEFAULT '#2563EB',
        kind TEXT NOT NULL DEFAULT 'tasks',
        position INTEGER NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1
    );
    INSERT INTO spaces(name,icon,color,position) VALUES ('Travail','💼','#2563EB',0);
    INSERT INTO spaces(name,icon,color,position) VALUES ('Personnel','🏠','#16A34A',1);
    INSERT INTO spaces(name,icon,color,position) VALUES ('Kingdom','⛪','#7C3AED',2);

    CREATE TABLE projects_new(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        space_id INTEGER NOT NULL DEFAULT 1 REFERENCES spaces(id),
        name TEXT NOT NULL COLLATE NOCASE,
        color TEXT,
        description TEXT,
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        UNIQUE(space_id, name)
    );
    INSERT INTO projects_new(id,space_id,name,color,description,archived,created_at)
        SELECT id,1,name,color,description,archived,created_at FROM projects;
    DROP TABLE projects;
    ALTER TABLE projects_new RENAME TO projects;
    -- le projet « Personnel » de l'ancien classeur rejoint l'espace Personnel
    UPDATE projects SET space_id=2 WHERE name='Personnel' COLLATE NOCASE;

    ALTER TABLE tasks ADD COLUMN space_id INTEGER NOT NULL DEFAULT 1 REFERENCES spaces(id);
    UPDATE tasks SET space_id=2 WHERE project_id IN (SELECT id FROM projects WHERE space_id=2);
    CREATE INDEX ix_tasks_space ON tasks(space_id);

    CREATE TABLE attachments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        display_name TEXT NOT NULL,
        path TEXT NOT NULL,
        is_relative INTEGER NOT NULL DEFAULT 0,
        size INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE INDEX ix_attachments_task ON attachments(task_id);
    """,
    # --- version 3 : tâches répétitives ---------------------------------------------------------
    """
    CREATE TABLE recurrences(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        space_id INTEGER NOT NULL DEFAULT 1 REFERENCES spaces(id),
        title TEXT NOT NULL,
        project_id INTEGER REFERENCES projects(id),
        description TEXT,
        assignee TEXT,
        priority TEXT NOT NULL DEFAULT 'normal',
        start_time TEXT,
        end_time TEXT,
        est_minutes INTEGER,
        freq TEXT NOT NULL,
        interval INTEGER NOT NULL DEFAULT 1,
        weekdays TEXT,
        month_day INTEGER,
        start_date TEXT NOT NULL,
        end_date TEXT,
        count INTEGER,
        auto_close INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        generated_until TEXT,
        created_at TEXT NOT NULL
    );
    ALTER TABLE tasks ADD COLUMN series_id INTEGER REFERENCES recurrences(id) ON DELETE SET NULL;
    ALTER TABLE tasks ADD COLUMN occurrence_date TEXT;
    CREATE UNIQUE INDEX ux_tasks_occurrence ON tasks(series_id, occurrence_date) WHERE series_id IS NOT NULL;
    """,
    # --- version 4 : événements (distincts des tâches) et tâches liées -----------------------------
    """
    CREATE TABLE events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        space_id INTEGER NOT NULL DEFAULT 1 REFERENCES spaces(id),
        series_id INTEGER REFERENCES recurrences(id) ON DELETE SET NULL,
        title TEXT NOT NULL,
        description TEXT,
        location TEXT,
        date TEXT NOT NULL,
        start_time TEXT,
        end_time TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX ux_events_occurrence ON events(series_id, date) WHERE series_id IS NOT NULL;
    CREATE INDEX ix_events_date ON events(date);
    CREATE TABLE event_templates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        series_id INTEGER NOT NULL REFERENCES recurrences(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        assignee TEXT,
        days_before INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0
    );
    ALTER TABLE recurrences ADD COLUMN kind TEXT NOT NULL DEFAULT 'task';
    ALTER TABLE recurrences ADD COLUMN location TEXT;
    ALTER TABLE tasks ADD COLUMN event_id INTEGER REFERENCES events(id) ON DELETE SET NULL;
    ALTER TABLE tasks ADD COLUMN template_id INTEGER;
    CREATE INDEX ix_tasks_event ON tasks(event_id);
    CREATE UNIQUE INDEX ux_tasks_event_template ON tasks(event_id, template_id)
        WHERE event_id IS NOT NULL AND template_id IS NOT NULL;
    -- les séries marquées « événement » (ancienne case à cocher) deviennent de vrais événements
    UPDATE recurrences SET kind='event' WHERE auto_close=1;
    INSERT INTO events(space_id,series_id,title,description,date,start_time,end_time,created_at)
        SELECT r.space_id, r.id, r.title, r.description, t.occurrence_date, r.start_time, r.end_time, r.created_at
        FROM tasks t JOIN recurrences r ON r.id=t.series_id
        WHERE r.kind='event' AND t.occurrence_date IS NOT NULL GROUP BY r.id, t.occurrence_date;
    DELETE FROM tasks WHERE series_id IN (SELECT id FROM recurrences WHERE kind='event');
    """,
]


def fold(value) -> str:
    """Normalise pour une recherche insensible à la casse et aux accents."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKD", str(value))
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = self._connect()
        self.migrate()

    # -- connexion ---------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.create_function("fold", 1, fold, deterministic=True)
        return conn

    def close(self) -> None:
        try:
            self.conn.commit()
            self.conn.close()
        except sqlite3.Error:  # pragma: no cover
            log.exception("Erreur à la fermeture de la base")

    # -- migrations --------------------------------------------------------
    def migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if 0 < version < len(MIGRATIONS):
            # base existante : copie de sécurité avant toute modification du schéma
            self.conn.commit()
            self.backup_to(self.path.with_name(f"{self.path.stem}_avant_migration_v{version}.db"))
        for i in range(version, len(MIGRATIONS)):
            log.info("Migration de la base vers la version %d", i + 1)
            try:
                self.conn.execute("PRAGMA foreign_keys=OFF")  # requis pour reconstruire une table
                self.conn.executescript("BEGIN;" + MIGRATIONS[i])
                if i == 0:
                    self._seed_statuses()
                self.conn.execute(f"PRAGMA user_version={i + 1}")
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            finally:
                self.conn.execute("PRAGMA foreign_keys=ON")

    def _seed_statuses(self) -> None:
        for pos, (label, kind, color) in enumerate(DEFAULT_STATUSES):
            self.conn.execute(
                "INSERT INTO statuses(label,kind,color,position) VALUES (?,?,?,?)",
                (label, kind, color, pos),
            )

    # -- transactions ------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Transaction atomique : tout est annulé en cas d'erreur."""
        if self.conn.in_transaction:  # transaction imbriquée : on réutilise l'externe
            yield self.conn
            return
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except BaseException:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    # -- sauvegarde / restauration ----------------------------------------
    def backup_to(self, dest: str | Path) -> None:
        """Copie cohérente de la base (API de sauvegarde SQLite, sûre même si la base est ouverte)."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        target = sqlite3.connect(str(tmp))
        try:
            self.conn.commit()
            self.conn.backup(target)
        finally:
            target.close()
        tmp.replace(dest)

    def restore_from(self, src: str | Path) -> None:
        """Remplace le contenu de la base ouverte par celui de la sauvegarde ``src``."""
        src = Path(src)
        probe = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
        try:
            ok = probe.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise ValueError(f"La sauvegarde est corrompue ({ok}).")
            probe.execute("SELECT count(*) FROM tasks").fetchone()
            probe.execute("SELECT count(*) FROM statuses").fetchone()
            probe.backup(self.conn)
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"Fichier de sauvegarde invalide : {exc}") from exc
        finally:
            probe.close()
        self.conn.create_function("fold", 1, fold, deterministic=True)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()  # sauvegarde plus ancienne : mise à niveau du schéma
