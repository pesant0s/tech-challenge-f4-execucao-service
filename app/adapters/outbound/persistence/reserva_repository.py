from sqlalchemy.orm import Session
from app.domain.entities.reserva import Reserva


class ReservaRepositoryAdapter:
    def __init__(self, db: Session):
        self._db = db

    def buscar_por_os_para_escrita(self, os_id) -> Reserva | None:
        return self._db.query(Reserva).filter(Reserva.os_id == os_id).with_for_update().first()

    def adicionar(self, reserva: Reserva) -> None:
        self._db.add(reserva)

    def commit(self) -> None:
        self._db.commit()
