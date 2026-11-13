import numpy as np
import pytest

from backend import perfil as pf
from backend.api import _estado
from backend.motor import Preferencias
from tests.conftest import CID

EMP = "C068579"    # empreendedora
PCD = "C059592"    # PcD e idosa (63 anos)
FAM = "C039227"    # Cadastro Unico / Bolsa Familia
JOV = "C036462"    # jovem estudante
SID = 953


def tipo_perfil(client, cid, **params):
    r = client.get(f"/cidadaos/{cid}/tipo-perfil", params=params)
    assert r.status_code == 200, r.text
    return r.json()


SECOES = ["descubra", "historico", "para_voce", "na_sua_regiao", "em_alta"]


def itens_da_vitrine(v):
    return [i for s in SECOES for i in v[s]]


def prefs_put(client, cid, **kw):
    base = {"consentimento_saude": False, "usar_historico": True, "usar_perfil": True,
            "usar_bairro": True, "usar_sazonalidade": True}
    assert client.put(f"/cidadaos/{cid}/preferencias", json={**base, **kw}).status_code == 200


# ------------------------------------------------------------ tipo de perfil
@pytest.mark.parametrize("cid,esperado", [
    (CID, "idoso"), (EMP, "empreendedor"), (PCD, "pcd"), (JOV, "jovem_estudante"),
    (FAM, "familia"), ("C076260", "familia"), ("C006566", "familia"), ("C062244", "idoso")])
def test_tipo_base_das_personas(client, cid, esperado):
    p = tipo_perfil(client, cid)
    assert p["tipo_base"] == esperado
    assert p["tipo"] in {esperado, *[i["tipo"] for i in p["inferidos"]]}


def test_prioridade_com_varios_tipos_do_cadastro(client):
    p = tipo_perfil(client, PCD)
    assert p["tipo"] == "pcd" and "idoso" in p["secundarios"]


def test_visitante_e_geral_e_novo(client):
    p = client.get("/vitrine").json()["perfil"]
    assert (p["tipo"], p["momento"], p["origem"], p["confianca"]) == ("geral", "novo", "padrao", 0.0)
    assert p["maturidade_digital"] is None and p["temas_foco"] == []


def test_usar_perfil_desligado_vira_geral(client):
    prefs_put(client, EMP, usar_perfil=False)
    p = tipo_perfil(client, EMP)
    assert p["tipo"] == "geral" and p["inferidos"] == [] and p["secundarios"] == []


def test_perfil_simulado_e_momento_forcado(client):
    p = tipo_perfil(client, CID, perfil_simulado="empreendedor", momento="recorrente")
    assert p["tipo"] == "empreendedor" and p["origem"] == "simulado" and p["momento"] == "recorrente"
    assert client.get(f"/cidadaos/{EMP}/tipo-perfil", params={"momento": "x"}).status_code == 422


# ------------------------------------------------------ inferencia por historico
def _servicos_do_tipo(tipo, n):
    an = _estado["analisador"]
    return np.flatnonzero(an.mask[tipo] & ~an.saude)[:n]


def test_historico_infere_tipo_e_pode_superar_o_cadastro(client, monkeypatch):
    an, m = _estado["analisador"], _estado["motor"]
    idx = _servicos_do_tipo("empreendedor", 6)
    monkeypatch.setitem(m.hist, CID, (idx, np.ones(len(idx))))  # cadastro: idosa
    p = an.definir(CID, Preferencias())
    assert p.tipo_base == "idoso"
    assert any(i["tipo"] == "empreendedor" for i in p.inferidos)
    assert p.tipo == "empreendedor" and p.origem == "comportamento"
    assert "empreendedor" in p.tags_inferidas
    # usar_historico desligado: sem inferencia, volta ao cadastro
    q = an.definir(CID, Preferencias(usar_historico=False))
    assert q.inferidos == [] and q.tipo == "idoso" and q.momento == "novo"
    # usar_perfil desligado: geral
    assert an.definir(CID, Preferencias(usar_perfil=False)).tipo == "geral"


def test_historico_pouco_nao_infere(client, monkeypatch):
    an, m = _estado["analisador"], _estado["motor"]
    idx = _servicos_do_tipo("empreendedor", 2)
    monkeypatch.setitem(m.hist, CID, (idx, np.ones(len(idx))))
    assert an.definir(CID, Preferencias()).inferidos == []


def test_saude_fora_da_analise_sem_consentimento(client, monkeypatch):
    an, m = _estado["analisador"], _estado["motor"]
    saude = np.flatnonzero(an.saude)[:8]
    monkeypatch.setitem(m.hist, CID, (saude, np.ones(len(saude))))
    sem = an.definir(CID, Preferencias())
    assert sem.temas_foco == [] and sem.maturidade_digital is None and sem.inferidos == []
    # a quantidade de acessos ainda define o momento, sem revelar conteudo
    assert sem.momento == "explorador"
    com = an.definir(CID, Preferencias(consentimento_saude=True))
    assert com.temas_foco and com.temas_foco[0].startswith("Saúde")


def test_momentos_pelo_historico(client, monkeypatch):
    an, m = _estado["analisador"], _estado["motor"]
    mesmo_tema = [i for i in range(m.n) if m.tema1[i] == "Cidadania"][:6]
    monkeypatch.setitem(m.hist, CID, (np.array(mesmo_tema), np.ones(6)))
    assert an.definir(CID, Preferencias()).momento == "recorrente"
    variados, vistos = [], set()
    for i in range(m.n):
        if m.tema1[i] and m.tema1[i] not in vistos and not an.saude[i]:
            vistos.add(m.tema1[i])
            variados.append(i)
        if len(variados) == 6:
            break
    monkeypatch.setitem(m.hist, CID, (np.array(variados), np.ones(6)))
    assert an.definir(CID, Preferencias()).momento == "explorador"
    monkeypatch.setitem(m.hist, CID, (np.array(variados[:2]), np.ones(2)))
    assert an.definir(CID, Preferencias()).momento == "novo"


# ----------------------------------------------------------- vitrine adaptada
def test_vitrine_traz_perfil_ui_e_cinco_secoes(client):
    v = client.get(f"/vitrine/{EMP}").json()
    assert v["perfil"]["tipo"] == "empreendedor"
    assert set(v["ui"]) == {"densidade", "texto_simples"}
    assert set(SECOES) | {"avisos"} <= set(v)
    assert not {"layout", "secoes"} & set(v)


def test_vitrine_sem_repeticao_e_sem_servico_ja_usado_fora_do_historico(client):
    m = _estado["motor"]
    for cid in (CID, EMP, PCD, FAM, JOV):
        v = client.get(f"/vitrine/{cid}").json()
        ids = [i["servico_id"] for i in itens_da_vitrine(v)]
        assert len(ids) == len(set(ids)), cid
        if cid in m.hist:
            usados = {int(m.ids[i]) for i in m.hist[cid][0]}
            recomendados = {i["servico_id"] for s in SECOES if s != "historico" for i in v[s]}
            assert not usados & recomendados, cid
            assert {i["servico_id"] for i in v["historico"]} <= usados, cid


def test_vitrine_muda_conforme_o_tipo(client):
    para_voce = {}
    for tipo in ("idoso", "empreendedor", "pcd", "familia", "jovem_estudante"):
        v = client.get(f"/vitrine/{EMP}", params={"perfil_simulado": tipo, "momento": "recorrente"}).json()
        para_voce[tipo] = tuple(i["servico_id"] for i in v["para_voce"])
        assert v["perfil"]["tipo"] == tipo
    assert len(set(para_voce.values())) == 5


def test_idoso_tem_vitrine_simplificada(client):
    v = client.get(f"/vitrine/{CID}", params={"perfil_simulado": "idoso", "momento": "recorrente"}).json()
    assert v["ui"] == {"densidade": "baixa", "texto_simples": True}
    assert len(v["para_voce"]) <= 4 and len(v["descubra"]) <= 1 and len(v["historico"]) <= 3
    base = client.get(f"/vitrine/{CID}", params={"perfil_simulado": "empreendedor",
                                                 "momento": "recorrente"}).json()
    assert base["ui"]["texto_simples"] is False


def test_momento_novo_prioriza_descoberta(client):
    novo = client.get("/vitrine", params={"momento": "novo", "rpa": 3}).json()
    rec = client.get("/vitrine", params={"momento": "recorrente", "rpa": 3}).json()
    assert len(novo["descubra"]) > len(rec["descubra"])
    assert len(novo["para_voce"]) < len(rec["para_voce"])


def test_preferencias_desligadas_esvaziam_secoes(client):
    prefs_put(client, EMP, usar_bairro=False, usar_sazonalidade=False)
    v = client.get(f"/vitrine/{EMP}").json()
    assert v["na_sua_regiao"] == [] and v["em_alta"] == []
    assert v["avisos"]["na_sua_regiao"] == "regiao_desligada"
    assert v["avisos"]["em_alta"] == "sazonalidade_desligada"


# ------------------------------------------------------------ pedidos (retomada)
def test_pedido_em_andamento_nao_volta_como_recomendacao(client):
    r = client.post("/pedidos", json={"cidadao_id": EMP, "servico_id": SID})
    pid = r.json()["id"]
    client.patch(f"/pedidos/{pid}", json={"ultimo_passo": 2})
    assert tipo_perfil(client, EMP)["momento"] == "retomada"
    v = client.get(f"/vitrine/{EMP}").json()
    assert v["perfil"]["momento"] == "retomada"
    assert SID not in [i["servico_id"] for i in itens_da_vitrine(v)]


# ------------------------------------------------------------------- feedback
def test_fator_feedback_limites():
    f = pf.fator_feedback(
        [(1, "abandono", 10), (2, "clique", 10), (3, "visualizacao", 5), (4, "conclusao", 5)],
        [(1, 1), (5, 5)])
    assert f[1] == 0.5                      # abandonos + nota baixa: piso
    assert 1.0 < f[2] <= 1.3 and 3 not in f
    assert f[4] == pytest.approx(1.2) and f[5] == pytest.approx(1.1)
    assert pf.fator_feedback([], []) == {}


def _score(client, cid, sid):
    itens = client.get(f"/cidadaos/{cid}/recomendacoes", params={"detalhe": True, "limite": 10}).json()["itens"]
    return next((i["score"] for i in itens if i["servico_id"] == sid), None), itens


def test_abandono_e_nota_baixa_reduzem_o_servico(client):
    antes, itens = _score(client, EMP, 0)
    alvo = itens[0]["servico_id"]
    antes, _ = _score(client, EMP, alvo)
    for _ in range(2):
        client.post("/eventos", json={"cidadao_id": EMP, "tipo": "abandono", "servico_id": alvo})
    client.post("/pesquisas", json={"cidadao_id": EMP, "servico_id": alvo, "nota": 1})
    depois, _ = _score(client, EMP, alvo)
    assert depois is None or depois < antes
    # outro cidadao nao e afetado (feedback e individual)
    outro, _ = _score(client, CID, alvo)
    assert outro is None or outro > 0


def test_cliques_aumentam_e_usar_historico_desligado_ignora_feedback(client):
    _, itens = _score(client, EMP, 0)
    alvo = itens[-1]["servico_id"]
    antes, _ = _score(client, EMP, alvo)
    for _ in range(3):
        client.post("/eventos", json={"cidadao_id": EMP, "tipo": "clique", "servico_id": alvo})
    depois, _ = _score(client, EMP, alvo)
    assert depois is None or depois >= antes
    prefs_put(client, EMP, usar_historico=False)
    a, _ = _score(client, EMP, alvo)
    client.post("/eventos", json={"cidadao_id": EMP, "tipo": "abandono", "servico_id": alvo})
    b, _ = _score(client, EMP, alvo)
    assert a == b


# --------------------------------------------------------------------- swagger
def test_swagger_documenta_perfil_e_vitrine(client):
    spec = client.get("/openapi.json").json()
    assert "/cidadaos/{cid}/tipo-perfil" in spec["paths"]
    esq = spec["components"]["schemas"]
    assert "example" in esq["TipoPerfilOut"] and set(SECOES) <= set(esq["VitrineOut"]["properties"])
    ex = esq["VitrineOut"]["example"]
    assert set(SECOES) <= set(ex) and ex["perfil"]["tipo"] == "empreendedor"
