import pytest
from fastapi.testclient import TestClient

from backend.api import app

CID = "C007938"  # Idosa, da persona do tutorial (tem historico)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Cliente com banco SQLite temporario e isolado por teste."""
    monkeypatch.setenv("KODIAK_DB", str(tmp_path / "app.db"))
    with TestClient(app) as c:
        yield c
