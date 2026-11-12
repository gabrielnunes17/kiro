import json
import sqlite3

from fastapi.testclient import TestClient

from backend import db
from backend.api import app
from backend.personas import PERSONAS
from tests.conftest import CID

PREFS_PADRAO = {"consentimento_saude": False, "usar_historico": True, "usar_perfil": True,
                "usar_bairro": True, "usar_sazonalidade": True}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_tabelas_criadas(client):
    con = sqlite3.connect(db.caminho_db())
    nomes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"preferencias", "pedidos", "pedido_eventos", "eventos_ux", "pesquisas"} <= nomes


def test_preferencias_padrao_e_gravacao(client):
    assert client.get(f"/cidadaos/{CID}/preferencias").json() == PREFS_PADRAO
    novo = {**PREFS_PADRAO, "usar_bairro": False}
    r = client.put(f"/cidadaos/{CID}/preferencias", json=novo)
    assert r.status_code == 200 and r.json() == novo
    assert client.get(f"/cidadaos/{CID}/preferencias").json() == novo


def test_preferencias_sobrevivem_a_reinicio(tmp_path, monkeypatch):
    monkeypatch.setenv("KODIAK_DB", str(tmp_path / "app.db"))
    novo = {**PREFS_PADRAO, "consentimento_saude": True}
    with TestClient(app) as c1:
        c1.put(f"/cidadaos/{CID}/preferencias", json=novo)
    with TestClient(app) as c2:  # nova instancia = reinicio da API
        assert c2.get(f"/cidadaos/{CID}/preferencias").json() == novo


def test_migracao_do_json_legado(tmp_path, monkeypatch):
    monkeypatch.setenv("KODIAK_DB", str(tmp_path / "app.db"))
    legado = tmp_path / "preferencias.json"
    legado.write_text(json.dumps({CID: {**PREFS_PADRAO, "usar_historico": False}}))
    monkeypatch.setattr(db, "ARQ_PREFS_LEGADO", legado)
    with TestClient(app) as c:
        assert c.get(f"/cidadaos/{CID}/preferencias").json()["usar_historico"] is False
    assert not legado.exists() and legado.with_suffix(".json.migrado").exists()


def test_put_cidadao_desconhecido_404_padronizado(client):
    r = client.put("/cidadaos/NAO_EXISTE/preferencias", json=PREFS_PADRAO)
    assert r.status_code == 404
    assert set(r.json()) == {"erro", "detalhe"} and r.json()["erro"] == "nao_encontrado"


def test_servico_inexistente_404_padronizado(client):
    r = client.get("/servicos/99999999")
    assert r.status_code == 404
    assert set(r.json()) == {"erro", "detalhe"}


def test_validacao_422_padronizada(client):
    r = client.put(f"/cidadaos/{CID}/preferencias", json={"usar_bairro": "talvez"})
    assert r.status_code == 422
    assert set(r.json()) == {"erro", "detalhe"} and r.json()["erro"] == "dados_invalidos"


def test_recomendacoes_cidadao_conhecido_e_anonimo(client):
    r = client.get(f"/cidadaos/{CID}/recomendacoes")
    assert r.status_code == 200 and r.json()["itens"]
    anon = client.get("/recomendacoes").json()
    assert anon["anonimo"] is True and anon["cidadao_id"] is None and anon["itens"]


def test_sem_consentimento_nenhum_motivo_cita_saude(client):
    # C059592 tem hipertensao; C036462 e C006566 sao gestantes (dados do tutorial).
    termos = ("gestan", "crônic", "cronic", "hipertens", "diabet", "saúde mental")
    for cid in ("C059592", "C036462", "C006566", "C062244"):
        r = client.get(f"/cidadaos/{cid}/recomendacoes").json()
        assert r["perfis_ativos"] and not {"gestante", "cronico", "saude_mental"} & set(r["perfis_ativos"])
        for i in r["itens"]:
            assert i["sinal_principal"] != "saude"
            assert "«" not in i["motivo"], i["motivo"]  # motivo nunca cita servico previo
            assert not any(t in i["motivo"].lower() for t in termos), i["motivo"]


def test_personas_existem_nos_dados(client):
    assert len(PERSONAS) == 8
    for p in PERSONAS:
        perfil = client.get(f"/cidadaos/{p['cidadao_id']}/perfil").json()
        assert perfil["anonimo"] is False, p["cidadao_id"]
