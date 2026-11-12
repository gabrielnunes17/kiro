"""Gera saidas/recomendacoes.csv para os 89.046 cidadaos e valida as regras."""
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from backend.motor import Motor, Preferencias  # noqa: E402

SAIDA = Path("saidas/recomendacoes.csv")


def main() -> int:
    motor = Motor()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    prefs = Preferencias()  # padrao: sem consentimento de saude
    t0 = time.time()
    ids = sorted(motor.cid)
    sem_descoberta, ja_usados, poucos = [], 0, []
    with open(SAIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(["cidadao_id", "posicao", "servico_id", "motivo"])
        for n, cid in enumerate(ids, 1):
            itens = motor.recomendar(cid, limite=10, prefs=prefs, vagas_descoberta=1)
            if len(itens) < 10:
                poucos.append(cid)
            if not any(i["tipo"] == "descoberta" for i in itens):
                sem_descoberta.append(cid)
            if cid in motor.hist:
                usados = {int(motor.ids[i]) for i in motor.hist[cid][0]}
                ja_usados += sum(1 for i in itens if i["servico_id"] in usados)
            for i in itens:
                w.writerow([cid, i["posicao"], i["servico_id"], i["motivo"]])
            if n % 10000 == 0:
                print(f"{n}/{len(ids)} ({time.time() - t0:.0f}s)")

    df = pd.read_csv(SAIDA, keep_default_na=False)
    serv = set(motor.ids.tolist())
    todos = set(pd.read_csv("data/raw/cidadaos.csv", usecols=["cidadao_id"])["cidadao_id"])
    checks = {
        "todos os 89.046 cidadaos presentes": set(df["cidadao_id"]) == todos,
        "no maximo 10 por cidadao": df.groupby("cidadao_id").size().max() <= 10,
        "posicao entre 1 e 10": df["posicao"].between(1, 10).all(),
        "sem posicao repetida por cidadao": not df.duplicated(["cidadao_id", "posicao"]).any(),
        "sem servico repetido por cidadao": not df.duplicated(["cidadao_id", "servico_id"]).any(),
        "servico_id existe em servicos.csv": df["servico_id"].isin(serv).all(),
        "motivo preenchido": (df["motivo"].str.len() > 0).all(),
        "nenhum servico ja usado sugerido": ja_usados == 0,
        "todos com 10 sugestoes": not poucos,
        "todos com ao menos 1 descoberta": not sem_descoberta,
        "nenhum motivo cita consentimento de saude": not df["motivo"].str.contains("autorizou").any(),
    }
    print(f"\nlinhas: {len(df)}  cidadaos: {df['cidadao_id'].nunique()}  tempo: {time.time() - t0:.0f}s")
    ok = True
    for nome, v in checks.items():
        print(("OK   " if v else "FALHA"), nome)
        ok &= bool(v)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
