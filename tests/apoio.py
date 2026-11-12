"""Montagem de cenários e leitura do outbox, compartilhadas pelos testes de mensageria."""
import os
import uuid
from decimal import Decimal
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from sqlalchemy import select

from app.adapters.outbound.persistence.catalogo_repository import CatalogoRepositoryAdapter
from app.adapters.outbound.persistence.estoque_repository import EstoqueRepositoryAdapter
from app.adapters.outbound.persistence.ordem_execucao_repository import OrdemExecucaoRepositoryAdapter
from app.adapters.outbound.persistence.outbox_repository import InboxRepositoryAdapter, OutboxRepositoryAdapter
from app.adapters.outbound.persistence.reserva_repository import ReservaRepositoryAdapter
from app.application.use_cases.comandos_saga import ProcessarComandoUseCase
from app.domain.entities.catalogo import Servico
from app.domain.entities.estoque import Peca
from app.infrastructure.orm_mapping import outbox

CONTRATO = Path(os.environ.get(
    "CONTRATO_ASYNCAPI",
    Path(__file__).resolve().parents[2] / "tech-challenge-f4-plataforma/docs/contratos/asyncapi.yaml",
))


def contrato() -> dict | None:
    return yaml.safe_load(CONTRATO.read_text()) if CONTRATO.exists() else None


MUDANCAS_NA_EXECUCAO = ("DiagnosticoIniciado", "ExecucaoIniciada", "ExecucaoFinalizada")


def validar_contra_o_contrato(corpo: dict) -> None:
    """Sem o repositório da plataforma ao lado, o contrato não está disponível e a conferência é pulada."""
    spec = contrato()
    if spec:
        schema = "MudancaNaExecucao" if corpo["tipo"] in MUDANCAS_NA_EXECUCAO else corpo["tipo"]
        Draft202012Validator({"$ref": f"#/components/schemas/{schema}", "components": spec["components"]}).validate(corpo)


def criar_servico(db, nome="Troca de óleo", preco="150.00") -> Servico:
    servico = Servico(nome=nome, preco=Decimal(preco))
    db.add(servico)
    db.commit()
    return servico


def criar_peca(db, nome="Filtro de óleo", preco="35.00", quantidade=10) -> Peca:
    peca = Peca(nome=nome, preco=Decimal(preco), quantidade=quantidade)
    db.add(peca)
    db.commit()
    return peca


def comando(tipo, os_id, saga_id, payload, message_id=None) -> dict:
    return {"message_id": message_id or str(uuid.uuid4()), "tipo": tipo, "versao": 1, "saga_id": str(saga_id),
            "os_id": str(os_id), "ocorrido_em": "2026-11-12T15:00:00Z", "origem": "os-service", "payload": payload}


def reservar(os_id, saga_id, *itens, message_id=None) -> dict:
    """Cada item é (tipo, entidade, quantidade)."""
    return comando("ReservarPecas", os_id, saga_id, {"itens": [
        {"tipo": tipo, "item_id": str(item.id), "quantidade": quantidade} for tipo, item, quantidade in itens]}, message_id)


def processar(db, envelope, agora=None) -> bool:
    return ProcessarComandoUseCase(
        EstoqueRepositoryAdapter(db), CatalogoRepositoryAdapter(db), ReservaRepositoryAdapter(db),
        OrdemExecucaoRepositoryAdapter(db), OutboxRepositoryAdapter(db), InboxRepositoryAdapter(db),
    ).executar(envelope, agora)


def publicadas(db) -> list[dict]:
    """Corpos do outbox em ordem; cada um já é conferido contra o AsyncAPI."""
    corpos = [linha.corpo for linha in db.execute(select(outbox).order_by(outbox.c.criado_em)).all()]
    for corpo in corpos:
        validar_contra_o_contrato(corpo)
    return corpos
