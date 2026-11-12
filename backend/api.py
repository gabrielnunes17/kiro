"""API REST do backend de hiperpersonalizacao (consumida pelo Kodiak).

Executar (a partir da raiz do projeto):
    .venv/bin/uvicorn backend.api:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from backend.motor import Motor, Preferencias

ARQ_PREFS = Path("data/preferencias.json")
_lock = threading.Lock()
_estado: Dict = {"motor": None, "prefs": {}}


def _carregar_prefs() -> Dict[str, dict]:
    if ARQ_PREFS.exists():
        try:
            return json.loads(ARQ_PREFS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}  # arquivo corrompido: volta ao padrao em vez de derrubar a API
    return {}


def _salvar_prefs() -> None:
    # Escrita atomica: grava em temporario e troca, evitando arquivo pela metade.
    ARQ_PREFS.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARQ_PREFS.with_suffix(".tmp")
    tmp.write_text(json.dumps(_estado["prefs"], ensure_ascii=False), encoding="utf-8")
    tmp.replace(ARQ_PREFS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _estado["motor"] = Motor()
    _estado["prefs"] = _carregar_prefs()
    yield


app = FastAPI(title="Kodiak - Hiperpersonalizacao", version="0.1.0", lifespan=lifespan,
              docs_url=None, redoc_url=None)
# Prototipo: libera o front local. Em producao, restringir aos dominios do Kodiak.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PreferenciasIn(BaseModel):
    consentimento_saude: bool = False
    usar_historico: bool = True
    usar_perfil: bool = True
    usar_bairro: bool = True
    usar_sazonalidade: bool = True


def _motor() -> Motor:
    return _estado["motor"]


def _prefs(cid: str) -> Preferencias:
    return Preferencias(**_estado["prefs"].get(cid, {}))


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
    with _lock:
        _estado["prefs"][cid] = body.model_dump()
        _salvar_prefs()
    return _estado["prefs"][cid]


@app.get("/cidadaos/{cid}/recomendacoes")
def recomendacoes(
    cid: str,
    limite: int = Query(10, ge=1, le=10),
    vagas_descoberta: int = Query(1, ge=0, le=3),
    semana: Optional[date] = None,
    detalhe: bool = False,
) -> Dict:
    m = _motor()
    prefs = _prefs(cid)
    itens = m.recomendar(cid, limite=limite, prefs=prefs, vagas_descoberta=vagas_descoberta,
                         data_ref=semana, detalhe=detalhe)
    return {
        "cidadao_id": cid,
        "anonimo": cid not in m.cid,
        "data_referencia": (semana or m.ref).isoformat(),
        "perfis_ativos": m.perfis_ativos(cid, prefs),
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

