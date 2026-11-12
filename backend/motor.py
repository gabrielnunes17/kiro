"""Motor de recomendacao hibrido e explicavel para o Kodiak.

Cada par cidadao x servico recebe um score que e a soma ponderada de sinais
(perfil, segmento, bairro, sazonalidade, proximo passo, conteudo, popularidade
e qualidade). Cada sinal tem uma frase de motivo em linguagem simples.

Regras de negocio principais:
- Servicos que o cidadao ja usou nao entram na lista (nao contam como acerto).
- Parte das vagas e reservada a "descoberta": servicos da cauda de popularidade
  que combinam com o perfil. Assim todo cidadao ve ao menos um servico que
  provavelmente ainda nao conhece.
- Marcadores de saude so entram com consentimento explicito.
"""
from __future__ import annotations

import unicodedata
import warnings
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

PARQUET = Path("data/parquet")
DATA_FIM = date(2026, 9, 27)
GERAL = "População em geral"

SINAIS = ["perfil", "segmento", "bairro", "saz", "proximo", "conteudo", "pop", "qualidade"]
SINAIS_COM_MOTIVO = ["perfil", "segmento", "bairro", "saz", "proximo", "conteudo", "pop"]

# Tags de perfil -> rotulos de publicos_alvo da Carta de Servicos.
ROTULOS_PUBLICO = {
    "idoso": {"Idoso"},
    "jovem": {"Jovem"},
    "empreendedor": {"Empreendedor", "Microempreendedor", "Profissional autônomo"},
    "pcd": {"Pessoa com deficiência - PCD"},
    "vulnerabilidade": {"Pessoa em situação de vulnerabilidade social"},
    "crianca_pequena": {"Criança na primeira infância (0 a 6 anos)", "Criança"},
    "crianca_escolar": {"Criança", "Responsável por aluno"},
    "estudante": {"Estudante"},
    "tutor_animal": {"Tutor de animal"},
    "proprietario": {"Proprietário de imóveis"},
    "servidor": {"Servidor público municipal"},
    "mulher": {"Mulher"},
    "gestante": {"Gestante"},
}
# Tags que dependem de dados de saude (exigem consentimento).
TAGS_SAUDE = {"gestante", "cronico", "saude_mental"}
TODAS_TAGS = list(ROTULOS_PUBLICO.keys()) + ["cronico", "saude_mental"]

GRUPO_PESO = {
    "idoso": "idoso",
    "empreendedor": "empreendedor",
    "pcd": "pcd",
    "vulnerabilidade": "familia",
    "crianca_pequena": "familia",
    "crianca_escolar": "familia",
}
# O perfil nao entra na soma: ele multiplica o score comportamental (1 + beta * perfil).
PESOS_BASE = dict(perfil=0.0, segmento=0.45, bairro=0.05, saz=0.0,
                  proximo=0.35, conteudo=0.0, pop=0.10, qualidade=0.05)
AJUSTE_GRUPO = {
    "idoso": dict(bairro=0.08),
    "empreendedor": dict(saz=0.05),
    "pcd": dict(),
    "familia": dict(saz=0.04),
}
BETA_BASE = 0.30
BETA_GRUPO = {"idoso": 0.40, "empreendedor": 0.40, "pcd": 0.60, "familia": 0.35}
SOMA = [k for k in SINAIS if k != "perfil"]

TEXTO_PERFIL = {
    "idoso": "Serviço pensado para pessoas idosas.",
    "jovem": "Serviço voltado para jovens.",
    "empreendedor": "Serviço para quem tem negócio ou trabalha por conta própria.",
    "pcd": "Serviço com atendimento para pessoas com deficiência.",
    "vulnerabilidade": "Serviço para famílias que recebem programas sociais.",
    "crianca_pequena": "Serviço para famílias com criança pequena.",
    "crianca_escolar": "Serviço para famílias com criança ou adolescente.",
    "estudante": "Serviço para estudantes.",
    "tutor_animal": "Serviço para quem cuida de um animal.",
    "proprietario": "Serviço para quem tem imóvel no Recife.",
    "servidor": "Serviço para servidores municipais.",
    "mulher": "Serviço voltado para mulheres.",
    "gestante": "Serviço para gestantes. Aparece porque você autorizou o uso de dados de saúde.",
}
TEXTO_SEGMENTO = {
    "faixa": "Muito usado por pessoas da sua faixa de idade.",
    "idoso": "Muito usado por pessoas idosas.",
    "empreendedor": "Muito usado por quem tem negócio.",
    "pcd": "Muito usado por pessoas com deficiência.",
    "vulnerabilidade": "Muito usado por famílias parecidas com a sua.",
    "crianca_pequena": "Muito usado por famílias parecidas com a sua.",
    "crianca_escolar": "Muito usado por famílias parecidas com a sua.",
    "estudante": "Muito usado por estudantes.",
}
TEXTO_SEGMENTO_PADRAO = "Muito usado por pessoas com perfil parecido com o seu."

STOP_PT = [
    "de", "da", "do", "das", "dos", "para", "por", "com", "em", "no", "na", "nos", "nas",
    "um", "uma", "uns", "umas", "ao", "aos", "as", "os", "que", "se", "ou", "e", "a", "o",
    "seu", "sua", "seus", "suas", "como", "mais", "ser", "sao", "foi", "pelo", "pela",
]


@dataclass
class Preferencias:
    """Controles do cidadao sobre a personalizacao."""
    consentimento_saude: bool = False
    usar_historico: bool = True
    usar_perfil: bool = True
    usar_bairro: bool = True
    usar_sazonalidade: bool = True


def _norm(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "")
    return "".join(ch for ch in txt if not unicodedata.combining(ch)).lower()


def _lista(txt: str) -> List[str]:
    return [t.strip() for t in (txt or "").split("|") if t.strip()]


def derivar_tags(c: Dict, saude: bool) -> List[str]:
    """Deriva as tags de perfil de um cidadao. Saude so entra com saude=True."""
    if not c:
        return []
    t: List[str] = []
    idade = int(c["idade"])
    if idade >= 60:
        t.append("idoso")
    if 18 <= idade <= 24:
        t.append("jovem")
    if c["empreendedor"] or c["mei"] or c["microcredito"]:
        t.append("empreendedor")
    if c["pessoa_com_deficiencia"]:
        t.append("pcd")
    if c["cadastro_unico"] or c["bolsa_familia"]:
        t.append("vulnerabilidade")
    cf = c["criancas_na_familia"]  # vazio = sem informacao, nunca "sem crianca"
    if cf == "primeira_infancia":
        t.append("crianca_pequena")
    if cf in ("crianca", "adolescente"):
        t.append("crianca_escolar")
    if c["estudante"]:
        t.append("estudante")
    if c["tutor_animal"]:
        t.append("tutor_animal")
    if c["proprietario_imovel"]:
        t.append("proprietario")
    if c["servidor_publico"]:
        t.append("servidor")
    if c["sexo"] == "F":
        t.append("mulher")
    if saude:
        if c["gestante"]:
            t.append("gestante")
        if c["hipertensao"] or c["diabetes"]:
            t.append("cronico")
        if c["saude_mental"]:
            t.append("saude_mental")
    return t


class Motor:
    K_SUAVIZACAO = 20.0

    def __init__(self, corte: Optional[date] = None, ref: Optional[date] = None,
                 parquet: Path = PARQUET) -> None:
        """corte: dados com data < corte entram no treino. ref: data de referencia."""
        self.corte = corte or (DATA_FIM + timedelta(days=1))
        self.ref = ref or self.corte
        self.p = Path(parquet)
        self._saz_cache: Dict[date, Dict[str, np.ndarray]] = {}
        self._carregar_servicos()
        self._carregar_cidadaos()
        self._carregar_historico()
        self._popularidade_e_qualidade()
        self._segmentos()
        self._transicoes()
        self._conteudo()
        self._carregar_uso_semanal()

    # ------------------------------------------------------------------ carga
    def _carregar_servicos(self) -> None:
        s = pd.read_parquet(self.p / "servicos.parquet")
        s["servico_id"] = s["servico_id"].astype(int)
        s = s.sort_values("servico_id").reset_index(drop=True)
        self.sv = s
        self.n = len(s)
        self.ids = s["servico_id"].values
        self.sid2idx = {int(sid): i for i, sid in enumerate(self.ids)}
        self.nome = s["item_nome"].tolist()
        self.publicos = [_lista(x) for x in s["publicos_alvo"]]
        self.temas = [_lista(x) for x in s["temas"]]
        self.tema1 = [t[0] if t else "" for t in self.temas]
        self.tag_srv = {
            tag: np.array([bool(set(l) & rot) for l in self.publicos])
            for tag, rot in ROTULOS_PUBLICO.items()
        }
        self.restrito = np.array([bool(l) and GERAL not in l for l in self.publicos])
        self.nivel = pd.to_numeric(s["nivel_digital_atual"], errors="coerce").values
        self.nota = pd.to_numeric(s["nota_media"], errors="coerce").values
        # chave de diversidade: duas primeiras palavras do nome
        self.prefixo = [" ".join(_norm(n).split()[:2]) for n in self.nome]

    def _carregar_cidadaos(self) -> None:
        c = pd.read_parquet(self.p / "cidadaos.parquet")
        self.cid = c.set_index("cidadao_id").to_dict("index")
        self.tags_all = {k: derivar_tags(v, True) for k, v in self.cid.items()}

    def _carregar_historico(self) -> None:
        h = pd.read_parquet(self.p / "historico.parquet")
        h = h[h["data"] < self.corte.isoformat()].copy()
        h["idx"] = h["servico_id"].map(self.sid2idx)
        h = h.dropna(subset=["idx"])
        h["idx"] = h["idx"].astype(int)
        h["dias"] = (pd.Timestamp(self.ref) - pd.to_datetime(h["data"])).dt.days.clip(lower=0)
        h["w"] = np.exp(-h["dias"].values / 45.0)
        self.h = h
        ind = h.groupby("cidadao_id").indices
        idx_arr, w_arr = h["idx"].values, h["w"].values
        self.hist = {k: (idx_arr[v], w_arr[v]) for k, v in ind.items()}
        self.hp = h[["cidadao_id", "idx"]].drop_duplicates()
        self.n_total = self.hp["cidadao_id"].nunique()

    def _popularidade_e_qualidade(self) -> None:
        n = self.n
        c_login = np.bincount(self.h["idx"].values, minlength=n).astype(float)
        con = duckdb.connect()
        df = con.execute(
            f"SELECT servico_id, count(*) AS c FROM read_parquet('{self.p / 'visitas_sem_login.parquet'}') "
            f"WHERE data < '{self.corte.isoformat()}' GROUP BY 1"
        ).df()
        con.close()
        c_nao = np.zeros(n)
        for sid, c in zip(df["servico_id"], df["c"]):
            if int(sid) in self.sid2idx:
                c_nao[self.sid2idx[int(sid)]] = c
        pop = np.log1p(c_login + c_nao / 6.0)
        self.pop = pop / max(pop.max(), 1e-9)
        self.pessoas = np.bincount(self.hp["idx"].values, minlength=n).astype(float)
        positivos = self.pessoas[self.pessoas > 0]
        self.cauda = self.pessoas <= np.quantile(positivos, 0.5)
        nota_n = np.where(np.isnan(self.nota), 0.5, (self.nota - 1) / 4.0)
        dig_map = {0: 0.0, 1: 0.4, 2: 0.6, 3: 0.8, 4: 1.0}
        dig_n = np.array([0.5 if np.isnan(v) else dig_map[int(v)] for v in self.nivel])
        self.qualidade = 0.5 * nota_n + 0.5 * dig_n
        # servicos 100% presenciais (nivel 0) sao mais dificeis de concluir no celular
        self.fator_digital = np.where(self.nivel == 0, 0.6, 1.0)

    def _vetor_segmento(self, ids: set, tipo: str) -> np.ndarray:
        sub = self.hp[self.hp["cidadao_id"].isin(ids)]
        n_seg = sub["cidadao_id"].nunique()
        cont = np.bincount(sub["idx"].values, minlength=self.n).astype(float)
        g = self.pessoas / max(self.n_total, 1)
        taxa = (cont + self.K_SUAVIZACAO * g) / (n_seg + self.K_SUAVIZACAO)
        lift = taxa / np.maximum(g, 1e-9)
        lift_n = np.clip(np.log2(np.maximum(lift, 1e-9)), 0, 3) / 3.0
        taxa_n = taxa / max(taxa.max(), 1e-9)
        lift_n = np.where(g > 0, lift_n, 0.0)
        if tipo == "bairro":
            return lift_n * np.sqrt(taxa_n)
        return 0.6 * taxa_n + 0.4 * lift_n

    def _segmentos(self) -> None:
        por_tag: Dict[str, set] = {t: set() for t in TODAS_TAGS}
        por_faixa: Dict[str, set] = {}
        por_rpa: Dict[int, set] = {}
        for k, v in self.cid.items():
            for t in self.tags_all[k]:
                por_tag[t].add(k)
            por_faixa.setdefault(v["faixa_etaria"], set()).add(k)
            por_rpa.setdefault(int(v["rpa"]), set()).add(k)
        self.seg_tag = {t: self._vetor_segmento(ids, "segmento") for t, ids in por_tag.items() if ids}
        self.seg_faixa = {f: self._vetor_segmento(ids, "segmento") for f, ids in por_faixa.items()}
        self.seg_rpa = {r: self._vetor_segmento(ids, "bairro") for r, ids in por_rpa.items()}

    def _transicoes(self) -> None:
        ci = self.corte.isoformat()
        con = duckdb.connect()
        df = con.execute(f"""
            WITH t AS (
              SELECT sessao_id, ordem_na_sessao AS o, servico_id AS s, 3.0 AS peso
                FROM read_parquet('{self.p / 'historico.parquet'}') WHERE data < '{ci}'
              UNION ALL
              SELECT sessao_id, ordem_na_sessao, servico_id, 1.0
                FROM read_parquet('{self.p / 'visitas_sem_login.parquet'}') WHERE data < '{ci}'
            )
            SELECT a.s AS a, b.s AS b, SUM(a.peso / (b.o - a.o)) AS w
              FROM t a JOIN t b ON a.sessao_id = b.sessao_id AND b.o - a.o BETWEEN 1 AND 3
             WHERE a.s <> b.s GROUP BY 1, 2
        """).df()
        con.close()
        W = np.zeros((self.n, self.n))
        df = df[df["a"].isin(self.sid2idx) & df["b"].isin(self.sid2idx)]
        ia = df["a"].map(self.sid2idx).values
        ib = df["b"].map(self.sid2idx).values
        W[ia, ib] = df["w"].values
        W[W < 3.0] = 0.0  # ruido
        self.P = W / (W.sum(axis=1, keepdims=True) + 5.0)

    def _conteudo(self) -> None:
        s = self.sv
        docs = []
        for i in range(self.n):
            r = s.iloc[i]
            docs.append(" ".join([
                r["item_nome"], r["item_nome"], r["temas"].replace("|", " "), r["temas"].replace("|", " "),
                r["grupos"].replace("|", " "), r["publicos_alvo"].replace("|", " "),
                r["palavras_chave"].replace("|", " "), r["descricao"][:500],
            ]))
        vec = TfidfVectorizer(strip_accents="unicode", sublinear_tf=True, min_df=2, max_df=0.4,
                              ngram_range=(1, 2), stop_words=STOP_PT)
        self.X = vec.fit_transform(docs).tocsr()
        # centroide de cada tag de perfil
        self.centroide = {}
        for tag, mask in self.tag_srv.items():
            if mask.any():
                v = np.asarray(self.X[mask].mean(axis=0)).ravel()
                nv = np.linalg.norm(v)
                self.centroide[tag] = v / nv if nv > 0 else v
        tema_lista = sorted({t for l in self.temas for t in l})
        self.tema_idx = {t: i for i, t in enumerate(tema_lista)}
        self.tema_mat = np.zeros((self.n, len(tema_lista)))
        for i, l in enumerate(self.temas):
            for t in l:
                self.tema_mat[i, self.tema_idx[t]] = 1.0

    def _carregar_uso_semanal(self) -> None:
        u = pd.read_parquet(self.p / "uso_semanal.parquet")
        u["semana"] = pd.to_datetime(u["semana"])
        u["idx"] = u["servico_id"].astype(int).map(self.sid2idx)
        u = u.dropna(subset=["idx"])
        self.sem0 = date(2025, 6, 9)
        nw = ((date(2026, 9, 21) - self.sem0).days // 7) + 1
        self.nw = nw
        self.W_nao = np.full((self.n, nw), np.nan)
        self.W_sim = np.zeros((self.n, nw))
        k = ((u["semana"] - pd.Timestamp(self.sem0)).dt.days // 7).values
        ok = (k >= 0) & (k < nw)
        for login, idx, kk, cl in zip(u["login"].values[ok], u["idx"].values[ok].astype(int),
                                      k[ok], u["cliques"].astype(float).values[ok]):
            if login == "nao":
                self.W_nao[idx, kk] = cl
            else:
                self.W_sim[idx, kk] = cl
        self.W_all = np.nan_to_num(self.W_nao) + self.W_sim

    # ------------------------------------------------------------ sazonalidade
    def _col(self, d: date) -> int:
        return (d - self.sem0).days // 7

    def _saz(self, ref: date) -> Dict[str, np.ndarray]:
        if ref in self._saz_cache:
            return self._saz_cache[ref]
        if len(self._saz_cache) >= 64:  # a API aceita datas arbitrarias: limita a memoria
            self._saz_cache.clear()
        kmax = min(self._col(self.corte - timedelta(days=7)), self.nw - 1)
        ref_w = ref - timedelta(days=ref.weekday())
        c = self._col(ref_w - timedelta(days=364))
        cols = [k for k in range(c - 1, c + 2) if 0 <= k <= kmax]
        season = np.ones(self.n)
        if cols:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=RuntimeWarning)
                win = np.nanmean(self.W_nao[:, cols], axis=1)
                base = np.nanmean(self.W_nao[:, : kmax + 1], axis=1)
                ratio = win / base
            season = np.where(np.isnan(ratio), 1.0, ratio)
        kr = self._col(ref_w)
        a4, b4 = max(0, min(kr - 4, kmax)), max(0, min(kr, kmax + 1))
        a8, b8 = max(0, min(kr - 12, kmax)), max(0, min(kr - 4, kmax + 1))
        m4 = self.W_all[:, a4:b4].mean(axis=1) if b4 > a4 else np.zeros(self.n)
        m8 = self.W_all[:, a8:b8].mean(axis=1) if b8 > a8 else np.zeros(self.n)
        trend = (m4 + 3.0) / (m8 + 3.0)
        idx = 0.5 * np.clip(season, 0, 5) + 0.5 * np.clip(trend, 0, 5)
        score = np.clip((idx - 1.0) / 1.5, 0, 1)
        out = {"score": score, "season": season, "trend": trend}
        self._saz_cache[ref] = out
        return out

    # ----------------------------------------------------------------- pesos
    def _pesos(self, grupos: List[str], ativos: Dict[str, bool]) -> Dict[str, float]:
        if grupos:
            acc = {k: 0.0 for k in SINAIS}
            for g in grupos:
                pw = dict(PESOS_BASE)
                pw.update(AJUSTE_GRUPO[g])
                for k in SINAIS:
                    acc[k] += pw[k] / len(grupos)
            pesos = acc
        else:
            pesos = dict(PESOS_BASE)
        for k in SINAIS:
            if not ativos.get(k, True):
                pesos[k] = 0.0
        tot = sum(pesos.values())
        return {k: v / tot for k, v in pesos.items()} if tot > 0 else dict(PESOS_BASE)

    # ----------------------------------------------------------------- score
    def _calcular(self, cidadao_id: str, prefs: Preferencias, ref: date) -> Dict:
        c = self.cid.get(cidadao_id)
        tags_todas = self.tags_all.get(cidadao_id, [])
        tags = [t for t in tags_todas if (prefs.consentimento_saude or t not in TAGS_SAUDE)]
        if not prefs.usar_perfil:
            tags = []
        h = self.hist.get(cidadao_id) if prefs.usar_historico else None
        wvec = np.zeros(self.n)
        if h is not None:
            np.add.at(wvec, h[0], h[1])
        tem_hist = wvec.sum() > 0
        conhecidos = np.zeros(self.n, dtype=bool)
        if prefs.usar_historico and cidadao_id in self.hist:
            conhecidos[self.hist[cidadao_id][0]] = True

        sin: Dict[str, np.ndarray] = {}
        # perfil: servicos cujo publico-alvo bate com alguma tag
        match = np.zeros(self.n, dtype=bool)
        for t in tags:
            if t in self.tag_srv:
                match |= self.tag_srv[t]
        sin["perfil"] = match.astype(float)
        # segmento comportamental (o que perfis parecidos usam)
        segs: Dict[str, np.ndarray] = {}
        if prefs.usar_perfil and c:
            segs["faixa"] = 0.5 * self.seg_faixa[c["faixa_etaria"]]
            for t in tags:
                if t in self.seg_tag:
                    segs[t] = self.seg_tag[t]
        if segs:
            tot_w = 0.5 + sum(1.0 for k in segs if k != "faixa")
            sin["segmento"] = sum(segs.values()) / tot_w
        else:
            sin["segmento"] = np.zeros(self.n)
        usar_bairro = prefs.usar_bairro and bool(c)
        sin["bairro"] = self.seg_rpa[int(c["rpa"])] if usar_bairro else np.zeros(self.n)
        saz = self._saz(ref) if prefs.usar_sazonalidade else None
        sin["saz"] = saz["score"] if saz else np.zeros(self.n)
        # proximo passo
        if tem_hist:
            prox = (wvec @ self.P) / wvec.sum()
            sin["proximo"] = np.clip(prox / 0.15, 0, 1)
        else:
            sin["proximo"] = np.zeros(self.n)
        # conteudo: historico (se houver) + centroide dos perfis
        u = np.zeros(self.X.shape[1])
        if tem_hist:
            uh = self.X.T.dot(wvec)
            nu = np.linalg.norm(uh)
            if nu > 0:
                u += 0.6 * uh / nu
        cents = [self.centroide[t] for t in tags if t in self.centroide]
        if cents:
            up = np.mean(cents, axis=0)
            nu = np.linalg.norm(up)
            u += (0.4 if tem_hist else 1.0) * (up / nu if nu > 0 else up)
        if np.linalg.norm(u) > 0:
            cos = self.X.dot(u) / np.linalg.norm(u)
            sin["conteudo"] = cos / max(cos.max(), 1e-9)
        else:
            sin["conteudo"] = np.zeros(self.n)
        sin["pop"] = self.pop
        sin["qualidade"] = self.qualidade

        grupos = sorted({GRUPO_PESO[t] for t in tags if t in GRUPO_PESO})
        ativos = {
            "perfil": prefs.usar_perfil, "segmento": prefs.usar_perfil and bool(segs),
            "bairro": usar_bairro, "saz": prefs.usar_sazonalidade,
            "proximo": tem_hist, "conteudo": bool(tem_hist or cents),
        }
        pesos = self._pesos(grupos, ativos)
        beta = float(np.mean([BETA_GRUPO[g] for g in grupos])) if grupos else BETA_BASE
        if not prefs.usar_perfil:
            beta = 0.0
        base = sum(pesos[k] * sin[k] for k in SOMA)
        final = base * (1.0 + beta * sin["perfil"])
        # servicos de publico especifico sem aderencia ao cidadao perdem forca
        ajuste = np.where(self.restrito & ~match, 0.45, 1.0) * self.fator_digital
        final = final * ajuste

        pesos_d = dict(pesos)
        pesos_d["pop"] = 0.0
        tot = sum(pesos_d.values())
        if tot > 0:
            pesos_d = {k: v / tot for k, v in pesos_d.items()}
        base_d = sum(pesos_d[k] * sin[k] for k in SOMA)
        disc = (base_d + 0.25 * sin["conteudo"]) * (1.0 + 2.0 * beta * sin["perfil"]) * ajuste
        return dict(beta=beta, base=base, c=c, tags=tags, segs=segs, sin=sin, pesos=pesos, final=final, disc=disc,
                    ajuste=ajuste, wvec=wvec, tem_hist=tem_hist, conhecidos=conhecidos,
                    match=match, saz=saz, usar_historico=prefs.usar_historico)

    # --------------------------------------------------------------- motivos
    def _motivo(self, s: int, x: Dict, principal: str) -> str:
        if principal == "perfil":
            for t in x["tags"]:
                if t in self.tag_srv and self.tag_srv[t][s]:
                    return TEXTO_PERFIL[t]
        if principal == "segmento" and x["segs"]:
            melhor = max(x["segs"], key=lambda k: x["segs"][k][s])
            return TEXTO_SEGMENTO.get(melhor, TEXTO_SEGMENTO_PADRAO)
        if principal == "bairro":
            return f"Muito procurado por quem mora na sua região (RPA {int(x['c']['rpa'])})."
        if principal == "saz":
            if x["saz"]["season"][s] >= 1.3:
                return "Costuma ser mais procurado nesta época do ano."
            return "A procura por este serviço está crescendo nas últimas semanas."
        if principal == "proximo":
            contrib = x["wvec"] * self.P[:, s]
            a = int(np.argmax(contrib))
            return f"Quem usou «{self.nome[a]}» costuma usar também este serviço."
        if principal == "conteudo":
            ut = x["wvec"] @ self.tema_mat
            temas = [self.tema_idx[t] for t in self.temas[s]]
            if temas and ut.sum() > 0:
                melhor = max(temas, key=lambda i: ut[i])
                if ut[melhor] > 0:
                    nome = [k for k, v in self.tema_idx.items() if v == melhor][0]
                    return f"Parecido com serviços de {nome} que você já usou."
            if self.tema1[s]:
                if x["tags"]:
                    return f"Serviço de {self.tema1[s]} que combina com o seu perfil."
                return f"Serviço de {self.tema1[s]} que pode ajudar você."
        return "Um dos serviços mais usados no app."

    def _principal(self, s: int, x: Dict) -> str:
        contrib = {k: x["pesos"][k] * x["sin"][k][s] for k in SINAIS_COM_MOTIVO}
        contrib["perfil"] = x["beta"] * x["sin"]["perfil"][s] * x["base"][s]
        # popularidade so explica quando nada mais pesa
        melhor = max(contrib, key=lambda k: contrib[k] if k != "pop" else contrib[k] * 0.5)
        return melhor if contrib[melhor] > 0.005 else "pop"

    # ------------------------------------------------------------- selecao
    def _escolher(self, ordem: np.ndarray, qtd: int, estado: Dict, banir: set) -> List[int]:
        escolhidos: List[int] = []
        for rigido in (True, False):
            for s in ordem:
                if len(escolhidos) >= qtd:
                    return escolhidos
                s = int(s)
                if s in estado["set"] or s in banir:
                    continue
                if rigido and (estado["pref"].get(self.prefixo[s], 0) >= 2
                               or estado["tema"].get(self.tema1[s], 0) >= 4):
                    continue
                estado["set"].add(s)
                estado["pref"][self.prefixo[s]] = estado["pref"].get(self.prefixo[s], 0) + 1
                estado["tema"][self.tema1[s]] = estado["tema"].get(self.tema1[s], 0) + 1
                escolhidos.append(s)
        return escolhidos

    def recomendar(self, cidadao_id: str, limite: int = 10, prefs: Optional[Preferencias] = None,
                   vagas_descoberta: int = 1, data_ref: Optional[date] = None,
                   detalhe: bool = False) -> List[Dict]:
        prefs = prefs or Preferencias()
        ref = data_ref or self.ref
        x = self._calcular(cidadao_id, prefs, ref)
        elegivel = ~x["conhecidos"]
        score = np.where(elegivel, x["final"], -1.0)
        ordem = np.argsort(-score, kind="stable")
        ordem = ordem[score[ordem] > 0]

        n_desc = min(vagas_descoberta, limite // 3)
        estado = {"set": set(), "pref": {}, "tema": {}}
        principais = self._escolher(ordem, limite - n_desc, estado, set())
        score_d = np.where(elegivel & self.cauda & (x["ajuste"] >= 1.0) & (x["disc"] > 0), x["disc"], -1.0)
        ordem_d = np.argsort(-score_d, kind="stable")
        ordem_d = ordem_d[score_d[ordem_d] > 0]
        descobertas = self._escolher(ordem_d, n_desc, estado, set())
        extras = self._escolher(ordem, limite - len(principais) - len(descobertas), estado, set())
        principais += extras

        posicoes_desc = [p for p in (3, 6, 9) if p < limite][: len(descobertas)]
        fila_p, fila_d = list(principais), list(descobertas)
        final: List[tuple] = []
        for pos in range(limite):
            if pos in posicoes_desc and fila_d:
                final.append((fila_d.pop(0), "descoberta"))
            elif fila_p:
                final.append((fila_p.pop(0), "para_voce"))
            elif fila_d:
                final.append((fila_d.pop(0), "descoberta"))

        itens = []
        for pos, (s, tipo) in enumerate(final, start=1):
            principal = self._principal(s, x) if tipo == "para_voce" else self._principal_desc(s, x)
            motivo = self._motivo(s, x, principal)
            if tipo == "descoberta":
                motivo = "Descoberta: " + motivo[0].lower() + motivo[1:]
            r = self.sv.iloc[s]
            item = {
                "posicao": pos,
                "servico_id": int(self.ids[s]),
                "nome": self.nome[s],
                "orgao": r["orgao_sigla"],
                "tema": self.tema1[s],
                "natureza": r["natureza"],
                "gratuito": str(r["gratuito"]).lower() == "true",
                "nivel_digital": None if np.isnan(self.nivel[s]) else int(self.nivel[s]),
                "canal_app": r["canal_app"] or None,
                "motivo": motivo,
                "sinal_principal": principal,
                "tipo": tipo,
                "novo": True if x["usar_historico"] else None,
            }
            if detalhe:
                item["sinais"] = {k: round(float(x["sin"][k][s]), 3) for k in SINAIS}
                item["pesos"] = {k: round(float(v), 3) for k, v in x["pesos"].items()}
                item["score"] = round(float(x["final"][s]), 4)
            itens.append(item)
        return itens

    def _principal_desc(self, s: int, x: Dict) -> str:
        contrib = {"perfil": x["sin"]["perfil"][s], "conteudo": x["sin"]["conteudo"][s],
                   "segmento": x["sin"]["segmento"][s], "bairro": 0.5 * x["sin"]["bairro"][s]}
        if x["sin"]["perfil"][s] > 0:
            return "perfil"
        melhor = max(contrib, key=contrib.get)
        return melhor if contrib[melhor] > 0.05 else "conteudo"

    # -------------------------------------------------------------- auxiliares
    def perfis_ativos(self, cidadao_id: str, prefs: Preferencias) -> List[str]:
        tags = self.tags_all.get(cidadao_id, [])
        return [t for t in tags if prefs.consentimento_saude or t not in TAGS_SAUDE]

    def proximos_passos(self, servico_id: int, limite: int = 5) -> List[Dict]:
        s = self.sid2idx.get(int(servico_id))
        if s is None:
            return []
        linha = self.P[s]
        out = []
        for b in np.argsort(-linha)[:limite]:
            if linha[b] <= 0:
                break
            out.append({"servico_id": int(self.ids[b]), "nome": self.nome[b],
                        "probabilidade": round(float(linha[b]), 3)})
        return out

    def detalhe_servico(self, servico_id: int) -> Optional[Dict]:
        s = self.sid2idx.get(int(servico_id))
        if s is None:
            return None
        r = self.sv.iloc[s]
        return {
            "servico_id": int(self.ids[s]), "nome": self.nome[s], "orgao": r["orgao_nome"],
            "orgao_sigla": r["orgao_sigla"], "temas": self.temas[s], "publicos_alvo": self.publicos[s],
            "natureza": r["natureza"], "descricao": r["descricao"], "requisitos": r["requisitos"],
            "passos": r["passos"], "gratuito": str(r["gratuito"]).lower() == "true",
            "canal_web": r["canal_web"] or None, "canal_app": r["canal_app"] or None,
            "nivel_digital": None if np.isnan(self.nivel[s]) else int(self.nivel[s]),
            "nota_media": None if np.isnan(self.nota[s]) else float(self.nota[s]),
        }
