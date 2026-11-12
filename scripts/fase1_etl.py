"""Fase 1: diagnostico de qualidade e conversao dos CSVs para Parquet."""
from pathlib import Path

import pandas as pd

RAW = Path("data/raw")
OUT = Path("data/parquet")
ARQUIVOS = ["servicos", "cidadaos", "historico", "visitas_sem_login", "uso_semanal"]


def explode_counts(serie: pd.Series) -> pd.Series:
    """Conta valores de colunas-lista separadas por '|'."""
    return serie[serie != ""].str.split("|").explode().str.strip().value_counts()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    dfs = {}
    for nome in ARQUIVOS:
        df = pd.read_csv(RAW / f"{nome}.csv", keep_default_na=False, dtype=str if nome == "servicos" else None)
        dfs[nome] = df
        print(f"{nome}: {df.shape}")

    s, c, h = dfs["servicos"], dfs["cidadaos"], dfs["historico"]
    print("\n== servicos: colunas")
    print(list(s.columns))
    print("\n== servicos: celulas vazias por coluna")
    print((s == "").sum().to_string())

    print("\n== publicos_alvo")
    print(explode_counts(s["publicos_alvo"]).to_string())
    print("\n== temas")
    print(explode_counts(s["temas"]).to_string())
    print("\n== natureza")
    print(s["natureza"].value_counts().to_string())
    print("\n== nivel_digital_atual")
    print(s["nivel_digital_atual"].value_counts().to_string())
    print("\n== tem_historico")
    print(s["tem_historico"].value_counts().to_string())

    print("\n== cidadaos")
    print("ids unicos:", c["cidadao_id"].nunique())
    for col in ["faixa_etaria", "sexo", "rpa", "situacao_renda", "criancas_na_familia"]:
        print(f"-- {col}")
        print(c[col].value_counts().to_string())
    bools = [x for x in c.columns if c[x].isin(["true", "false"]).all()]
    print("-- marcadores (% true)")
    print((c[bools] == "true").mean().mul(100).round(1).to_string())

    print("\n== historico")
    sem_hist = set(c["cidadao_id"]) - set(h["cidadao_id"])
    print("cidadaos sem historico:", len(sem_hist))
    print("cidadaos no historico fora de cidadaos:", len(set(h["cidadao_id"]) - set(c["cidadao_id"])))
    print("servicos do historico fora de servicos:", len(set(h["servico_id"].astype(str)) - set(s["servico_id"])))
    print("servicos distintos no historico:", h["servico_id"].nunique())
    print("periodo:", h["data"].min(), "->", h["data"].max())
    cliques = h.groupby("cidadao_id").size()
    sess = h.groupby("cidadao_id")["sessao_id"].nunique()
    print("cliques por cidadao:", cliques.describe().round(1).to_dict())
    print("sessoes por cidadao:", sess.describe().round(1).to_dict())

    print("\n== uso_semanal")
    u = dfs["uso_semanal"]
    print(u["login"].value_counts().to_dict(), u["semana"].min(), "->", u["semana"].max())

    # Parquet: servicos fica como texto, os demais com tipos inferidos
    for nome, df in dfs.items():
        df.to_parquet(OUT / f"{nome}.parquet", index=False)
    print("\nParquet gravado em", OUT)


if __name__ == "__main__":
    main()
