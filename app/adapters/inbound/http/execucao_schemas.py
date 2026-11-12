from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.domain.entities.execucao import StatusExecucao


class AndamentoRequest(BaseModel):
    observacao: str | None = Field(default=None, max_length=500)


class OrdemExecucaoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    os_id: UUID
    saga_id: UUID
    veiculo_id: UUID
    status: StatusExecucao
    observacao: str | None = None
    enfileirada_em: datetime
    iniciada_em: datetime | None = None
    finalizada_em: datetime | None = None
