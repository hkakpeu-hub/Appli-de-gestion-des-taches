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
        for i in range(version, len(MIGRATIONS)):
            log.info("Migration de la base vers la version %d", i + 1)
            try:
                self.conn.executescript("BEGIN;" + MIGRATIONS[i])
                if i == 0:
                    self._seed_statuses()
                self.conn.execute(f"PRAGMA user_version={i + 1}")
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

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
