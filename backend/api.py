"""API REST do backend de hiperpersonalizacao (consumida pelo Kodiak).

Executar (a partir da raiz do projeto):
    .venv/bin/uvicorn backend.api:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from enum import Enum
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from backend import db, erros
from backend.motor import Motor, Preferencias
from backend.personas import PERFIS_SIMULADOS

_estado: Dict = {"motor": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.iniciar()
    _estado["motor"] = Motor()
    yield


app = FastAPI(title="Kodiak - Hiperpersonalizacao", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None)
# Prototipo: libera o front local. Em producao, restringir aos dominios do Kodiak.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
erros.registrar(app)


class PreferenciasIn(BaseModel):
    consentimento_saude: bool = False
    usar_historico: bool = True
    usar_perfil: bool = True
    usar_bairro: bool = True
    usar_sazonalidade: bool = True


class PerfilSimulado(str, Enum):
    idoso = "idoso"
    empreendedor = "empreendedor"
    pcd = "pcd"
    familia = "familia"


def _tags(perfil: Optional[PerfilSimulado]) -> Optional[List[str]]:
    return PERFIS_SIMULADOS[perfil.value] if perfil else None


def _motor() -> Motor:
    return _estado["motor"]


def _prefs(cid: str) -> Preferencias:
    salvas = db.ler_prefs(cid) or {}
    # Ignora chaves desconhecidas (ex.: campos de versoes futuras) em vez de quebrar.
    validas = {k: v for k, v in salvas.items() if k in Preferencias.__dataclass_fields__}
    return Preferencias(**validas)


@app.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    # Caminho relativo: funciona tambem atras de proxy com prefixo.
    return RedirectResponse(url="docs")


@app.get("/docs", include_in_schema=False)
def docs() -> HTMLResponse:
    # openapi_url relativo: o navegador resolve a partir da URL da propria pagina.
    return get_swagger_ui_html(openapi_url="openapi.json", title="Kodiak - Hiperpersonalizacao")


@app.get("/health")
def health() -> Dict:
    m = _motor()
    return {"status": "ok", "servicos": m.n, "cidadaos": len(m.cid), "com_historico": len(m.hist)}


@app.get("/cidadaos/{cid}/perfil")
def perfil(cid: str) -> Dict:
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


@app.get("/cidadaos/{cid}/preferencias")
def ler_preferencias(cid: str) -> Dict:
    return _prefs(cid).__dict__


@app.put("/cidadaos/{cid}/preferencias")
def gravar_preferencias(cid: str, body: PreferenciasIn) -> Dict:
    if cid not in _motor().cid:
        raise HTTPException(status_code=404, detail="Cidadão não encontrado")
    dados = body.model_dump()
    db.gravar_prefs(cid, dados)
    return dados


@app.get("/vitrine/{cid}")
def vitrine(
    cid: str,
    perfil_simulado: Optional[PerfilSimulado] = None,
    rpa: Optional[int] = Query(None, ge=1, le=6),
    semana: Optional[date] = None,
) -> Dict:
    """Secoes da home. perfil_simulado e rpa so servem ao modo demonstracao."""
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


@app.get("/cidadaos/{cid}/recomendacoes")
def recomendacoes(
    cid: str,
    limite: int = Query(10, ge=1, le=10),
    vagas_descoberta: int = Query(1, ge=0, le=3),
    semana: Optional[date] = None,
    detalhe: bool = False,
    perfil_simulado: Optional[PerfilSimulado] = None,
    rpa: Optional[int] = Query(None, ge=1, le=6),
) -> Dict:
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


@app.get("/servicos/{sid}")
def servico(sid: int) -> Dict:
    d = _motor().detalhe_servico(sid)
    if d is None:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")
    return d


@app.get("/servicos/{sid}/proximos-passos")
def proximos_passos(sid: int, limite: int = Query(5, ge=1, le=10)) -> List[Dict]:
    if _motor().detalhe_servico(sid) is None:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")
    return _motor().proximos_passos(sid, limite)

