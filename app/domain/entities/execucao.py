import enum

from app.domain.exceptions import BusinessRuleException


class StatusExecucao(str, enum.Enum):
    NA_FILA = "NA_FILA"
    EM_DIAGNOSTICO = "EM_DIAGNOSTICO"
    EM_EXECUCAO = "EM_EXECUCAO"
    FINALIZADA = "FINALIZADA"
    CANCELADA = "CANCELADA"


TRANSICOES = {
    StatusExecucao.NA_FILA: (StatusExecucao.EM_DIAGNOSTICO, StatusExecucao.CANCELADA),
    StatusExecucao.EM_DIAGNOSTICO: (StatusExecucao.EM_EXECUCAO,),
    StatusExecucao.EM_EXECUCAO: (StatusExecucao.FINALIZADA,),
}


class OrdemExecucao:
    """A OS na oficina: entra na fila, passa pelo diagnóstico e pelo reparo até ser finalizada."""

    def __init__(self, os_id=None, saga_id=None, veiculo_id=None, status=StatusExecucao.NA_FILA,
                 observacao=None, enfileirada_em=None, iniciada_em=None, finalizada_em=None, id=None):
        self.id = id
        self.os_id = os_id
        self.saga_id = saga_id
        self.veiculo_id = veiculo_id
        self.status = status
        self.observacao = observacao
        self.enfileirada_em = enfileirada_em
        self.iniciada_em = iniciada_em
        self.finalizada_em = finalizada_em

    def transicionar(self, destino: StatusExecucao, agora, observacao: str | None = None) -> None:
        if destino not in TRANSICOES.get(self.status, ()):
            raise BusinessRuleException(f"Transição inválida: {self.status.value} → {destino.value}")
        self.status = destino
        if observacao is not None:
            self.observacao = observacao
        if destino == StatusExecucao.EM_EXECUCAO:
            self.iniciada_em = agora
        elif destino == StatusExecucao.FINALIZADA:
            self.finalizada_em = agora
