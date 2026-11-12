"""Backtest offline: treina ate o corte e confere servicos novos usados depois."""
import argparse
import random
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backend.motor import DATA_FIM, Motor, Preferencias  # noqa: E402


def avaliar(motor, alvos, k, vagas, pop_ordem, analisador=None):
    hits, rec, mrr, desc_hits = [], [], [], []
    base_hits, base_rec = [], []
    for cid, novos in alvos.items():
        extra = analisador.definir(cid, Preferencias()).tags_inferidas if analisador else None
        itens = motor.recomendar(cid, limite=k, vagas_descoberta=vagas, tags_extra=extra)
        ids = [i["servico_id"] for i in itens]
        achados = [p for p, s in enumerate(ids, 1) if s in novos]
        hits.append(1.0 if achados else 0.0)
        rec.append(len(achados) / len(novos))
        mrr.append(1.0 / achados[0] if achados else 0.0)
        conhecidos = set(motor.ids[motor.hist[cid][0]])
        base = [s for s in pop_ordem if s not in conhecidos][:k]
        b = [s for s in base if s in novos]
        base_hits.append(1.0 if b else 0.0)
        base_rec.append(len(b) / len(novos))
    return {
        "hit@k": np.mean(hits), "recall@k": np.mean(rec), "mrr": np.mean(mrr),
        "base_pop_hit@k": np.mean(base_hits), "base_pop_recall@k": np.mean(base_rec),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corte", default="2026-09-14")
    ap.add_argument("--amostra", type=int, default=3000)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--vagas", type=int, nargs="+", default=[0, 3])
    ap.add_argument("--com-perfil", action="store_true",
                    help="inclui as tags inferidas do comportamento (backend.perfil)")
    args = ap.parse_args()

    corte = date.fromisoformat(args.corte)
    t0 = time.time()
    motor = Motor(corte=corte)
    print(f"motor pronto em {time.time() - t0:.1f}s")

    import pandas as pd
    h = pd.read_parquet("data/parquet/historico.parquet")
    h = h[(h["data"] >= corte.isoformat()) & (h["data"] <= DATA_FIM.isoformat())]
    h["idx"] = h["servico_id"].map(motor.sid2idx)
    futuro = h.groupby("cidadao_id")["servico_id"].apply(set).to_dict()
    alvos = {}
    for cid, serv in futuro.items():
        if cid not in motor.hist:
            continue
        conhecidos = {int(motor.ids[i]) for i in motor.hist[cid][0]}
        novos = {int(s) for s in serv} - conhecidos
        if novos:
            alvos[cid] = novos
    print(f"cidadaos com historico previo e servico novo no periodo: {len(alvos)}")
    random.seed(7)
    amostra = random.sample(sorted(alvos), min(args.amostra, len(alvos)))
    alvos = {c: alvos[c] for c in amostra}
    pop_ordem = [int(motor.ids[i]) for i in np.argsort(-motor.pessoas)]
    analisador = None
    if args.com_perfil:
        from backend.perfil import Analisador
        analisador = Analisador(motor)
    for v in args.vagas:
        t = time.time()
        r = avaliar(motor, alvos, args.k, v, pop_ordem, analisador)
        print(f"vagas_descoberta={v} ({time.time() - t:.0f}s): " +
              ", ".join(f"{k}={x:.4f}" for k, x in r.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
