"""Ablacao e calibracao de pesos no backtest (sinais isolados e combinacoes)."""
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import backend.motor as M  # noqa: E402
from backtest import avaliar  # noqa: E402


def preparar(corte: date, amostra: int):
    motor = M.Motor(corte=corte)
    h = pd.read_parquet("data/parquet/historico.parquet")
    h = h[(h["data"] >= corte.isoformat()) & (h["data"] <= M.DATA_FIM.isoformat())]
    futuro = h.groupby("cidadao_id")["servico_id"].apply(set).to_dict()
    alvos = {}
    for cid, serv in futuro.items():
        if cid in motor.hist:
            conh = {int(motor.ids[i]) for i in motor.hist[cid][0]}
            novos = {int(s) for s in serv} - conh
            if novos:
                alvos[cid] = novos
    random.seed(7)
    pick = random.sample(sorted(alvos), min(amostra, len(alvos)))
    pop_ordem = [int(motor.ids[i]) for i in np.argsort(-motor.pessoas)]
    return motor, {c: alvos[c] for c in pick}, pop_ordem


def rodar(motor, alvos, pop_ordem, pesos, vagas=0):
    M.PESOS_BASE = dict(pesos)
    M.AJUSTE_GRUPO = {k: {} for k in M.AJUSTE_GRUPO}
    r = avaliar(motor, alvos, 10, vagas, pop_ordem)
    return r["hit@k"], r["recall@k"], r["mrr"]


def main() -> int:
    motor, alvos, pop_ordem = preparar(date(2026, 9, 14), 1500)
    zero = {k: 0.0 for k in M.SINAIS}
    print("== sinais isolados (hit@10, recall@10, mrr)")
    for s in M.SINAIS:
        p = dict(zero)
        p[s] = 1.0
        print(f"{s:10s}", *[f"{v:.4f}" for v in rodar(motor, alvos, pop_ordem, p)])
    print("== combinacoes")
    combos = {
        "pop+segmento": dict(zero, pop=0.5, segmento=0.5),
        "segmento+proximo": dict(zero, segmento=0.6, proximo=0.4),
        "seg+prox+pop": dict(zero, segmento=0.4, proximo=0.3, pop=0.3),
        "seg+prox+pop+saz": dict(zero, segmento=0.35, proximo=0.25, pop=0.25, saz=0.15),
        "v1 base": dict(M.PESOS_BASE),
    }
    for nome, p in combos.items():
        print(f"{nome:20s}", *[f"{v:.4f}" for v in rodar(motor, alvos, pop_ordem, p)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
