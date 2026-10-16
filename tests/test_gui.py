import os
from datetime import date, time, timedelta
from pathlib import Path

from PySide6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from suivi.core.models import TaskInput  # noqa: E402
from suivi.core.quickadd import parse_quick  # noqa: E402
from suivi.core.models import ValidationError  # noqa: E402

TODAY = date(2026, 10, 13)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    from suivi.ui.theme import STYLESHEET
    app.setStyleSheet(STYLESHEET)
    return app


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """Un dialogue modal bloquerait les tests : on le transforme en erreur visible."""
    from PySide6.QtWidgets import QMessageBox

    def boom(*a, **k):
        raise RuntimeError(f"Dialogue inattendu : {a[1:3] if len(a) > 2 else a}")

    for name in ("warning", "critical", "information", "question", "exec"):
        monkeypatch.setattr(QMessageBox, name, boom)


@pytest.fixture
def window(qapp, ctx):
    from suivi.ui.main_window import MainWindow
    for i in range(6):
        ctx.tasks.create(TaskInput(title=f"Tâche {i}", project_name=f"P{i % 3}", deadline=TODAY + timedelta(days=i),
                                   start_date=TODAY, start_time=time(9 + i, 0), end_time=time(10 + i, 0)))
    w = MainWindow(ctx)
    w.tray.hide()
    w.show()
    w.enter_space(1)
    qapp.processEvents()
    yield w
    w._quitting = True
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_all_pages_render(window, qapp):
    for key in window.pages:
        window.go(key)
        qapp.processEvents()
        assert window.pages[key].isVisible() or key == "ai"
    assert window.stack.count() == 10


def test_dashboard_updates_immediately_after_creation(window, qapp, ctx):
    window.go("dashboard")
    dash = window.pages["dashboard"]
    before = int(dash.kpis["total"].value.text())
    ctx.tasks.create(TaskInput(title="Nouvelle", deadline=TODAY - timedelta(days=1)))
    qapp.processEvents()
    import time as _t
    _t.sleep(0.1)
    qapp.processEvents()
    assert int(dash.kpis["total"].value.text()) == before + 1
    assert int(dash.kpis["overdue"].value.text()) >= 1


def test_quick_add_and_alert_badge(window, qapp, ctx):
    window.quick.setText("Relancer Donald #Centaures !demain @Hermann")
    window.quick_add()
    t = [x for x in ctx.tasks.all() if x.title == "Relancer Donald"][0]
    assert t.project_name == "Centaures" and t.assignee == "Hermann" and t.deadline == TODAY + timedelta(days=1)


def test_tasks_page_filters_and_search(window, qapp, ctx):
    page = window.pages["tasks"]
    window.go("tasks")
    page.reload()
    assert len(page.table.model_.tasks) == 6
    page.search.setText("tâche 3")
    page.reload()
    assert [t.title for t in page.table.model_.tasks] == ["Tâche 3"]
    page.reset_filters()
    ctx.tasks.create(TaskInput(title="Vieille", deadline=TODAY - timedelta(days=4)))
    page.set_view("overdue")
    assert [t.title for t in page.table.model_.tasks] == ["Vieille"]
    window.go("today")
    window.pages["today"].reload()


def test_planning_blocks(window, qapp):
    window.go("planning")
    plan = window.pages["planning"]
    plan.set_anchor(TODAY)
    qapp.processEvents()
    assert sum(len(b) for b in plan.grid.blocks.values()) == 6


def test_quickadd_parser():
    d = parse_quick("Faire le CR #Mon_Projet !25/12 @Adama", TODAY)
    assert (d.title, d.project_name, d.assignee, d.deadline) == ("Faire le CR", "Mon Projet", "Adama", date(2026, 12, 25))
    assert parse_quick("X !+3j", TODAY).deadline == TODAY + timedelta(days=3)
    with pytest.raises(ValidationError):
        parse_quick("#seulement", TODAY)
    with pytest.raises(ValidationError):
        parse_quick("X !nimportequoi", TODAY)



def test_home_page_and_space_switching(window, qapp, ctx):
    window.go_home()
    qapp.processEvents()
    assert window.root_stack.currentWidget() is window.home
    assert window.home.grid1.count() - 1 == 3  # Travail, Personnel, Kingdom (+ tuile « Nouvel espace »)
    perso = ctx.spaces.by_name("Personnel")
    window.enter_space(perso.id)
    qapp.processEvents()
    assert window.root_stack.currentIndex() == 1
    assert int(window.pages["dashboard"].kpis["total"].value.text()) == 0  # l'espace Personnel est vide
    window.quick.setText("Appeler le plombier")
    window.quick_add()
    assert [t.title for t in ctx.tasks.all()] == ["Appeler le plombier"]
    window.enter_space(1)
    qapp.processEvents()
    assert int(window.pages["dashboard"].kpis["total"].value.text()) == 6
    # un espace désactivé disparaît de l'accueil
    ctx.spaces.set_enabled(ctx.spaces.by_name("Kingdom").id, False)
    window.go_home()
    qapp.processEvents()
    assert window.home.grid1.count() - 1 == 2


def test_archive_project_from_projects_page(window, qapp, ctx, monkeypatch):
    import suivi.ui.projects_page as pp
    monkeypatch.setattr(pp, "confirm", lambda *a, **k: True)
    window.go("projects")
    page = window.pages["projects"]
    page.refresh()
    names = [ctx.projects.get(i).name for i in page._ids]
    page.table.setCurrentCell(names.index("P0"), 0)
    page.toggle_archive()
    qapp.processEvents()
    assert all(t.project_name != "P0" for t in ctx.tasks.all())
    window.go("dashboard")
    dash = window.pages["dashboard"]
    dash.refresh()
    assert int(dash.kpis["total"].value.text()) == 4  # 6 tâches - 2 du projet archivé


def test_task_dialog_attachments(window, qapp, ctx, tmp_path, monkeypatch):
    from suivi.ui.task_dialog import TaskDialog
    ctx.settings.set("attachments_dir", str(tmp_path / "PJ"))
    f = tmp_path / "devis.pdf"
    f.write_bytes(b"%PDF-1.4 test")
    t = ctx.tasks.all()[0]
    dlg = TaskDialog(ctx, t.id)
    dlg._att_add_files([str(f)])
    assert dlg.att_list.count() == 1 and ctx.tasks.get(t.id).n_attach == 1
    opened = []
    import suivi.osutils as osu
    monkeypatch.setattr(osu, "open_path", lambda p: opened.append(Path(p)))
    monkeypatch.setattr(osu, "reveal_in_explorer", lambda p: opened.append(("reveal", Path(p))))
    dlg.att_list.setCurrentRow(0)
    dlg._att_open()
    dlg._att_reveal()
    assert opened[0].read_bytes() == b"%PDF-1.4 test" and opened[1][0] == "reveal"
    # nouvelle tâche : les fichiers sont joints à l'enregistrement
    new = TaskDialog(ctx, None)
    new.title.setText("Avec pièce jointe")
    new._att_add_files([str(f)])
    assert new.pending and ctx.tasks.count() == 6
    new._save()
    created = [x for x in ctx.tasks.all() if x.title == "Avec pièce jointe"][0]
    assert created.n_attach == 1

def test_calendar_marks_today_with_red_circle(window, qapp):
    window.go("planning")
    plan = window.pages["planning"]
    plan.set_anchor(TODAY)
    qapp.processEvents()
    img = plan.cal.grab().toImage()
    reds = sum(1 for x in range(img.width()) for y in range(img.height())
               if (c := img.pixelColor(x, y)).red() > 200 and c.green() < 80 and 40 < c.blue() < 130)
    assert reds > 40, "le cercle rouge d'aujourd'hui doit être dessiné"
    assert plan.cal.TODAY_COLOR.red() > 200


def test_recurrence_dialog_creates_weekly_sunday_event(window, qapp, ctx):
    from datetime import time as t
    from suivi.ui.recurrence_dialog import RecurrenceDialog, RecurrenceManager
    dlg = RecurrenceDialog(ctx, None, {"start_date": date(2026, 10, 18)})
    dlg.title.setText("Culte")
    dlg.start_time.set_value(t(7, 0))
    dlg.end_time.set_value(t(11, 0))
    assert [cb.isChecked() for cb in dlg.day_checks] == [False] * 6 + [True]
    assert "dimanche" in dlg.summary.text() and "07:00" in dlg.summary.text()
    dlg._save()
    series = ctx.recurrences.list()
    assert len(series) == 1 and series[0].title == "Culte"
    sundays = [x for x in ctx.tasks.all() if x.series_id]
    assert sundays and all(x.start_date.weekday() == 6 and x.end_time == t(11, 0) for x in sundays)
    mgr = RecurrenceManager(ctx)
    assert mgr.table.rowCount() == 1 and "dimanche" in mgr.table.item(0, 2).text()
    window.go("planning")
    plan = window.pages["planning"]
    plan.set_anchor(date(2026, 10, 18))
    qapp.processEvents()
    blocks = plan.grid.blocks[date(2026, 10, 18)]
    assert [b.task.title for b in blocks] == ["Culte"] and blocks[0].minutes == 240  # dimanche 7 h – 11 h dans le planning

def _culte_event_series(ctx):
    from datetime import time as t
    from suivi.core.models import EventTemplate
    from suivi.core.recurrence import RecurrenceInput
    return ctx.recurrences.create(RecurrenceInput(
        title="Culte", kind="event", freq="weekly", weekdays=[6], start_date=date(2026, 10, 18), start_time=t(7), end_time=t(11),
        templates=[EventTemplate("Chanter"), EventTemplate("Danser"), EventTemplate("Prier"), EventTemplate("Lecture biblique")]))


def test_events_dashboard_section_does_not_change_task_kpis(window, qapp, ctx):
    window.go("dashboard")
    dash = window.pages["dashboard"]
    dash.refresh()
    before = {k: dash.kpis[k].value.text() for k in dash.kpis}
    _culte_event_series(ctx)
    qapp.processEvents()
    dash.refresh()
    after = {k: dash.kpis[k].value.text() for k in dash.kpis}
    # seules les 4 tâches modèles de chaque culte (échéance = date du culte) peuvent changer les compteurs, jamais l'événement lui-même
    assert int(after["total"]) - int(before["total"]) == len([x for x in ctx.tasks.all() if x.event_id])
    assert dash.ev_list.count() >= 1 and "Culte" in dash.ev_list.item(0).text() and "0/4" in dash.ev_list.item(0).text()
    assert "Événements à venir" in dash.ev_card.title_label.text()


def test_event_dialog_links_tasks_and_progress(window, qapp, ctx, make):
    from suivi.ui.event_dialog import EventDialog
    _culte_event_series(ctx)
    ev = ctx.events.list()[0]
    dlg = EventDialog(ctx, ev.id)
    assert dlg.table.rowCount() == 4 and dlg.progress_label.text() == "0 / 4 faite(s)"
    dlg.table.item(0, 0).setCheckState(Qt.Checked)  # coche « Chanter » (ou la 1re ligne)
    assert dlg.progress_label.text() == "1 / 4 faite(s)" and ctx.events.get(ev.id).n_done == 1
    dlg.quick.setText("Accueil @Paul")
    dlg._quick_add()
    assert dlg.table.rowCount() == 5 and any(t.assignee == "Paul" for t in ctx.events.linked_tasks(ev.id))
    extra = make("Imprimer les chants")
    ctx.events.link(extra.id, ev.id)
    dlg._refresh_tasks()
    assert dlg.table.rowCount() == 6
    dlg.table.setCurrentCell(5, 1)
    dlg._detach()
    assert dlg.table.rowCount() == 5


def test_task_dialog_event_combo_and_marker(window, qapp, ctx):
    from suivi.ui.task_dialog import TaskDialog
    _culte_event_series(ctx)
    ev = ctx.events.list()[0]
    dlg = TaskDialog(ctx, None)
    dlg.title.setText("Préparer les chants")
    dlg.event_combo.setCurrentIndex(dlg.event_combo.findData(ev.id))
    assert dlg.deadline.value() == ev.date  # date reprise de l'événement
    dlg._save()
    t = [x for x in ctx.tasks.all() if x.title == "Préparer les chants"][0]
    assert t.event_id == ev.id and t.event_title == "Culte"
    window.go("tasks")
    page = window.pages["tasks"]
    page.reload()
    row = [x.title for x in page.table.model_.tasks].index("Préparer les chants")
    assert "🗓" in page.table.model_.data(page.table.model_.index(row, 1))


def test_event_dialog_creates_one_off_with_tasks_and_planning_shows_event(window, qapp, ctx):
    from datetime import time as t
    from suivi.ui.recurrence_dialog import RecurrenceDialog
    dlg = RecurrenceDialog(ctx, None, {"start_date": date(2026, 10, 18), "start_time": t(7), "end_time": t(11)}, "event")
    assert dlg.freq.currentData() == "once"
    dlg.title.setText("Baptême")
    dlg._tpl_add("Préparer le bassin", "Paul", 1)
    dlg._save()
    assert ctx.recurrences.list() == [] and [e.title for e in ctx.events.list()] == ["Baptême"]  # événement unique : pas de série
    assert [x.title for x in ctx.tasks.all() if x.event_id] == ["Préparer le bassin"]
    window.go("planning")
    plan = window.pages["planning"]
    plan.set_anchor(date(2026, 10, 18))
    qapp.processEvents()
    assert [b.event.title for b in plan.grid.eblocks[date(2026, 10, 18)]] == ["Baptême"]
    assert plan.ev_list.item(0).text().startswith("🗓")

def test_event_dialog_task_weeks_parameter_defaults_to_one(window, qapp, ctx):
    from datetime import time as t
    from suivi.ui.recurrence_dialog import RecurrenceDialog
    dlg = RecurrenceDialog(ctx, None, {"start_date": date(2026, 10, 18), "start_time": t(7), "end_time": t(11)}, "event")
    dlg.freq.setCurrentIndex(dlg.freq.findData("weekly"))
    assert dlg.task_weeks.value() == 1  # une semaine par défaut
    dlg.title.setText("Culte")
    dlg._tpl_add("Chanter"); dlg._tpl_add("Prier")
    dlg.task_weeks.setValue(2)
    dlg._save()
    assert ctx.recurrences.list()[0].task_weeks == 2
    edit = RecurrenceDialog(ctx, ctx.recurrences.list()[0].id)
    assert edit.task_weeks.value() == 2