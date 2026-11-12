"""schema do serviço de Execução: catálogo, estoque, reservas, fila de execução, outbox e inbox
Revision ID: 0001 · Revises: nenhuma"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ESTADOS_RESERVA = ("ATIVA", "LIBERADA", "CONSUMIDA")
TIPOS_ITEM = ("SERVICO", "PECA")
STATUS_EXECUCAO = ("NA_FILA", "EM_DIAGNOSTICO", "EM_EXECUCAO", "FINALIZADA", "CANCELADA")
AGORA = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "servicos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("descricao", sa.String(500), nullable=True),
        sa.Column("preco", sa.Numeric(10, 2), nullable=False),
        sa.Column("tempo_estimado_minutos", sa.Integer(), nullable=True),
        sa.CheckConstraint("preco > 0", name="ck_servicos_preco_positivo"),
        sa.CheckConstraint("tempo_estimado_minutos IS NULL OR tempo_estimado_minutos > 0", name="ck_servicos_tempo_positivo"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome", name="uq_servicos_nome"),
    )
    op.create_table(
        "pecas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(150), nullable=False),
        sa.Column("descricao", sa.String(500), nullable=True),
        sa.Column("preco", sa.Numeric(10, 2), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("estoque_minimo", sa.Integer(), nullable=False),
        sa.Column("reservada", sa.Integer(), nullable=False),
        sa.CheckConstraint("preco > 0", name="ck_pecas_preco_positivo"),
        sa.CheckConstraint("quantidade >= 0", name="ck_pecas_quantidade_nao_negativa"),
        sa.CheckConstraint("estoque_minimo >= 0", name="ck_pecas_estoque_minimo_nao_negativo"),
        sa.CheckConstraint("reservada >= 0", name="ck_pecas_reservada_nao_negativa"),
        sa.CheckConstraint("reservada <= quantidade", name="ck_pecas_reservada_dentro_do_estoque"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nome", name="uq_pecas_nome"),
    )
    op.create_table(
        "movimentacoes_estoque",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("peca_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pecas.id"), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.String(200), nullable=True),
        sa.CheckConstraint("quantidade > 0", name="ck_movimentacoes_quantidade_positiva"),
        sa.CheckConstraint("tipo IN ('ENTRADA', 'SAIDA')", name="ck_movimentacoes_tipo"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_movimentacoes_estoque_peca_id", "movimentacoes_estoque", ["peca_id"])

    op.create_table(
        "reservas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("os_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("saga_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("estado", sa.Enum(*ESTADOS_RESERVA, name="reservaestado"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("os_id"),
    )
    op.create_table(
        "reserva_itens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reserva_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reservas.id"), nullable=False),
        sa.Column("tipo", sa.Enum(*TIPOS_ITEM, name="tipoitem"), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("descricao", sa.String(200), nullable=False),
        sa.Column("quantidade", sa.Integer(), nullable=False),
        sa.Column("preco_unitario", sa.Numeric(10, 2), nullable=False),
        sa.CheckConstraint("quantidade > 0", name="ck_reserva_itens_quantidade_positiva"),
        sa.CheckConstraint("preco_unitario >= 0", name="ck_reserva_itens_preco_nao_negativo"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reserva_itens_reserva_id", "reserva_itens", ["reserva_id"])

    op.create_table(
        "ordens_execucao",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("os_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("saga_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("veiculo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Enum(*STATUS_EXECUCAO, name="statusexecucao"), nullable=False),
        sa.Column("observacao", sa.String(500), nullable=True),
        sa.Column("enfileirada_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("iniciada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalizada_em", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("os_id"),
    )
    op.create_index("ix_ordens_execucao_status", "ordens_execucao", ["status"])

    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.String(60), nullable=False),
        sa.Column("rota", sa.String(80), nullable=False),
        sa.Column("tipo", sa.String(40), nullable=False),
        sa.Column("corpo", sa.JSON(), nullable=False),
        sa.Column("cabecalhos", sa.JSON(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), server_default=AGORA, nullable=False),
        sa.Column("publicado_em", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outbox_pendentes", "outbox", ["publicado_em", "criado_em"])

    op.create_table(
        "mensagens_processadas",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tipo", sa.String(40), nullable=False),
        sa.Column("processada_em", sa.DateTime(timezone=True), server_default=AGORA, nullable=False),
        sa.PrimaryKeyConstraint("message_id"),
    )


def downgrade() -> None:
    op.drop_table("mensagens_processadas")
    op.drop_index("ix_outbox_pendentes", table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("ix_ordens_execucao_status", table_name="ordens_execucao")
    op.drop_table("ordens_execucao")
    op.drop_index("ix_reserva_itens_reserva_id", table_name="reserva_itens")
    op.drop_table("reserva_itens")
    op.drop_table("reservas")
    op.drop_index("ix_movimentacoes_estoque_peca_id", table_name="movimentacoes_estoque")
    op.drop_table("movimentacoes_estoque")
    op.drop_table("pecas")
    op.drop_table("servicos")
    for tipo in ("statusexecucao", "tipoitem", "reservaestado"):
        sa.Enum(name=tipo).drop(op.get_bind(), checkfirst=True)
