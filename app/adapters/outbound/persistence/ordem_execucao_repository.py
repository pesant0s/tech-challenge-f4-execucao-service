from sqlalchemy import case
from sqlalchemy.orm import Session
from app.domain.entities.execucao import OrdemExecucao, StatusExecucao

PRIORIDADE = {StatusExecucao.EM_EXECUCAO: 0, StatusExecucao.EM_DIAGNOSTICO: 1, StatusExecucao.NA_FILA: 2}


class OrdemExecucaoRepositoryAdapter:
    def __init__(self, db: Session):
        self._db = db

    def buscar_por_os(self, os_id) -> OrdemExecucao | None:
        return self._db.query(OrdemExecucao).filter(OrdemExecucao.os_id == os_id).first()

    def buscar_por_os_para_escrita(self, os_id) -> OrdemExecucao | None:
        return self._db.query(OrdemExecucao).filter(OrdemExecucao.os_id == os_id).with_for_update().first()

    def proxima_na_fila_para_escrita(self) -> OrdemExecucao | None:
        """A mais antiga; SKIP LOCKED faz dois atendentes pegarem ordens diferentes."""
        return (
            self._db.query(OrdemExecucao).filter(OrdemExecucao.status == StatusExecucao.NA_FILA)
            .order_by(OrdemExecucao.enfileirada_em).limit(1).with_for_update(skip_locked=True).first()
        )

    def fila(self) -> list[OrdemExecucao]:
        return (
            self._db.query(OrdemExecucao)
            .filter(OrdemExecucao.status.in_(PRIORIDADE))
            .order_by(case(PRIORIDADE, value=OrdemExecucao.status), OrdemExecucao.enfileirada_em).all()
        )

    def posicao(self, ordem: OrdemExecucao) -> int:
        """1 mais as ordens na fila que entraram antes desta."""
        antes = (
            self._db.query(OrdemExecucao)
            .filter(OrdemExecucao.status == StatusExecucao.NA_FILA, OrdemExecucao.enfileirada_em < ordem.enfileirada_em)
            .count()
        )
        return antes + 1

    def adicionar(self, ordem: OrdemExecucao) -> None:
        self._db.add(ordem)
        self._db.flush()

    def commit(self) -> None:
        self._db.commit()
