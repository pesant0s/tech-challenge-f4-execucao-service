"""Envelope das mensagens da Saga, igual ao contrato (docs/contratos no tech-challenge-f4-plataforma)."""
import re
import uuid
from datetime import datetime

ORIGEM = "execucao-service"
EXCHANGE_EVENTOS = "oficina.eventos"


def montar_envelope(tipo: str, saga_id, os_id, payload: dict, agora: datetime) -> dict:
    return {
        "message_id": str(uuid.uuid4()),
        "tipo": tipo,
        "versao": 1,
        "saga_id": str(saga_id),
        "os_id": str(os_id),
        "ocorrido_em": agora.isoformat().replace("+00:00", "Z"),
        "origem": ORIGEM,
        "payload": payload,
    }


def publicar_evento(outbox, tipo: str, saga_id, os_id, payload: dict, agora: datetime) -> None:
    """Grava o evento no outbox com a chave `execucao.<nome-em-kebab>` do contrato."""
    kebab = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "-", tipo).lower()
    outbox.adicionar(montar_envelope(tipo, saga_id, os_id, payload, agora), EXCHANGE_EVENTOS, f"execucao.{kebab}")
