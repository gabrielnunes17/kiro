"""Persistencia em SQLite (stdlib). Uma conexao por operacao: seguro com varios workers.

Tabelas: preferencias, pedidos, pedido_eventos, eventos_ux, pesquisas.
O caminho vem de KODIAK_DB (padrao data/app.db); os testes apontam para um arquivo temporario.
"""
from __future__ import annotations

import hashlib
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
CREATE INDEX IF NOT EXISTS ix_eventos_pseudo ON eventos_ux(usuario_pseudo);
CREATE INDEX IF NOT EXISTS ix_pesquisas_pseudo ON pesquisas(usuario_pseudo);
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


# ---------------------------------------------------------------- pedidos
def _pedido(r: sqlite3.Row) -> Dict:
    d = dict(r)
    d["dados"] = json.loads(d["dados"])
    d["simulado"] = bool(d["simulado"])
    return d


def criar_pedido(cid: str, servico_id: int, dados: Dict) -> Dict:
    with conexao() as con:
        cur = con.execute("INSERT INTO pedidos (cidadao_id, servico_id, dados) VALUES (?, ?, ?)",
                          (cid, servico_id, json.dumps(dados, ensure_ascii=False)))
        r = con.execute("SELECT * FROM pedidos WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _pedido(r)


def ler_pedido(pid: int) -> Optional[Dict]:
    with conexao() as con:
        r = con.execute("SELECT * FROM pedidos WHERE id = ?", (pid,)).fetchone()
    return _pedido(r) if r else None


def listar_pedidos(cid: str) -> list:
    with conexao() as con:
        rs = con.execute("SELECT * FROM pedidos WHERE cidadao_id = ? ORDER BY id DESC", (cid,)).fetchall()
    return [_pedido(r) for r in rs]


def atualizar_rascunho(pid: int, dados: Optional[Dict], ultimo_passo: Optional[int]) -> Optional[Dict]:
    """Mescla dados no rascunho. Retorna None se nao existe; levanta ValueError se ja enviado."""
    with conexao() as con:
        r = con.execute("SELECT * FROM pedidos WHERE id = ?", (pid,)).fetchone()
        if r is None:
            return None
        if r["status"] != "rascunho":
            raise ValueError("pedido ja enviado")
        novos = json.loads(r["dados"])
        novos.update(dados or {})
        passo = r["ultimo_passo"] if ultimo_passo is None else ultimo_passo
        con.execute("UPDATE pedidos SET dados = ?, ultimo_passo = ? WHERE id = ?",
                    (json.dumps(novos, ensure_ascii=False), passo, pid))
        r = con.execute("SELECT * FROM pedidos WHERE id = ?", (pid,)).fetchone()
    return _pedido(r)


# Linha do tempo simulada: (etapa, status, horas desde o envio).
LINHA_DO_TEMPO = [("recebido", "concluida", 0), ("em_analise", "concluida", 24),
                  ("decisao", "pendente", 72)]


def enviar_pedido(pid: int) -> Optional[Dict]:
    """Gera o protocolo, muda para 'enviado' e cria os eventos simulados."""
    with conexao() as con:
        r = con.execute("SELECT * FROM pedidos WHERE id = ?", (pid,)).fetchone()
        if r is None:
            return None
        if r["status"] != "rascunho":
            raise ValueError("pedido ja enviado")
        protocolo = f"KDK-{r['criado_em'][:4]}-{pid:06d}"
        con.execute("UPDATE pedidos SET status = 'enviado', protocolo = ?, enviado_em = datetime('now') "
                    "WHERE id = ?", (protocolo, pid))
        for etapa, status, horas in LINHA_DO_TEMPO:
            con.execute("INSERT INTO pedido_eventos (pedido_id, etapa, status, horas_simuladas) "
                        "VALUES (?, ?, ?, ?)", (pid, etapa, status, horas))
        r = con.execute("SELECT * FROM pedidos WHERE id = ?", (pid,)).fetchone()
    return _pedido(r)


def eventos_pedido(pid: int) -> list:
    with conexao() as con:
        rs = con.execute("SELECT etapa, status, horas_simuladas, criado_em FROM pedido_eventos "
                         "WHERE pedido_id = ? ORDER BY id", (pid,)).fetchall()
    return [dict(r) for r in rs]


# -------------------------------------------------- eventos de UX e pesquisas
def gravar_evento_ux(pseudo: str, e: Dict) -> int:
    with conexao() as con:
        cur = con.execute(
            "INSERT INTO eventos_ux (usuario_pseudo, tipo, servico_id, passo, posicao, origem, duracao_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pseudo, e["tipo"], e.get("servico_id"), e.get("passo"), e.get("posicao"),
             e.get("origem"), e.get("duracao_ms")))
        return cur.lastrowid


def resumo_eventos_ux() -> Dict:
    with conexao() as con:
        rs = con.execute("SELECT tipo, COUNT(*) AS n FROM eventos_ux GROUP BY tipo").fetchall()
    return {r["tipo"]: r["n"] for r in rs}


def gravar_pesquisa(pseudo: str, servico_id: Optional[int], nota: int, comentario: Optional[str]) -> int:
    with conexao() as con:
        cur = con.execute("INSERT INTO pesquisas (usuario_pseudo, servico_id, nota, comentario) "
                          "VALUES (?, ?, ?, ?)", (pseudo, servico_id, nota, comentario))
        return cur.lastrowid


def resumo_pesquisas(servico_id: int) -> Dict:
    with conexao() as con:
        r = con.execute("SELECT COUNT(*) AS n, AVG(nota) AS media FROM pesquisas WHERE servico_id = ?",
                        (servico_id,)).fetchone()
        dist = con.execute("SELECT nota, COUNT(*) AS n FROM pesquisas WHERE servico_id = ? GROUP BY nota",
                           (servico_id,)).fetchall()
    return {"servico_id": servico_id, "total": r["n"],
            "media": round(r["media"], 2) if r["media"] is not None else None,
            "distribuicao": {str(k["nota"]): k["n"] for k in dist}}


def pseudonimo(cid: str) -> str:
    """Pseudonimo estavel: eventos e pesquisas nunca guardam o id real."""
    sal = os.environ.get("KODIAK_SALT", "kodiak-prototipo")
    return hashlib.sha256(f"{sal}:{cid}".encode()).hexdigest()[:16]


def feedback_bruto(pseudo: str) -> tuple:
    """Retorna (eventos, notas): eventos = [(servico_id, tipo, n)], notas = [(servico_id, nota)]."""
    with conexao() as con:
        ev = con.execute("SELECT servico_id, tipo, COUNT(*) AS n FROM eventos_ux "
                         "WHERE usuario_pseudo = ? AND servico_id IS NOT NULL GROUP BY 1, 2",
                         (pseudo,)).fetchall()
        nt = con.execute("SELECT servico_id, nota FROM pesquisas "
                         "WHERE usuario_pseudo = ? AND servico_id IS NOT NULL", (pseudo,)).fetchall()
    return [(r["servico_id"], r["tipo"], r["n"]) for r in ev], [(r["servico_id"], r["nota"]) for r in nt]
