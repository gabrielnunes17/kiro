"""Configuracao declarativa da vitrine por tipo de perfil, momento e maturidade digital.

Define so o tamanho de cada secao e a densidade da tela. Para mudar o comportamento de um
perfil, edite os dados abaixo: nao ha logica espalhada.
"""
from __future__ import annotations

from typing import Dict

from backend.perfil import Perfil

# Chaves internas do motor (para_voce_agora e em_alta_nesta_epoca); a API as expoe como
# para_voce e em_alta. "historico" e tratado a parte, fora do motor de recomendacao.
BASE_TAMANHOS = {"historico": 5, "para_voce_agora": 5, "na_sua_regiao": 3, "em_alta_nesta_epoca": 3,
                 "descubra": 2}

# Ajustes por tipo.
AJUSTE_TIPO: Dict[str, Dict] = {
    "idoso": {"tamanhos": {"historico": 3, "para_voce_agora": 4, "em_alta_nesta_epoca": 2, "descubra": 1},
              "ui": {"densidade": "baixa", "texto_simples": True}},
    "empreendedor": {"tamanhos": {"em_alta_nesta_epoca": 4}},
    "pcd": {"ui": {"densidade": "baixa", "texto_simples": True}},
    "jovem_estudante": {"tamanhos": {"descubra": 3}},
}

# Ajustes por momento (aplicados depois dos de tipo).
AJUSTE_MOMENTO: Dict[str, Dict] = {
    "novo": {"tamanhos": {"para_voce_agora": 3, "descubra": 4}},
    "explorador": {"soma_tamanhos": {"descubra": 2}},
}


def montar_config(perfil: Perfil) -> Dict:
    """Devolve {tamanhos, ui} para o perfil."""
    tamanhos = dict(BASE_TAMANHOS)
    ui = {"densidade": "normal", "texto_simples": False}

    aj = AJUSTE_TIPO.get(perfil.tipo, {})
    tamanhos.update(aj.get("tamanhos", {}))
    ui.update(aj.get("ui", {}))

    am = AJUSTE_MOMENTO.get(perfil.momento, {})
    tamanhos.update(am.get("tamanhos", {}))
    for k, v in am.get("soma_tamanhos", {}).items():
        tamanhos[k] += v

    if perfil.maturidade_digital == "baixa":
        tamanhos = {k: min(v, 3) for k, v in tamanhos.items()}
        ui.update({"densidade": "baixa", "texto_simples": True})

    return {"tamanhos": tamanhos, "ui": ui}
