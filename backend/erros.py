"""Erros padronizados: {"erro": "...", "detalhe": "..."}."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_NOMES = {400: "requisicao_invalida", 404: "nao_encontrado", 405: "metodo_nao_permitido",
          409: "conflito", 422: "dados_invalidos", 429: "muitas_requisicoes"}


def _resp(status: int, erro: str, detalhe) -> JSONResponse:
    return JSONResponse(status_code=status, content={"erro": erro, "detalhe": detalhe})


def registrar(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        return _resp(exc.status_code, _NOMES.get(exc.status_code, "erro"), exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validacao(_: Request, exc: RequestValidationError) -> JSONResponse:
        campos = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return _resp(422, "dados_invalidos", "; ".join(campos))
