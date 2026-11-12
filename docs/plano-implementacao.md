# Plano de implementação da API: Hiperpersonalização Conecta Recife

Este plano cobre só a API que alimenta o frontend. Telas, templates e layout estão fora do escopo.

## 1. Ponto de partida

### Dados (`data/parquet`)

| Arquivo | Conteúdo | Uso |
|---|---|---|
| `servicos` | 843 serviços da Carta | Vitrine, busca, jornada |
| `cidadaos` | 89.046 cidadãos simulados, com `rpa` (1 a 6) | Perfil, região, privacidade |
| `historico` | 593 mil cliques com sessão e data | Próxima ação, "novo para você" |
| `visitas_sem_login` | 3,56 milhões de cliques anônimos | Transições, popularidade |
| `uso_semanal` | Tendência semanal por serviço | Sazonalidade |

Limites que a API respeita:
- Não existe bairro. O dado geográfico é a RPA. A API devolve `regiao` (ex.: "RPA 3").
- `criancas_na_familia` vazio significa "sem informação".
- Dados de saúde só personalizam com consentimento (LGPD art. 11).
- Não há dados de abandono, tempo ou satisfação. Serão registrados pela API (4.7).
- A Carta não tem prazos. Prazos são simulados e marcados como `exemplo`.

### O que já existe

- `backend/motor.py`: recomendação híbrida e explicável, com `motivo` por item.
- `backend/api.py`: `/health`, `/cidadaos/{id}/perfil`, `/cidadaos/{id}/preferencias` (GET e PUT), `/cidadaos/{id}/recomendacoes`, `/servicos/{id}`, `/servicos/{id}/proximos-passos`.
- `scripts/`: ETL, backtest, calibração e geração de `saidas/recomendacoes.csv`.

### Pendências conhecidas

- CORS `*` e sem autenticação. Aceitável no protótipo; em produção, autenticar e restringir origens.
- Preferências em JSON com `threading.Lock`. Serve a um processo só. A etapa 0 migra para SQLite.
- Sem testes automatizados e sem `httpx` no `requirements.txt`.

## 2. Arquitetura

```
Frontend  <--HTTP/JSON-->  FastAPI (backend/api.py)
                              |-- motor.py       recomendação e busca
                              |-- jornada.py     formulário, protocolo, linha do tempo
                              |-- eventos.py     medição
                              |-- assistente.py  busca por linguagem natural (IA)
                              `-- SQLite data/app.db
```

- Tudo parte de `cidadao_id`. Funciona sem histórico e para visitante anônimo.
- Toda sugestão traz `motivo` e `sinal_principal`.
- A IA só escolhe entre serviços do catálogo e nunca inventa um.

## 3. Etapa 0: fundação

- `backend/db.py` com SQLite: `preferencias`, `pedidos`, `pedido_eventos`, `eventos_ux`, `pesquisas`.
- Migrar `preferencias.json` para SQLite, mantendo a mesma API.
- Adicionar `httpx` e `pytest` (versões fixas) e criar `tests/` com testes de contrato.
- `backend/personas.py` com as personas do tutorial.
- Erros padronizados: `{"erro": "...", "detalhe": "..."}`.

Aceite: `pytest` verde e preferências sobrevivem a reinício.

## 4. Rotas por funcionalidade

### 4.1 Vitrine personalizada

**`GET /vitrine/{cid}`** (nova)
Parâmetros: `perfil_simulado` (`idoso | empreendedor | pcd | familia`), `rpa`, `semana`.
Retorna as seções da home, prontas para exibir:
- `para_voce_agora`: até 5 serviços.
- `na_sua_regiao`: serviços fortes na RPA do cidadão.
- `em_alta_nesta_epoca`: serviços da sazonalidade da `semana`.
- `descubra`: ao menos 1 serviço novo para o cidadão.

Cada item traz `servico_id`, `nome`, `orgao`, `motivo`, `sinal_principal` e `tipo`.

**`GET /cidadaos/{cid}/recomendacoes`** (alterar)
Ganha `perfil_simulado` e `rpa`. Retorna a lista plana de itens com `motivo`, mais `perfis_ativos` e `data_referencia`.
O `perfil_simulado` força as tags do grupo só no modo demonstração (`familia` vira `vulnerabilidade`, `crianca_pequena`, `crianca_escolar`). Implementação: `Motor.recomendar(..., tags_forcadas=...)`.

Aceite:
- Idoso, empreendedor, PcD e família recebem vitrines diferentes e coerentes.
- Mudar `semana` muda a seção sazonal.
- Cidadão sem histórico recebe vitrine por perfil, região, sazonalidade e popularidade.

### 4.2 Atalhos e próxima melhor ação

**`GET /cidadaos/{cid}/proxima-acao`** (nova)
Retorna:
- `atalhos`: até 4 serviços que o cidadão mais usa.
- `proxima_melhor_acao`: 1 serviço com o motivo ("Quem usou X costuma usar este").
- `novo_para_voce`: ao menos 1 serviço que o cidadão nunca usou.

**`GET /servicos/{sid}/proximos-passos`** (já existe)
Retorna os serviços que costumam vir depois deste.

Aceite: `novo_para_voce` nunca vem vazio. Estender `gerar_recomendacoes.py` para validar `proxima_melhor_acao`.

### 4.3 Jornada simplificada: denúncia de dengue (serviço 594)

Os passos reais da Carta definem os campos. O conteúdo em linguagem simples fica em `backend/conteudo/jornadas.json`.

**`GET /jornadas/{sid}`** (nova)
Retorna a definição dos passos e campos, com `valores_iniciais` do cidadão:
1. Onde é: rua, número, complemento, referência (região já preenchida).
2. O que você viu: descrição e até 3 fotos (opcional).
3. Seus dados: nome e telefone, preenchidos do perfil.
4. Conferir: resumo para envio.

**`POST /pedidos`** (nova)
Recebe `servico_id`, `cidadao_id`, `dados`. Retorna o `protocolo` (`REC-AAAA-NNNNNN`) e o status inicial.

**`PATCH /pedidos/{id}/rascunho`** (nova)
Salva o progresso. Retorna o rascunho salvo e o último passo.

Regras: só dados fictícios; rejeitar texto que pareça CPF; fotos e complemento opcionais. O envio é simulado e não chama o sistema real da Prefeitura.

Aceite: do serviço à confirmação em no máximo 4 passos, com endereço e contato pré-preenchidos.

### 4.4 Confirmação e acompanhamento

**`GET /pedidos/{id}`** (nova)
Retorna `protocolo`, `status`, `prazo_estimado` (marcado como exemplo) e `linha_do_tempo`:

| Etapa | Status |
|---|---|
| Denúncia recebida | concluída ao enviar |
| Em análise pela Vigilância Ambiental | em andamento |
| Visita do agente ao local | prevista |
| Resultado e encerramento | pendente |

Com `?avancar_horas=48`, simula a passagem do tempo e registra a mudança em `pedido_eventos`.

**`GET /cidadaos/{cid}/pedidos`** (nova)
Retorna a lista de pedidos do cidadão, cada um com protocolo, serviço, status e data.

Aviso por notificação só se `aceita_notificacao` for verdadeiro e a preferência `receber_avisos` permitir.

Aceite: após enviar, o pedido mostra protocolo e linha do tempo. Reabrir pelo histórico mostra o status atualizado.

### 4.5 Acessibilidade (lado API)

A API entrega o necessário para o frontend se adaptar:
- Textos em linguagem simples: `nome_resumido` nos serviços, frases curtas, sem sigla solta. Um teste valida tamanho médio de frase e termos proibidos.
- `perfil_acessibilidade` nas preferências (4.6): `texto_maior`, `alto_contraste`, `leitor_de_tela`, `menos_passos`, `falar_em_vez_de_digitar`.
- **`GET /cidadaos/{cid}/perfil`** (alterar): ganha `acessibilidade_sugerida` (lista) com o motivo. Vale para cidadãos com `pessoa_com_deficiencia` ou 60 anos ou mais. É sugestão, nunca ativação automática.
- Status de pedido sempre em texto, não só em código ou cor.

Limite: validar WCAG exige teste manual com tecnologia assistiva e revisão de especialista.

### 4.6 Preferências e privacidade

**`GET` e `PUT /cidadaos/{cid}/preferencias`** (já existem)
Retornam os interruptores: `consentimento_saude`, `usar_historico`, `usar_perfil`, `usar_bairro`, `usar_sazonalidade`. Novos campos: `perfil_acessibilidade`, `receber_avisos`, `permitir_medicao`.

**`GET /cidadaos/{cid}/preferencias/explicacao`** (nova)
Retorna, para cada dado, se está ligado, para que serve e o que muda ao desligar. Inclui o texto "Como usamos seus dados" (finalidade, minimização, revogação).

**`DELETE /cidadaos/{cid}/preferencias`** (nova)
Volta ao padrão e retorna as preferências padrão.

**Explicação por item:** cada item de recomendação traz `dado_usado` derivado de `sinal_principal`: `proximo`/`conteudo` → histórico; `perfil`/`segmento` → perfil; `bairro` → região; `saz` → época; `pop` → serviço muito usado. Assim o frontend mostra "Por que estou vendo isto?" e o atalho para desligar o dado.

**Consentimento de saúde:** desligado por padrão, nunca pré-marcado, revogável. Ao revogar, tags de saúde somem da próxima resposta.

Aceite: com `consentimento_saude=false`, nenhum motivo cita saúde. Desligar um dado muda a resposta seguinte.

### 4.7 Medição da experiência

Eventos só são gravados se `permitir_medicao` estiver ligado, com identificador pseudonimizado.

**`POST /eventos`** (nova)
Recebe um lote de eventos e retorna a quantidade aceita. Tipos: `vitrine_exibida`, `sugestao_clicada`, `jornada_etapa_concluida`, `jornada_abandonada`, `pedido_enviado`, `busca_realizada`.

**`POST /pesquisas`** (nova)
Recebe nota de 1 a 5 e comentário opcional ("Foi fácil pedir este serviço?"). Retorna confirmação.

**`GET /metricas/funil?servico_id=594`** (nova)
Retorna conclusão e abandono por etapa, tempo mediano e nota média.

**`GET /metricas/resumo`** (nova)
Retorna taxa de conclusão, CSAT e CTR por posição e por `tipo` (recomendado vs. descoberta).

Os números do protótipo são simulados e devem vir rotulados (`simulado: true`). Offline: `hit@10` e `recall@10` via `scripts/backtest.py`.

Aceite: abandonar a jornada no passo 2 gera evento visível em `/metricas/funil`.

### 4.8 Descoberta facilitada (busca)

Reaproveita o TF-IDF do motor (`self.X`).

**`GET /busca?q=...&cid=...&limite=10`** (nova)
Retorna serviços ordenados por relevância, cada um com nome simples, órgão, `gratuito`, `nivel_digital` e `servico_id`. Sem `q`, retorna os populares do perfil.
Técnicas: normalização de acentos, sinônimos populares (`backend/conteudo/sinonimos.json`, ex.: "mosquito" → dengue), tolerância a erro de digitação e leve reordenação por perfil e qualidade.

**`GET /busca/sugestoes?q=...`** (nova)
Retorna sugestões de autocompletar.

**`GET /busca/situacoes`** (nova)
Retorna atalhos por situação ("Tenho um problema na rua", "Estou com filho pequeno", "Preciso de documento", "Quero abrir um negócio"), cada um com uma consulta pronta.

Aceite: "foco de dengue", "mosquito", "agua parada" e "denunciar dengue" trazem o serviço 594 entre os 3 primeiros.

### 4.9 Assistente de IA para pesquisa por voz

O dispositivo converte fala em texto. A API recebe só texto e não guarda áudio.

**`POST /assistente/buscar`** (nova)
Recebe `texto`, `cid` (opcional) e `canal` (`voz` ou `texto`). Retorna:
- `entendimento`: frase para confirmar ("Entendi: denunciar foco de dengue. Está certo?").
- `servicos`: até 3 serviços do catálogo.
- `resposta`: parágrafo curto em linguagem simples.
- `modo`: `ia` ou `busca` (quando cai no fallback).

Desenho seguro:
- O modelo recebe só os 10 candidatos da busca (4.8) e só pode citar ids dessa lista. A API valida que cada id existe.
- Sem resultado útil, retorna "Não encontrei. Quer tentar de outro jeito?" com a busca comum.
- No prompt entram no máximo faixa etária, região e perfil de acessibilidade, sem saúde, nome ou telefone, e só se as preferências permitirem.
- Provedor atrás da interface `ProvedorLLM` (Amazon Bedrock é a opção natural, modelo a definir). Sem credencial, usa só a busca 4.8.
- Limites: taxa por cidadão e tamanho máximo do texto.

Aceite: a frase "quero denunciar mosquito da dengue na minha rua" retorna 594 em primeiro, sem citar serviço inexistente. Sem credencial, a busca comum continua funcionando.

## 5. Resumo das rotas

| Rota | O que retorna | Situação | Item |
|---|---|---|---|
| `GET /vitrine/{cid}` | Seções da home | nova | 4.1 |
| `GET /cidadaos/{cid}/recomendacoes` | Lista de sugestões com motivo | alterar | 4.1 |
| `GET /cidadaos/{cid}/proxima-acao` | Atalhos, próxima ação, novo | nova | 4.2 |
| `GET /servicos/{sid}/proximos-passos` | Serviços que vêm depois | existe | 4.2 |
| `GET /jornadas/{sid}` | Passos e campos do formulário | nova | 4.3 |
| `POST /pedidos` | Protocolo do pedido | nova | 4.3 |
| `PATCH /pedidos/{id}/rascunho` | Rascunho salvo | nova | 4.3 |
| `GET /pedidos/{id}` | Status e linha do tempo | nova | 4.4 |
| `GET /cidadaos/{cid}/pedidos` | Lista de pedidos | nova | 4.4 |
| `GET /cidadaos/{cid}/perfil` | Perfil e acessibilidade sugerida | alterar | 4.5 |
| `GET`/`PUT /cidadaos/{cid}/preferencias` | Interruptores de privacidade | existe | 4.6 |
| `GET /cidadaos/{cid}/preferencias/explicacao` | O que cada dado faz | nova | 4.6 |
| `DELETE /cidadaos/{cid}/preferencias` | Preferências padrão | nova | 4.6 |
| `POST /eventos` | Eventos aceitos | nova | 4.7 |
| `POST /pesquisas` | Confirmação da nota | nova | 4.7 |
| `GET /metricas/funil` | Funil por etapa | nova | 4.7 |
| `GET /metricas/resumo` | Conclusão, CSAT, CTR | nova | 4.7 |
| `GET /busca` | Resultados da busca | nova | 4.8 |
| `GET /busca/sugestoes` | Autocompletar | nova | 4.8 |
| `GET /busca/situacoes` | Atalhos por situação | nova | 4.8 |
| `POST /assistente/buscar` | Serviços e resposta da IA | nova | 4.9 |
| `GET /servicos/{sid}`, `GET /health` | Detalhe do serviço, saúde da API | existe | — |

## 6. Sequência

| Ordem | Entrega | Itens |
|---|---|---|
| 1 | Fundação (SQLite, testes, personas) | 3 |
| 2 | Vitrine com perfil simulado e motivos | 4.1 |
| 3 | Próxima ação e descoberta | 4.2 |
| 4 | Jornada 594, protocolo e linha do tempo | 4.3, 4.4 |
| 5 | Preferências e consentimento completos | 4.6 |
| 6 | Acessibilidade na API | 4.5 |
| 7 | Busca | 4.8 |
| 8 | Medição e pesquisa | 4.7 |
| 9 | Assistente de IA | 4.9 |

Se o tempo apertar, cortar de baixo para cima. A busca (4.8) já cobre a descoberta sem o assistente.

## 7. Verificação

- **Motor**: `python scripts/gerar_recomendacoes.py` e `python scripts/backtest.py`.
- **API**: `pytest` de contrato por rota, incluindo cidadão sem histórico, id desconhecido, consentimento desligado e 404.
- **Jornada**: teste ponta a ponta (criar pedido, avançar tempo, ler linha do tempo).
- **Busca**: consultas de referência com a posição esperada.
- **Linguagem simples**: teste de tamanho de frase e termos proibidos.

## 8. Riscos

| Risco | Mitigação |
|---|---|
| Envio da denúncia é simulado | Marcar como simulado e isolar atrás de `EnviadorPedido` |
| Uso indevido de dados de saúde | Desligado por padrão, consentimento explícito, teste automático |
| IA inventar serviço | Recuperação primeiro, validação de ids, fallback para busca |
| Dados pessoais em prompt ou logs | Não enviar dados sensíveis, não guardar áudio, pseudonimizar eventos |
| "Bairro" mal interpretado | Usar `regiao` (RPA) em toda resposta |
| Métricas simuladas confundirem | Campo `simulado: true` e definição de cada indicador |

## 9. Fora de escopo

- Telas, templates e qualquer parte do frontend.
- Integração real com o protocolo da Prefeitura.
- Autenticação real (login Conecta Recife).
- Treinar modelo de linguagem próprio.
- Dados reais de cidadãos. Só dados fictícios, apagados ao fim do evento.
