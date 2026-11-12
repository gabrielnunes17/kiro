"""Tipo de perfil do cidadao: o que ele E (cadastro) + o que ele FAZ (historico, pedidos, feedback).

O perfil molda o formato da vitrine (ver perfis_vitrine.py) e alimenta o motor com tags inferidas.

Regras de privacidade:
- Servicos de Saude nunca entram na inferencia de tipo nem nos temas de foco sem consentimento_saude.
- usar_historico=False desliga inferencia, temas, maturidade digital e feedback.
- usar_perfil=False resulta em tipo "geral" (sem inferencia).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.motor import Motor, Preferencias

# Tipo -> tags do motor que o caracterizam.
TIPO_TAGS: Dict[str, List[str]] = {
    "pcd": ["pcd"],
    "idoso": ["idoso"],
    "familia": ["vulnerabilidade", "crianca_pequena", "crianca_escolar"],
    "empreendedor": ["empreendedor"],
    "jovem_estudante": ["jovem", "estudante"],
}
# Quando o cadastro tem varios tipos, o primeiro da lista e o principal.
PRIORIDADE = ["pcd", "idoso", "familia", "empreendedor", "jovem_estudante"]
ROTULOS = {"pcd": "Pessoa com deficiência", "idoso": "Pessoa idosa", "familia": "Família",
           "empreendedor": "Empreendedor", "jovem_estudante": "Jovem e estudante", "geral": "Geral"}

# Cadastro vale 0,70 (menos 0,01 por posicao na prioridade). Um tipo inferido so passa a
# principal quando sua confianca supera isso; abaixo de MIN_INFERIDO nem e considerado.
SCORE_CADASTRO = 0.70
MIN_INFERIDO = 0.40
INFER_MIN_SERVICOS = 3     # servicos distintos do tipo no historico
INFER_MIN_SHARE = 0.20     # fatia do uso (ponderada por recencia) em servicos do tipo
INFER_MIN_LIFT = 2.0       # fatia do cidadao / fatia media da populacao

MOMENTOS = ("novo", "explorador", "recorrente", "retomada")
MIN_EVENTOS = 3           # abaixo disso, o cidadao e "novo"
FOCO_RECORRENTE = 0.40    # fatia do tema mais usado que caracteriza "recorrente"
JANELA_PEDIDO_DIAS = 30   # pedido enviado ha menos disso ainda conta como "retomada"
# Media do nivel digital (0 a 4) dos servicos usados. Calibrado em scripts/analisar_perfis.py:
# a maioria dos servicos tem nivel 3 ou 4, entao os cortes ficam perto dos quartis reais.
MATURIDADE_BAIXA = 3.0
MATURIDADE_ALTA = 3.7

# Feedback implicito (por servico). Fator final fica entre 0,5 e 1,3.
FB_CLIQUE, FB_CLIQUE_MAX = 0.05, 3
FB_CONCLUSAO, FB_CONCLUSAO_MAX = 0.10, 2
FB_ABANDONO, FB_ABANDONO_MAX = -0.15, 3
FB_NOTA_BAIXA, FB_NOTA_ALTA = -0.25, 0.10


@dataclass
class Contexto:
    """Dados do proprio cidadao guardados pela API (nao fazem parte do motor)."""
    pedidos: List[Dict] = field(default_factory=list)
    feedback: Dict[int, float] = field(default_factory=dict)

    def rascunhos(self) -> List[Dict]:
        return [p for p in self.pedidos if p["status"] == "rascunho"]

    def enviados_recentes(self, agora: Optional[datetime] = None) -> List[Dict]:
        limite = (agora or datetime.utcnow()) - timedelta(days=JANELA_PEDIDO_DIAS)
        out = []
        for p in self.pedidos:
            if p["status"] != "enviado" or not p.get("enviado_em"):
                continue
            if datetime.strptime(p["enviado_em"], "%Y-%m-%d %H:%M:%S") >= limite:
                out.append(p)
        return out

    def servicos_em_pedidos(self) -> set:
        return {p["servico_id"] for p in self.rascunhos() + self.enviados_recentes()}


@dataclass
class Perfil:
    tipo: str
    tipo_base: str
    secundarios: List[str]
    inferidos: List[Dict]
    momento: str
    maturidade_digital: Optional[str]
    temas_foco: List[str]
    confianca: float
    origem: str  # cadastro | comportamento | simulado | padrao
    tags_inferidas: List[str] = field(default_factory=list)  # uso interno, vai para o motor

    def publico(self) -> Dict:
        return {"tipo": self.tipo, "rotulo": ROTULOS[self.tipo], "tipo_base": self.tipo_base,
                "secundarios": self.secundarios, "inferidos": self.inferidos, "momento": self.momento,
                "maturidade_digital": self.maturidade_digital, "temas_foco": self.temas_foco,
                "confianca": self.confianca, "origem": self.origem}


def tipos_do_cadastro(tags: List[str]) -> List[str]:
    return [t for t in PRIORIDADE if set(TIPO_TAGS[t]) & set(tags)]


def fator_feedback(eventos: List[Tuple[int, str, int]], notas: List[Tuple[int, int]]) -> Dict[int, float]:
    """Converte cliques, conclusoes, abandonos e notas do cidadao em fator por servico."""
    delta: Dict[int, float] = {}
    for sid, tipo, n in eventos:
        if tipo == "clique":
            d = FB_CLIQUE * min(n, FB_CLIQUE_MAX)
        elif tipo == "conclusao":
            d = FB_CONCLUSAO * min(n, FB_CONCLUSAO_MAX)
        elif tipo == "abandono":
            d = FB_ABANDONO * min(n, FB_ABANDONO_MAX)
        else:
            continue
        delta[sid] = delta.get(sid, 0.0) + d
    for sid, nota in notas:
        if nota <= 2:
            delta[sid] = delta.get(sid, 0.0) + FB_NOTA_BAIXA
        elif nota >= 4:
            delta[sid] = delta.get(sid, 0.0) + FB_NOTA_ALTA
    return {sid: float(np.clip(1.0 + d, 0.5, 1.3)) for sid, d in delta.items() if d != 0.0}


class Analisador:
    """Define o perfil de um cidadao. Pre-calcula mascaras e taxas medias uma unica vez."""

    def __init__(self, motor: Motor) -> None:
        self.m = motor
        self.mask = {
            t: np.logical_or.reduce([motor.tag_srv[g] for g in TIPO_TAGS[t] if g in motor.tag_srv])
            for t in PRIORIDADE
        }
        self.saude = np.array([any(x.startswith("Saúde") for x in tm) for tm in motor.temas])
        hidx = motor.h["idx"].values
        self.base = {t: float(self.mask[t][hidx].mean()) for t in PRIORIDADE}

    # ------------------------------------------------------------------
    def _historico(self, cid: str, prefs: Preferencias) -> Tuple[np.ndarray, np.ndarray, int]:
        """Retorna (indices, pesos, total). Sem consentimento, saude sai de indices/pesos, mas
        `total` conta todos os acessos: so a quantidade define o momento, nunca o conteudo."""
        vazio = (np.array([], dtype=int), np.array([], dtype=float), 0)
        if not prefs.usar_historico or cid not in self.m.hist:
            return vazio
        idx, w = self.m.hist[cid]
        total = len(idx)
        if not prefs.consentimento_saude:
            k = ~self.saude[idx]
            idx, w = idx[k], w[k]
        return idx, w, total

    def _inferir(self, idx: np.ndarray, w: np.ndarray, excluir: List[str]) -> List[Dict]:
        tot = float(w.sum())
        if tot <= 0:
            return []
        out = []
        for t in PRIORIDADE:
            if t in excluir:
                continue
            sel = self.mask[t][idx]
            n_dist = len(set(idx[sel].tolist()))
            share = float(w[sel].sum()) / tot
            lift = share / max(self.base[t], 1e-6)
            if n_dist >= INFER_MIN_SERVICOS and share >= INFER_MIN_SHARE and lift >= INFER_MIN_LIFT:
                conf = min(1.0, lift / 4.0) * min(1.0, n_dist / 6.0)
                if conf >= MIN_INFERIDO:
                    out.append({"tipo": t, "confianca": round(conf, 2)})
        return sorted(out, key=lambda i: -i["confianca"])

    def _temas(self, idx: np.ndarray, w: np.ndarray) -> Tuple[List[str], float]:
        pesos: Dict[str, float] = {}
        for i, wt in zip(idx.tolist(), w.tolist()):
            t = self.m.tema1[i]
            if t:
                pesos[t] = pesos.get(t, 0.0) + wt
        tot = sum(pesos.values())
        if tot <= 0:
            return [], 0.0
        ordem = sorted(pesos, key=pesos.get, reverse=True)
        return ordem[:3], pesos[ordem[0]] / tot

    def _maturidade(self, idx: np.ndarray, w: np.ndarray) -> Optional[str]:
        if len(idx) == 0:
            return None
        nv = self.m.nivel[idx]
        ok = ~np.isnan(nv)
        if not ok.any() or w[ok].sum() <= 0:
            return None
        media = float(np.average(nv[ok], weights=w[ok]))
        if media < MATURIDADE_BAIXA:
            return "baixa"
        return "alta" if media >= MATURIDADE_ALTA else "media"

    # ------------------------------------------------------------------
    def definir(self, cid: str, prefs: Preferencias, ctx: Optional[Contexto] = None,
                tags_forcadas: Optional[List[str]] = None, momento_forcado: Optional[str] = None) -> Perfil:
        ctx = ctx or Contexto()
        simulado = bool(tags_forcadas)
        tags = tags_forcadas if simulado else self.m.tags_all.get(cid, [])
        cad = tipos_do_cadastro(tags) if prefs.usar_perfil else []

        idx, w, total = self._historico(cid, prefs)
        inferidos = []
        if prefs.usar_perfil and not simulado:
            inferidos = self._inferir(idx, w, cad)

        candidatos = {t: SCORE_CADASTRO - 0.01 * PRIORIDADE.index(t) for t in cad}
        candidatos.update({i["tipo"]: i["confianca"] for i in inferidos})
        tipo = max(candidatos, key=candidatos.get) if candidatos else "geral"
        if simulado:
            origem = "simulado"
        elif tipo == "geral":
            origem = "padrao"
        else:
            origem = "cadastro" if tipo in cad else "comportamento"

        temas, foco = self._temas(idx, w)
        if momento_forcado:
            momento = momento_forcado
        elif ctx.rascunhos() or ctx.enviados_recentes():
            momento = "retomada"
        elif total < MIN_EVENTOS:
            momento = "novo"
        else:
            momento = "recorrente" if foco >= FOCO_RECORRENTE else "explorador"

        confianca = (0.3 if (cad or simulado) else 0.0) + 0.7 * min(1.0, total / 15.0)
        tags_inferidas = sorted({g for i in inferidos for g in TIPO_TAGS[i["tipo"]]})
        return Perfil(
            tipo=tipo, tipo_base=cad[0] if cad else "geral",
            secundarios=[t for t in cad if t != tipo], inferidos=inferidos, momento=momento,
            maturidade_digital=self._maturidade(idx, w), temas_foco=temas,
            confianca=round(min(confianca, 1.0), 2), origem=origem, tags_inferidas=tags_inferidas)
