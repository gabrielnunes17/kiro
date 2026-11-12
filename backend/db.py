"""Persistencia em SQLite (stdlib). Uma conexao por operacao: seguro com varios workers.

Tabelas: preferencias, pedidos, pedido_eventos, eventos_ux, pesquisas.
O caminho vem de KODIAK_DB (padrao data/app.db); os testes apontam para um arquivo temporario.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional

ARQ_PREFS_LEGADO = Path("data/preferencias.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS preferencias (
    cidadao_id TEXT PRIMARY KEY,
    dados      TEXT NOT NULL,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pedidos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo   TEXT UNIQUE,
    cidadao_id  TEXT NOT NULL,
    servico_id  INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'rascunho',
    dados       TEXT NOT NULL DEFAULT '{}',
    ultimo_passo INTEGER NOT NULL DEFAULT 0,
    simulado    INTEGER NOT NULL DEFAULT 1,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now')),
    enviado_em  TEXT
);
CREATE INDEX IF NOT EXISTS ix_pedidos_cidadao ON pedidos(cidadao_id);
CREATE TABLE IF NOT EXISTS pedido_eventos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL REFERENCES pedidos(id),
    etapa     TEXT NOT NULL,
    status    TEXT NOT NULL,
    horas_simuladas INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS eventos_ux (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_pseudo TEXT NOT NULL,
    tipo      TEXT NOT NULL,
    servico_id INTEGER,
    passo     INTEGER,
    posicao   INTEGER,
    origem    TEXT,
    duracao_ms INTEGER,
    simulado  INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pesquisas (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_pseudo TEXT NOT NULL,
    servico_id INTEGER,
    nota      INTEGER NOT NULL CHECK (nota BETWEEN 1 AND 5),
    comentario TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def caminho_db() -> Path:
    return Path(os.environ.get("KODIAK_DB", "data/app.db"))


@contextmanager
def conexao() -> Iterator[sqlite3.Connection]:
    """Abre, confirma ao sair sem erro, desfaz em erro e sempre fecha."""
    arq = caminho_db()
    arq.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(arq, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def iniciar() -> None:
    """Cria o schema e migra preferencias.json (uma vez) para o SQLite."""
    with conexao() as con:
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(SCHEMA)
    _migrar_prefs_legado()


def _migrar_prefs_legado() -> None:
    if not ARQ_PREFS_LEGADO.exists():
        return
    try:
        antigas = json.loads(ARQ_PREFS_LEGADO.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        antigas = {}
    with conexao() as con:
        for cid, dados in antigas.items():
            # INSERT OR IGNORE: nunca sobrescreve o que ja esta no banco.
            con.execute("INSERT OR IGNORE INTO preferencias (cidadao_id, dados) VALUES (?, ?)",
                        (cid, json.dumps(dados, ensure_ascii=False)))
    ARQ_PREFS_LEGADO.rename(ARQ_PREFS_LEGADO.with_suffix(".json.migrado"))


def ler_prefs(cid: str) -> Optional[Dict]:
    with conexao() as con:
        r = con.execute("SELECT dados FROM preferencias WHERE cidadao_id = ?", (cid,)).fetchone()
    return json.loads(r["dados"]) if r else None


def gravar_prefs(cid: str, dados: Dict) -> None:
    with conexao() as con:
        con.execute(
            "INSERT INTO preferencias (cidadao_id, dados) VALUES (?, ?) "
            "ON CONFLICT(cidadao_id) DO UPDATE SET dados = excluded.dados, "
            "atualizado_em = datetime('now')",
            (cid, json.dumps(dados, ensure_ascii=False)))


def apagar_prefs(cid: str) -> None:
    with conexao() as con:
        con.execute("DELETE FROM preferencias WHERE cidadao_id = ?", (cid,))
