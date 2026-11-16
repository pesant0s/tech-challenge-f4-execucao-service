# tech-challenge-f4-execucao-service — Execução e Produção

Microsserviço da oficina mecânica que guarda o catálogo de serviços e peças, controla o estoque
(reserva, baixa e liberação por ordem de serviço) e conduz a fila de execução: diagnóstico, reparo e
finalização. Recebe comandos do orquestrador da Saga (OS Service) pelo RabbitMQ, responde com eventos e
mantém um banco PostgreSQL só seu.

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=pesant0s_tech-challenge-f4-execucao-service&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=pesant0s_tech-challenge-f4-execucao-service)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=pesant0s_tech-challenge-f4-execucao-service&metric=coverage)](https://sonarcloud.io/summary/new_code?id=pesant0s_tech-challenge-f4-execucao-service)

> Pós-Tech Software Architecture · FIAP · Tech Challenge, Fase 04

## Os cinco repositórios

| Repositório | Papel |
|---|---|
| [`tech-challenge-f4-plataforma`](https://github.com/pesant0s/tech-challenge-f4-plataforma) | Base na AWS (VPC, EKS, NLB, API Gateway, RabbitMQ, New Relic), contrato AsyncAPI das mensagens, ADRs, coleção Postman e ambiente local da Saga |
| [`tech-challenge-f4-os-service`](https://github.com/pesant0s/tech-challenge-f4-os-service) | Clientes, veículos, usuários, login de funcionários, abertura e status da OS. Orquestra a Saga |
| [`tech-challenge-f4-execucao-service`](https://github.com/pesant0s/tech-challenge-f4-execucao-service) ← **este** | Catálogo, estoque com reserva, fila de execução, diagnóstico e reparo (PostgreSQL) |
| [`tech-challenge-f4-billing-service`](https://github.com/pesant0s/tech-challenge-f4-billing-service) | Orçamento, aprovação, cobrança e reembolso no Mercado Pago (MongoDB) |
| [`tech-challenge-f4-auth-lambda`](https://github.com/pesant0s/tech-challenge-f4-auth-lambda) | Lambda `POST /auth/cpf`, que emite o token do cliente |

## Sumário

1. [Visão geral do sistema](#visão-geral-do-sistema)
2. [Arquitetura do serviço](#arquitetura-do-serviço)
3. [Responsabilidades e limites](#responsabilidades-e-limites)
4. [Regras de negócio](#regras-de-negócio) (estoque, ordem de baixa, fila de execução)
5. [Modelo de dados](#modelo-de-dados)
6. [Mensageria](#mensageria)
7. [Papel na Saga](#papel-na-saga)
8. [API REST](#api-rest)
9. [Configuração](#configuração)
10. [Como rodar localmente](#como-rodar-localmente)
11. [Testes e cobertura](#testes-e-cobertura)
12. [Pipeline CI/CD](#pipeline-cicd)
13. [Infraestrutura própria (`infra/`)](#infraestrutura-própria-infra)
14. [Kubernetes (`k8s/`)](#kubernetes-k8s)
15. [Deploy na AWS](#deploy-na-aws)
16. [Observabilidade](#observabilidade)
17. [Decisões arquiteturais](#decisões-arquiteturais)
18. [Limitações conhecidas](#limitações-conhecidas)

---

## Visão geral do sistema

A entrada é o API Gateway; os três serviços só se comunicam entre si pelo RabbitMQ e cada um tem o banco
próprio. O Execução e Produção (`EX`, em destaque) é alcançado pelo NLB na porta 8081, que aponta para
o NodePort 30081, e usa o RDS PostgreSQL `execucao-service`.

```mermaid
flowchart LR
  U["Funcionário / Cliente"]
  MP["Mercado Pago<br/>Orders API · QR dinâmico"]
  NR["New Relic<br/>APM · logs · traces · dashboards"]
  GH["GitHub Actions<br/>testes · SonarQube · deploy"]
  subgraph AWS["AWS · us-east-1"]
    APIGW["API Gateway HTTP<br/>rota por prefixo"]
    L["Lambda tech-challenge-f4-auth<br/>POST /auth/cpf"]
    ECR["ECR · um por serviço"]
    SSM["SSM Parameter Store<br/>/tech-challenge-f4/*"]
    subgraph VPC["VPC"]
      NLB["NLB interno<br/>80 · 8081 · 8082"]
      subgraph EKS["EKS · 3 nós t3.medium"]
        OS["OS Service<br/>orquestrador da Saga"]
        EX["Execução e Produção"]
        BI["Billing"]
        RMQ["RabbitMQ<br/>namespace mensageria"]
        MDB[("MongoDB rs0<br/>namespace billing-service")]
      end
      RDS1[("RDS PostgreSQL<br/>os-service")]
      RDS2[("RDS PostgreSQL<br/>execucao-service")]
    end
  end
  U --> APIGW
  APIGW -->|"POST /auth/cpf"| L
  APIGW -->|"VPC Link"| NLB
  L -->|"/interno/clientes/autenticar"| NLB
  NLB -->|"NodePort 30080"| OS
  NLB -->|"NodePort 30081"| EX
  NLB -->|"NodePort 30082"| BI
  OS --- RDS1
  EX --- RDS2
  BI --- MDB
  OS <-->|"comandos e eventos"| RMQ
  EX <--> RMQ
  BI <--> RMQ
  BI -->|"cobrança · consulta · cancelamento · reembolso"| MP
  MP -.->|"webhook /billing/webhooks/mercadopago"| APIGW
  EKS -.->|"agente"| NR
  GH -->|"imagem"| ECR
  GH -->|"deploy"| EKS
  style EX fill:#fde68a,stroke:#b45309,color:#000
```

Rotas do API Gateway que chegam a este serviço, sem reescrita de caminho:

| Rota | Destino |
|---|---|
| `ANY /catalogo/{proxy+}` | execucao-service |
| `ANY /estoque/{proxy+}` | execucao-service |
| `ANY /execucao/{proxy+}` (inclui `/execucao/docs`, `/execucao/redoc` e `/execucao/openapi.json`) | execucao-service |

`/interno/*` não tem rota no gateway, e este serviço não expõe rota interna. O texto completo da
arquitetura do sistema, a subida do ambiente e o contrato de infraestrutura estão no
[README da plataforma](https://github.com/pesant0s/tech-challenge-f4-plataforma#readme) e em
[`docs/infraestrutura/contrato.md`](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/infraestrutura/contrato.md).

### Ficha do serviço

| | |
|---|---|
| Runtime | Amazon EKS, namespace `execucao-service`, 2 a 4 réplicas (HPA) |
| Exposição | API Gateway → VPC Link → NLB (listener 8081) → NodePort 30081 → pod (porta 8000) |
| Banco | Amazon RDS PostgreSQL 16 próprio (`tech-challenge-f4-execucao-service-db`), banco `execucao` |
| Mensageria | RabbitMQ do cluster (`rabbitmq.mensageria.svc.cluster.local:5672`), fila `execucao-service.comandos` |
| Autenticação | JWT de funcionário emitido pelo OS Service, validado aqui com a mesma `SECRET_KEY` |
| Stack | Python 3.12 · FastAPI 0.111 · SQLAlchemy 2.0 (mapeamento imperativo) · Alembic · psycopg2 · pika 1.3 · python-jose · New Relic |

---

## Arquitetura do serviço

Hexagonal (portas e adaptadores). O domínio não importa FastAPI, SQLAlchemy nem pika: o mapeamento
objeto-relacional é imperativo (`registry.map_imperatively` em `app/infrastructure/orm_mapping.py`), então as
entidades não sabem que existe um banco. `tests/test_dominio.py` exercita as entidades sem banco e sem HTTP;
se o domínio voltar a depender da infraestrutura, ele quebra primeiro.

```mermaid
flowchart LR
  subgraph IN["Adapters inbound"]
    HTTP["HTTP · FastAPI<br/>catalogo_routes · estoque_routes · execucao_routes<br/>CorrelationIdMiddleware · SecurityHeadersMiddleware"]
    MSG["Mensageria<br/>tratar_mensagem · ack manual"]
  end
  subgraph APP["Application"]
    UC1["GerenciarCatalogoUseCase"]
    UC2["GerenciarEstoqueUseCase"]
    UC3["ConduzirExecucaoUseCase"]
    UC4["ProcessarComandoUseCase<br/>ReservarPecas · LiberarReserva · EnfileirarOS"]
    ENV["mensagens.py<br/>envelope e publicar_evento"]
  end
  subgraph DOM["Domain"]
    ENT["Servico · Peca · MovimentacaoEstoque<br/>Reserva · ReservaItem · OrdemExecucao"]
    EXC["NotFound · Conflict · BusinessRule"]
  end
  subgraph OUT["Adapters outbound"]
    REPO["Repositórios SQLAlchemy<br/>catalogo · estoque · reserva · ordem_execucao<br/>outbox e inbox"]
    REL["Relay do outbox<br/>declarar_topologia · publicar_pendentes"]
  end
  subgraph INF["Infrastructure"]
    CFG["config · database · orm_mapping<br/>security · logging_config · rastreamento"]
    TRAB["TrabalhadorMensageria<br/>uma thread por processo"]
  end
  DB[("PostgreSQL")]
  RMQ["RabbitMQ"]
  HTTP --> UC1 & UC2 & UC3
  MSG --> UC4
  UC1 & UC2 & UC3 & UC4 --> ENT
  UC3 & UC4 --> ENV
  UC1 & UC2 & UC3 & UC4 --> REPO
  REPO --> DB
  TRAB --> MSG
  TRAB --> REL
  REL --> REPO
  REL --> RMQ
  RMQ --> MSG
```

**Regra de dependência.** As setas apontam para dentro: adaptadores e infraestrutura conhecem a aplicação
e o domínio; o domínio não conhece ninguém. Os casos de uso recebem os repositórios pelo construtor.

Pacotes reais de `app/`:

| Pacote | Conteúdo |
|---|---|
| `app/main.py` | Cria a aplicação FastAPI, configura o log, registra middlewares, handlers de erro, routers, `/health` e `/health/ready`; no `lifespan` sobe a thread de mensageria quando há `RABBITMQ_URL` |
| `app/adapters/inbound/http/` | `catalogo_routes`, `estoque_routes`, `execucao_routes`, os `*_schemas` (Pydantic) e `middleware` (correlação e cabeçalhos de segurança) |
| `app/adapters/inbound/mensageria.py` | `tratar_mensagem`: valida o envelope, chama o caso de uso e faz `ack` ou `nack` |
| `app/adapters/outbound/persistence/` | Repositórios: `catalogo`, `estoque`, `reserva`, `ordem_execucao` e `outbox` (que inclui o inbox) |
| `app/adapters/outbound/mensageria.py` | Topologia (exchanges, fila, DLQ) e relay do outbox |
| `app/application/use_cases/` | `gerenciar_catalogo`, `gerenciar_estoque`, `conduzir_execucao`, `comandos_saga` |
| `app/application/mensagens.py` | Montagem do envelope e escolha da chave de roteamento |
| `app/domain/entities/` | `catalogo` (Servico), `estoque` (Peca, MovimentacaoEstoque), `reserva` (Reserva, ReservaItem), `execucao` (OrdemExecucao, StatusExecucao) |
| `app/domain/exceptions.py` | `NotFoundException` (404), `ConflictException` (409), `BusinessRuleException` (422) |
| `app/infrastructure/` | `config`, `database`, `orm_mapping`, `security`, `logging_config`, `rastreamento`, `trabalhador` |

---

## Responsabilidades e limites

| O serviço faz | O serviço NÃO faz |
|---|---|
| Mantém o catálogo de serviços (nome, preço, tempo estimado) | Não abre a OS nem altera o status dela: isso é do OS Service |
| Mantém peças e estoque, com reserva por OS, baixa e liberação | Não conhece cliente, veículo nem usuário; guarda só `os_id`, `saga_id` e `veiculo_id` como referência, sem chave estrangeira |
| Define o preço dos itens: a reserva devolve cada item com o preço da época | Não gera orçamento nem cobra: isso é do Billing |
| Mantém a fila de execução (FIFO) e as transições de diagnóstico, reparo e finalização | Não orquestra a Saga: só atende três comandos e publica eventos |
| Consome comandos e publica eventos pelo RabbitMQ, com outbox e inbox | Não chama outro serviço por HTTP e não lê o banco de outro serviço |
| Valida o token de funcionário (assinatura e claims) | Não emite token, não tem tabela de usuários e recusa token de cliente (403) |
| Expõe a API REST da oficina (catálogo, estoque e fila) | Não entrega o veículo: `ENTREGUE` é uma ação do funcionário no OS Service, depois de `ExecucaoFinalizada` |

De quem é cada dado:

| Dado | Dono | Neste serviço |
|---|---|---|
| Serviços, peças, quantidades, movimentações | Execução | tabelas `servicos`, `pecas`, `movimentacoes_estoque` |
| Reserva de peças por OS (e o preço da época) | Execução | tabelas `reservas` e `reserva_itens` |
| Ordem na fila e seu andamento | Execução | tabela `ordens_execucao` |
| OS, cliente, veículo, usuário | OS Service | referências `os_id`, `saga_id` e `veiculo_id` |
| Orçamento e pagamento | Billing | não aparecem aqui |

---

## Regras de negócio

### Estoque: quantidade, reservada e disponível

Cada peça tem estes números:

| Campo | Significado |
|---|---|
| `quantidade` | Unidades físicas em estoque |
| `reservada` | Unidades prometidas a OS cuja reserva está `ATIVA` e que ainda não saíram |
| `disponivel` | `quantidade - reservada`. Não é coluna: é calculado na leitura e devolvido pela API |
| `estoque_minimo` | Número informado no cadastro (padrão 1, não negativo). É guardado e devolvido pela API; nenhuma regra do serviço o consulta (ver [Limitações](#limitações-conhecidas)) |

Regras:

- **Reserva tudo ou nada.** `ReservarPecas` só é aceito se, para cada peça do pedido, `disponivel >= quantidade pedida`.
  Itens repetidos no mesmo comando são somados. Se uma peça não tem saldo, nada é reservado e o serviço
  responde `ReservaRecusada` com motivo `ESTOQUE_INSUFICIENTE` e o detalhe `disponível X, pedido Y`.
- **Item inexistente** (serviço ou peça que não existe no catálogo) recusa antes de olhar o saldo: `ReservaRecusada` com
  motivo `ITEM_INEXISTENTE`.
- **Serviços não têm estoque.** Entram no pedido só para serem precificados.
- **Preço da época.** `reserva_itens.preco_unitario` guarda o preço no momento da reserva. Mudar o preço no
  catálogo depois não altera uma reserva existente, e repetir o comando devolve os mesmos valores.
- **Uma reserva por OS** (`reservas.os_id` é único). Repetir `ReservarPecas` para a mesma OS devolve `PecasReservadas`
  com os itens da reserva existente, sem reservar de novo.
- **Trava de linha.** Toda alteração de quantidade usa `SELECT ... FOR UPDATE`. Quando o comando toca várias peças,
  elas são travadas em ordem de `id`, para que duas OS com as mesmas peças não se bloqueiem em ciclo.
- **Garantias do banco** (CHECK): `quantidade >= 0`, `reservada >= 0` e `reservada <= quantidade`. Duas reservas
  simultâneas não conseguem vender a mesma peça.
- **Entrada de estoque** (`POST /estoque/pecas/{peca_id}/entrada`) soma na `quantidade`, com trava de linha, e registra
  uma movimentação `ENTRADA` com o motivo informado.
- **Alteração (`PUT`)**: a nova `quantidade` não pode ficar abaixo de `reservada` (422).
- **Remoção**: peça com reserva ativa ou com qualquer movimentação não pode ser removida (409). Serviço em
  reserva ativa também não (409).
- Nomes de serviço e de peça são únicos; a checagem da aplicação ignora maiúsculas e minúsculas (409).

### Ordem de baixa: quando a reserva vira baixa

A reserva não tira nada do estoque físico: ela só aumenta `reservada`. A **baixa acontece no `EnfileirarOS`**, ou
seja, depois que o Billing confirmou o pagamento e o OS Service mandou a OS para a fila. Não depende do
diagnóstico nem do reparo.

```mermaid
stateDiagram-v2
    [*] --> ATIVA: ReservarPecas aceito
    ATIVA --> LIBERADA: LiberarReserva
    ATIVA --> CONSUMIDA: EnfileirarOS
    LIBERADA --> [*]
    CONSUMIDA --> [*]
```

Efeito de cada passo nas colunas da peça (`q` é a quantidade do item na reserva):

| Passo | `quantidade` | `reservada` | `disponivel` | Movimentação | Reserva |
|---|---|---|---|---|---|
| `ReservarPecas` aceito | igual | +q | -q | nenhuma | `ATIVA` |
| `LiberarReserva` com reserva `ATIVA` | igual | -q | +q | nenhuma | `LIBERADA` |
| `EnfileirarOS` com reserva `ATIVA` | -q | -q | igual | `SAIDA`, motivo `Baixa da OS <os_id>` | `CONSUMIDA` |
| `LiberarReserva` com reserva `CONSUMIDA` e ordem ainda `NA_FILA` (estorno) | +q | igual | +q | `ENTRADA`, motivo `Estorno da OS <os_id>` | segue `CONSUMIDA`; a ordem vai a `CANCELADA` |
| `LiberarReserva` com reserva `CONSUMIDA` e ordem em andamento ou finalizada | igual | igual | igual | nenhuma | segue `CONSUMIDA` |
| `LiberarReserva` sem reserva | igual | igual | igual | nenhuma | não existe |
| `POST /estoque/pecas/{id}/entrada` | +q | igual | +q | `ENTRADA` | não se aplica |

Observações:

- Entre a reserva e a baixa, as peças ficam reservadas: outra OS não as enxerga como disponíveis.
- `EnfileirarOS` sem reserva `ATIVA` responde `EnfileiramentoRecusado` (motivo `RESERVA_INEXISTENTE`) e não baixa nada.
- `EnfileirarOS` repetido para a mesma OS não baixa de novo: responde `OSEnfileirada` com a posição atual.
- `LiberarReserva` é idempotente: sempre responde `ReservaLiberada`, mesmo sem reserva, e uma segunda liberação não devolve
  as peças duas vezes.
- Cadastrar a peça com `quantidade` inicial não gera movimentação; só entrada, baixa e estorno geram.

### Fila de execução

```mermaid
stateDiagram-v2
    [*] --> NA_FILA: EnfileirarOS
    NA_FILA --> EM_DIAGNOSTICO: chamar a próxima ou diagnóstico
    EM_DIAGNOSTICO --> EM_EXECUCAO: reparo
    EM_EXECUCAO --> FINALIZADA: finalização
    NA_FILA --> CANCELADA: estorno da Saga
    FINALIZADA --> [*]
    CANCELADA --> [*]
```

- Transição fora do mapa acima é recusada com `422` e não publica evento.
- A ordem é a mais antiga primeiro (`enfileirada_em`). `POST /execucao/fila/proxima` pega a mais antiga em `NA_FILA` com
  `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`: dois atendentes chamando ao mesmo tempo recebem ordens diferentes.
- `GET /execucao/fila` lista primeiro as ordens `EM_EXECUCAO`, depois `EM_DIAGNOSTICO`, depois `NA_FILA`, cada grupo da mais
  antiga para a mais nova. `FINALIZADA` e `CANCELADA` saem da lista.
- `posicao` (em `OSEnfileirada`) é 1 mais a quantidade de ordens `NA_FILA` que entraram antes.
- `iniciada_em` é gravada ao entrar em `EM_EXECUCAO`; `finalizada_em`, ao finalizar. As rotas de andamento aceitam um corpo
  opcional `{"observacao": "..."}` (até 500 caracteres), gravado na ordem e enviado no evento.
- Não existe rota HTTP para cancelar uma ordem. `CANCELADA` só acontece pelo estorno da compensação da Saga, enquanto
  a ordem está `NA_FILA`.

---

## Modelo de dados

PostgreSQL 16, schema versionado pelo Alembic em `alembic/versions/0001_init_execucao.py`. O diagrama, com as
regras que o banco garante, também está em [`docs/modelo-de-dados.md`](docs/modelo-de-dados.md).

```mermaid
erDiagram
    pecas ||--o{ movimentacoes_estoque : movimenta
    reservas ||--|{ reserva_itens : "guarda o preço de"
    reservas ||..o| ordens_execucao : "mesmo os_id, sem FK"

    servicos {
        uuid id PK
        varchar nome UK
        varchar descricao
        numeric preco
        int tempo_estimado_minutos
    }
    pecas {
        uuid id PK
        varchar nome UK
        varchar descricao
        numeric preco
        int quantidade
        int estoque_minimo
        int reservada
    }
    movimentacoes_estoque {
        uuid id PK
        uuid peca_id FK
        varchar tipo "ENTRADA ou SAIDA"
        int quantidade
        varchar motivo
    }
    reservas {
        uuid id PK
        uuid os_id UK
        uuid saga_id
        enum estado "ATIVA, LIBERADA, CONSUMIDA"
    }
    reserva_itens {
        uuid id PK
        uuid reserva_id FK
        enum tipo "SERVICO ou PECA"
        uuid item_id
        varchar descricao
        int quantidade
        numeric preco_unitario
    }
    ordens_execucao {
        uuid id PK
        uuid os_id UK
        uuid saga_id
        uuid veiculo_id
        enum status "NA_FILA, EM_DIAGNOSTICO, EM_EXECUCAO, FINALIZADA, CANCELADA"
        varchar observacao
        timestamptz enfileirada_em
        timestamptz iniciada_em
        timestamptz finalizada_em
    }
    outbox {
        uuid id PK "message_id"
        varchar exchange
        varchar rota
        varchar tipo
        json corpo
        json cabecalhos
        timestamptz criado_em
        timestamptz publicado_em "nulo até o relay publicar"
    }
    mensagens_processadas {
        uuid message_id PK
        varchar tipo
        timestamptz processada_em
    }
```

| Tabela | Campos e tamanhos principais | Restrições e índices |
|---|---|---|
| `servicos` | `nome` varchar(150), `descricao` varchar(500), `preco` numeric(10,2), `tempo_estimado_minutos` int | `uq_servicos_nome`; CHECK `preco > 0`; CHECK `tempo_estimado_minutos` nulo ou `> 0` |
| `pecas` | `nome` varchar(150), `descricao` varchar(500), `preco` numeric(10,2), `quantidade`, `estoque_minimo`, `reservada` (int) | `uq_pecas_nome`; CHECK `preco > 0`, `quantidade >= 0`, `estoque_minimo >= 0`, `reservada >= 0`, `reservada <= quantidade` |
| `movimentacoes_estoque` | `peca_id` (FK `pecas.id`), `tipo` varchar(10), `quantidade`, `motivo` varchar(200) | CHECK `quantidade > 0`; CHECK `tipo` em (`ENTRADA`, `SAIDA`); índice `ix_movimentacoes_estoque_peca_id` |
| `reservas` | `os_id`, `saga_id`, `estado` (enum `reservaestado`) | `os_id` único: uma reserva por OS |
| `reserva_itens` | `reserva_id` (FK), `tipo` (enum `tipoitem`), `item_id`, `descricao` varchar(200), `quantidade`, `preco_unitario` numeric(10,2) | CHECK `quantidade > 0`, `preco_unitario >= 0`; índice `ix_reserva_itens_reserva_id`. `item_id` aponta para `servicos` ou `pecas` conforme `tipo`, sem FK |
| `ordens_execucao` | `os_id`, `saga_id`, `veiculo_id`, `status` (enum `statusexecucao`), `observacao` varchar(500), `enfileirada_em`, `iniciada_em`, `finalizada_em` (timestamptz) | `os_id` único: uma ordem por OS; índice `ix_ordens_execucao_status` |
| `outbox` | `id` (igual ao `message_id`), `exchange` varchar(60), `rota` varchar(80), `tipo` varchar(40), `corpo` json, `cabecalhos` json, `criado_em`, `publicado_em` | índice `ix_outbox_pendentes` (`publicado_em`, `criado_em`) |
| `mensagens_processadas` | `message_id` (PK), `tipo` varchar(40), `processada_em` | A chave primária é a chave de idempotência do consumidor |

Todas as chaves primárias são UUID criados pela aplicação. Datas em `timestamptz`, sempre devolvidas em UTC.

Conexões: cada processo usa um pool de até 5 conexões (`pool_size=3`, `max_overflow=2`), com `pool_pre_ping`. Cada pod
roda 2 processos (`UVICORN_WORKERS`); no teto do HPA (4 pods) são até 40 conexões.

---

## Mensageria

RabbitMQ, três exchanges `topic` duráveis e filas `quorum`. O serviço declara a topologia ao conectar (a declaração
é idempotente, então a ordem de subida dos serviços não importa). Fonte do contrato:
[`asyncapi.yaml`](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/contratos/asyncapi.yaml) e
[resumo do contrato](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/contratos/README.md), na plataforma.

| Elemento | Nome | Detalhe |
|---|---|---|
| Exchange de comandos | `oficina.comandos` | O OS Service publica; este serviço só liga a fila a ela |
| Exchange de eventos | `oficina.eventos` | Este serviço publica as respostas e as mudanças de estado |
| Exchange de DLQ | `oficina.dlx` | Destino das mensagens que esgotaram as entregas |
| Fila de comandos | `execucao-service.comandos` | `quorum`, ligada a `oficina.comandos` pela chave `execucao.#`, `x-delivery-limit: 5` |
| DLQ | `execucao-service.comandos.dlq` | `quorum`, ligada a `oficina.dlx` pela chave `execucao-service.comandos`; sem consumidor, serve para alerta e inspeção |

### Comandos consumidos

O serviço decide o tratamento pelo campo `tipo` do envelope, não pela chave de roteamento.

| Comando | Chave de roteamento | Payload | O que faz | Resposta |
|---|---|---|---|---|
| `ReservarPecas` | `execucao.reservar-pecas` | `itens`: lista de `{tipo, item_id, quantidade}` (`tipo` é `SERVICO` ou `PECA`; `quantidade >= 1`) | Precifica os itens e reserva as peças (tudo ou nada) | `PecasReservadas` ou `ReservaRecusada` |
| `LiberarReserva` | `execucao.liberar-reserva` | `motivo` (motivo da compensação; é aceito, mas não é usado) | Devolve a reserva `ATIVA` ao estoque; estorna se a reserva já foi consumida e a ordem ainda está `NA_FILA` | `ReservaLiberada`, sempre |
| `EnfileirarOS` | `execucao.enfileirar-os` | `veiculo_id` | Baixa as peças reservadas, consome a reserva e cria a ordem `NA_FILA` | `OSEnfileirada` ou `EnfileiramentoRecusado` |

### Eventos publicados

Exchange `oficina.eventos`, chave `execucao.<nome-do-evento-em-kebab-case>`.

| Evento | Chave de roteamento | Payload principal | Quando |
|---|---|---|---|
| `PecasReservadas` | `execucao.pecas-reservadas` | `itens` (cada um com `tipo`, `item_id`, `descricao`, `quantidade`, `preco_unitario`, `subtotal`) e `valor_total` | Reserva aceita, ou comando repetido para a mesma OS |
| `ReservaRecusada` | `execucao.reserva-recusada` | `motivo` (`ESTOQUE_INSUFICIENTE` ou `ITEM_INEXISTENTE`) e `itens` (`item_id`, `detalhe`) | Peça sem saldo ou item que não existe |
| `ReservaLiberada` | `execucao.reserva-liberada` | `{}` | Resposta a todo `LiberarReserva` |
| `OSEnfileirada` | `execucao.os-enfileirada` | `posicao` | Ordem criada na fila, ou `EnfileirarOS` repetido |
| `EnfileiramentoRecusado` | `execucao.enfileiramento-recusado` | `motivo` (`RESERVA_INEXISTENTE`) | `EnfileirarOS` sem reserva `ATIVA` |
| `DiagnosticoIniciado` | `execucao.diagnostico-iniciado` | `observacao` | `POST /execucao/fila/proxima` ou `POST /execucao/os/{os_id}/diagnostico` |
| `ExecucaoIniciada` | `execucao.execucao-iniciada` | `observacao` | `POST /execucao/os/{os_id}/reparo` |
| `ExecucaoFinalizada` | `execucao.execucao-finalizada` | `observacao` | `POST /execucao/os/{os_id}/finalizacao` |

Valores monetários trafegam como texto com duas casas (`"150.00"`), nunca como número de ponto flutuante.

### Envelope

Todo corpo de mensagem é o mesmo envelope JSON:

```json
{
  "message_id": "0d6f3c1e-5b7a-4c1e-9a52-6a0f3f8d2b11",
  "tipo": "PecasReservadas",
  "versao": 1,
  "saga_id": "7a1b2c3d-1111-4222-8333-444455556666",
  "os_id": "c93e5a10-2222-4333-8444-555566667777",
  "ocorrido_em": "2026-11-12T15:00:00Z",
  "origem": "execucao-service",
  "payload": {
    "itens": [
      {"tipo": "SERVICO", "item_id": "…", "descricao": "Troca de óleo", "quantidade": 1, "preco_unitario": "150.00", "subtotal": "150.00"},
      {"tipo": "PECA", "item_id": "…", "descricao": "Filtro de óleo", "quantidade": 2, "preco_unitario": "35.00", "subtotal": "70.00"}
    ],
    "valor_total": "220.00"
  }
}
```

| Campo | Descrição |
|---|---|
| `message_id` | UUID único por mensagem; é a chave de idempotência do consumidor |
| `tipo` | Nome do comando ou evento |
| `versao` | Sempre `1` |
| `saga_id`, `os_id` | Identificam a Saga (uma por OS) e a ordem de serviço |
| `ocorrido_em` | RFC 3339 em UTC |
| `origem` | `execucao-service` nos eventos; `os-service` nos comandos |
| `payload` | Conteúdo específico, descrito nas tabelas acima |

O contexto de rastreamento distribuído (`traceparent`, `tracestate` e `newrelic`) **não vai no corpo**: vai nos cabeçalhos AMQP.
As propriedades AMQP de cada evento publicado são `message_id` (igual ao do corpo), `type` (igual ao `tipo`), `correlation_id`
(igual ao `saga_id`), `content_type: application/json` e `delivery_mode: 2` (persistente).

### Outbox: publicação confiável

O evento nunca é publicado dentro do caso de uso. Ele é gravado na tabela `outbox` **na mesma transação** da mudança
de estado (estoque, reserva ou ordem). Um relay publica depois:

- O relay roda na mesma thread que consome comandos, a cada volta do laço de consumo (de até 1 segundo).
- Lê as linhas com `publicado_em IS NULL`, em ordem de `criado_em`, até 50 por volta, com `FOR UPDATE SKIP LOCKED`
  (réplicas diferentes não publicam a mesma linha).
- Publica com *publisher confirms* e `mandatory=True`; só marca `publicado_em` depois da confirmação do broker.
- Se o broker não aceita (por exemplo, nenhuma fila ligada à chave, porque o OS Service ainda não subiu), registra
  `publicacao_recusada`, interrompe a volta e tenta de novo na seguinte. O evento fica no outbox até alguém consumir.
- Se o processo cai depois de publicar e antes de marcar, o evento sai duas vezes; o inbox do consumidor absorve a repetição.
- A coluna `cabecalhos` guarda os cabeçalhos de rastreamento do momento em que o evento foi gravado, e o relay os
  republica como cabeçalhos AMQP.

### Inbox: idempotência do consumo

`ProcessarComandoUseCase.executar` começa gravando o `message_id` em `mensagens_processadas`, dentro da mesma transação
do efeito. Se a chave já existe, o comando é ignorado (log `mensagem_repetida`) e a mensagem recebe `ack`, sem repetir o
efeito. O estado, a resposta no outbox e o registro no inbox são confirmados juntos, no mesmo `COMMIT`.

```mermaid
sequenceDiagram
    autonumber
    participant OS as OS Service
    participant Q as Fila execucao-service.comandos
    participant W as Thread de mensageria
    participant DB as PostgreSQL
    participant X as Exchange oficina.eventos
    OS->>Q: comando em oficina.comandos
    Q->>W: entrega (prefetch 10)
    W->>DB: INSERT em mensagens_processadas
    alt message_id já existe
        W-->>Q: ack, sem efeito
    else mensagem nova
        W->>DB: SELECT FOR UPDATE nas peças e na reserva
        W->>DB: altera estoque, reserva ou ordem
        W->>DB: INSERT em outbox com o evento de resposta
        W->>DB: COMMIT
        W-->>Q: ack
    end
    W->>DB: SELECT outbox pendentes FOR UPDATE SKIP LOCKED
    W->>X: publica com confirmação do broker
    W->>DB: marca publicado_em
```

### Ack, falhas, retentativas e DLQ

| Situação | O que acontece |
|---|---|
| Comando processado (ou repetido) | `ack` manual, enviado **só depois do commit** |
| Mensagem ilegível: JSON inválido, `message_id`, `saga_id` ou `os_id` que não são UUID, ou `tipo` desconhecido | Log `mensagem_invalida` e `nack` sem reentrega: vai direto para a DLQ |
| Erro inesperado (banco fora do ar, por exemplo) | Rollback, log `falha_no_consumo` e `nack` com reentrega na mesma fila |
| Entregas esgotadas | O RabbitMQ conta as entregas (`x-delivery-limit: 5`): depois de seis entregas sem `ack` (a primeira e cinco reentregas) a mensagem vai para `oficina.dlx` e para a `execucao-service.comandos.dlq` |
| Broker ou banco indisponível | A thread não morre: reconecta com espera crescente (1 s, 2 s, 4 s, até 30 s) e redeclara a topologia |
| Sem `RABBITMQ_URL` | A API sobe e atende; a mensageria não sobe e os eventos ficam parados no outbox |

O serviço não espera entre as tentativas: o `nack` devolve a mensagem à fila na hora. A ordem entre mensagens não é garantida
quando há mais de um consumidor: cada processo da API (2 por pod) abre a própria conexão e consome da mesma fila.

### Propagação do trace

Com o agente do New Relic ativo, o serviço continua o trace do outro lado da fila:

1. Ao gravar o evento no outbox, `cabecalhos_de_rastreamento` captura o contexto do trace atual (`insert_distributed_trace_headers`).
2. O relay publica esses cabeçalhos junto com a mensagem.
3. Ao receber um comando, `consumo_rastreado` abre uma transação de background (`Message/RabbitMQ`, com o nome do comando) e aceita os
   cabeçalhos do comando (`accept_distributed_trace_headers`, transporte AMQP).

Sem o agente (ou fora de uma transação), os cabeçalhos ficam vazios e nada muda no fluxo.

---

## Papel na Saga

O OS Service orquestra a Saga de abertura da OS ([ADR-018](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/adr/ADR-018-saga-orquestrada.md)).
A Execução participa de três momentos: `RESERVANDO_PECAS`, `ENFILEIRANDO` e, depois, o andamento da execução.

Caminho feliz, só com o que passa por este serviço:

```mermaid
sequenceDiagram
    autonumber
    participant OS as OS Service
    participant EX as Execução
    participant BI as Billing
    actor F as Funcionário
    OS->>EX: ReservarPecas (itens da OS)
    EX-->>OS: PecasReservadas (itens com preço e valor_total)
    OS->>BI: GerarOrcamento
    Note over OS,BI: aprovação do cliente, cobrança e pagamento ficam no Billing
    BI-->>OS: PagamentoConfirmado
    OS->>EX: EnfileirarOS (veiculo_id)
    Note over EX: baixa das peças reservadas e ordem NA_FILA
    EX-->>OS: OSEnfileirada (posicao)
    F->>EX: POST /execucao/fila/proxima
    EX-->>OS: DiagnosticoIniciado
    F->>EX: POST /execucao/os/{os_id}/reparo
    EX-->>OS: ExecucaoIniciada
    F->>EX: POST /execucao/os/{os_id}/finalizacao
    EX-->>OS: ExecucaoFinalizada
    Note over OS: a Saga conclui e o funcionário entrega o veículo no OS Service
```

Recusas e compensações:

```mermaid
sequenceDiagram
    autonumber
    participant OS as OS Service
    participant EX as Execução
    OS->>EX: ReservarPecas
    EX-->>OS: ReservaRecusada (ESTOQUE_INSUFICIENTE ou ITEM_INEXISTENTE)
    Note over OS: nada foi reservado, a OS é cancelada
    OS->>EX: EnfileirarOS
    EX-->>OS: EnfileiramentoRecusado (RESERVA_INEXISTENTE)
    Note over OS: compensa em ordem inversa, uma por vez
    OS->>EX: LiberarReserva (motivo)
    EX-->>OS: ReservaLiberada
```

Como o OS Service usa cada resposta (`app/domain/saga.py`, no repositório do OS Service):

| Evento da Execução | Efeito no orquestrador |
|---|---|
| `PecasReservadas` | Precifica a OS com os itens recebidos e envia `GerarOrcamento` ao Billing |
| `ReservaRecusada` | Compensa com motivo `RESERVA_RECUSADA`; como não há reserva a liberar, a Saga encerra e a OS vai a `CANCELADA` |
| `ReservaLiberada` | Confirma a compensação `LiberarReserva` e segue para a próxima, ou encerra a Saga |
| `OSEnfileirada` | A OS vai para `NA_FILA`; a reserva é dada como consumida |
| `EnfileiramentoRecusado` | Compensa com motivo `ENFILEIRAMENTO_RECUSADO`: `Reembolsar`, `CancelarOrcamento` e `LiberarReserva`, nessa ordem |
| `DiagnosticoIniciado`, `ExecucaoIniciada`, `ExecucaoFinalizada` | A OS passa a `EM_DIAGNOSTICO`, `EM_EXECUCAO` e `FINALIZADA`; com `ExecucaoFinalizada` a Saga conclui |

Se a resposta não chega no prazo, o OS Service reenvia `EnfileirarOS` até 3 vezes e, esgotadas as tentativas, compensa; nos passos
anteriores ao pagamento, compensa direto. Por isso os três comandos são idempotentes: repetir `ReservarPecas`, `LiberarReserva` ou
`EnfileirarOS` responde de novo sem repetir o efeito. Depois que a OS entra na fila de execução, a oficina não pode mais cancelá-la.

---

## API REST

Autenticação: `Authorization: Bearer <token>` com o token de **funcionário** emitido pelo OS Service
(`POST /auth/token`, formulário com `username` e `password`). Aqui só se confere a assinatura (`SECRET_KEY` e `ALGORITHM`) e os
claims `tipo = usuario`, `sub` e `role` (`ADMIN` ou `ATENDENTE`). Não há banco de usuários neste serviço.

| Resposta | Quando |
|---|---|
| `401` | Token ausente, inválido, expirado ou sem os claims esperados |
| `403` | Token de cliente, ou funcionário sem perfil `ADMIN` em rota de escrita |
| `404` | Recurso não encontrado |
| `409` | Conflito: nome repetido, remoção de item com vínculo |
| `422` | Regra de negócio violada ou corpo inválido |

Erros de negócio devolvem `{"detail": "...", "correlation_id": "..."}`. Toda resposta leva o cabeçalho `x-request-id`.

### Catálogo de serviços

| Método | Caminho | Perfil | Descrição |
|---|---|---|---|
| POST | `/catalogo/servicos` | ADMIN | Cadastra serviço (201). Nome de 2 a 200 caracteres, `preco > 0`, `tempo_estimado_minutos` de 1 a 2880 |
| GET | `/catalogo/servicos` | ADMIN ou ATENDENTE | Lista serviços, com `skip` (padrão 0) e `limit` (padrão 100, máximo 1000) |
| GET | `/catalogo/servicos/{servico_id}` | ADMIN ou ATENDENTE | Obtém um serviço |
| PUT | `/catalogo/servicos/{servico_id}` | ADMIN | Atualiza o serviço |
| DELETE | `/catalogo/servicos/{servico_id}` | ADMIN | Remove (204); 409 se estiver em reserva ativa |

### Estoque de peças

| Método | Caminho | Perfil | Descrição |
|---|---|---|---|
| POST | `/estoque/pecas` | ADMIN | Cadastra peça (201), com `quantidade` (padrão 0) e `estoque_minimo` (padrão 1) |
| GET | `/estoque/pecas` | ADMIN ou ATENDENTE | Lista peças, com `skip` e `limit`; cada peça traz `reservada` e `disponivel` |
| GET | `/estoque/pecas/{peca_id}` | ADMIN ou ATENDENTE | Obtém uma peça |
| PUT | `/estoque/pecas/{peca_id}` | ADMIN | Atualiza a peça; 422 se `quantidade` ficar abaixo de `reservada` |
| DELETE | `/estoque/pecas/{peca_id}` | ADMIN | Remove (204); 409 com reserva ativa ou movimentação |
| POST | `/estoque/pecas/{peca_id}/entrada` | ADMIN | Registra entrada em estoque (`quantidade > 0`, `motivo` opcional) |

### Fila de execução

| Método | Caminho | Perfil | Descrição |
|---|---|---|---|
| GET | `/execucao/fila` | ADMIN ou ATENDENTE | Ordens em andamento ou na fila: em execução, em diagnóstico e na fila, da mais antiga para a mais nova |
| POST | `/execucao/fila/proxima` | ADMIN ou ATENDENTE | Pega a ordem mais antiga da fila e inicia o diagnóstico; 404 se a fila está vazia |
| GET | `/execucao/os/{os_id}` | ADMIN ou ATENDENTE | Ordem de execução da OS |
| POST | `/execucao/os/{os_id}/diagnostico` | ADMIN ou ATENDENTE | `NA_FILA` → `EM_DIAGNOSTICO`; corpo opcional `{"observacao": "..."}` |
| POST | `/execucao/os/{os_id}/reparo` | ADMIN ou ATENDENTE | `EM_DIAGNOSTICO` → `EM_EXECUCAO` |
| POST | `/execucao/os/{os_id}/finalizacao` | ADMIN ou ATENDENTE | `EM_EXECUCAO` → `FINALIZADA` |

Cada transição publica o evento correspondente (tabela de eventos acima) na mesma transação.

### Sistema e documentação

| Método | Caminho | Perfil | Descrição |
|---|---|---|---|
| GET | `/health` | público | Liveness: não consulta o banco, para que uma queda do banco não faça o Kubernetes reiniciar pods saudáveis |
| GET | `/health/ready` | público | Readiness: executa `SELECT 1`; sem banco responde 503 e o pod sai do balanceamento |
| GET | `{PREFIXO_DOCS}/docs` | público | Swagger UI |
| GET | `{PREFIXO_DOCS}/redoc` | público | ReDoc |
| GET | `{PREFIXO_DOCS}/openapi.json` | público | Especificação OpenAPI |

### Swagger

| Onde | URL |
|---|---|
| Local (`make up`, `PREFIXO_DOCS` vazio) | http://localhost:8002/docs |
| Na nuvem, pelo API Gateway (`PREFIXO_DOCS=/execucao`) | `<url_api>/execucao/docs` |

`<url_api>` é a URL do API Gateway: saída `url_api` de `make output` na plataforma, ou o parâmetro SSM
`/tech-challenge-f4/apigateway/endpoint`. O prefixo `/execucao` existe porque o OS Service ocupa `/docs` no mesmo gateway.
No Swagger, o botão **Authorize** (esquema `TokenFuncionario`) recebe o token de funcionário.

A coleção Postman da Saga completa (cadastro de serviço e peça, abertura da OS, pagamento, fila, compensações e conferência do
estoque) está em
[`docs/postman/`](https://github.com/pesant0s/tech-challenge-f4-plataforma/tree/main/docs/postman) na plataforma
(`oficina-fase04.postman_collection.json` e `local.postman_environment.json`).

---

## Configuração

Lida por `app/infrastructure/config.py` (pydantic-settings), de variáveis de ambiente ou de um arquivo `.env`.

| Variável | Obrigatória | Padrão no código | Local (`.env.example`) | No EKS | Descrição |
|---|---|---|---|---|---|
| `DATABASE_URL` | sim | — | `postgresql://execucao:execucao@db:5432/execucao` | Secret `execucao-service-segredos` (SSM `execucao-service/database_url`, com `?sslmode=require`) | Conexão PostgreSQL |
| `SECRET_KEY` | sim | — | `troque-por-uma-chave-aleatoria-de-pelo-menos-32-chars` | Secret (SSM `segredos/jwt_secret_key`) | Chave de assinatura do JWT. **Precisa ser a mesma do OS Service**, que emite os tokens |
| `ALGORITHM` | não | `HS256` | `HS256` | padrão | Algoritmo do JWT |
| `ALLOWED_ORIGINS` | não | `["http://localhost:3000"]` | `["http://localhost:3000"]` | ConfigMap: `["*"]` | CORS, lista em JSON |
| `RABBITMQ_URL` | não | vazio | `amqp://oficina:oficina@rabbitmq:5672/%2F` | Secret (SSM `rabbitmq/url`) | Sem ela, a API sobe sem consumir comandos nem publicar eventos |
| `PREFIXO_DOCS` | não | vazio | vazio | ConfigMap: `/execucao` | Prefixo do Swagger, do ReDoc e do `openapi.json` |
| `LOG_FORMAT` | não | `console` | `console` | ConfigMap: `json` | `json` em ambiente remoto |
| `LOG_LEVEL` | não | `INFO` | `INFO` | ConfigMap: `INFO` | Nível do logger raiz |
| `UVICORN_WORKERS` | não | `2` (em `entrypoint.sh`) | não definida | ConfigMap: `2` | Processos do uvicorn por pod |
| `NEW_RELIC_LICENSE_KEY` | não | vazio | vazio | Secret (SSM `newrelic/license_key`), só se houver licença | Vazia, o agente não sobe |
| `NEW_RELIC_APP_NAME` | não | — | `tech-challenge-execucao-service` | ConfigMap: `tech-challenge-f4-execucao-service` | Nome da aplicação no New Relic |
| `NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED` | não | — | não definida | ConfigMap: `false` | O stdout já chega ao New Relic pelo `nri-bundle`; o encaminhamento do agente duplicaria cada linha |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | só no compose | — | `execucao` / `execucao` / `execucao` | não se aplica | Usadas pelo container `db` do docker compose |
| `CONTRATO_ASYNCAPI` | não | — | — | não se aplica | Caminho do `asyncapi.yaml` para os testes (ver [Testes](#testes-e-cobertura)) |

O `.env` é ignorado pelo Git; `make setup` o cria a partir do `.env.example`, sem sobrescrever.

---

## Como rodar localmente

Não exige AWS nem conta no New Relic. Pré-requisitos: Docker (com Compose) e, para rodar os testes fora do container, Python 3.12.

### Alvos do Makefile

| Alvo | O que faz |
|---|---|
| `make help` | Lista os alvos |
| `make setup` | Cria o `.env` a partir do `.env.example`, sem sobrescrever |
| `make up` | `setup` e `docker compose up --build`: API, PostgreSQL e RabbitMQ com hot-reload |
| `make down` | `docker compose down -v`: derruba a stack local e remove os volumes |
| `make logs` | Acompanha os logs da API |
| `make sh` | Abre um shell no container da API |
| `make venv` | Cria o `.venv` (usa `python3.12` quando existe) e instala o `requirements.txt` |
| `make test` | Roda os testes com SQLite em memória (cria o `.venv` na primeira vez) |
| `make test-docker` | Roda os testes dentro do container, sem Python na máquina |
| `make cov` | Testes com cobertura (`term-missing` e `coverage.xml`) |
| `make build` | Constrói a imagem `tech-challenge-f4-execucao-service:<sha curto>` |
| `make render` | Renderiza os manifestos (`kubectl kustomize k8s/overlays/producao`) |
| `make implantar` | Aciona o pipeline de deploy na `main` (`gh workflow run`) |
| `make conta` | Mostra em qual conta AWS os comandos de infra vão atuar |
| `make infra-init` | Inicializa o Terraform com o estado desta conta |
| `make infra-up` | Cria o ECR e o banco (a plataforma precisa estar no ar) |
| `make infra-down` | Destrói o ECR e o banco |
| `make infra-validate` | `terraform fmt -check`, `init -backend=false` e `validate`, sem AWS |

### Modo isolado: este serviço sozinho

```bash
make up
```

O compose sobe três containers e roda `alembic upgrade head` antes de iniciar o servidor:

| Container | Imagem | Porta no host |
|---|---|---|
| `execucao-api` | build local, com o código montado e `--reload` | `8002` (aponta para a 8000 do container) |
| `execucao-db` | `postgres:16-alpine` | `5434` |
| `execucao-rabbitmq` | `rabbitmq:4.1-alpine` | `5672` |

| Recurso | URL |
|---|---|
| Swagger | http://localhost:8002/docs |
| ReDoc | http://localhost:8002/redoc |
| OpenAPI | http://localhost:8002/openapi.json |
| Liveness | http://localhost:8002/health |
| Readiness | http://localhost:8002/health/ready |

Este serviço não emite token. Em modo isolado, gere um token de funcionário com a mesma `SECRET_KEY` do `.env`:

```bash
docker compose exec api python -c "
from datetime import datetime, timedelta, timezone
from jose import jwt
from app.infrastructure.config import settings
claims = {'sub': 'admin', 'role': 'ADMIN', 'tipo': 'usuario', 'exp': datetime.now(timezone.utc) + timedelta(hours=1)}
print(jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM))"
```

Cole o token no **Authorize** do Swagger e cadastre um serviço e uma peça (com `quantidade` 10, por exemplo). Para exercitar os comandos
sem o OS Service, publique um `ReservarPecas` e um `EnfileirarOS` e leia as respostas (troque `<ID_DA_PECA>` e `<ID_DO_SERVICO>` pelos `id`
devolvidos no cadastro):

```bash
docker compose exec -T -e PECA_ID=<ID_DA_PECA> -e SERVICO_ID=<ID_DO_SERVICO> api python - <<'EOF'
import json, os, time, uuid
from datetime import datetime, timezone
import pika

conexao = pika.BlockingConnection(pika.URLParameters(os.environ["RABBITMQ_URL"]))
canal = conexao.channel()
fila = canal.queue_declare("", exclusive=True).method.queue
canal.queue_bind(fila, "oficina.eventos", "execucao.#")
os_id, saga_id = str(uuid.uuid4()), str(uuid.uuid4())

def enviar(tipo, rota, payload):
    envelope = {"message_id": str(uuid.uuid4()), "tipo": tipo, "versao": 1, "saga_id": saga_id, "os_id": os_id,
                "ocorrido_em": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "origem": "os-service", "payload": payload}
    canal.basic_publish("oficina.comandos", rota, json.dumps(envelope).encode())
    for _ in range(50):
        metodo, _propriedades, corpo = canal.basic_get(fila, auto_ack=True)
        if metodo:
            print(metodo.routing_key, json.loads(corpo)["payload"])
            return
        time.sleep(0.1)
    print("sem resposta para", tipo)

enviar("ReservarPecas", "execucao.reservar-pecas", {"itens": [
    {"tipo": "SERVICO", "item_id": os.environ["SERVICO_ID"], "quantidade": 1},
    {"tipo": "PECA", "item_id": os.environ["PECA_ID"], "quantidade": 2}]})
enviar("EnfileirarOS", "execucao.enfileirar-os", {"veiculo_id": str(uuid.uuid4())})
conexao.close()
EOF
```

Saída esperada: `execucao.pecas-reservadas` com os itens e o `valor_total`, e `execucao.os-enfileirada` com `{'posicao': 1}`. Depois,
`GET /estoque/pecas/<ID_DA_PECA>` mostra `quantidade` 8 e `reservada` 0, e `POST /execucao/fila/proxima` devolve a ordem em
`EM_DIAGNOSTICO`.

### Modo integrado: com os outros serviços

O ambiente local da Saga (RabbitMQ, os dois PostgreSQL e o MongoDB) sobe pela plataforma:

```bash
# no repositório tech-challenge-f4-plataforma
make local-up        # RabbitMQ :5672, PostgreSQL da Execução :5434 (execucao/execucao), entre outros
make local-status
make local-down      # derruba e apaga os volumes
```

O container `db` e o RabbitMQ do `make up` deste repositório publicam as mesmas portas (`5434` e `5672`) e as mesmas credenciais.
Por isso, no modo integrado **não rode `make up`**: rode a API na máquina, apontando para o ambiente da plataforma, com a mesma
`SECRET_KEY` do OS Service:

```bash
make venv
export DATABASE_URL=postgresql://execucao:execucao@localhost:5434/execucao
export RABBITMQ_URL='amqp://oficina:oficina@localhost:5672/%2F'
export SECRET_KEY='<a mesma do OS Service>'
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --port 8002
```

Com o OS Service e o Billing rodando do mesmo jeito (cada um na sua porta), importe a coleção e o ambiente `local` do Postman
(`execucaoUrl` é `http://localhost:8002`) e execute a pasta *Caminho feliz*.

---

## Testes e cobertura

```bash
make test         # SQLite em memória, Python 3.12 (cria o .venv na primeira vez)
make test-docker  # a mesma suíte dentro do container
make cov          # com cobertura
```

Os testes usam SQLite em memória (`DATABASE_URL="sqlite:///:memory:"`) e uma `SECRET_KEY` de teste; não precisam de PostgreSQL.
O comando do CI é:

```bash
pytest --cov=app --cov-report=term-missing --cov-report=xml --cov-fail-under=80 -q
```

**Cobertura mínima de 80%**: abaixo disso o job `Testes e cobertura` falha.

| Suíte | Testes | O que cobre |
|---|---|---|
| `test_dominio.py` | 17 | Entidades sem banco e sem HTTP: `disponivel`, reservar, liberar, baixar, repor, soma da reserva em decimal, transições da ordem |
| `test_comandos_saga.py` | 17 | Os três comandos contra o banco de testes: precificação, recusa sem reserva parcial, itens repetidos, idempotência por `message_id`, liberação, estorno, baixa, posição na fila |
| `test_mensageria.py` | 20 | Consumidor (ack depois do processamento, duplicata, DLQ, devolução à fila), relay do outbox, chave de roteamento, topologia (quorum, limite de entregas, DLQ), rastreamento e a prova contra um RabbitMQ real |
| `test_execucao.py` | 16 | Rotas da fila, ordenação, `proxima`, eventos por passo, transição inválida (422), 404, `reservada` e `disponivel`, remoções com 409 |
| `test_catalogo.py` | 11 | CRUD de serviços, validações, paginação e exigência de token |
| `test_estoque.py` | 12 | CRUD de peças, validações, paginação e entrada de estoque |
| `test_autenticacao.py` | 11 | Claims do token, token expirado, token de cliente (403), ADMIN e ATENDENTE |
| `test_observabilidade.py` | 13 | Campos do log JSON, `correlation_id`, cabeçalhos de segurança, liveness sem banco e readiness |
| `test_integridade.py` | 7 | As restrições CHECK e UNIQUE do banco recusam dado inconsistente |
| `test_prefixo_docs.py` | 2 | Swagger na raiz ou sob `PREFIXO_DOCS` |
| **Total** | **126** | `pytest --collect-only -q`: 126 coletados; 125 passam e 1 é pulado |

O teste pulado é `test_trabalhador_contra_rabbitmq_real`: ele só roda se houver um RabbitMQ em `localhost:5672` (o CI sobe um
como serviço do job). Os testes com canal falso cobrem o mesmo código sem o broker.

Contrato: cada evento gravado no outbox pelos testes é validado contra os schemas do `asyncapi.yaml` quando o repositório
`tech-challenge-f4-plataforma` está ao lado deste (ou em `CONTRATO_ASYNCAPI`). Sem o arquivo, a conferência é pulada, que é o
caso do CI.

### Cobertura e qualidade atuais

| Medição | Valor | Fonte |
|---|---|---|
| Cobertura (SonarQube Cloud, branch `main`) | 97,2% | API pública do SonarQube Cloud |
| Cobertura local, `pytest --cov=app`, sem RabbitMQ | 94,61% | execução local (a prova contra RabbitMQ real fica pulada) |
| Quality Gate | OK | SonarQube Cloud |
| Bugs | 0 | SonarQube Cloud |
| Vulnerabilidades | 6 | SonarQube Cloud: alertas de segurança do workflow e do `Dockerfile` (ver abaixo) |
| Code smells | 1 | SonarQube Cloud: ordem do `CORSMiddleware` em `app/main.py` |
| Linhas duplicadas | 0,0% | SonarQube Cloud |

```bash
curl -s "https://sonarcloud.io/api/measures/component?component=pesant0s_tech-challenge-f4-execucao-service&metricKeys=coverage,bugs,vulnerabilities,code_smells"
```

As 6 vulnerabilidades abertas estão no `ci-cd.yml` (instalação de dependências sem travar versões e sem `--only-binary`, download do
kubeconform, e a senha descartável do PostgreSQL que existe só no job de prova da imagem) e no `COPY . .` do `Dockerfile`. Nenhuma está
em `app/`. Os arquivos de `tests/` e `alembic/` ficam fora da conta de cobertura (`sonar.coverage.exclusions`).

---

## Pipeline CI/CD

Arquivo: `.github/workflows/ci-cd.yml`. Gatilhos: push em `develop` e `main`, pull request para `develop` e `main`, e
`workflow_dispatch` (execução manual, usada por `make implantar`). Execuções novas do mesmo ref cancelam as anteriores só em pull request.

```mermaid
flowchart LR
  T["Testes e cobertura<br/>pytest · mínimo de 80%"]
  M["Validar manifestos Kubernetes<br/>kustomize + kubeconform"]
  Q["Qualidade<br/>SonarQube Cloud"]
  I["Build e prova da imagem<br/>PostgreSQL + RabbitMQ"]
  D["Deploy no EKS<br/>main e AMBIENTE_ATIVO true"]
  N["Publicação e deploy não executados<br/>main e ambiente desligado"]
  T --> Q
  T --> I
  M --> I
  T --> D
  Q --> D
  M --> D
  I --> D
  I --> N
```

| Job | Quando roda | O que faz |
|---|---|---|
| `Testes e cobertura` | sempre | Python 3.12, RabbitMQ 4.1 como serviço, `pytest` com `--cov-fail-under=80`, publica `coverage.xml` como artefato |
| `Qualidade (SonarQube Cloud)` | sempre, depois dos testes | Baixa a cobertura e roda o scanner; o quality gate reprova o pipeline (`sonar.qualitygate.wait=true`). Usa o secret `SONAR_TOKEN` |
| `Validar manifestos Kubernetes` | sempre | `kubectl kustomize k8s/overlays/producao` e `kubeconform -strict` |
| `Build e prova da imagem` | depois de testes e manifestos | Constrói a imagem, sobe contra PostgreSQL 16 (senha com caracteres especiais, como em produção) e RabbitMQ 4.1, e espera `GET /health/ready` responder e o log `mensageria_conectada` aparecer. Exercita o mesmo caminho de um deploy novo: o entrypoint migra um banco vazio |
| `Publicação e deploy não executados` | `main`, sem ser pull request, com `AMBIENTE_ATIVO` diferente de `true` | Só registra no resumo que o ambiente está desligado. Job pulado não é falha |
| `Deploy no EKS` | `main`, sem ser pull request, com `AMBIENTE_ATIVO = true`; depois de testes, qualidade, manifestos e imagem | Ver abaixo |

**Checks obrigatórios da `main`** (proteção de branch): `Testes e cobertura`, `Validar manifestos Kubernetes`, `Build e prova da imagem`
e `Qualidade (SonarQube Cloud)`. A `main` só recebe código por Pull Request, a regra vale também para administradores, e não há push direto
nem force push.

**`AMBIENTE_ATIVO`** é uma variável do repositório que diz ao pipeline se o ambiente AWS existe ([ADR-013](https://github.com/pesant0s/tech-challenge-f4-plataforma#readme),
README da plataforma). A plataforma a liga em `make up` e a desliga em `make down`. Com ela desligada, o pipeline roda tudo o que
não depende da nuvem.

### Passos do job de deploy

1. Autentica na AWS. Com o secret `AWS_ROLE_ARN`, por OIDC (sem chave estática). Sem ele, com as credenciais temporárias
   do laboratório da AWS Academy (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `AWS_SESSION_TOKEN`).
2. Descobre o ID da conta e roda `terraform apply` em `infra/` (ECR, banco e parâmetro SSM; idempotente), com o estado no bucket
   `tech-challenge-f4-tfstate-<conta>`.
3. Faz login no ECR, constrói a imagem e publica com a tag dos 7 primeiros caracteres do SHA do commit.
4. Aponta o `kubectl` para o cluster, lendo o nome em `/tech-challenge-f4/cluster/nome`.
5. Cria o namespace `execucao-service`.
6. Monta o Secret `execucao-service-segredos` a partir do SSM, a cada deploy: `DATABASE_URL`, `SECRET_KEY`, `RABBITMQ_URL` e,
   se houver licença (valor diferente de vazio e de `desligado`), `NEW_RELIC_LICENSE_KEY`. Nenhum segredo é versionado.
7. Troca o placeholder da imagem (`kustomize edit set image`), aplica `kubectl apply -k k8s/overlays/producao` e espera o
   `rollout status` por até 300 s.
8. Teste de fumaça pelo API Gateway: `GET <endpoint>/execucao/openapi.json` até responder 200 (30 tentativas, 10 s entre elas).
9. Se algo falhar, mostra `kubectl get all` e as últimas 100 linhas de log do namespace.

### Secrets e variáveis do repositório (só os nomes)

| Nome | Tipo | Uso |
|---|---|---|
| `SONAR_TOKEN` | secret | Scanner do SonarQube Cloud |
| `AWS_ROLE_ARN` | secret | Autenticação OIDC (conta comum) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | secrets | Credenciais temporárias do laboratório (quando não há `AWS_ROLE_ARN`) |
| `AMBIENTE_ATIVO` | variável | Liga ou desliga publicação e deploy |

A plataforma grava os secrets e a variável nos cinco repositórios (`make github-segredos`, `make ambiente-ligar` e `make ambiente-desligar`).

---

## Infraestrutura própria (`infra/`)

Terraform (versão 1.10 ou superior, provider `aws` ~> 5.60 e `random` ~> 3.6). Rede e cluster pertencem à plataforma; aqui só se lê o que ela publicou.

| Recurso | Detalhe |
|---|---|
| `aws_ecr_repository.api` | `tech-challenge-f4-execucao-service`, scan ao enviar a imagem, `force_delete` |
| `aws_ecr_lifecycle_policy.api` | Mantém as 10 últimas imagens |
| `aws_db_subnet_group.banco` | Subnets privadas da VPC |
| `aws_security_group.banco` | Entrada TCP 5432 só a partir do security group do cluster |
| `random_password.banco` | 24 caracteres; especiais limitados a `_` e `-` (o RDS recusa `/`, `@`, `"` e espaço, e eles quebrariam a URL) |
| `aws_db_instance.banco` | `tech-challenge-f4-execucao-service-db`: PostgreSQL 16, `db.t3.micro`, 20 GB gp2, criptografado, não público, banco e usuário `execucao`, backup de 7 dias, sem snapshot final e sem proteção contra exclusão (ambiente efêmero), sem enhanced monitoring nem Performance Insights |
| `aws_ssm_parameter.database_url` | `SecureString` `/tech-challenge-f4/execucao-service/database_url`, com `?sslmode=require` |

Saídas: `ecr_url` e `banco_endpoint`. Etiquetas padrão em todo recurso: `Project=tech-challenge-f4`, `Fase=04`,
`Repositorio=tech-challenge-f4-execucao-service`, `ManagedBy=terraform`.

**Estado remoto.** Backend S3 no bucket `tech-challenge-f4-tfstate-<conta>` (criado pela plataforma em `make bootstrap`), chave
`execucao-service/terraform.tfstate`, criptografado, com trava por `use_lockfile`. Bucket e região entram por `-backend-config`, porque dependem
da conta de quem executa (`make infra-init` e o pipeline fazem isso).

**Parâmetros SSM** (contrato em
[`docs/infraestrutura/contrato.md`](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/infraestrutura/contrato.md)):

| Parâmetro | Quem usa | Direção |
|---|---|---|
| `/tech-challenge-f4/rede/vpc_id` | `infra/` (security group do banco) | lê |
| `/tech-challenge-f4/rede/subnets_privadas` | `infra/` (subnet group do banco) | lê |
| `/tech-challenge-f4/cluster/sg_id` | `infra/` (regra de entrada do banco) | lê |
| `/tech-challenge-f4/cluster/nome` | pipeline (kubeconfig) | lê |
| `/tech-challenge-f4/apigateway/endpoint` | pipeline (teste de fumaça) | lê |
| `/tech-challenge-f4/segredos/jwt_secret_key` | pipeline (Secret `SECRET_KEY`) | lê |
| `/tech-challenge-f4/rabbitmq/url` | pipeline (Secret `RABBITMQ_URL`) | lê |
| `/tech-challenge-f4/newrelic/license_key` | pipeline (Secret `NEW_RELIC_LICENSE_KEY`) | lê |
| `/tech-challenge-f4/execucao-service/database_url` | `infra/` grava; o pipeline lê para o Secret `DATABASE_URL` | **escreve** |

---

## Kubernetes (`k8s/`)

Kustomize: `k8s/base` e o overlay `k8s/overlays/producao` (namespace `execucao-service`, rótulo `app.kubernetes.io/instance: producao`, imagem trocada
pelo pipeline). O Secret não está nos manifestos: quem o cria é o pipeline.

| Recurso | Configuração |
|---|---|
| `Namespace` | `execucao-service` |
| `ServiceAccount` | `execucao-service`, sem montar o token da API do Kubernetes |
| `ConfigMap` | `execucao-service`: `ALLOWED_ORIGINS`, `LOG_FORMAT=json`, `LOG_LEVEL`, `UVICORN_WORKERS=2`, `NEW_RELIC_APP_NAME`, `NEW_RELIC_APPLICATION_LOGGING_FORWARDING_ENABLED=false`, `PREFIXO_DOCS=/execucao` |
| `Deployment` | 2 réplicas, porta 8000, `envFrom` do ConfigMap e do Secret `execucao-service-segredos` |
| `Service` | `NodePort`, porta 80 para a porta `http` do pod, **`nodePort: 30081`** (fixo: o NLB da plataforma aponta para ele) |
| `HorizontalPodAutoscaler` | 2 a 4 réplicas, alvo de 70% de CPU; só CPU, porque a memória de um processo Python é quase fixa; janela de estabilização de 300 s na redução |
| `PodDisruptionBudget` | `minAvailable: 1` |

Probes (todas por HTTP na porta `http`):

| Sonda | Caminho | Parâmetros |
|---|---|---|
| `startupProbe` | `/health` | a cada 5 s, até 12 falhas (60 s): cobre o `alembic upgrade head` do boot sem a liveness matar o pod |
| `readinessProbe` | `/health/ready` | a cada 10 s, 3 falhas |
| `livenessProbe` | `/health` | a cada 20 s, 3 falhas |

Recursos: requests de `100m` de CPU e `256Mi` de memória; limite de memória de `512Mi` (sem limite de CPU). Segurança do container: `runAsNonRoot`,
UID e GID `10001`, `allowPrivilegeEscalation: false`, todas as capabilities removidas; `readOnlyRootFilesystem` fica `false`
porque o agente do New Relic grava o próprio log em disco.

A imagem (`Dockerfile`) tem dois estágios sobre `python:3.12-slim`, roda com o usuário numérico `10001` e declara `HEALTHCHECK` em
`GET /health`. O `entrypoint.sh` executa `alembic upgrade head` e inicia `uvicorn` com `--workers ${UVICORN_WORKERS:-2}` e `--no-access-log`;
só usa `newrelic-admin run-program` se `NEW_RELIC_LICENSE_KEY` estiver definida.

```bash
make render    # mostra o que irá para o cluster
```

---

## Deploy na AWS

O ambiente é efêmero: sobe para ensaio e gravação e é destruído depois ([ADR-024](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/adr/ADR-024-ambientes.md)).
O deploy passa sempre pelo pipeline; não há deploy manual paralelo.

```mermaid
flowchart LR
  P["1. plataforma<br/>make bootstrap · make up<br/>make github-segredos"]
  S["2. este repositório<br/>make infra-up · make implantar"]
  L["3. auth-lambda<br/>make apply"]
  P --> S --> L
```

Ordem de subida (os três serviços podem subir em paralelo entre si):

1. **Plataforma** (`tech-challenge-f4-plataforma`): `make bootstrap` (bucket do estado, uma vez por conta), `make up` (VPC, EKS, NLB, API Gateway, RabbitMQ; liga
   `AMBIENTE_ATIVO` nos cinco repositórios) e `make github-segredos` (credenciais da AWS e chaves do New Relic nos repositórios).
2. **Este serviço**, com as credenciais AWS da conta no ambiente (`AWS_PROFILE`, ou `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `AWS_SESSION_TOKEN`):
   ```bash
   make conta         # confirma a conta AWS e a região
   make infra-up      # ECR, RDS e parâmetro SSM (pede confirmação do terraform apply)
   make implantar     # aciona o pipeline na main: imagem, Secret, manifestos e teste de fumaça
   ```
   Se o ambiente já estava ligado quando o código chegou à `main`, o próprio merge dispara o deploy.
3. **Lambda** (`tech-challenge-f4-auth-lambda`): `make apply`, depois que o OS Service estiver no ar.

Validação: `GET <url_api>/execucao/openapi.json` responde 200 (é o teste de fumaça do pipeline), e o fluxo completo roda com a coleção Postman
apontando para a URL do API Gateway.

**Destruição, na ordem inversa:** Lambda, depois os serviços (`make infra-down` aqui: apaga o ECR, o RDS e o parâmetro SSM) e por último a
plataforma (`make down`, que recusa a destruição enquanto existirem Lambda ou bancos dos serviços). O namespace do serviço some junto com o cluster.

---

## Observabilidade

| Sinal | Como |
|---|---|
| APM e traces | Agente Python do New Relic na imagem. Só sobe com `NEW_RELIC_LICENSE_KEY`; sem ela, a mesma imagem roda igual em desenvolvimento |
| Logs | JSON no stdout (`LOG_FORMAT=json`); o `nri-bundle` da plataforma os coleta. Com o agente ativo, cada linha leva `trace.id` e `span.id` |
| Correlação | `correlation_id` em todas as linhas: nas requisições HTTP vem de `x-request-id`, `x-correlation-id` ou `x-amzn-trace-id` (o `requestId` do API Gateway) ou é criado aqui; ao consumir um comando é o `saga_id` |
| Traces pela fila | O contexto do trace atravessa o RabbitMQ nos cabeçalhos AMQP (ver [Propagação do trace](#propagação-do-trace)) |
| Health | `/health` (liveness) e `/health/ready` (readiness, consulta o banco) |

Exemplo de linha de log de um comando processado:

```json
{"timestamp": "2026-11-12T15:00:00.123456+00:00", "level": "INFO", "logger": "oficina.execucao",
 "message": "c93e5a10-... · ReservarPecas → PecasReservadas", "correlation_id": "7a1b2c3d-...",
 "evento": "comando_processado", "saga_id": "7a1b2c3d-...", "os_id": "c93e5a10-...",
 "tipo": "ReservarPecas", "resposta": "PecasReservadas"}
```

Valores do campo `evento` que o serviço registra: `comando_processado`, `mensagem_repetida`, `mensagem_invalida`, `falha_no_consumo`,
`publicacao_recusada`, `mensageria_conectada` e `mensageria_reconectando`. Requisições HTTP saem com `logger=oficina.http` e os campos
`http_method`, `http_path`, `http_status` e `duracao_ms`. Campos nulos ficam fora da linha (o New Relic gravaria `null` como texto).

Dashboard e alertas são definidos como código na plataforma (`observabilidade.tf`) e leem estes logs:

| Item | Onde usa os dados da Execução |
|---|---|
| Dashboard **Tech Challenge · Oficina**, página *Saga* | *Comandos atendidos pela Execução e pelo Billing* (`evento = comando_processado`, por `tipo`); *Mensagens repetidas, descartadas ou com falha*; *Consumo de mensagens por serviço (rastreamento distribuído)* |
| Dashboard, página *Kubernetes* | CPU, memória, réplicas do HPA e reinícios por pod, incluindo o namespace `execucao-service` |
| Alerta *Falha ao processar mensagens da Saga* | Linhas de `oficina.mensageria` com `falha_no_consumo` ou `mensagem_invalida`, em janela de 5 minutos |

---

## Decisões arquiteturais

ADRs no repositório da plataforma, em
[`docs/adr/`](https://github.com/pesant0s/tech-challenge-f4-plataforma/tree/main/docs/adr):

| ADR | Decisão | Relação com este serviço |
|---|---|---|
| [ADR-017](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/adr/ADR-017-divisao-em-microsservicos.md) | Três microsserviços, divididos pelas áreas da oficina | A Execução absorve catálogo, estoque e fila de OS; o preço dos itens passa a vir daqui |
| [ADR-018](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/adr/ADR-018-saga-orquestrada.md) | Saga orquestrada, com o orquestrador no OS Service | Este serviço é o participante que reserva peças e enfileira |
| [ADR-019](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/adr/ADR-019-rabbitmq.md) | Mensageria com RabbitMQ no cluster | Topologia, filas quorum, DLQ e limite de entregas |
| [ADR-020](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/adr/ADR-020-banco-por-servico.md) | Um banco por serviço: PostgreSQL na OS e na Execução | Escolhido pela reserva com `FOR UPDATE` e pela fila com `FOR UPDATE SKIP LOCKED` |
| [ADR-021](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/adr/ADR-021-outbox-e-idempotencia.md) | Outbox transacional e consumo idempotente | Tabelas `outbox` e `mensagens_processadas`, `ack` depois do commit |
| [ADR-024](https://github.com/pesant0s/tech-challenge-f4-plataforma/blob/main/docs/adr/ADR-024-ambientes.md) | Desenvolvimento local com docker compose, entrega na AWS | `make up` local; EKS efêmero na entrega |

---

## Limitações conhecidas

- **Migrations com duas réplicas.** Cada pod roda `alembic upgrade head` na subida (`entrypoint.sh`, com `set -e`), e o Deployment tem 2 réplicas. Num banco
  vazio, as duas migram ao mesmo tempo e uma delas pode falhar com erro de duplicidade do PostgreSQL (`DuplicateTable alembic_version` na nuvem;
  `UniqueViolation` em `pg_type_typname_nsp_index` ao repetir a corrida com dois `alembic upgrade head` simultâneos); o container sai, o Kubernetes o reinicia
  uma vez e, na volta, a migration já está aplicada e o pod sobe normalmente. Não há trava entre as réplicas. Resolver exigiria rodar a migration fora da
  subida dos pods (um Job ou um `initContainer`) ou travar com um *advisory lock* do PostgreSQL; isso não está implementado.
- **RabbitMQ sem volume.** O broker do cluster usa `emptyDir`: se o pod for recriado, filas e mensagens pendentes somem. O outbox deste serviço
  republica o que não foi confirmado, e o prazo por passo da Saga do OS Service cobre comandos que se perderam. A topologia é redeclarada na reconexão.
- **Os testes não exercitam as travas.** A suíte roda em SQLite, que ignora `FOR UPDATE` e `SKIP LOCKED`. A garantia contra reserva concorrente
  depende do PostgreSQL e das restrições CHECK (que os testes conferem à parte).
- **`estoque_minimo` é informativo.** É gravado e devolvido pela API, mas nenhuma regra o usa: não bloqueia reserva, não gera alerta nem filtra listagem.
- **`PUT /estoque/pecas/{id}` não registra movimentação.** Ajustar a `quantidade` por ele muda o saldo sem deixar rastro em `movimentacoes_estoque`;
  só a entrada, a baixa e o estorno registram.
- **Limites de tamanho diferentes entre a API e o banco.** O corpo HTTP aceita nome de até 200 caracteres e descrição de até 1000 (serviços e peças), e motivo
  de entrada de até 500, mas as colunas são `varchar(150)`, `varchar(500)` e `varchar(200)`. Um valor entre os dois limites é aceito pela API e recusado pelo PostgreSQL.
- **Contrato × código.** O AsyncAPI permite `ESTOQUE_INSUFICIENTE` como motivo de `EnfileiramentoRecusado`, mas este serviço só emite `RESERVA_INEXISTENTE`
  (o saldo já foi reservado antes). O campo `motivo` de `LiberarReserva` é aceito e ignorado. O contrato diz que orçamento expirado leva a OS a `NEGADA`,
  mas o código do OS Service a leva a `CANCELADA`.
- **Contrato fora do CI.** A validação dos eventos contra o `asyncapi.yaml` só roda quando o repositório da plataforma está ao lado deste
  (ou em `CONTRATO_ASYNCAPI`); o CI não o baixa e pula essa conferência.
- **DLQ sem consumidor e reentrega imediata.** Uma mensagem que falha volta à fila sem espera até o limite de entregas e depois fica na DLQ, onde
  só há alerta e inspeção manual; não há reprocessamento automático.
- **Token sem revogação.** O serviço só confere assinatura e validade: um usuário desativado no OS Service continua aceito até o token expirar.
- **Webhook do Mercado Pago.** Não é deste serviço, mas afeta o ambiente: a URL do API Gateway precisa ser cadastrada no painel do Mercado Pago a cada ambiente novo.
- **Alertas abertos no SonarQube Cloud.** Os 6 alertas de segurança do workflow e do `Dockerfile` e o code smell da ordem do `CORSMiddleware` seguem abertos; o Quality Gate está aprovado.
