import sqlite3

import pytest

from backend import db
from tests.conftest import CID

DESCONHECIDO = "NAO_EXISTE"

ROTAS_COM_ID = [
    "/vitrine/{}", "/cidadaos/{}/recomendacoes", "/cidadaos/{}/perfil", "/cidadaos/{}/tipo-perfil",
    "/cidadaos/{}/preferencias", "/cidadaos/{}/pedidos",
]


@pytest.mark.parametrize("rota", ROTAS_COM_ID)
def test_id_fora_do_cadastro_devolve_404_padronizado(client, rota):
    r = client.get(rota.format(DESCONHECIDO))
    assert r.status_code == 404
    assert r.json() == {"erro": "nao_encontrado", "detalhe": "Cidadão não encontrado"}


def test_id_com_espaco_ou_vazio_nao_vira_anonimo(client):
    assert client.get("/vitrine/%20").status_code == 404
    assert client.get("/vitrine/null").status_code == 404
    assert client.get("/vitrine/anonimo").status_code == 404


def test_cidadao_cadastrado_continua_200(client):
    for rota in ROTAS_COM_ID:
        assert client.get(rota.format(CID)).status_code == 200, rota


def test_vitrine_anonima_sem_id(client):
    r = client.get("/vitrine")
    assert r.status_code == 200
    v = r.json()
    assert v["anonimo"] is True and v["cidadao_id"] is None
    assert v["perfil"]["tipo"] == "geral" and v["perfil"]["momento"] == "novo"
    assert v["layout"] and v["layout"][0]["titulo"] == "Comece por aqui"
    assert v["avisos"]["na_sua_regiao"] == "regiao_desconhecida"
    ids = [i["servico_id"] for s in v["layout"] for i in s["itens"]]
    assert len(ids) == len(set(ids))


def test_vitrine_anonima_com_regiao_e_perfil_simulado(client):
    v = client.get("/vitrine", params={"rpa": 3, "perfil_simulado": "empreendedor"}).json()
    assert v["perfil"]["tipo"] == "empreendedor" and v["perfil"]["origem"] == "simulado"
    ids = [s["id"] for s in v["layout"]]
    assert "na_sua_regiao" in ids and "para_o_seu_negocio" in ids
    assert all("RPA 3" in i["motivo"] for s in v["layout"] if s["id"] == "na_sua_regiao" for i in s["itens"])


def test_vitrine_anonima_preferencias_por_parametro(client):
    v = client.get("/vitrine", params={"rpa": 3, "perfil_simulado": "pcd", "usar_perfil": False,
                                       "usar_bairro": False, "usar_sazonalidade": False}).json()
    assert v["perfil"]["tipo"] == "geral" and v["perfis_ativos"] == []
    ids = [s["id"] for s in v["layout"]]
    assert "na_sua_regiao" not in ids and "em_alta_nesta_epoca" not in ids
    assert v["avisos"]["na_sua_regiao"] == "regiao_desligada"
    assert v["preferencias"]["usar_bairro"] is False


def test_vitrine_anonima_valida_parametros(client):
    assert client.get("/vitrine", params={"rpa": 9}).status_code == 422
    assert client.get("/vitrine", params={"perfil_simulado": "alien"}).status_code == 422
    assert client.get("/vitrine", params={"usar_bairro": "talvez"}).status_code == 422


def test_recomendacoes_anonimas(client):
    r = client.get("/recomendacoes", params={"limite": 5, "rpa": 2})
    assert r.status_code == 200
    j = r.json()
    assert j["anonimo"] is True and j["cidadao_id"] is None and len(j["itens"]) == 5
    assert client.get("/recomendacoes", params={"limite": 11}).status_code == 422


def test_anonimo_nao_grava_nada_no_servidor(client):
    client.get("/vitrine", params={"rpa": 3})
    client.get("/recomendacoes")
    con = sqlite3.connect(db.caminho_db())
    n = [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ("preferencias", "pedidos", "eventos_ux", "pesquisas")]
    con.close()
    assert n == [0, 0, 0, 0]


def test_anonimo_nao_herda_estado_de_nenhum_cidadao(client):
    # preferencias e pedidos de um cidadao nao vazam para a rota anonima
    client.put(f"/cidadaos/{CID}/preferencias", json={
        "consentimento_saude": True, "usar_historico": False, "usar_perfil": False,
        "usar_bairro": False, "usar_sazonalidade": False})
    client.post("/pedidos", json={"cidadao_id": CID, "servico_id": 953})
    v = client.get("/vitrine", params={"rpa": 3}).json()
    assert v["preferencias"] == {"consentimento_saude": False, "usar_historico": True, "usar_perfil": True,
                                 "usar_bairro": True, "usar_sazonalidade": True}
    assert v["perfil"]["momento"] == "novo"
    assert all(s["tipo_secao"] == "recomendacao" for s in v["layout"])


def test_swagger_lista_rotas_anonimas_e_404(client):
    spec = client.get("/openapi.json").json()
    assert "get" in spec["paths"]["/vitrine"] and "get" in spec["paths"]["/recomendacoes"]
    assert "404" in spec["paths"]["/vitrine/{cid}"]["get"]["responses"]
    assert "404" in spec["paths"]["/cidadaos/{cid}/preferencias"]["get"]["responses"]
    props = spec["components"]["schemas"]["VitrineOut"]["properties"]
    assert "anyOf" in props["cidadao_id"]  # aceita null
