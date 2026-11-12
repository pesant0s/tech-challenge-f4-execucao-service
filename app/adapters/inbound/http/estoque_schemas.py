from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class PecaCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    descricao: str | None = Field(default=None, max_length=1000)
    preco: Decimal = Field(gt=0)
    quantidade: int = Field(default=0, ge=0)
    estoque_minimo: int = Field(default=1, ge=0)


class PecaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nome: str
    descricao: str | None = None
    preco: Decimal
    quantidade: int
    estoque_minimo: int
    reservada: int
    disponivel: int


class EntradaEstoque(BaseModel):
    quantidade: int = Field(gt=0)
    motivo: str | None = Field(default=None, max_length=500)
