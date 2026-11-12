from app.domain.exceptions import BusinessRuleException


class Peca:
    """Peça/insumo em estoque; `reservada` são as unidades prometidas a OS que ainda não saíram."""

    def __init__(self, nome=None, preco=None, descricao=None,
                 quantidade=0, estoque_minimo=1, reservada=0, id=None):
        self.id = id
        self.nome = nome
        self.descricao = descricao
        self.preco = preco
        self.quantidade = quantidade
        self.estoque_minimo = estoque_minimo
        self.reservada = reservada

    @property
    def disponivel(self) -> int:
        return self.quantidade - self.reservada

    def reservar(self, quantidade: int) -> None:
        if quantidade > self.disponivel:
            raise BusinessRuleException(f"Estoque insuficiente para a peça '{self.nome}'")
        self.reservada += quantidade

    def liberar(self, quantidade: int) -> None:
        self.reservada -= quantidade

    def baixar(self, quantidade: int) -> None:
        """Consome uma reserva: as unidades saem do estoque e deixam de estar reservadas."""
        self.quantidade -= quantidade
        self.reservada -= quantidade

    def repor(self, quantidade: int) -> None:
        self.quantidade += quantidade


class MovimentacaoEstoque:
    """Registro de entrada/saída de estoque (entidade de domínio pura)."""

    def __init__(self, peca_id=None, tipo=None, quantidade=None, motivo=None, id=None):
        self.id = id
        self.peca_id = peca_id
        self.tipo = tipo  # ENTRADA | SAIDA
        self.quantidade = quantidade
        self.motivo = motivo
