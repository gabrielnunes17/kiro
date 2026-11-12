"""Personas de demonstracao do tutorial (secao 4), todas de cidadaos.csv (dados ficticios)."""
from __future__ import annotations

from typing import Dict, List

PERSONAS: List[Dict] = [
    {"cidadao_id": "C007938", "rotulo": "Idosa", "perfil_simulado": "idoso",
     "resumo": "Mulher, 68 anos, RPA 3; nenhum marcador."},
    {"cidadao_id": "C068579", "rotulo": "Microempreendedor", "perfil_simulado": "empreendedor",
     "resumo": "Mulher, 42 anos, RPA 6; empreendedora, MEI, aceita avisos."},
    {"cidadao_id": "C059592", "rotulo": "Pessoa com deficiência", "perfil_simulado": "pcd",
     "resumo": "Mulher, 63 anos, RPA 5; pessoa com deficiência, Cadastro Único, aceita avisos."},
    {"cidadao_id": "C036462", "rotulo": "Jovem estudante", "perfil_simulado": "jovem_estudante",
     "resumo": "Mulher, 19 anos, RPA 2; estudante, aceita avisos."},
    {"cidadao_id": "C039227", "rotulo": "Família no Cadastro Único", "perfil_simulado": "familia",
     "resumo": "Homem, 26 anos, RPA 4; Cadastro Único, Bolsa Família, aceita avisos."},
    {"cidadao_id": "C076260", "rotulo": "Família com criança", "perfil_simulado": "familia",
     "resumo": "Mulher, 25 anos, RPA 5; Cadastro Único, criança de 7 a 11 anos na família."},
    {"cidadao_id": "C006566", "rotulo": "Gestante", "perfil_simulado": None,
     "resumo": "Mulher, 37 anos, RPA 6; Cadastro Único, Bolsa Família, aceita avisos."},
    {"cidadao_id": "C062244", "rotulo": "Doença crônica", "perfil_simulado": "idoso",
     "resumo": "Homem, 70 anos, RPA 6; Cadastro Único, aceita avisos."},
]
# Os resumos acima omitem de proposito os dados de saude (gestante, hipertensao, diabetes):
# eles so aparecem para o cidadao se ele der consentimento.

# Modo demonstracao: cada perfil simulado forca as tags do grupo (sem dados de saude).
PERFIS_SIMULADOS: Dict[str, List[str]] = {
    "idoso": ["idoso"],
    "empreendedor": ["empreendedor"],
    "pcd": ["pcd"],
    "familia": ["vulnerabilidade", "crianca_pequena", "crianca_escolar"],
    "jovem_estudante": ["jovem", "estudante"],
}
