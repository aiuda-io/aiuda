"""Fixtures compartidas de los tests del server.

`demo_login`: reliquia de cuando el producto tenía login. En local no hay
sesiones: el API resuelve SU workspace (el tenant más antiguo, o el que diga
``settings.workspace_id``). El fixture conserva su firma para no tocar decenas
de tests: hoy "loguearse" = fijar ``settings.workspace_id`` al tenant marcado
``config={"demo": True}`` por el test. El autouse lo limpia entre tests.
"""

import pytest

from aiuda_server.api.main import app, get_db
from aiuda_core.config import settings
from aiuda_core.models import Tenant


@pytest.fixture(autouse=True)
def _reset_workspace():
    yield
    settings.workspace_id = ""


@pytest.fixture()
def demo_login():
    def _login(client, email=None):
        db = app.dependency_overrides[get_db]()
        tenant = next(
            (t for t in db.query(Tenant).all() if (t.config or {}).get("demo")),
            None,
        )
        assert tenant is not None, (
            "demo_login: no hay tenant marcado config={'demo': True} para activar"
        )
        settings.workspace_id = tenant.id
        return tenant

    return _login
