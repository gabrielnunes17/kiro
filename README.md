# Kodiak – Hiperpersonalização

Backend de recomendação de serviços públicos da Carta de Serviços do Recife para o app Kodiak. Ele monta a home de cada cidadão (vitrine) com serviços sugeridos e um motivo em linguagem simples para cada um, respeitando as preferências de privacidade da pessoa.

Projeto de demonstração (hackathon). Os dados são fictícios.

## O que tem aqui

- **Motor de recomendação** (`backend/motor.py`): híbrido e explicável. Combina perfil, segmento, região, sazonalidade, próximo passo na sessão, similaridade de conteúdo, popularidade e qualidade.
- **Perfil do cidadão** (`backend/perfil.py`): define o tipo (idoso, empreendedor, PcD, família, jovem estudante ou geral) e o momento de uso (novo, explorador, recorrente, retomada) a partir do cadastro e do comportamento.
- **API REST** (`backend/api.py`): FastAPI, com Swagger em `/docs`.
- **Persistência** (`backend/db.py`): SQLite com preferências, pedidos, eventos de UX, pesquisas e acessos a serviços.
- **Scripts** (`scripts/`): ETL, backtest, calibração de pesos e geração de recomendações em lote.

## Estrutura

```
backend/
  api.py             rotas da API
  motor.py           motor de recomendação
  perfil.py          tipo e momento do cidadão
  perfis_vitrine.py  tamanho das seções e densidade da tela por perfil
  schemas.py         modelos de request/response (com exemplos do Swagger)
  db.py              SQLite
  personas.py        personas de demonstração
  erros.py           erros padronizados {"erro", "detalhe"}
scripts/
  fase1_etl.py            CSVs de data/raw -> Parquet em data/parquet
  backtest.py             avaliação offline (hit@k, recall@k, MRR)
  calibrar.py             ablação de sinais e pesos
  gerar_recomendacoes.py  gera saidas/recomendacoes.csv e valida as regras
  derrubar_deploy.sh      remove o deploy de demonstração na AWS
tests/                    suíte pytest
run.sh                    atalho para subir a API e rodar os testes
```

## Requisitos

- Python 3.9 ou mais novo
- Dependências fixadas em `requirements.txt`

## Configuração

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Dados

A pasta `data/` fica fora do git. A API lê os arquivos Parquet de `data/parquet/`:

```
cidadaos.parquet  historico.parquet  servicos.parquet  uso_semanal.parquet  visitas_sem_login.parquet
```

Se você só tiver os CSVs em `data/raw/`, gere os Parquet com:

```bash
.venv/bin/python scripts/fase1_etl.py
```

## Como rodar

```bash
./run.sh          # sobe a API em http://127.0.0.1:8000 (Swagger em /docs)
./run.sh dev      # mesma coisa, com recarga automática ao editar o código
./run.sh test     # roda os testes
```

Variáveis opcionais:

| Variável | Padrão | Uso |
|---|---|---|
| `HOST` | `127.0.0.1` | Endereço da API |
| `PORT` | `8000` | Porta da API |
| `KODIAK_DB` | `data/app.db` | Arquivo SQLite (criado sozinho na primeira subida) |
| `KODIAK_SALT` | valor de protótipo | Sal do pseudônimo usado em eventos e pesquisas. Defina um valor próprio fora do ambiente local |

A API carrega o motor inteiro em memória ao subir, o que leva alguns segundos. Se você mudar o código com a API rodando sem `dev`, reinicie para ver a mudança.

## API

A referência completa, com exemplos, fica no Swagger (`/docs`). Visão geral:

| Grupo | Rotas |
|---|---|
| Sistema | `GET /health` |
| Personalização | `GET /vitrine`, `GET /vitrine/{cid}`, `GET /recomendacoes`, `GET /cidadaos/{cid}/recomendacoes`, `GET /personas` |
| Cidadão | `GET /cidadaos/{cid}/perfil`, `GET /cidadaos/{cid}/tipo-perfil`, `GET/PUT /cidadaos/{cid}/preferencias`, `POST /cidadaos/{cid}/historico` |
| Serviços | `GET /servicos/{sid}`, `GET /servicos/{sid}/proximos-passos` |
| Pedidos (simulados) | `POST /pedidos`, `GET /pedidos/{pid}`, `PATCH /pedidos/{pid}`, `POST /pedidos/{pid}/enviar`, `GET /pedidos/{pid}/acompanhamento`, `GET /cidadaos/{cid}/pedidos` |
| Medição | `POST /eventos`, `POST /pesquisas`, `GET /servicos/{sid}/pesquisas` |

Rotas sem id (`/vitrine`, `/recomendacoes`) servem visitantes e não gravam nada no servidor. Rotas com id devolvem 404 para cidadão fora do cadastro. Para testar, use os ids de `GET /personas`.

### Vitrine da home

`GET /vitrine/{cid}` e `GET /vitrine` devolvem o mesmo formato. As cinco seções estão sempre presentes (lista vazia quando desligadas), e nenhum serviço aparece em mais de uma:

| Seção | Conteúdo |
|---|---|
| `descubra` | Serviços pouco conhecidos que combinam com o perfil |
| `historico` | Serviços que o cidadão já usou, do mais recente ao mais antigo |
| `para_voce` | Melhores sugestões do motor |
| `na_sua_regiao` | Mais procurados na região (RPA 1 a 6) |
| `em_alta` | O que está em alta nesta época |

A resposta também traz `perfil` (o que moldou a vitrine), `ui` (`densidade` e `texto_simples`, para o front adaptar a tela) e `avisos` (por que uma seção veio vazia).

Exemplo resumido:

```json
{
  "cidadao_id": "C068579",
  "anonimo": false,
  "data_referencia": "2026-09-28",
  "perfil": { "tipo": "empreendedor", "momento": "recorrente", "...": "..." },
  "ui": { "densidade": "normal", "texto_simples": false },
  "descubra": [ { "servico_id": 1475, "nome": "...", "motivo": "Descoberta: ...", "tipo": "descoberta" } ],
  "historico": [ { "servico_id": 798, "motivo": "Você já usou este serviço.", "tipo": "historico" } ],
  "para_voce": [ "..." ],
  "na_sua_regiao": [],
  "em_alta": [ "..." ],
  "avisos": { "na_sua_regiao": "regiao_desligada" }
}
```

### Histórico de acesso

Quando o cidadão abrir um serviço no app, chame:

```http
POST /cidadaos/{cid}/historico
Content-Type: application/json

{"servico_id": 798}
```

Na próxima vitrine, o serviço aparece no topo de `historico` e deixa de ser sugerido nas outras seções. Abrir o mesmo serviço de novo só o move para o topo. Com `usar_historico` desligado, nada é gravado e a rota responde 200 com `salvo: false`.

Os acessos registrados ainda não alteram o perfil nem o cálculo do motor, que usam o histórico da base.

### Modo demonstração

`perfil_simulado` (idoso, empreendedor, pcd, familia, jovem_estudante), `rpa`, `momento` e `semana` forçam perfil, região, momento e data de referência sem alterar o cadastro.

## Privacidade

- O cidadão liga e desliga cada sinal em `PUT /cidadaos/{cid}/preferencias`: `usar_historico`, `usar_perfil`, `usar_bairro` e `usar_sazonalidade`.
- Dados de saúde (gestante, doença crônica, saúde mental) e serviços de saúde no histórico só são usados ou exibidos com `consentimento_saude = true`.
- Motivos de "próximo passo" são genéricos de propósito, para não revelar na tela um serviço anterior sensível.
- Eventos de UX e pesquisas guardam o cidadão só como pseudônimo (hash com `KODIAK_SALT`).

## Testes

```bash
./run.sh test
```

A suíte usa um SQLite temporário por teste e precisa dos arquivos em `data/parquet/`. Leva alguns minutos, porque o motor é montado a partir dos dados reais.

## Deploy de demonstração

A demonstração roda numa EC2 (`t3.small`, us-east-1) atrás de uma distribuição CloudFront. A instância é configurada pelo user data no primeiro boot:

1. baixa o pacote (`backend/`, `requirements.txt`, `data/parquet/`) de um bucket S3 privado por URL pré-assinada;
2. instala as dependências em `/opt/kodiak/.venv`;
3. gera `/opt/kodiak/kodiak.env` com `KODIAK_SALT` aleatório e `KODIAK_DB=/opt/kodiak/data/app.db`;
4. sobe o serviço systemd `kodiak` (uvicorn na porta 8000).

A instância não tem SSH nem SSM. Para publicar uma versão nova, sobe-se uma instância nova com o pacote atualizado, aponta-se a origem da CloudFront para ela e encerra-se a antiga. Os dados gravados no SQLite da instância antiga se perdem nessa troca.

Ao fim do evento, `scripts/derrubar_deploy.sh` remove a CloudFront, a instância e o grupo de segurança. Mantenha o id da instância atualizado no script.

## Limitações conhecidas

- Não há autenticação, e o CORS está aberto (`*`). Com o `cidadao_id` na URL, dá para ler e alterar dados de qualquer cidadão. Isso é aceitável só para a demonstração.
- Pedidos são simulados: nada é encaminhado aos órgãos.
- O motor fica todo em memória, e cada worker do uvicorn carrega uma cópia.
- O SQLite é local à instância. Não há backup nem banco compartilhado.
