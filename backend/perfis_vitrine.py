"""Configuracao declarativa da vitrine por tipo de perfil, momento e maturidade digital.

Para mudar o comportamento de um perfil, edite os dados abaixo: nao ha logica espalhada.
O layout nunca traz secao vazia, e os campos antigos (secoes, avisos) seguem na resposta.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Dict, List, Optional

from backend.perfil import Contexto, Perfil

BASE_ORDEM = ["para_voce_agora", "na_sua_regiao", "em_alta_nesta_epoca", "descubra"]
BASE_TAMANHOS = {"para_voce_agora": 5, "na_sua_regiao": 3, "em_alta_nesta_epoca": 3, "descubra": 2}

TEXTOS: Dict[str, Dict[str, str]] = {
    "para_voce_agora": {"titulo": "Para você agora", "subtitulo": "Com base no que você costuma usar"},
    "na_sua_regiao": {"titulo": "Na sua região", "subtitulo": "Muito procurados por quem mora perto de você"},
    "em_alta_nesta_epoca": {"titulo": "Em alta nesta época", "subtitulo": "O que mais procuram neste momento"},
    "descubra": {"titulo": "Descubra", "subtitulo": "Serviços que você talvez ainda não conheça"},
    "continue_de_onde_parou": {"titulo": "Continue de onde parou",
                               "subtitulo": "Pedidos que você começou e ainda não enviou"},
    "acompanhe_seus_pedidos": {"titulo": "Acompanhe seus pedidos",
                               "subtitulo": "Pedidos que você enviou recentemente"},
}

# Secao propria de cada tipo: servicos cujo publico-alvo bate com as tags.
EXTRAS_TIPO: Dict[str, Dict] = {
    "empreendedor": {"id": "para_o_seu_negocio", "tags": ["empreendedor"], "tamanho": 3,
                     "titulo": "Para o seu negócio", "subtitulo": "Serviços para quem trabalha por conta própria"},
    "familia": {"id": "para_a_sua_familia", "tags": ["crianca_pequena", "crianca_escolar", "vulnerabilidade"],
                "tamanho": 3, "titulo": "Para a sua família",
                "subtitulo": "Serviços para famílias e programas sociais"},
    "pcd": {"id": "atendimento_para_pcd", "tags": ["pcd"], "tamanho": 3,
            "titulo": "Atendimento para pessoas com deficiência",
            "subtitulo": "Serviços com atendimento pensado para você"},
    "jovem_estudante": {"id": "para_estudantes_e_jovens", "tags": ["estudante", "jovem"], "tamanho": 3,
                        "titulo": "Para estudar e começar", "subtitulo": "Serviços para jovens e estudantes"},
}

# Ajustes por tipo: tamanhos, ordem e textos que mudam em relacao a base.
AJUSTE_TIPO: Dict[str, Dict] = {
    "idoso": {"tamanhos": {"para_voce_agora": 4, "em_alta_nesta_epoca": 2, "descubra": 1},
              "textos": {"na_sua_regiao": {"titulo": "Perto de você",
                                           "subtitulo": "Serviços muito procurados na sua região"}},
              "ui": {"densidade": "baixa", "texto_simples": True}},
    "empreendedor": {"tamanhos": {"em_alta_nesta_epoca": 4},
                     "ordem": ["para_voce_agora", "para_o_seu_negocio", "em_alta_nesta_epoca",
                               "na_sua_regiao", "descubra"]},
    "pcd": {"ordem": ["para_voce_agora", "atendimento_para_pcd", "na_sua_regiao",
                      "em_alta_nesta_epoca", "descubra"],
            "ui": {"densidade": "baixa", "texto_simples": True}},
    "familia": {"ordem": ["para_voce_agora", "para_a_sua_familia", "na_sua_regiao",
                          "em_alta_nesta_epoca", "descubra"]},
    "jovem_estudante": {"tamanhos": {"descubra": 3},
                        "ordem": ["para_voce_agora", "para_estudantes_e_jovens", "descubra",
                                  "em_alta_nesta_epoca", "na_sua_regiao"]},
}

# Ajustes por momento (aplicados depois dos de tipo).
AJUSTE_MOMENTO: Dict[str, Dict] = {
    "novo": {"tamanhos": {"para_voce_agora": 3, "descubra": 4},
             "textos": {"para_voce_agora": {"titulo": "Comece por aqui",
                                            "subtitulo": "Serviços muito usados por pessoas parecidas com você"}},
             "descubra_antes_da_regiao": True},
    "explorador": {"soma_tamanhos": {"descubra": 2}},
    "recorrente": {"textos": {"para_voce_agora": {"titulo": "Seu próximo passo",
                                                  "subtitulo": "Com base no que você já usou"}}},
    "retomada": {},
}


def montar_config(perfil: Perfil) -> Dict:
    """Devolve {ordem, tamanhos, textos, extras, ui} para o perfil."""
    ordem = list(BASE_ORDEM)
    tamanhos = dict(BASE_TAMANHOS)
    textos = deepcopy(TEXTOS)
    ui = {"densidade": "normal", "texto_simples": False}
    extras: List[Dict] = []

    aj = AJUSTE_TIPO.get(perfil.tipo, {})
    tamanhos.update(aj.get("tamanhos", {}))
    for k, v in aj.get("textos", {}).items():
        textos[k].update(v)
    ui.update(aj.get("ui", {}))
    ex = EXTRAS_TIPO.get(perfil.tipo)
    if ex:
        extras.append({"id": ex["id"], "tags": ex["tags"], "tamanho": ex["tamanho"]})
        textos[ex["id"]] = {"titulo": ex["titulo"], "subtitulo": ex["subtitulo"]}
    ordem = aj.get("ordem", ordem)

    am = AJUSTE_MOMENTO.get(perfil.momento, {})
    tamanhos.update(am.get("tamanhos", {}))
    for k, v in am.get("soma_tamanhos", {}).items():
        tamanhos[k] += v
    for k, v in am.get("textos", {}).items():
        textos[k].update(v)
    if am.get("descubra_antes_da_regiao") and "descubra" in ordem:
        ordem.remove("descubra")
        ordem.insert(ordem.index("na_sua_regiao") if "na_sua_regiao" in ordem else len(ordem), "descubra")

    if perfil.maturidade_digital == "baixa":
        tamanhos = {k: min(v, 3) for k, v in tamanhos.items()}
        extras = [{**e, "tamanho": min(e["tamanho"], 3)} for e in extras]
        ui.update({"densidade": "baixa", "texto_simples": True})

    return {"ordem": ordem, "tamanhos": tamanhos, "textos": textos, "extras": extras, "ui": ui}


def itens_de_pedidos(motor, pedidos: List[Dict], enviados: bool) -> List[Dict]:
    """Converte pedidos em itens da vitrine (servico + dados do pedido)."""
    itens = []
    for p in pedidos:
        d = motor.detalhe_servico(p["servico_id"])
        if d is None:
            continue
        if enviados:
            motivo = f"Pedido {p['protocolo']} enviado. Veja o andamento."
        elif p["ultimo_passo"] > 0:
            motivo = f"Você começou este pedido e parou no passo {p['ultimo_passo']}."
        else:
            motivo = "Você começou este pedido e ainda não enviou."
        itens.append({
            "posicao": len(itens) + 1, "servico_id": d["servico_id"], "nome": d["nome"],
            "orgao": d["orgao_sigla"], "tema": d["temas"][0] if d["temas"] else "",
            "natureza": d["natureza"], "gratuito": d["gratuito"], "nivel_digital": d["nivel_digital"],
            "canal_app": d["canal_app"], "motivo": motivo, "sinal_principal": "pedido",
            "tipo": "pedido", "novo": None, "pedido_id": p["id"], "ultimo_passo": p["ultimo_passo"],
            "protocolo": p["protocolo"], "status_pedido": p["status"],
        })
    return itens


def montar_layout(motor, cfg: Dict, resultado: Dict, perfil: Perfil, ctx: Contexto) -> List[Dict]:
    """Lista ordenada de secoes nao vazias, com titulo e subtitulo adaptados ao perfil."""
    por_id: Dict[str, Dict] = {}
    for sid, itens in {**resultado["secoes"], **resultado.get("extras", {})}.items():
        por_id[sid] = {"itens": itens, "tipo_secao": "recomendacao"}
    ordem = list(cfg["ordem"])
    if perfil.momento == "retomada":
        ped = [("continue_de_onde_parou", ctx.rascunhos(), False),
               ("acompanhe_seus_pedidos", ctx.enviados_recentes(), True)]
        topo = []
        for sid, lista, enviados in ped:
            itens = itens_de_pedidos(motor, lista, enviados)
            if itens:
                por_id[sid] = {"itens": itens, "tipo_secao": "pedido"}
                topo.append(sid)
        ordem = topo + ordem
    layout = []
    for sid in ordem:
        sec = por_id.get(sid)
        if not sec or not sec["itens"]:
            continue
        t = cfg["textos"][sid]
        layout.append({"id": sid, "titulo": t["titulo"], "subtitulo": t["subtitulo"],
                       "tipo_secao": sec["tipo_secao"], "itens": sec["itens"]})
    return layout
