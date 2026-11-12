from datetime import datetime, timezone

from app.application.mensagens import publicar_evento
from app.domain.entities.execucao import OrdemExecucao, StatusExecucao
from app.domain.exceptions import NotFoundException

EVENTOS = {
    StatusExecucao.EM_DIAGNOSTICO: "DiagnosticoIniciado",
    StatusExecucao.EM_EXECUCAO: "ExecucaoIniciada",
    StatusExecucao.FINALIZADA: "ExecucaoFinalizada",
}


class ConduzirExecucaoUseCase:
    """Fila da oficina e andamento de cada ordem; a mudança e o evento saem na mesma transação."""

    def __init__(self, ordem_repo, outbox_repo):
        self._ordens = ordem_repo
        self._outbox = outbox_repo

    def fila(self) -> list[OrdemExecucao]:
        return self._ordens.fila()

    def obter(self, os_id) -> OrdemExecucao:
        ordem = self._ordens.buscar_por_os(os_id)
        if not ordem:
            raise NotFoundException("Ordem de execução não encontrada")
        return ordem

    def chamar_proxima(self) -> OrdemExecucao:
        ordem = self._ordens.proxima_na_fila_para_escrita()
        if not ordem:
            raise NotFoundException("Não há ordem na fila")
        return self._transicionar(ordem, StatusExecucao.EM_DIAGNOSTICO, None)

    def avancar(self, os_id, destino: StatusExecucao, observacao: str | None) -> OrdemExecucao:
        ordem = self._ordens.buscar_por_os_para_escrita(os_id)
        if not ordem:
            raise NotFoundException("Ordem de execução não encontrada")
        return self._transicionar(ordem, destino, observacao)

    def _transicionar(self, ordem, destino, observacao) -> OrdemExecucao:
        agora = datetime.now(timezone.utc)
        ordem.transicionar(destino, agora, observacao)
        publicar_evento(self._outbox, EVENTOS[destino], ordem.saga_id, ordem.os_id, {"observacao": observacao}, agora)
        self._ordens.commit()
        return ordem
