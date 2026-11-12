"""API REST do backend de hiperpersonalizacao (consumida pelo Kodiak).

Executar (a partir da raiz do projeto):
    .venv/bin/uvicorn backend.api:app --host 127.0.0.1 --port 8000
Swagger UI na rota /docs.
"""
from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse

from backend import db, erros
from backend import schemas as sc
from backend.motor import Motor, Preferencias
from backend.personas import PERFIS_SIMULADOS, PERSONAS

_estado: Dict = {"motor": None}

DESCRICAO = """
API de **hiperpersonalização** da Carta de Serviços do Recife para o app Kodiak.

* **Vitrine e recomendações**: serviços sugeridos com um motivo em linguagem simples.
* **Preferências**: o cidadão liga e desliga cada tipo de personalização. Dados de saúde só
  são usados com `consentimento_saude = true`.
* **Pedidos**: rascunho, envio e acompanhamento (simulados, nada é encaminhado a órgãos).
* **Eventos de UX e pesquisas**: medição de uso. O `cidadao_id` é guardado apenas como pseudônimo.

**Modo demonstração**: `perfil_simulado` e `rpa` forçam um perfil e uma região sem alterar o cadastro.
Use os ids da rota `GET /personas` para testar. Todos os erros seguem `{"erro": "...", "detalhe": "..."}`.
"""

TAGS = [
    {"name": "Sistema", "description": "Status da API."},
    {"name": "Personalização", "description": "Vitrine, recomendações e demonstração."},
    {"name": "Cidadão", "description": "Perfil e preferências de privacidade."},
    {"name": "Serviços", "description": "Detalhe e próximos passos."},
    {"name": "Pedidos", "description": "Rascunho, envio e acompanhamento (simulado)."},
    {"name": "Medição", "description": "Eventos de UX e pesquisa de satisfação."},
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.iniciar()
    _estado["motor"] = Motor()
    yield


app = FastAPI(title="Kodiak - Hiperpersonalizacao", version="0.2.0", description=DESCRICAO,
              openapi_tags=TAGS, lifespan=lifespan, docs_url=None, redoc_url=None,
              # URL relativa: o "Try it out" do Swagger resolve a partir do openapi.json, entao
              # funciona direto (/) e atras de proxy com prefixo (ex.: /proxy/8000/).
              servers=[{"url": "."}])
# Prototipo: libera o front local. Em producao, restringir aos dominios do Kodiak.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
erros.registrar(app)


def _tags(perfil: Optional[sc.PerfilSimulado]) -> Optional[List[str]]:
    return PERFIS_SIMULADOS[perfil.value] if perfil else None


def _motor() -> Motor:
    return _estado["motor"]


def _prefs(cid: str) -> Preferencias:
    salvas = db.ler_prefs(cid) or {}
    # Ignora chaves desconhecidas (ex.: campos de versoes futuras) em vez de quebrar.
    validas = {k: v for k, v in salvas.items() if k in Preferencias.__dataclass_fields__}
    return Preferencias(**validas)


def _pseudo(cid: str) -> str:
    """Pseudonimo estavel: eventos e pesquisas nunca guardam o id real."""
    sal = os.environ.get("KODIAK_SALT", "kodiak-prototipo")
    return hashlib.sha256(f"{sal}:{cid}".encode()).hexdigest()[:16]


def _exigir_servico(sid: int) -> None:
    if _motor().detalhe_servico(sid) is None:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")


def _exigir_cidadao(cid: str) -> None:
    if cid not in _motor().cid:
        raise HTTPException(status_code=404, detail="Cidadão não encontrado")


def _exigir_pedido(pid: int) -> Dict:
    p = db.ler_pedido(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return p


@app.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    # Caminho relativo: funciona tambem atras de proxy com prefixo.
    return RedirectResponse(url="docs")


@app.get("/docs", include_in_schema=False)
def docs() -> HTMLResponse:
    # openapi_url relativo: o navegador resolve a partir da URL da propria pagina.
    return get_swagger_ui_html(openapi_url="openapi.json", title="Kodiak - Hiperpersonalizacao")


# ------------------------------------------------------------------ sistema
@app.get("/health", tags=["Sistema"], summary="Status da API", response_model=sc.Health)
def health() -> Dict:
    """Confirma que a API está no ar e mostra o tamanho da base carregada."""
    m = _motor()
    return {"status": "ok", "servicos": m.n, "cidadaos": len(m.cid), "com_historico": len(m.hist)}


# ------------------------------------------------------------------ cidadao
@app.get("/personas", tags=["Personalização"], summary="Personas de demonstração",
         response_model=List[sc.Persona])
def personas() -> List[Dict]:
    """Cidadãos fictícios prontos para testar. Use `cidadao_id` nas outras rotas e, se quiser
    reproduzir o perfil por simulação, `perfil_simulado`."""
    return PERSONAS


@app.get("/cidadaos/{cid}/perfil", tags=["Cidadão"], summary="Perfil do cidadão",
         response_model=sc.PerfilOut, response_model_exclude_unset=True)
def perfil(cid: str) -> Dict:
    """Dados básicos e perfis ativos. Id desconhecido devolve `anonimo: true` (visitante).
    Marcadores de saúde não aparecem aqui; só são usados na personalização com consentimento."""
    m = _motor()
    c = m.cid.get(cid)
    prefs = _prefs(cid)
    if c is None:
        return {"cidadao_id": cid, "anonimo": True, "perfis_ativos": [], "preferencias": prefs.__dict__}
    publico = {k: c[k] for k in ("idade", "faixa_etaria", "sexo", "rpa", "aceita_notificacao")}
    return {
        "cidadao_id": cid,
        "anonimo": False,
        "perfil": publico,
        "perfis_ativos": m.perfis_ativos(cid, prefs),
        "tem_historico": cid in m.hist,
        "preferencias": prefs.__dict__,
        # Dados de saude nunca saem sem consentimento.
        "saude_disponivel": bool(prefs.consentimento_saude),
    }


@app.get("/cidadaos/{cid}/preferencias", tags=["Cidadão"], summary="Ler preferências",
         response_model=sc.Preferencias)
def ler_preferencias(cid: str) -> Dict:
    """Sem preferências salvas, devolve o padrão (tudo ligado, exceto consentimento de saúde)."""
    return _prefs(cid).__dict__


@app.put("/cidadaos/{cid}/preferencias", tags=["Cidadão"], summary="Gravar preferências",
         response_model=sc.Preferencias, responses={**sc.RESP_404, **sc.RESP_422})
def gravar_preferencias(cid: str, body: sc.Preferencias) -> Dict:
    """Substitui todas as preferências do cidadão. Têm efeito imediato na vitrine e nas recomendações."""
    _exigir_cidadao(cid)
    dados = body.model_dump()
    db.gravar_prefs(cid, dados)
    return dados


# ----------------------------------------------------------- personalizacao
@app.get("/vitrine/{cid}", tags=["Personalização"], summary="Vitrine da home",
         response_model=sc.VitrineOut, response_model_exclude_unset=True, responses=sc.RESP_422)
def vitrine(
    cid: str,
    perfil_simulado: Optional[sc.PerfilSimulado] = Query(None, description="Modo demonstração: força o perfil."),
    rpa: Optional[int] = Query(None, ge=1, le=6, description="Modo demonstração: força a região (RPA 1 a 6)."),
    semana: Optional[date] = Query(None, description="Data de referência da sazonalidade (AAAA-MM-DD)."),
) -> Dict:
    """Quatro seções da home: `para_voce_agora` (5), `na_sua_regiao` (3), `em_alta_nesta_epoca` (3)
    e `descubra` (2). Nenhum serviço se repete nem vem do histórico do cidadão. Seções desligadas
    nas preferências voltam vazias, com o motivo em `avisos`."""
    m = _motor()
    prefs = _prefs(cid)
    tags = _tags(perfil_simulado)
    v = m.vitrine(cid, prefs=prefs, data_ref=semana, tags_forcadas=tags, rpa=rpa)
    return {
        "cidadao_id": cid,
        "anonimo": cid not in m.cid,
        "perfil_simulado": perfil_simulado.value if perfil_simulado else None,
        "data_referencia": (semana or m.ref).isoformat(),
        "perfis_ativos": m.perfis_ativos(cid, prefs, tags),
        "preferencias": prefs.__dict__,
        **v,
    }


@app.get("/cidadaos/{cid}/recomendacoes", tags=["Personalização"], summary="Recomendações em lista",
         response_model=sc.RecomendacoesOut, response_model_exclude_unset=True, responses=sc.RESP_422)
def recomendacoes(
    cid: str,
    limite: int = Query(10, ge=1, le=10, description="Quantidade de itens."),
    vagas_descoberta: int = Query(1, ge=0, le=3, description="Vagas reservadas a serviços pouco conhecidos."),
    semana: Optional[date] = Query(None, description="Data de referência da sazonalidade (AAAA-MM-DD)."),
    detalhe: bool = Query(False, description="Inclui `sinais`, `pesos` e `score` de cada item (depuração)."),
    perfil_simulado: Optional[sc.PerfilSimulado] = Query(None, description="Modo demonstração."),
    rpa: Optional[int] = Query(None, ge=1, le=6, description="Modo demonstração (RPA 1 a 6)."),
) -> Dict:
    """Lista ordenada de serviços com o motivo de cada um. Nunca inclui serviços já usados.
    Cidadão desconhecido é tratado como visitante (`anonimo: true`)."""
    m = _motor()
    prefs = _prefs(cid)
    tags = _tags(perfil_simulado)
    itens = m.recomendar(cid, limite=limite, prefs=prefs, vagas_descoberta=vagas_descoberta,
                         data_ref=semana, detalhe=detalhe, tags_forcadas=tags, rpa=rpa)
    return {
        "cidadao_id": cid,
        "anonimo": cid not in m.cid,
        "perfil_simulado": perfil_simulado.value if perfil_simulado else None,
        "data_referencia": (semana or m.ref).isoformat(),
        "perfis_ativos": m.perfis_ativos(cid, prefs, tags),
        "preferencias": prefs.__dict__,
        "itens": itens,
    }


# ----------------------------------------------------------------- servicos
@app.get("/servicos/{sid}", tags=["Serviços"], summary="Detalhe do serviço",
         response_model=sc.ServicoOut, responses=sc.RESP_404)
def servico(sid: int) -> Dict:
    """Descrição, requisitos, passos e canais do serviço."""
    d = _motor().detalhe_servico(sid)
    if d is None:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")
    return d


@app.get("/servicos/{sid}/proximos-passos", tags=["Serviços"], summary="Próximos passos mais comuns",
         response_model=List[sc.ProximoPasso], responses=sc.RESP_404)
def proximos_passos(sid: int, limite: int = Query(5, ge=1, le=10)) -> List[Dict]:
    """Serviços que as pessoas costumam usar logo depois deste, com a probabilidade estimada."""
    _exigir_servico(sid)
    return _motor().proximos_passos(sid, limite)


@app.get("/servicos/{sid}/pesquisas", tags=["Medição"], summary="Resumo das notas do serviço",
         response_model=sc.ResumoPesquisa, responses=sc.RESP_404)
def resumo_pesquisas(sid: int) -> Dict:
    """Média e distribuição das notas dadas pelos cidadãos pela pesquisa de satisfação."""
    _exigir_servico(sid)
    return db.resumo_pesquisas(sid)


# ------------------------------------------------------------------ pedidos
@app.post("/pedidos", tags=["Pedidos"], summary="Criar rascunho de pedido", status_code=201,
          response_model=sc.PedidoOut, responses={**sc.RESP_404, **sc.RESP_422})
def criar_pedido(body: sc.PedidoIn) -> Dict:
    """Cria um pedido em `rascunho`. O protocolo só nasce no envio."""
    _exigir_cidadao(body.cidadao_id)
    _exigir_servico(body.servico_id)
    return db.criar_pedido(body.cidadao_id, body.servico_id, body.dados)


@app.get("/cidadaos/{cid}/pedidos", tags=["Pedidos"], summary="Pedidos do cidadão",
         response_model=List[sc.PedidoOut])
def listar_pedidos(cid: str) -> List[Dict]:
    """Do mais recente para o mais antigo."""
    return db.listar_pedidos(cid)


@app.get("/pedidos/{pid}", tags=["Pedidos"], summary="Ler pedido",
         response_model=sc.PedidoOut, responses=sc.RESP_404)
def ler_pedido(pid: int) -> Dict:
    return _exigir_pedido(pid)


@app.patch("/pedidos/{pid}", tags=["Pedidos"], summary="Salvar progresso do rascunho",
           response_model=sc.PedidoOut, responses={**sc.RESP_404, **sc.RESP_409, **sc.RESP_422})
def atualizar_pedido(pid: int, body: sc.PedidoPatch) -> Dict:
    """Mescla `dados` aos já salvos e atualiza `ultimo_passo`. Só vale para pedidos em `rascunho`."""
    try:
        p = db.atualizar_rascunho(pid, body.dados, body.ultimo_passo)
    except ValueError:
        raise HTTPException(status_code=409, detail="Pedido já enviado não pode ser alterado")
    if p is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return p


@app.post("/pedidos/{pid}/enviar", tags=["Pedidos"], summary="Enviar pedido",
          response_model=sc.PedidoOut, responses={**sc.RESP_404, **sc.RESP_409})
def enviar_pedido(pid: int) -> Dict:
    """Gera o protocolo (`KDK-AAAA-NNNNNN`) e a linha do tempo simulada. Simulado: nada é encaminhado."""
    try:
        p = db.enviar_pedido(pid)
    except ValueError:
        raise HTTPException(status_code=409, detail="Pedido já foi enviado")
    if p is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return p


@app.get("/pedidos/{pid}/acompanhamento", tags=["Pedidos"], summary="Acompanhar pedido",
         response_model=sc.AcompanhamentoOut, responses=sc.RESP_404)
def acompanhamento(pid: int) -> Dict:
    """Etapas do pedido. Em rascunho a lista é vazia."""
    p = _exigir_pedido(pid)
    return {"pedido_id": pid, "protocolo": p["protocolo"], "status": p["status"],
            "etapas": db.eventos_pedido(pid)}


# ------------------------------------------------------------------ medicao
@app.post("/eventos", tags=["Medição"], summary="Registrar evento de UX", status_code=201,
          response_model=sc.RegistroOut, responses=sc.RESP_422)
def registrar_evento(body: sc.EventoUxIn) -> Dict:
    """Cliques, visualizações e passos de pedido. Aceita visitantes. O id vira pseudônimo."""
    dados = body.model_dump(mode="json")
    return {"id": db.gravar_evento_ux(_pseudo(body.cidadao_id), dados)}


@app.post("/pesquisas", tags=["Medição"], summary="Enviar nota de satisfação", status_code=201,
          response_model=sc.RegistroOut, responses={**sc.RESP_404, **sc.RESP_422})
def registrar_pesquisa(body: sc.PesquisaIn) -> Dict:
    """Nota de 1 a 5 e comentário opcional, geral ou sobre um serviço."""
    if body.servico_id is not None:
        _exigir_servico(body.servico_id)
    return {"id": db.gravar_pesquisa(_pseudo(body.cidadao_id), body.servico_id, body.nota, body.comentario)}
