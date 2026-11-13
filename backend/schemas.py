"""Modelos de request/response da API, com exemplos exibidos no Swagger."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------ comuns
class Erro(BaseModel):
    erro: str = Field(description="Codigo curto do erro (ex.: nao_encontrado, dados_invalidos).")
    detalhe: Any = Field(description="Mensagem explicando o que houve.")

    model_config = ConfigDict(json_schema_extra={"example": {
        "erro": "nao_encontrado", "detalhe": "Serviço não encontrado"}})


RESP_404 = {404: {"model": Erro, "description": "Recurso não encontrado."}}
RESP_409 = {409: {"model": Erro, "description": "Operação incompatível com o estado atual."}}
RESP_422 = {422: {"model": Erro, "description": "Dados inválidos."}}


class PerfilSimulado(str, Enum):
    idoso = "idoso"
    empreendedor = "empreendedor"
    pcd = "pcd"
    familia = "familia"
    jovem_estudante = "jovem_estudante"


class Momento(str, Enum):
    novo = "novo"
    explorador = "explorador"
    recorrente = "recorrente"
    retomada = "retomada"


# ------------------------------------------------------------- preferencias
class Preferencias(BaseModel):
    consentimento_saude: bool = Field(False, description="Autoriza usar dados de saúde (gestante, doença crônica).")
    usar_historico: bool = Field(True, description="Usar o histórico de serviços acessados.")
    usar_perfil: bool = Field(True, description="Usar idade, renda e marcadores de perfil.")
    usar_bairro: bool = Field(True, description="Usar a região (RPA) onde a pessoa mora.")
    usar_sazonalidade: bool = Field(True, description="Usar o que está em alta na época do ano.")

    model_config = ConfigDict(json_schema_extra={"example": {
        "consentimento_saude": False, "usar_historico": True, "usar_perfil": True,
        "usar_bairro": False, "usar_sazonalidade": True}})


# ------------------------------------------------------------------ health
class Health(BaseModel):
    status: str
    servicos: int
    cidadaos: int
    com_historico: int

    model_config = ConfigDict(json_schema_extra={"example": {
        "status": "ok", "servicos": 843, "cidadaos": 89046, "com_historico": 83268}})


# ------------------------------------------------------------------ perfil
class PerfilPublico(BaseModel):
    idade: int
    faixa_etaria: str
    sexo: str
    rpa: int
    aceita_notificacao: bool


class PerfilOut(BaseModel):
    cidadao_id: str
    anonimo: bool = Field(description="True quando o id não existe no cadastro (visitante).")
    perfil: Optional[PerfilPublico] = None
    perfis_ativos: List[str]
    tem_historico: Optional[bool] = None
    preferencias: Preferencias
    saude_disponivel: Optional[bool] = Field(None, description="True só se houve consentimento de saúde.")

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", "anonimo": False,
        "perfil": {"idade": 42, "faixa_etaria": "35-44", "sexo": "F", "rpa": 6, "aceita_notificacao": True},
        "perfis_ativos": ["empreendedor", "mulher"], "tem_historico": True,
        "preferencias": Preferencias().model_dump(), "saude_disponivel": False}})


# ----------------------------------------------------------- recomendacoes
class Item(BaseModel):
    posicao: int
    servico_id: int
    nome: str
    orgao: str
    tema: str
    natureza: str
    gratuito: bool
    nivel_digital: Optional[int] = Field(None, description="0 (presencial) a 4 (100% digital).")
    canal_app: Optional[str] = None
    motivo: str = Field(description="Frase em linguagem simples explicando a sugestão.")
    sinal_principal: str
    tipo: str = Field(description="para_voce, descoberta, regiao, epoca, historico, afinidade ou pedido.")
    novo: Optional[bool] = Field(None, description="True se o cidadão ainda não usou (null sem histórico).")
    sinais: Optional[Dict[str, float]] = Field(None, description="Só com detalhe=true.")
    pesos: Optional[Dict[str, float]] = Field(None, description="Só com detalhe=true.")
    score: Optional[float] = Field(None, description="Só com detalhe=true.")
    pedido_id: Optional[int] = Field(None, description="Só em itens de pedido (tipo=pedido).")
    ultimo_passo: Optional[int] = Field(None, description="Só em itens de pedido.")
    protocolo: Optional[str] = Field(None, description="Só em itens de pedido enviado.")
    status_pedido: Optional[str] = Field(None, description="rascunho ou enviado. Só em itens de pedido.")


EXEMPLO_ITEM = {
    "posicao": 1, "servico_id": 519, "nome": "Ver resultado de exames laboratoriais", "orgao": "SESAU",
    "tema": "Saúde", "natureza": "Emissão de documentos", "gratuito": True, "nivel_digital": 3,
    "canal_app": "205 - Resultados de exames",
    "motivo": "Pessoas com um uso parecido com o seu costumam usar este serviço.",
    "sinal_principal": "proximo", "tipo": "para_voce", "novo": True}


class Contexto(BaseModel):
    cidadao_id: Optional[str] = Field(None, description="Null nas rotas anônimas (sem id).")
    anonimo: bool
    perfil_simulado: Optional[PerfilSimulado] = None
    data_referencia: str = Field(description="Data usada na sazonalidade (AAAA-MM-DD).")
    perfis_ativos: List[str]
    preferencias: Preferencias


class RecomendacoesOut(Contexto):
    itens: List[Item]

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", "anonimo": False, "perfil_simulado": None,
        "data_referencia": "2026-09-28", "perfis_ativos": ["empreendedor", "mulher"],
        "preferencias": Preferencias().model_dump(), "itens": [EXEMPLO_ITEM]}})


class Inferido(BaseModel):
    tipo: str
    confianca: float = Field(description="0 a 1. Quanto o histórico sustenta o tipo.")


class PerfilTipo(BaseModel):
    tipo: str = Field(description="Tipo principal: pcd, idoso, familia, empreendedor, jovem_estudante ou geral.")
    rotulo: str = Field(description="Nome para uso interno do front. Não exibir como etiqueta ao cidadão.")
    tipo_base: str = Field(description="Tipo pelo cadastro. Pode diferir de `tipo` se o comportamento o superar.")
    secundarios: List[str] = Field(description="Outros tipos do cadastro.")
    inferidos: List[Inferido] = Field(description="Tipos sugeridos pelo histórico de uso.")
    momento: str = Field(description="novo, explorador, recorrente ou retomada.")
    maturidade_digital: Optional[str] = Field(None, description="baixa, media ou alta. Null sem histórico.")
    temas_foco: List[str] = Field(description="Até 3 temas mais usados. Sem saúde, salvo consentimento.")
    confianca: float = Field(description="0 a 1. Quanto dado sustenta o perfil.")
    origem: str = Field(description="cadastro, comportamento, simulado ou padrao.")


EXEMPLO_PERFIL_TIPO = {
    "tipo": "empreendedor", "rotulo": "Empreendedor", "tipo_base": "empreendedor",
    "secundarios": [], "inferidos": [{"tipo": "familia", "confianca": 0.55}], "momento": "recorrente",
    "maturidade_digital": "alta", "temas_foco": ["PJ e Autônomo", "Licenças, Alvarás e Permissões"],
    "confianca": 1.0, "origem": "cadastro"}


class TipoPerfilOut(PerfilTipo):
    cidadao_id: str

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", **EXEMPLO_PERFIL_TIPO}})


class Ui(BaseModel):
    densidade: str = Field(description="normal ou baixa (menos itens e menos ruído visual).")
    texto_simples: bool = Field(description="True: usar linguagem e telas mais simples.")


class VitrineOut(BaseModel):
    cidadao_id: Optional[str] = Field(None, description="Null na rota anônima (sem id).")
    anonimo: bool
    perfil_simulado: Optional[PerfilSimulado] = None
    data_referencia: str = Field(description="Data usada na sazonalidade (AAAA-MM-DD).")
    perfil: PerfilTipo = Field(description="Perfil que moldou a vitrine.")
    ui: Ui
    descubra: List[Item] = Field(description="Serviços pouco conhecidos que combinam com o perfil.")
    historico: List[Item] = Field(description="Serviços que o cidadão já usou, do mais recente ao mais antigo.")
    para_voce: List[Item] = Field(description="Próximos passos por perfil, uso parecido e histórico.")
    na_sua_regiao: List[Item] = Field(description="Mais procurados na RPA. Vazio sem região ou com `usar_bairro` desligado.")
    em_alta: List[Item] = Field(description="Em alta nesta época. Vazio com `usar_sazonalidade` desligado.")
    avisos: Dict[str, str] = Field(
        description="Seção vazia e o motivo. `historico`: sem_historico ou historico_desligado. "
                    "`na_sua_regiao`: regiao_desligada ou regiao_desconhecida. `em_alta`: sazonalidade_desligada.")

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", "anonimo": False, "perfil_simulado": None,
        "data_referencia": "2026-09-28",
        "perfil": EXEMPLO_PERFIL_TIPO, "ui": {"densidade": "normal", "texto_simples": False},
        "descubra": [{**EXEMPLO_ITEM, "servico_id": 1475, "tipo": "descoberta", "sinal_principal": "perfil"}],
        "historico": [{**EXEMPLO_ITEM, "servico_id": 953, "motivo": "Você já usou este serviço.",
                       "sinal_principal": "historico", "tipo": "historico", "novo": False}],
        "para_voce": [EXEMPLO_ITEM], "na_sua_regiao": [], "em_alta": [],
        "avisos": {"na_sua_regiao": "regiao_desligada"}}})


# ---------------------------------------------------------------- servicos
class ServicoOut(BaseModel):
    servico_id: int
    nome: str
    orgao: str
    orgao_sigla: str
    temas: List[str]
    publicos_alvo: List[str]
    natureza: str
    descricao: str
    requisitos: str
    passos: str
    gratuito: bool
    canal_web: Optional[str] = None
    canal_app: Optional[str] = None
    nivel_digital: Optional[int] = None
    nota_media: Optional[float] = None

    model_config = ConfigDict(json_schema_extra={"example": {
        "servico_id": 953, "nome": "Ver meus agendamentos de Saúde", "orgao": "Secretaria de Saúde",
        "orgao_sigla": "SESAU", "temas": ["Saúde"], "publicos_alvo": ["População em geral"],
        "natureza": "Agendamento",
        "descricao": "Visualizar a agenda de atendimentos marcados nas Unidades Básicas de Saúde.",
        "requisitos": "- Ter uma solicitação de atendimento agendada.",
        "passos": "- Acesse o app e faça login.", "gratuito": True,
        "canal_web": "https://conecta-saude.recife.pe.gov.br/agendamentos/meus-agendamentos",
        "canal_app": "303 - Minhas consultas/exames agendados", "nivel_digital": 4, "nota_media": None}})


class ProximoPasso(BaseModel):
    servico_id: int
    nome: str
    probabilidade: float

    model_config = ConfigDict(json_schema_extra={"example": {
        "servico_id": 942, "nome": "Agendar consultas e procedimentos na Minha Unidade de Saúde",
        "probabilidade": 0.424}})


class ResumoPesquisa(BaseModel):
    servico_id: int
    total: int
    media: Optional[float] = None
    distribuicao: Dict[str, int] = Field(description="Quantidade de respostas por nota (1 a 5).")

    model_config = ConfigDict(json_schema_extra={"example": {
        "servico_id": 953, "total": 3, "media": 4.33, "distribuicao": {"4": 1, "5": 2}}})


# ---------------------------------------------------------------- personas
class Persona(BaseModel):
    cidadao_id: str
    rotulo: str
    perfil_simulado: Optional[PerfilSimulado] = Field(
        None, description="Valor para o parâmetro perfil_simulado que reproduz o perfil.")
    resumo: str

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", "rotulo": "Microempreendedor", "perfil_simulado": "empreendedor",
        "resumo": "Mulher, 42 anos, RPA 6; empreendedora, MEI, aceita avisos."}})


# ----------------------------------------------------------------- historico
class AcessoIn(BaseModel):
    servico_id: int = Field(description="Serviço que o cidadão acabou de abrir.", examples=[519])

    model_config = ConfigDict(json_schema_extra={"example": {"servico_id": 519}})


class AcessoOut(BaseModel):
    cidadao_id: str
    servico_id: int
    salvo: bool = Field(description="False quando o cidadão desligou `usar_historico` (nada é gravado).")
    acessado_em: Optional[str] = Field(None, description="Data e hora UTC do registro. Null se não salvo.")

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", "servico_id": 519, "salvo": True, "acessado_em": "2026-11-12 20:31:05"}})


# ----------------------------------------------------------------- pedidos
class PedidoIn(BaseModel):
    cidadao_id: str = Field(examples=["C068579"])
    servico_id: int = Field(examples=[953])
    dados: Dict[str, Any] = Field(default_factory=dict, description="Campos do formulário preenchidos até agora.")

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", "servico_id": 953, "dados": {"telefone": "81 99999-0000"}}})


class PedidoPatch(BaseModel):
    dados: Optional[Dict[str, Any]] = Field(None, description="Campos mesclados aos já salvos.")
    ultimo_passo: Optional[int] = Field(None, ge=0, description="Último passo concluído do formulário.")

    model_config = ConfigDict(json_schema_extra={"example": {
        "dados": {"email": "maria@exemplo.com"}, "ultimo_passo": 2}})


class PedidoOut(BaseModel):
    id: int
    protocolo: Optional[str] = Field(None, description="Gerado no envio.")
    cidadao_id: str
    servico_id: int
    status: str = Field(description="rascunho ou enviado.")
    dados: Dict[str, Any]
    ultimo_passo: int
    simulado: bool = Field(description="True: o pedido não é encaminhado a nenhum órgão (protótipo).")
    criado_em: str
    enviado_em: Optional[str] = None

    model_config = ConfigDict(json_schema_extra={"example": {
        "id": 1, "protocolo": "KDK-2026-000001", "cidadao_id": "C068579", "servico_id": 953,
        "status": "enviado", "dados": {"telefone": "81 99999-0000", "email": "maria@exemplo.com"},
        "ultimo_passo": 2, "simulado": True, "criado_em": "2026-11-12 14:00:00",
        "enviado_em": "2026-11-12 14:05:00"}})


class EtapaOut(BaseModel):
    etapa: str
    status: str = Field(description="concluida ou pendente.")
    horas_simuladas: int = Field(description="Horas após o envio em que a etapa ocorre (simulação).")
    criado_em: str


class AcompanhamentoOut(BaseModel):
    pedido_id: int
    protocolo: Optional[str]
    status: str
    etapas: List[EtapaOut]

    model_config = ConfigDict(json_schema_extra={"example": {
        "pedido_id": 1, "protocolo": "KDK-2026-000001", "status": "enviado",
        "etapas": [
            {"etapa": "recebido", "status": "concluida", "horas_simuladas": 0, "criado_em": "2026-11-12 14:05:00"},
            {"etapa": "em_analise", "status": "concluida", "horas_simuladas": 24, "criado_em": "2026-11-12 14:05:00"},
            {"etapa": "decisao", "status": "pendente", "horas_simuladas": 72, "criado_em": "2026-11-12 14:05:00"}]}})


# ------------------------------------------------------------ eventos de UX
class TipoEvento(str, Enum):
    visualizacao = "visualizacao"
    clique = "clique"
    inicio_pedido = "inicio_pedido"
    passo = "passo"
    conclusao = "conclusao"
    abandono = "abandono"


class EventoUxIn(BaseModel):
    cidadao_id: str = Field(description="Gravado apenas como pseudônimo (hash).", examples=["C068579"])
    tipo: TipoEvento
    servico_id: Optional[int] = None
    passo: Optional[int] = Field(None, ge=0)
    posicao: Optional[int] = Field(None, ge=1, le=10, description="Posição do item na lista clicada.")
    origem: Optional[str] = Field(None, max_length=60, description="Ex.: vitrine/para_voce_agora.")
    duracao_ms: Optional[int] = Field(None, ge=0)

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", "tipo": "clique", "servico_id": 519, "posicao": 1,
        "origem": "vitrine/para_voce_agora", "duracao_ms": 1200}})


class RegistroOut(BaseModel):
    id: int
    model_config = ConfigDict(json_schema_extra={"example": {"id": 1}})


class PesquisaIn(BaseModel):
    cidadao_id: str = Field(description="Gravado apenas como pseudônimo (hash).", examples=["C068579"])
    servico_id: Optional[int] = None
    nota: int = Field(ge=1, le=5)
    comentario: Optional[str] = Field(None, max_length=500)

    model_config = ConfigDict(json_schema_extra={"example": {
        "cidadao_id": "C068579", "servico_id": 953, "nota": 5, "comentario": "Foi rápido e fácil."}})
