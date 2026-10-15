from datetime import date, timedelta
from pathlib import Path

import pytest

from suivi.core.metrics import compute_dashboard
from suivi.core.models import TaskInput, ValidationError
from suivi.core.tasks import TaskFilter
from suivi.db import database

TODAY = date(2026, 10, 13)


# ------------------------------------------------------------------------- archivage
def test_archived_project_disappears_everywhere(ctx, make):
    a = make("Dans A", project_name="A", deadline=TODAY - timedelta(days=3))
    make("Dans B", project_name="B", deadline=TODAY - timedelta(days=3))
    ctx.alerts.run()
    assert ctx.alerts.unread_count() == 2
    pid = ctx.projects.by_name("A").id
    ctx.projects.set_archived(pid, True)
    ctx.tasks.notify_changed()
    assert [t.title for t in ctx.tasks.all()] == ["Dans B"]
    assert [t.title for t in ctx.tasks.list(TaskFilter())] == ["Dans B"]
    assert [t.title for t in ctx.tasks.list(TaskFilter(text="dans"))] == ["Dans B"]
    d = compute_dashboard(ctx.tasks.all(), ctx.clock(), ctx.settings.all())
    assert d.total == 1 and d.overdue == 1 and [p.name for p in d.projects] == ["B"]
    ctx.alerts.run()
    assert [x.task_title for x in ctx.alerts.visible()] == ["Dans B"]
    assert "A" not in [p.name for p in ctx.projects.list(include_archived=False)]
    # rien n'est perdu : explicitement demandées, les tâches archivées existent toujours
    assert [t.title for t in ctx.tasks.all(include_archived=True) if t.id == a.id] == ["Dans A"]
    # désarchivage : tout revient
    ctx.projects.set_archived(pid, False)
    assert {t.title for t in ctx.tasks.all()} == {"Dans A", "Dans B"}


def test_cannot_create_task_in_archived_project(ctx, make):
    make("x", project_name="Vieux")
    ctx.projects.set_archived(ctx.projects.by_name("Vieux").id, True)
    with pytest.raises(ValidationError, match="archivé"):
        ctx.tasks.create(TaskInput(title="y", project_name="Vieux"))


# ------------------------------------------------------------------------- espaces
def test_default_spaces_and_scope(ctx, make):
    assert [s.name for s in ctx.spaces.list()] == ["Travail", "Personnel", "Kingdom"]
    work, perso = ctx.spaces.by_name("Travail"), ctx.spaces.by_name("Personnel")
    ctx.set_space(work.id)
    t1 = make("Boulot", project_name="Client")
    ctx.set_space(perso.id)
    t2 = make("Maison", project_name="Client")  # même nom de projet, autre espace : autorisé
    assert [t.title for t in ctx.tasks.all()] == ["Maison"]
    assert [p.id for p in ctx.projects.list()] != [p.id for p in ctx.projects.list(space_id=work.id)]
    assert {t.title for t in ctx.tasks.all(space_id=None)} == {"Boulot", "Maison"}
    assert [t.title for t in ctx.tasks.list(TaskFilter(space_id=work.id))] == ["Boulot"]
    # alertes : globales ou filtrées
    ctx.tasks.update(t1.id, ctx.tasks.to_input(t1, deadline=TODAY - timedelta(days=1)))
    ctx.tasks.update(t2.id, ctx.tasks.to_input(t2, deadline=TODAY - timedelta(days=1)))
    ctx.alerts.run()
    assert ctx.alerts.unread_count() == 2
    assert [a.space_name for a in ctx.alerts.visible(space_id=work.id)] == ["Travail"]


def test_move_task_between_spaces(ctx, make):
    work, kingdom = ctx.spaces.by_name("Travail"), ctx.spaces.by_name("Kingdom")
    ctx.set_space(work.id)
    t = make("Préparer la prédication", project_name="Culte")
    moved = ctx.tasks.move_to_space(t.id, kingdom.id)
    assert moved.space_id == kingdom.id and ctx.tasks.all() == []
    ctx.set_space(kingdom.id)
    assert ctx.tasks.all()[0].project_name == "Culte"


def test_space_management(ctx):
    s = ctx.spaces.create("Famille", "👪")
    assert s.name in [x.name for x in ctx.spaces.list()]
    with pytest.raises(ValidationError):
        ctx.spaces.create("famille")
    ctx.spaces.set_enabled(s.id, False)
    assert s.id not in [x.id for x in ctx.spaces.list(enabled_only=True)]
    ctx.spaces.delete(s.id)  # vide : supprimable
    t = ctx.spaces.by_name("Travail")
    ctx.set_space(t.id)
    ctx.tasks.create(TaskInput(title="x"))
    with pytest.raises(ValidationError):
        ctx.spaces.delete(t.id)
    for sp in ctx.spaces.list(enabled_only=True)[1:]:
        ctx.spaces.set_enabled(sp.id, False)
    with pytest.raises(ValidationError):
        ctx.spaces.set_enabled(t.id, False)  # dernier espace actif


def test_migration_from_v1_keeps_data_and_backs_up(tmp_path):
    path = tmp_path / "old.db"
    full = list(database.MIGRATIONS)
    database.MIGRATIONS[:] = full[:1]
    try:
        db = database.Database(path)
        c = db.conn
        c.execute("INSERT INTO projects(name,color,created_at) VALUES ('Personnel','#111','2025-01-01T00:00:00')")
        c.execute("INSERT INTO projects(name,color,created_at) VALUES ('Centaures','#222','2025-01-01T00:00:00')")
        for title, pid in (("Perso 1", 1), ("Boulot 1", 2), ("Sans projet", None)):
            c.execute("INSERT INTO tasks(title,project_id,created_at,status_id,priority,updated_at,status_changed_at) "
                      "VALUES (?,?,'2025-01-01T00:00:00',1,'normal','2025-01-01T00:00:00','2025-01-01T00:00:00')", (title, pid))
        c.commit()
        db.close()
    finally:
        database.MIGRATIONS[:] = full
    from suivi.context import AppContext
    ctx = AppContext(path, tmp_path / "bk")
    try:
        assert (tmp_path / "old_avant_migration_v1.db").exists()
        perso = ctx.spaces.by_name("Personnel")
        by_title = {t.title: t for t in ctx.tasks.all(space_id=None)}
        assert by_title["Perso 1"].space_id == perso.id and by_title["Boulot 1"].space_id == 1
        assert by_title["Sans projet"].space_id == 1 and by_title["Boulot 1"].project_name == "Centaures"
    finally:
        ctx.close()


# ------------------------------------------------------------------------- pièces jointes
@pytest.fixture
def att_dir(ctx, tmp_path):
    d = tmp_path / "Pieces"
    ctx.settings.set("attachments_dir", str(d))
    return d


def make_file(tmp_path, name="rapport.xlsx", data=b"contenu"):
    p = tmp_path / "src" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(data)
    return p


def test_attachment_copy_stored_on_disk_not_in_db(ctx, make, tmp_path, att_dir):
    t = make("Dossier client")
    big = make_file(tmp_path, "gros.pptx", b"x" * 2_000_000)
    a = ctx.attachments.add(t.id, big)
    stored = ctx.attachments.resolve(a)
    assert stored.is_file() and att_dir in stored.parents and stored.read_bytes() == big.read_bytes()
    assert a.is_relative and a.size == 2_000_000
    assert ctx.tasks.get(t.id).n_attach == 1
    # la base ne contient que le chemin : elle reste petite
    ctx.db.conn.commit()
    assert Path(ctx.db.path).stat().st_size < 500_000


def test_attachment_name_collision_and_link_mode(ctx, make, tmp_path, att_dir):
    t = make("Doublons")
    f = make_file(tmp_path)
    a1, a2 = ctx.attachments.add(t.id, f), ctx.attachments.add(t.id, f)
    assert ctx.attachments.resolve(a1) != ctx.attachments.resolve(a2)
    assert ctx.attachments.resolve(a1).is_file() and ctx.attachments.resolve(a2).is_file()
    link = ctx.attachments.add(t.id, f, copy=False)
    assert not link.is_relative and ctx.attachments.resolve(link) == f.resolve()


def test_attachment_remove_and_missing_file(ctx, make, tmp_path, att_dir):
    t = make("Retrait")
    a = ctx.attachments.add(t.id, make_file(tmp_path))
    path = ctx.attachments.resolve(a)
    ctx.attachments.remove(a.id)  # retire le lien, garde le fichier
    assert path.is_file() and ctx.attachments.list(t.id) == []
    b = ctx.attachments.add(t.id, make_file(tmp_path, "autre.docx"))
    pb = ctx.attachments.resolve(b)
    pb.unlink()
    assert not ctx.attachments.exists(b)  # fichier supprimé hors de l'appli : détecté
    c = ctx.attachments.add(t.id, make_file(tmp_path, "c.png"))
    pc = ctx.attachments.resolve(c)
    ctx.attachments.remove(c.id, delete_file=True)
    assert not pc.exists()
    with pytest.raises(ValidationError):
        ctx.attachments.add(t.id, tmp_path / "inexistant.pdf")


def test_change_attachment_folder_moves_files_and_links_survive(ctx, make, tmp_path, att_dir):
    t = make("Déménagement")
    a = ctx.attachments.add(t.id, make_file(tmp_path))
    new = tmp_path / "Nouveau dossier"
    assert ctx.attachments.change_base(new) == 1
    assert ctx.attachments.exists(ctx.attachments.get(a.id))
    assert new in ctx.attachments.resolve(a).parents
    assert not any(att_dir.rglob("*.xlsx"))


def test_unsafe_names(ctx, make, tmp_path, att_dir):
    t = make('Tâche: "spéciale" <a/b>?')
    a = ctx.attachments.add(t.id, make_file(tmp_path))
    assert ctx.attachments.exists(a)
