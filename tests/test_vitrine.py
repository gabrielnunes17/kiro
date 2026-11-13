from backend.api import _estado
from backend.motor import Preferencias
from tests.conftest import CID

SECOES = ["descubra", "historico", "para_voce", "na_sua_regiao", "em_alta"]
RECOMENDADAS = ["descubra", "para_voce", "na_sua_regiao", "em_alta"]
CAMPOS_ITEM = {"servico_id", "nome", "orgao", "motivo", "sinal_principal", "tipo"}
ANON = "VISITANTE_ANONIMO"


def ids(v, secao):
    return [i["servico_id"] for i in v[secao]]


def todos_ids(v):
    return [i for s in SECOES for i in ids(v, s)]


def vitrine(client, cid=ANON, **params):
    # ANON usa a rota sem id; id desconhecido em /vitrine/{cid} devolve 404 (ver test_anonimo.py)
    r = client.get("/vitrine" if cid == ANON else f"/vitrine/{cid}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_estrutura_e_campos(client):
    v = vitrine(client, CID)
    assert [k for k in v if k in SECOES] == SECOES
    assert not {"layout", "secoes", "perfis_ativos", "preferencias"} & set(v)
    assert 1 <= len(v["para_voce"]) <= 5
    for s in SECOES:
        for i in v[s]:
            assert CAMPOS_ITEM <= set(i)


def test_descubra_nunca_vazio_e_sem_repeticao(client):
    for cid, p in [(CID, {}), (ANON, {}), (ANON, {"perfil_simulado": "pcd", "rpa": 2})]:
        v = vitrine(client, cid, **p)
        assert len(v["descubra"]) >= 1
        assert all(i["tipo"] == "descoberta" for i in v["descubra"])
        t = todos_ids(v)
        assert len(t) == len(set(t)), "servico repetido entre secoes"


def test_nao_sugere_servico_ja_usado(client):
    # C007938 usou 519, 1475 e 953 (tutorial)
    v = vitrine(client, CID)
    assert not {519, 1475, 953} & set(todos_ids(v))


def test_perfis_simulados_geram_vitrines_diferentes(client):
    v = {p: vitrine(client, ANON, perfil_simulado=p, rpa=3)
         for p in ("idoso", "empreendedor", "pcd", "familia")}
    para_voce = {p: tuple(ids(x, "para_voce")) for p, x in v.items()}
    assert len(set(para_voce.values())) == 4
    # coerencia: o servico ancora de cada perfil aparece na vitrine dele
    assert {908, 1428} & set(todos_ids(v["idoso"]))            # idoso
    assert {798, 222, 990} & set(todos_ids(v["empreendedor"]))  # alvara, CredPop, CNPJ
    assert {271, 1239, 1238} & set(todos_ids(v["pcd"]))         # credencial/passe PCD
    assert {352, 839} & set(todos_ids(v["familia"]))            # Cadastro Unico, matricula


def test_semana_muda_secao_sazonal(client):
    a = ids(vitrine(client, ANON, semana="2026-01-05"), "em_alta")
    b = ids(vitrine(client, ANON, semana="2026-07-06"), "em_alta")
    assert a and b and a != b


def test_visitante_sem_historico_recebe_vitrine_por_regiao_e_popularidade(client):
    v = vitrine(client, ANON, rpa=4)
    assert v["anonimo"] is True
    assert all(len(v[s]) >= 1 for s in RECOMENDADAS)
    assert v["historico"] == [] and v["avisos"] == {"historico": "sem_historico"}
    assert all("RPA 4" in i["motivo"] for i in v["na_sua_regiao"])


def test_regiao_desconhecida_ou_desligada(client):
    v = vitrine(client, ANON)
    assert v["na_sua_regiao"] == [] and v["avisos"]["na_sua_regiao"] == "regiao_desconhecida"
    prefs = {"consentimento_saude": False, "usar_historico": True, "usar_perfil": True,
             "usar_bairro": False, "usar_sazonalidade": False}
    assert client.put(f"/cidadaos/{CID}/preferencias", json=prefs).status_code == 200
    v = vitrine(client, CID)
    assert v["na_sua_regiao"] == [] and v["avisos"]["na_sua_regiao"] == "regiao_desligada"
    assert v["em_alta"] == []
    assert v["avisos"]["em_alta"] == "sazonalidade_desligada"
    assert len(v["para_voce"]) >= 1


def test_perfil_desligado_ignora_perfil_simulado(client):
    prefs = {"consentimento_saude": False, "usar_historico": True, "usar_perfil": False,
             "usar_bairro": True, "usar_sazonalidade": True}
    client.put(f"/cidadaos/{CID}/preferencias", json=prefs)
    v = vitrine(client, CID, perfil_simulado="pcd")
    assert v["perfil"]["tipo"] == "geral"


def test_parametros_invalidos_422(client):
    assert client.get(f"/vitrine/{CID}", params={"perfil_simulado": "alien"}).status_code == 422
    assert client.get(f"/vitrine/{CID}", params={"rpa": 7}).status_code == 422
    r = client.get(f"/vitrine/{CID}", params={"semana": "ontem"})
    assert r.status_code == 422 and set(r.json()) == {"erro", "detalhe"}


def test_recomendacoes_com_perfil_simulado_e_rpa(client):
    r = client.get("/recomendacoes", params={"perfil_simulado": "empreendedor", "rpa": 6})
    assert r.status_code == 200
    j = r.json()
    assert j["perfil_simulado"] == "empreendedor" and j["perfis_ativos"] == ["empreendedor"]
    assert {798, 222, 990} & {i["servico_id"] for i in j["itens"]}
    assert {"perfis_ativos", "data_referencia", "itens"} <= set(j)


def test_motivos_nao_citam_servico_previo(client):
    for p in ("idoso", "familia"):
        v = vitrine(client, CID, perfil_simulado=p)
        assert all("«" not in i["motivo"] for s in RECOMENDADAS for i in v[s])


def test_historico_traz_o_que_o_cidadao_ja_usou(client):
    # o historico de CID e todo de saude: so aparece com consentimento
    assert vitrine(client, CID)["historico"] == []
    prefs = {"consentimento_saude": True, "usar_historico": True, "usar_perfil": True,
             "usar_bairro": True, "usar_sazonalidade": True}
    client.put(f"/cidadaos/{CID}/preferencias", json=prefs)
    v = vitrine(client, CID)
    h = ids(v, "historico")
    assert set(h) == {519, 1475, 953} and len(h) == len(set(h)) <= 5
    assert [i["posicao"] for i in v["historico"]] == list(range(1, len(h) + 1))
    assert all(i["tipo"] == "historico" and i["novo"] is False for i in v["historico"])
    assert "historico" not in v["avisos"]
    # nada do historico reaparece nas outras secoes
    assert not set(h) & {i for s in RECOMENDADAS for i in ids(v, s)}


def test_historico_desligado_ou_visitante_vem_vazio_com_aviso(client):
    prefs = {"consentimento_saude": False, "usar_historico": False, "usar_perfil": True,
             "usar_bairro": True, "usar_sazonalidade": True}
    client.put(f"/cidadaos/{CID}/preferencias", json=prefs)
    v = vitrine(client, CID)
    assert v["historico"] == [] and v["avisos"]["historico"] == "historico_desligado"
    assert vitrine(client, ANON)["avisos"]["historico"] == "sem_historico"


def test_historico_sem_saude_sem_consentimento(client):
    m = _estado["motor"]
    for cid in list(m.hist)[:300]:
        for i in m.historico(cid, Preferencias(), limite=50):
            assert not i["tema"].startswith("Saúde"), cid
