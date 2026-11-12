from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.infrastructure.database import get_db
from app.infrastructure.security import get_current_user, require_admin
from app.adapters.outbound.persistence.catalogo_repository import CatalogoRepositoryAdapter
from app.application.use_cases.gerenciar_catalogo import GerenciarCatalogoUseCase
from app.adapters.inbound.http.catalogo_schemas import ServicoCreate, ServicoResponse

router = APIRouter(prefix="/catalogo", tags=["🔧 Catálogo de Serviços"])


def _use_case(db: Session) -> GerenciarCatalogoUseCase:
    return GerenciarCatalogoUseCase(CatalogoRepositoryAdapter(db))


@router.post("/servicos", response_model=ServicoResponse, status_code=201,
    summary="Cadastrar serviço",
    description="**Requer ADMIN.**")
def criar_servico(data: ServicoCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    return _use_case(db).criar(data.model_dump())


@router.get("/servicos", response_model=list[ServicoResponse], summary="Listar serviços")
def listar_servicos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return _use_case(db).listar(skip=skip, limit=limit)


@router.get("/servicos/{servico_id}", response_model=ServicoResponse, summary="Obter serviço")
def obter_servico(servico_id: UUID, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _use_case(db).obter(servico_id)


@router.put("/servicos/{servico_id}", response_model=ServicoResponse,
    summary="Atualizar serviço",
    description="**Requer ADMIN.**")
def atualizar_servico(servico_id: UUID, data: ServicoCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    return _use_case(db).atualizar(servico_id, data.model_dump())


@router.delete("/servicos/{servico_id}", status_code=204,
    summary="Remover serviço",
    description="Não permite remoção se estiver em uma reserva ativa. **Requer ADMIN.**")
def deletar_servico(servico_id: UUID, db: Session = Depends(get_db), _=Depends(require_admin)):
    _use_case(db).remover(servico_id)
