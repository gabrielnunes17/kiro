import sqlite3

from backend import db
from tests.conftest import CID

SID = 953


def test_personas(client):
    r = client.get("/personas")
    assert r.status_code == 200
    assert len(r.json()) == 8
    assert {"cidadao_id", "rotulo", "perfil_simulado", "resumo"} <= set(r.json()[0])


def test_fluxo_completo_do_pedido(client):
    r = client.post("/pedidos", json={"cidadao_id": CID, "servico_id": SID, "dados": {"a": 1}})
    assert r.status_code == 201
    p = r.json()
    assert p["status"] == "rascunho" and p["protocolo"] is None and p["simulado"] is True
    pid = p["id"]
    assert client.get(f"/pedidos/{pid}/acompanhamento").json()["etapas"] == []

    r = client.patch(f"/pedidos/{pid}", json={"dados": {"b": 2}, "ultimo_passo": 2})
    assert r.json()["dados"] == {"a": 1, "b": 2} and r.json()["ultimo_passo"] == 2

    r = client.post(f"/pedidos/{pid}/enviar")
    assert r.status_code == 200
    assert r.json()["status"] == "enviado"
    assert r.json()["protocolo"] == f"KDK-{r.json()['criado_em'][:4]}-{pid:06d}"

    etapas = client.get(f"/pedidos/{pid}/acompanhamento").json()["etapas"]
    assert [e["etapa"] for e in etapas] == ["recebido", "em_analise", "decisao"]

    assert client.post(f"/pedidos/{pid}/enviar").status_code == 409
    assert client.patch(f"/pedidos/{pid}", json={"dados": {"c": 3}}).status_code == 409
    assert [x["id"] for x in client.get(f"/cidadaos/{CID}/pedidos").json()] == [pid]


def test_pedido_erros_padronizados(client):
    assert client.get("/pedidos/999").json()["erro"] == "nao_encontrado"
    assert client.post("/pedidos/999/enviar").status_code == 404
    assert client.patch("/pedidos/999", json={}).status_code == 404
    assert client.post("/pedidos", json={"cidadao_id": "XX", "servico_id": SID}).status_code == 404
    assert client.post("/pedidos", json={"cidadao_id": CID, "servico_id": 99999}).status_code == 404
    assert client.post("/pedidos", json={"cidadao_id": CID}).status_code == 422


def test_evento_ux_guarda_so_pseudonimo(client):
    r = client.post("/eventos", json={"cidadao_id": CID, "tipo": "clique", "servico_id": SID,
                                      "posicao": 1, "origem": "vitrine/para_voce_agora"})
    assert r.status_code == 201 and r.json()["id"] == 1
    con = sqlite3.connect(db.caminho_db())
    pseudo, tipo = con.execute("SELECT usuario_pseudo, tipo FROM eventos_ux").fetchone()
    con.close()
    assert tipo == "clique" and CID not in pseudo and len(pseudo) == 16
    assert client.post("/eventos", json={"cidadao_id": CID, "tipo": "inexistente"}).status_code == 422
    assert client.post("/eventos", json={"cidadao_id": CID, "tipo": "clique", "posicao": 11}).status_code == 422


def test_pesquisa_e_resumo(client):
    assert client.get(f"/servicos/{SID}/pesquisas").json() == {
        "servico_id": SID, "total": 0, "media": None, "distribuicao": {}}
    for nota in (4, 5, 5):
        assert client.post("/pesquisas", json={"cidadao_id": CID, "servico_id": SID, "nota": nota}
                           ).status_code == 201
    r = client.get(f"/servicos/{SID}/pesquisas").json()
    assert r["total"] == 3 and r["media"] == 4.67 and r["distribuicao"] == {"4": 1, "5": 2}
    assert client.post("/pesquisas", json={"cidadao_id": CID, "nota": 6}).status_code == 422
    assert client.post("/pesquisas", json={"cidadao_id": CID, "servico_id": 99999, "nota": 3}
                       ).status_code == 404
    assert client.get("/servicos/99999/pesquisas").status_code == 404


def test_swagger_documentado_com_exemplos(client):
    spec = client.get("/openapi.json").json()
    rotas = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    esperadas = {("POST", "/pedidos"), ("PATCH", "/pedidos/{pid}"), ("POST", "/pedidos/{pid}/enviar"),
                 ("GET", "/pedidos/{pid}/acompanhamento"), ("POST", "/eventos"), ("POST", "/pesquisas"),
                 ("GET", "/personas"), ("GET", "/vitrine/{cid}"), ("PUT", "/cidadaos/{cid}/preferencias")}
    assert esperadas <= rotas
    for p, ops in spec["paths"].items():
        for m, op in ops.items():
            assert op.get("summary") and op.get("tags"), (m, p)
    esq = spec["components"]["schemas"]
    for nome in ("PedidoIn", "PedidoOut", "EventoUxIn", "PesquisaIn", "VitrineOut",
                 "RecomendacoesOut", "Preferencias", "Erro", "ServicoOut"):
        assert "example" in esq[nome], nome
    assert client.get("/docs").status_code == 200
