"""Mapeamento imperativo: as entidades de domínio seguem sem nenhum import de SQLAlchemy."""
import uuid
from datetime import timezone
from sqlalchemy import (
    Table, Column, String, Integer, Numeric, DateTime, ForeignKey,
    Enum, UniqueConstraint, CheckConstraint, Index, JSON, TypeDecorator,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.infrastructure.database import mapper_registry, metadata
from app.domain.entities.catalogo import Servico
from app.domain.entities.estoque import Peca, MovimentacaoEstoque
from app.domain.entities.execucao import OrdemExecucao, StatusExecucao
from app.domain.entities.reserva import Reserva, ReservaEstado, ReservaItem, TipoItem


class DataHoraUTC(TypeDecorator):
    """timestamptz sempre devolvido em UTC; o SQLite dos testes perde o fuso na leitura."""

    impl = DateTime
    cache_ok = True

    def process_result_value(self, valor, dialect):
        if valor is None:
            return None
        return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor.astimezone(timezone.utc)


servicos = Table(
    "servicos", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("nome", String(150), nullable=False),
    Column("descricao", String(500), nullable=True),
    Column("preco", Numeric(10, 2), nullable=False),
    Column("tempo_estimado_minutos", Integer, nullable=True),
    UniqueConstraint("nome", name="uq_servicos_nome"),
    CheckConstraint("preco > 0", name="ck_servicos_preco_positivo"),
    CheckConstraint("tempo_estimado_minutos IS NULL OR tempo_estimado_minutos > 0", name="ck_servicos_tempo_positivo"),
)

pecas = Table(
    "pecas", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("nome", String(150), nullable=False),
    Column("descricao", String(500), nullable=True),
    Column("preco", Numeric(10, 2), nullable=False),
    Column("quantidade", Integer, nullable=False, default=0),
    Column("estoque_minimo", Integer, nullable=False, default=1),
    Column("reservada", Integer, nullable=False, default=0),
    UniqueConstraint("nome", name="uq_pecas_nome"),
    CheckConstraint("preco > 0", name="ck_pecas_preco_positivo"),
    CheckConstraint("quantidade >= 0", name="ck_pecas_quantidade_nao_negativa"),
    CheckConstraint("estoque_minimo >= 0", name="ck_pecas_estoque_minimo_nao_negativo"),
    CheckConstraint("reservada >= 0", name="ck_pecas_reservada_nao_negativa"),
    CheckConstraint("reservada <= quantidade", name="ck_pecas_reservada_dentro_do_estoque"),
)

movimentacoes_estoque = Table(
    "movimentacoes_estoque", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("peca_id", UUID(as_uuid=True), ForeignKey("pecas.id"), nullable=False, index=True),
    Column("tipo", String(10), nullable=False),
    Column("quantidade", Integer, nullable=False),
    Column("motivo", String(200), nullable=True),
    CheckConstraint("quantidade > 0", name="ck_movimentacoes_quantidade_positiva"),
    CheckConstraint("tipo IN ('ENTRADA', 'SAIDA')", name="ck_movimentacoes_tipo"),
)

reservas = Table(
    "reservas", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("os_id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("saga_id", UUID(as_uuid=True), nullable=False),
    Column("estado", Enum(ReservaEstado), nullable=False, default=ReservaEstado.ATIVA),
)

reserva_itens = Table(
    "reserva_itens", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("reserva_id", UUID(as_uuid=True), ForeignKey("reservas.id"), nullable=False, index=True),
    Column("tipo", Enum(TipoItem), nullable=False),
    Column("item_id", UUID(as_uuid=True), nullable=False),
    Column("descricao", String(200), nullable=False),
    Column("quantidade", Integer, nullable=False),
    Column("preco_unitario", Numeric(10, 2), nullable=False),
    CheckConstraint("quantidade > 0", name="ck_reserva_itens_quantidade_positiva"),
    CheckConstraint("preco_unitario >= 0", name="ck_reserva_itens_preco_nao_negativo"),
)

# veiculo_id é do OS Service: aqui é só uma referência, sem chave estrangeira.
ordens_execucao = Table(
    "ordens_execucao", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("os_id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("saga_id", UUID(as_uuid=True), nullable=False),
    Column("veiculo_id", UUID(as_uuid=True), nullable=False),
    Column("status", Enum(StatusExecucao), nullable=False, default=StatusExecucao.NA_FILA, index=True),
    Column("observacao", String(500), nullable=True),
    Column("enfileirada_em", DataHoraUTC(timezone=True), nullable=False),
    Column("iniciada_em", DataHoraUTC(timezone=True), nullable=True),
    Column("finalizada_em", DataHoraUTC(timezone=True), nullable=True),
)

# Outbox e inbox não são entidades de domínio: só tabelas da mensageria (ADR-021).
outbox = Table(
    "outbox", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("exchange", String(60), nullable=False),
    Column("rota", String(80), nullable=False),
    Column("tipo", String(40), nullable=False),
    Column("corpo", JSON, nullable=False),
    Column("cabecalhos", JSON, nullable=False),
    Column("criado_em", DataHoraUTC(timezone=True), nullable=False, server_default=func.now()),
    Column("publicado_em", DataHoraUTC(timezone=True), nullable=True),
    Index("ix_outbox_pendentes", "publicado_em", "criado_em"),
)

mensagens_processadas = Table(
    "mensagens_processadas", metadata,
    Column("message_id", UUID(as_uuid=True), primary_key=True),
    Column("tipo", String(40), nullable=False),
    Column("processada_em", DataHoraUTC(timezone=True), nullable=False, server_default=func.now()),
)

mapper_registry.map_imperatively(Servico, servicos)
mapper_registry.map_imperatively(Peca, pecas)
mapper_registry.map_imperatively(MovimentacaoEstoque, movimentacoes_estoque)
mapper_registry.map_imperatively(ReservaItem, reserva_itens)
mapper_registry.map_imperatively(Reserva, reservas, properties={
    "itens": relationship(ReservaItem, order_by=reserva_itens.c.item_id, lazy="selectin"),
})
mapper_registry.map_imperatively(OrdemExecucao, ordens_execucao)
