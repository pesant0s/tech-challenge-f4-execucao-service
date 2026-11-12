"""Publicação no RabbitMQ: topologia do contrato e relay do outbox (ADR-019 e ADR-021)."""
import json
import logging
from datetime import datetime, timezone

import pika
from pika.exceptions import NackError, UnroutableError

from app.adapters.outbound.persistence.outbox_repository import OutboxRepositoryAdapter

logger = logging.getLogger("oficina.mensageria")

FILA_COMANDOS = "execucao-service.comandos"
LIGACAO_DA_FILA = "execucao.#"
LIMITE_DE_ENTREGAS = 5


def declarar_topologia(canal) -> None:
    """Exchanges em que a Execução publica e a fila que ela consome, com DLQ; declarar é idempotente."""
    for exchange in ("oficina.comandos", "oficina.eventos", "oficina.dlx"):
        canal.exchange_declare(exchange, "topic", durable=True)
    dlq = f"{FILA_COMANDOS}.dlq"
    canal.queue_declare(dlq, durable=True, arguments={"x-queue-type": "quorum"})
    canal.queue_bind(dlq, "oficina.dlx", FILA_COMANDOS)
    canal.queue_declare(FILA_COMANDOS, durable=True, arguments={
        "x-queue-type": "quorum",
        "x-delivery-limit": LIMITE_DE_ENTREGAS,
        "x-dead-letter-exchange": "oficina.dlx",
        "x-dead-letter-routing-key": FILA_COMANDOS,
    })
    canal.queue_bind(FILA_COMANDOS, "oficina.comandos", LIGACAO_DA_FILA)


def publicar_pendentes(canal, sessoes, limite: int = 50) -> int:
    """Publica o outbox em ordem, com confirmação do broker; para no primeiro que não for aceito."""
    publicadas = 0
    with sessoes() as db:
        outbox = OutboxRepositoryAdapter(db)
        for mensagem in outbox.pendentes_para_publicar(limite):
            try:
                canal.basic_publish(
                    mensagem.exchange, mensagem.rota, json.dumps(mensagem.corpo).encode(),
                    pika.BasicProperties(
                        message_id=str(mensagem.id), type=mensagem.tipo, correlation_id=mensagem.corpo["saga_id"],
                        content_type="application/json", delivery_mode=2, headers=mensagem.cabecalhos or {},
                    ),
                    mandatory=True,
                )
            except (UnroutableError, NackError):
                # Sem fila ligada à rota (o OS Service ainda não subiu): tenta de novo na próxima volta.
                logger.warning("Mensagem %s para %s não foi aceita pelo broker", mensagem.id, mensagem.rota,
                               extra={"evento": "publicacao_recusada", "rota": mensagem.rota})
                break
            outbox.marcar_publicada(mensagem.id, datetime.now(timezone.utc))
            publicadas += 1
        db.commit()
    return publicadas
