from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.infrastructure.database import get_db
from app.infrastructure.security import get_current_user, require_admin
from app.adapters.outbound.persistence.estoque_repository import EstoqueRepositoryAdapter
from app.application.use_cases.gerenciar_estoque import GerenciarEstoqueUseCase
from app.adapters.inbound.http.estoque_schemas import PecaCreate, PecaResponse, EntradaEstoque

router = APIRouter(prefix="/estoque", tags=["📦 Estoque de Peças"])


def _use_case(db: Session) -> GerenciarEstoqueUseCase:
    return GerenciarEstoqueUseCase(EstoqueRepositoryAdapter(db))


@router.post("/pecas", response_model=PecaResponse, status_code=201,
    summary="Cadastrar peça/insumo",
    description="**Requer ADMIN.**")
def criar_peca(data: PecaCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    return _use_case(db).criar(data.model_dump())


@router.get("/pecas", response_model=list[PecaResponse], summary="Listar peças")
def listar_pecas(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return _use_case(db).listar(skip=skip, limit=limit)


@router.get("/pecas/{peca_id}", response_model=PecaResponse, summary="Obter peça")
def obter_peca(peca_id: UUID, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _use_case(db).obter(peca_id)


@router.put("/pecas/{peca_id}", response_model=PecaResponse,
    summary="Atualizar peça",
    description="**Requer ADMIN.**")
def atualizar_peca(peca_id: UUID, data: PecaCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    return _use_case(db).atualizar(peca_id, data.model_dump())


@router.delete("/pecas/{peca_id}", status_code=204,
    summary="Remover peça",
    description="Não permite remoção se tiver reserva ativa ou movimentação. **Requer ADMIN.**")
def deletar_peca(peca_id: UUID, db: Session = Depends(get_db), _=Depends(require_admin)):
    _use_case(db).remover(peca_id)


@router.post("/pecas/{peca_id}/entrada", response_model=PecaResponse,
    summary="Registrar entrada em estoque",
    description="**Requer ADMIN.**")
def entrada_estoque(peca_id: UUID, data: EntradaEstoque, db: Session = Depends(get_db), _=Depends(require_admin)):
    return _use_case(db).registrar_entrada(peca_id, data.quantidade, data.motivo)
