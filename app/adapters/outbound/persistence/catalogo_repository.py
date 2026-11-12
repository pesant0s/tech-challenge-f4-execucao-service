from sqlalchemy import func
from sqlalchemy.orm import Session
from app.domain.entities.catalogo import Servico
from app.domain.entities.reserva import Reserva, ReservaEstado, ReservaItem, TipoItem


class CatalogoRepositoryAdapter:
    """Implementação SQLAlchemy do repositório de serviços do catálogo."""

    def __init__(self, db: Session):
        self._db = db

    def buscar_servico(self, servico_id) -> Servico | None:
        return self._db.query(Servico).filter(Servico.id == servico_id).first()

    def buscar_servicos(self, ids) -> dict:
        return {s.id: s for s in self._db.query(Servico).filter(Servico.id.in_(ids)).all()}

    def listar(self, skip: int = 0, limit: int = 100) -> list[Servico]:
        return self._db.query(Servico).offset(skip).limit(limit).all()

    def existe_nome(self, nome: str, exclude_id=None) -> bool:
        q = self._db.query(Servico).filter(func.lower(Servico.nome) == nome.strip().lower())
        if exclude_id:
            q = q.filter(Servico.id != exclude_id)
        return q.first() is not None

    def possui_reserva_ativa(self, servico_id) -> bool:
        return (
            self._db.query(ReservaItem).join(Reserva, Reserva.id == ReservaItem.reserva_id)
            .filter(ReservaItem.tipo == TipoItem.SERVICO, ReservaItem.item_id == servico_id,
                    Reserva.estado == ReservaEstado.ATIVA)
            .first() is not None
        )

    def adicionar(self, servico) -> None:
        self._db.add(servico)

    def remover(self, servico) -> None:
        self._db.delete(servico)

    def commit(self) -> None:
        self._db.commit()

    def refresh(self, servico) -> None:
        self._db.refresh(servico)
