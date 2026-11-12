"""Distribuicao de tipos, momentos e maturidade digital entre os cidadaos (calibracao dos limiares)."""
import argparse
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402

from backend.motor import Motor, Preferencias  # noqa: E402
from backend.perfil import Analisador  # noqa: E402


def pct(c: Counter, n: int) -> str:
    return ", ".join(f"{k}={v} ({100 * v / n:.1f}%)" for k, v in c.most_common())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amostra", type=int, default=10000)
    ap.add_argument("--consentimento-saude", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    motor = Motor()
    an = Analisador(motor)
    print(f"motor pronto em {time.time() - t0:.0f}s")
    print("taxa media de cada tipo no uso:", {k: round(v, 3) for k, v in an.base.items()})

    random.seed(7)
    ids = sorted(motor.cid)
    ids = random.sample(ids, min(args.amostra, len(ids)))
    prefs = Preferencias(consentimento_saude=args.consentimento_saude)
    tipo, base, origem, momento, mat = Counter(), Counter(), Counter(), Counter(), Counter()
    inferidos, sobrepoe, medias = Counter(), 0, []
    for cid in ids:
        p = an.definir(cid, prefs)
        tipo[p.tipo] += 1
        base[p.tipo_base] += 1
        origem[p.origem] += 1
        momento[p.momento] += 1
        mat[p.maturidade_digital or "sem_historico"] += 1
        for i in p.inferidos:
            inferidos[i["tipo"]] += 1
        if p.origem == "comportamento" and p.tipo_base != "geral":
            sobrepoe += 1
        if cid in motor.hist:
            nv = motor.nivel[motor.hist[cid][0]]
            ok = ~np.isnan(nv)
            if ok.any():
                medias.append(float(np.average(nv[ok], weights=motor.hist[cid][1][ok])))
    n = len(ids)
    print(f"\namostra: {n} cidadaos")
    print("tipo principal :", pct(tipo, n))
    print("tipo pelo cadastro:", pct(base, n))
    print("origem          :", pct(origem, n))
    print("momento         :", pct(momento, n))
    print("maturidade      :", pct(mat, n))
    print("inferidos (com repeticao):", dict(inferidos))
    print(f"comportamento superou um tipo do cadastro em {sobrepoe} casos ({100 * sobrepoe / n:.1f}%)")
    if medias:
        q = np.quantile(medias, [0.1, 0.25, 0.5, 0.75, 0.9])
        print("media do nivel digital (p10,p25,p50,p75,p90):", np.round(q, 2).tolist())
    return 0


if __name__ == "__main__":
    sys.exit(main())
