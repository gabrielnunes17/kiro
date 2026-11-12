# Análise do projeto Kodiak – Hiperpersonalização

Data da análise: 12/11/2026
Base da análise: leitura do código em `backend/`, `scripts/`, `tests/`, dos cabeçalhos dos CSVs em `data/raw/`, do histórico git e execução da suíte de testes.

Não foi possível ler o `data/raw/tutorial.pdf` (a extração de texto não retornou conteúdo). Referências ao "tutorial" abaixo vêm apenas de comentários no código (`personas.py`).

---

## 1. Resumo executivo

O projeto é um backend de recomendação de serviços públicos (Carta de Serviços do Recife) para o app Kodiak. Hoje existem:

- Um motor de recomendação híbrido e explicável (`backend/motor.py`, ~730 linhas).
- Uma API REST em FastAPI com vitrine da home, recomendações, perfil, preferências e detalhe de serviço.
- Persistência em SQLite (só preferências estão em uso).
- Scripts de ETL, backtest, calibração e geração em lote.
- 22 testes automatizados, todos passando (52 s).

Status geral: a base de recomendação e a API de leitura estão prontas e testadas. O que o schema do banco já prevê (pedidos, eventos de UX, pesquisas) ainda não tem endpoints.

Histórico git (3 commits):

1. `first commit`
2. `feat(api): adiciona API REST e reequilibra o score do motor de recomendação`
3. `feat(api): adiciona camada de dados, personas, erros e testes da API`

---

## 2. Estrutura do repositório

| Caminho | Conteúdo |
|---|---|
| `backend/motor.py` | Motor de recomendação |
| `backend/api.py` | API FastAPI |
| `backend/db.py` | SQLite (schema, preferências, migração do JSON legado) |
| `backend/erros.py` | Handlers de erro padronizados |
| `backend/personas.py` | 8 personas de demonstração e mapa de perfis simulados |
| `scripts/fase1_etl.py` | Diagnóstico dos CSVs e conversão para Parquet |
| `scripts/backtest.py` | Avaliação offline (hit@k, recall@k, MRR) contra baseline de popularidade |
| `scripts/calibrar.py` | Ablação de sinais e combinações de pesos |
| `scripts/gerar_recomendacoes.py` | Gera `saidas/recomendacoes.csv` e valida regras |
| `tests/` | `test_fundacao.py` (11 testes) e `test_vitrine.py` (11 testes) |
| `data/raw`, `data/parquet` | Dados de entrada (ficam fora do git) |
| `docs/` | Vazia até esta análise |

Dependências fixadas em `requirements.txt`: duckdb, fastapi, httpx, numpy, pandas, pyarrow, pydantic, pytest, scikit-learn, scipy, uvicorn. `.gitignore` exclui `data/`, `.venv/`, `__pycache__/` e `saidas/`.

---

## 3. Dados

| Arquivo | Linhas aprox. | Observação |
|---|---|---|
| `servicos.csv` | ~14.9 mil linhas físicas (campos multilinha; número real de serviços é menor) | 33 colunas: órgão, temas, públicos-alvo, descrição, requisitos, passos, canais, nível digital, nota |
| `cidadaos.csv` | 89.046 | Idade, sexo, RPA, marcadores de perfil e de saúde, renda, crianças na família |
| `historico.csv` | ~593 mil | Cliques de cidadãos logados, com sessão e ordem |
| `visitas_sem_login.csv` | ~3,56 milhões | Cliques anônimos, com sessão |
| `uso_semanal.csv` | ~11,6 mil | Agregado semanal por serviço, com/sem login |

O ETL (`fase1_etl.py`) converte tudo para Parquet e imprime diagnósticos (vazios, distribuição de públicos e temas, cidadãos sem histórico, integridade referencial).

Dados são fictícios, conforme comentário em `personas.py`.

---

## 4. Motor de recomendação

### 4.1 Sinais

O score combina oito sinais, cada um com uma frase de motivo em linguagem simples:

| Sinal | O que mede |
|---|---|
| `perfil` | Serviço cujo público-alvo bate com as tags do cidadão |
| `segmento` | O que pessoas do mesmo segmento (faixa etária e tags) mais usam, com suavização e lift |
| `bairro` | Uso por região (RPA 1 a 6) |
| `saz` | Sazonalidade (mesma época do ano anterior) e tendência recente |
| `proximo` | Próximo passo: matriz de transição entre serviços dentro da sessão |
| `conteudo` | Similaridade TF-IDF (texto) entre histórico/perfil e serviços |
| `pop` | Popularidade (logados + visitas sem login ponderadas) |
| `qualidade` | Nota média e nível digital |

### 4.2 Fórmula

- Soma ponderada dos sinais (`PESOS_BASE`: segmento 0,45, proximo 0,35, pop 0,10, bairro 0,05, qualidade 0,05; perfil, saz e conteudo com peso 0 na base).
- O perfil não soma: ele multiplica o score por `1 + beta * perfil` (beta base 0,30; idoso 0,40, empreendedor 0,40, PCD 0,60, família 0,35).
- Ajustes por grupo (ex.: idoso reforça bairro, empreendedor reforça sazonalidade).
- Serviços de público restrito sem aderência ao cidadão ficam com 45% da força.
- Serviços 100% presenciais (nível digital 0) ficam com 60%.

### 4.3 Regras de negócio implementadas

- Serviços já usados pelo cidadão nunca são sugeridos.
- Vaga de descoberta: serviços da cauda de popularidade (metade menos usada) que combinam com o perfil. Posições 4, 7 e 10 da lista (índices 3, 6, 9).
- Diversidade: no máximo 2 serviços com o mesmo prefixo de nome e 4 do mesmo tema (regra relaxada se faltar item).
- Privacidade de saúde: tags de gestante, crônico e saúde mental só entram com `consentimento_saude`. Em modo demonstração, tags de saúde nunca são forçadas.
- Motivos de próximo passo são genéricos de propósito, para não revelar serviço anterior sensível na tela.
- Preferências do cidadão (`usar_historico`, `usar_perfil`, `usar_bairro`, `usar_sazonalidade`) desligam os sinais correspondentes.
- Visitante anônimo ou sem histórico recebe resultado por região, popularidade e qualidade.

### 4.4 Vitrine da home

Quatro seções, sem repetição entre elas e sem itens do histórico:

| Seção | Itens | Condição |
|---|---|---|
| `para_voce_agora` | 5 | Score final |
| `na_sua_regiao` | 3 | `usar_bairro` ligado e RPA conhecida |
| `em_alta_nesta_epoca` | 3 | `usar_sazonalidade` ligado |
| `descubra` | 2 | Cauda de popularidade; fallback por qualidade |

Quando uma seção é desligada, vem vazia com um aviso (`regiao_desligada`, `regiao_desconhecida`, `sazonalidade_desligada`).

### 4.5 Modo demonstração

Parâmetros `perfil_simulado` (idoso, empreendedor, pcd, familia) e `rpa` substituem as tags e a região derivadas do cadastro. O perfil simulado não herda a faixa etária real. `usar_perfil=false` continua valendo.

---

## 5. API REST

| Método e rota | Função |
|---|---|
| `GET /` e `/docs` | Redireciona e serve Swagger UI (caminhos relativos, funciona atrás de proxy) |
| `GET /health` | Status e contagens (serviços, cidadãos, com histórico) |
| `GET /cidadaos/{cid}/perfil` | Perfil público, perfis ativos, preferências; dados de saúde só sinalizados como disponíveis |
| `GET/PUT /cidadaos/{cid}/preferencias` | Lê e grava preferências (PUT retorna 404 para cidadão desconhecido) |
| `GET /vitrine/{cid}` | Seções da home |
| `GET /cidadaos/{cid}/recomendacoes` | Lista (limite 1 a 10, vagas de descoberta 0 a 3, `detalhe` expõe sinais e pesos) |
| `GET /servicos/{sid}` | Detalhe do serviço |
| `GET /servicos/{sid}/proximos-passos` | Serviços mais prováveis depois deste |

Pontos de qualidade:

- Erros padronizados `{"erro", "detalhe"}` (400, 404, 405, 409, 422, 429 mapeados).
- Validação de parâmetros via pydantic/Query (RPA 1 a 6, limites).
- Preferências ignoram chaves desconhecidas salvas.
- Cache de sazonalidade limitado a 64 datas.

---

## 6. Persistência

SQLite via stdlib, uma conexão por operação, WAL, `foreign_keys` ligado. Caminho em `KODIAK_DB` (padrão `data/app.db`).

Tabelas criadas: `preferencias`, `pedidos`, `pedido_eventos`, `eventos_ux`, `pesquisas`.

Em uso hoje: apenas `preferencias`. Há migração única e não destrutiva de `data/preferencias.json` (INSERT OR IGNORE, arquivo renomeado para `.json.migrado`).

---

## 7. Scripts e avaliação

- `backtest.py`: treina até uma data de corte (padrão 14/09/2026), mede hit@10, recall@10 e MRR sobre serviços novos usados depois do corte e compara com baseline de popularidade, com e sem vagas de descoberta.
- `calibrar.py`: ablação de cada sinal isolado e de combinações de pesos.
- `gerar_recomendacoes.py`: gera 10 recomendações para os 89.046 cidadãos em `saidas/recomendacoes.csv` e valida 11 regras (sem repetidos, sem já usados, todos com descoberta, nenhum motivo cita consentimento de saúde etc.). Retorna código de saída 1 se alguma falhar.

Não executei os scripts nesta análise, então não há números de backtest para citar. O CSV de saída existe e as primeiras linhas têm o formato esperado (`cidadao_id, posicao, servico_id, motivo`).

---

## 8. Testes

Execução: `22 passed in 52.52s`.

- `test_fundacao.py`: health, criação de tabelas, preferências (padrão, gravação, persistência após reinício), migração do JSON legado, erros 404/422 padronizados, recomendações para cidadão conhecido e anônimo, ausência de motivos de saúde sem consentimento, existência das personas nos dados.
- `test_vitrine.py`: estrutura e campos, "descubra" nunca vazio, sem repetição, sem serviço já usado, perfis simulados geram vitrines diferentes, semana altera seção sazonal, visitante anônimo, região desconhecida/desligada, perfil desligado ignora simulação, parâmetros inválidos, motivos não citam serviço prévio.

---

## 9. Lacunas e riscos observados

1. Tabelas `pedidos`, `pedido_eventos`, `eventos_ux` e `pesquisas` existem no schema, mas não há endpoints nem código que as use.
2. As 8 personas (`PERSONAS`) estão definidas, mas nenhuma rota as expõe; só um teste as valida.
3. CORS está aberto (`*`) e não há autenticação. O código já comenta que é de protótipo; o `cidadao_id` na URL permite ler e alterar preferências de qualquer cidadão.
4. `PUT /preferencias` valida 404, mas `GET` de cidadão desconhecido retorna preferências padrão sem erro (comportamento intencional para anônimos, vale documentar).
5. O motor carrega tudo em memória na inicialização (matriz de transição `n x n` densa, TF-IDF, histórico). A suíte leva ~52 s, em boa parte pelo custo de montar o motor. Com muitos workers, o consumo de memória se multiplica.
6. `calibrar.py` sobrescreve variáveis globais do módulo (`PESOS_BASE`, `AJUSTE_GRUPO`); é aceitável como script, mas não deve ser importado na API.
7. `recomendar` e `vitrine` têm lógica de descoberta parecida duplicada; candidato a refatoração.
8. `docs/` estava vazia: não havia README nem documentação de execução (o comando de subida está só no docstring de `api.py`).
9. Sem métricas de backtest registradas em lugar nenhum do repositório; seria útil guardar os resultados para acompanhar regressões de qualidade.
10. Qualidade dos motivos de "descoberta" depende de manipulação de string (`motivo[0].lower()`), que pode falhar com motivo vazio (hoje todos têm texto).

---

## 10. Próximos passos sugeridos

1. Definir e implementar os endpoints de pedidos, eventos de UX e pesquisa sobre as tabelas já criadas.
2. Expor `GET /personas` para a demonstração.
3. Rodar `backtest.py` e `calibrar.py`, e registrar os números em `docs/`.
4. Escrever um README com setup, comando da API, variável `KODIAK_DB` e como gerar o CSV.
5. Antes de produção: autenticação, restrição de CORS e revisão de privacidade (LGPD) do uso de dados de saúde.
6. Avaliar tempo de inicialização e memória do motor (por exemplo, matriz de transição esparsa).
