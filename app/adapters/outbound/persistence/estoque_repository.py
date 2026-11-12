from sqlalchemy import func
from sqlalchemy.orm import Session
from app.domain.entities.estoque import Peca, MovimentacaoEstoque
from app.domain.entities.reserva import Reserva, ReservaEstado, ReservaItem, TipoItem
from app.domain.exceptions import NotFoundException


class EstoqueRepositoryAdapter:
    """Implementação SQLAlchemy para operações de estoque de peças."""

    def __init__(self, db: Session):
        self._db = db

    def buscar_peca(self, peca_id) -> Peca | None:
        return self._db.query(Peca).filter(Peca.id == peca_id).first()

    def buscar_peca_para_escrita(self, peca_id) -> Peca:
        """Busca com SELECT FOR UPDATE — usar antes de alterar a quantidade."""
        p = self._db.query(Peca).filter(Peca.id == peca_id).with_for_update().first()
        if not p:
            raise NotFoundException("Peça não encontrada")
        return p

    def buscar_pecas_para_escrita(self, ids) -> dict:
        """Trava em ordem de id: duas OS com as mesmas peças não se bloqueiam em ciclo."""
        pecas = self._db.query(Peca).filter(Peca.id.in_(ids)).order_by(Peca.id).with_for_update().all()
        return {p.id: p for p in pecas}

    def listar(self, skip: int = 0, limit: int = 100) -> list[Peca]:
        return self._db.query(Peca).offset(skip).limit(limit).all()

    def existe_nome(self, nome: str, exclude_id=None) -> bool:
        q = self._db.query(Peca).filter(func.lower(Peca.nome) == nome.strip().lower())
        if exclude_id:
            q = q.filter(Peca.id != exclude_id)
        return q.first() is not None

    def possui_vinculo(self, peca_id) -> bool:
        """Reserva ativa ou qualquer movimentação de estoque."""
        movimentada = self._db.query(MovimentacaoEstoque).filter(MovimentacaoEstoque.peca_id == peca_id).first()
        reservada = (
            self._db.query(ReservaItem).join(Reserva, Reserva.id == ReservaItem.reserva_id)
            .filter(ReservaItem.tipo == TipoItem.PECA, ReservaItem.item_id == peca_id,
                    Reserva.estado == ReservaEstado.ATIVA)
            .first()
        )
        return movimentada is not None or reservada is not None

    def registrar_movimentacao(self, peca_id, tipo: str, quantidade: int, motivo: str | None) -> None:
        self._db.add(MovimentacaoEstoque(peca_id=peca_id, tipo=tipo, quantidade=quantidade, motivo=motivo))

    def adicionar(self, peca) -> None:
        self._db.add(peca)

    def remover(self, peca) -> None:
        self._db.delete(peca)

    def commit(self) -> None:
        self._db.commit()

    def refresh(self, peca) -> None:
        self._db.refresh(peca)
