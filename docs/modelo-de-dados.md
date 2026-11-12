# Modelo de dados

Schema PostgreSQL do serviço de Execução, versionado pelo Alembic em `alembic/versions`. O OS Service
e o Billing têm bancos próprios: aqui `os_id`, `saga_id` e `veiculo_id` são só referências, sem chave
estrangeira.

## Diagrama ER

```mermaid
erDiagram
    pecas ||--o{ movimentacoes_estoque : movimenta
    reservas ||--|{ reserva_itens : "guarda o preço de"
    reservas ||--o| ordens_execucao : "vira, por os_id"

    servicos {
        uuid id PK
        varchar nome UK
        numeric preco "> 0"
        int tempo_estimado_minutos
    }
    pecas {
        uuid id PK
        varchar nome UK
        numeric preco "> 0"
        int quantidade ">= 0"
        int estoque_minimo
        int reservada "0 a quantidade"
    }
    movimentacoes_estoque {
        uuid id PK
        uuid peca_id FK
        varchar tipo "ENTRADA | SAIDA"
        int quantidade
        varchar motivo
    }
    reservas {
        uuid id PK
        uuid os_id UK
        uuid saga_id
        enum estado "ATIVA | LIBERADA | CONSUMIDA"
    }
    reserva_itens {
        uuid id PK
        uuid reserva_id FK
        enum tipo "SERVICO | PECA"
        uuid item_id
        varchar descricao
        int quantidade
        numeric preco_unitario "preço no momento da reserva"
    }
    ordens_execucao {
        uuid id PK
        uuid os_id UK
        uuid saga_id
        uuid veiculo_id
        enum status "NA_FILA | EM_DIAGNOSTICO | EM_EXECUCAO | FINALIZADA | CANCELADA"
        varchar observacao
        timestamptz enfileirada_em
        timestamptz iniciada_em
        timestamptz finalizada_em
    }
    outbox {
        uuid id PK "message_id"
        varchar exchange
        varchar rota
        jsonb corpo
        timestamptz publicado_em "nulo até o relay publicar"
    }
    mensagens_processadas {
        uuid message_id PK
        varchar tipo
    }
```

## Regras que o banco garante

- `pecas.reservada` fica entre 0 e `quantidade`: duas reservas simultâneas não vendem a mesma peça.
- `reservas.os_id` e `ordens_execucao.os_id` são únicos: uma reserva e uma ordem por OS.
- `mensagens_processadas.message_id` é a chave de idempotência dos comandos; o registro entra na mesma
  transação da mudança de estado.
- `outbox` é gravado na mesma transação da mudança e esvaziado pelo relay, com confirmação do broker.
