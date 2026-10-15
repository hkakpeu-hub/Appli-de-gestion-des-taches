import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from suivi.context import AppContext  # noqa: E402
from suivi.core.models import TaskInput  # noqa: E402


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 13, 9, 0))


@pytest.fixture
def ctx(tmp_path, clock):
    c = AppContext(tmp_path / "t.db", tmp_path / "bk", clock)
    yield c
    c.close()


@pytest.fixture
def make(ctx):
    def _make(title="Tâche", **kw):
        kind = kw.pop("kind", None)
        data = TaskInput(title=title, **kw)
        if kind:
            data.status_id = ctx.statuses.first_of_kind(kind).id
        return ctx.tasks.create(data)

    return _make
