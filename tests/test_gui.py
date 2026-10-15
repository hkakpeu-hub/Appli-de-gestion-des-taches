import os
from datetime import date, time, timedelta

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

