from uuid import UUID
from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session
from app.infrastructure.database import get_db
from app.infrastructure.security import get_current_user
from app.adapters.outbound.persistence.ordem_execucao_repository import OrdemExecucaoRepositoryAdapter
from app.adapters.outbound.persistence.outbox_repository import OutboxRepositoryAdapter
from app.application.use_cases.conduzir_execucao import ConduzirExecucaoUseCase
from app.adapters.inbound.http.execucao_schemas import AndamentoRequest, OrdemExecucaoResponse
from app.domain.entities.execucao import StatusExecucao

router = APIRouter(prefix="/execucao", tags=["🛠️ Execução e Produção"])


def _use_case(db: Session) -> ConduzirExecucaoUseCase:
    return ConduzirExecucaoUseCase(OrdemExecucaoRepositoryAdapter(db), OutboxRepositoryAdapter(db))


@router.get("/fila", response_model=list[OrdemExecucaoResponse],
    summary="Fila de execução",
    description="Ordens em andamento ou na fila: primeiro as em execução, depois as em diagnóstico e as na fila, da mais antiga para a mais nova.")
def listar_fila(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _use_case(db).fila()


@router.post("/fila/proxima", response_model=OrdemExecucaoResponse,
    summary="Chamar a próxima ordem",
    description="Pega a ordem mais antiga da fila e inicia o diagnóstico. 404 quando a fila está vazia.")
def chamar_proxima(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _use_case(db).chamar_proxima()


@router.get("/os/{os_id}", response_model=OrdemExecucaoResponse, summary="Ordem de execução da OS")
def obter_ordem(os_id: UUID, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _use_case(db).obter(os_id)


@router.post("/os/{os_id}/diagnostico", response_model=OrdemExecucaoResponse, summary="Iniciar diagnóstico")
def iniciar_diagnostico(os_id: UUID, dados: AndamentoRequest = Body(default_factory=AndamentoRequest),
                        db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _use_case(db).avancar(os_id, StatusExecucao.EM_DIAGNOSTICO, dados.observacao)


@router.post("/os/{os_id}/reparo", response_model=OrdemExecucaoResponse, summary="Iniciar reparo")
def iniciar_reparo(os_id: UUID, dados: AndamentoRequest = Body(default_factory=AndamentoRequest),
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _use_case(db).avancar(os_id, StatusExecucao.EM_EXECUCAO, dados.observacao)


@router.post("/os/{os_id}/finalizacao", response_model=OrdemExecucaoResponse, summary="Finalizar execução")
def finalizar(os_id: UUID, dados: AndamentoRequest = Body(default_factory=AndamentoRequest),
              db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _use_case(db).avancar(os_id, StatusExecucao.FINALIZADA, dados.observacao)
