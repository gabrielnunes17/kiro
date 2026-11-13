import sqlite3

from backend import db
from tests.conftest import CID

EMP = "C068579"
SECOES = ["descubra", "historico", "para_voce", "na_sua_regiao", "em_alta"]


def registrar(client, cid, sid):
    return client.post(f"/cidadaos/{cid}/historico", json={"servico_id": sid})


def prefs_put(client, cid, **kw):
    base = {"consentimento_saude": False, "usar_historico": True, "usar_perfil": True,
            "usar_bairro": True, "usar_sazonalidade": True}
    assert client.put(f"/cidadaos/{cid}/preferencias", json={**base, **kw}).status_code == 200


def test_acesso_aparece_no_topo_do_historico_e_sai_das_recomendacoes(client):
    antes = client.get(f"/vitrine/{EMP}").json()
    # servico de saude nao entra no historico sem consentimento (ver teste proprio)
    alvo = next(i["servico_id"] for i in antes["para_voce"] if not i["tema"].startswith("Saúde"))
    r = registrar(client, EMP, alvo)
    assert r.status_code == 201
    j = r.json()
    assert j["salvo"] is True and j["servico_id"] == alvo and j["acessado_em"]

    v = client.get(f"/vitrine/{EMP}").json()
    assert v["historico"][0]["servico_id"] == alvo
    assert v["historico"][0]["tipo"] == "historico" and v["historico"][0]["posicao"] == 1
    outros = [i["servico_id"] for s in SECOES if s != "historico" for i in v[s]]
    assert alvo not in outros
    todos = [i["servico_id"] for s in SECOES for i in v[s]]
    assert len(todos) == len(set(todos))


def test_acesso_repetido_nao_duplica_e_volta_ao_topo(client):
    a, b = 798, 222
    registrar(client, EMP, a)
    registrar(client, EMP, b)
    h = [i["servico_id"] for i in client.get(f"/vitrine/{EMP}").json()["historico"]]
    assert h[:2] == [b, a]
    registrar(client, EMP, a)
    h = [i["servico_id"] for i in client.get(f"/vitrine/{EMP}").json()["historico"]]
    assert h[:2] == [a, b] and h.count(a) == 1


def test_cidadao_sem_historico_na_base_passa_a_ter(client):
    # CID so tem servicos de saude na base: sem consentimento, o historico comeca vazio
    assert client.get(f"/vitrine/{CID}").json()["historico"] == []
    registrar(client, CID, 798)
    v = client.get(f"/vitrine/{CID}").json()
    assert [i["servico_id"] for i in v["historico"]] == [798]
    assert "historico" not in v["avisos"]


def test_usar_historico_desligado_nao_grava(client):
    prefs_put(client, EMP, usar_historico=False)
    r = registrar(client, EMP, 798)
    assert r.status_code == 200 and r.json()["salvo"] is False and r.json()["acessado_em"] is None
    con = sqlite3.connect(db.caminho_db())
    assert con.execute("SELECT COUNT(*) FROM acessos").fetchone()[0] == 0
    con.close()


def test_acesso_de_saude_so_aparece_com_consentimento(client):
    registrar(client, EMP, 519)  # resultado de exames (Saude)
    v = client.get(f"/vitrine/{EMP}").json()
    assert 519 not in [i["servico_id"] for s in SECOES for i in v[s]]  # nem no historico, nem sugerido
    prefs_put(client, EMP, consentimento_saude=True)
    assert client.get(f"/vitrine/{EMP}").json()["historico"][0]["servico_id"] == 519


def test_erros_404_e_422(client):
    assert registrar(client, "NAO_EXISTE", 798).status_code == 404
    assert registrar(client, EMP, 999999).status_code == 404
    assert client.post(f"/cidadaos/{EMP}/historico", json={}).status_code == 422
    assert client.post(f"/cidadaos/{EMP}/historico", json={"servico_id": "x"}).status_code == 422


def test_swagger_documenta_rota(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"]["/cidadaos/{cid}/historico"]["post"]
    assert {"200", "201", "404", "422"} <= set(op["responses"])
    assert "example" in spec["components"]["schemas"]["AcessoOut"]
