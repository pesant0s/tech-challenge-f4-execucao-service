import enum
from decimal import Decimal


class ReservaEstado(str, enum.Enum):
    ATIVA = "ATIVA"
    LIBERADA = "LIBERADA"
    CONSUMIDA = "CONSUMIDA"


class TipoItem(str, enum.Enum):
    SERVICO = "SERVICO"
    PECA = "PECA"


class ReservaItem:
    """Item já precificado da reserva: guarda o preço da época para responder de novo igual."""

    def __init__(self, tipo=None, item_id=None, descricao=None, quantidade=None, preco_unitario=None, id=None):
        self.id = id
        self.tipo = tipo
        self.item_id = item_id
        self.descricao = descricao
        self.quantidade = quantidade
        self.preco_unitario = preco_unitario

    @property
    def subtotal(self) -> Decimal:
        return self.quantidade * self.preco_unitario


class Reserva:
    """Peças de uma OS separadas do estoque, uma reserva por OS."""

    def __init__(self, os_id=None, saga_id=None, estado=ReservaEstado.ATIVA, itens=None, id=None):
        self.id = id
        self.os_id = os_id
        self.saga_id = saga_id
        self.estado = estado
        # Ao carregar do banco o ORM não chama __init__, então a coleção não é sobrescrita.
        self.itens = itens if itens is not None else []

    @property
    def ativa(self) -> bool:
        return self.estado == ReservaEstado.ATIVA

    @property
    def valor_total(self) -> Decimal:
        return sum((item.subtotal for item in self.itens), Decimal("0"))

    @property
    def pecas(self) -> list[ReservaItem]:
        return [item for item in self.itens if item.tipo == TipoItem.PECA]

    def liberar(self) -> None:
        self.estado = ReservaEstado.LIBERADA

    def consumir(self) -> None:
        self.estado = ReservaEstado.CONSUMIDA
