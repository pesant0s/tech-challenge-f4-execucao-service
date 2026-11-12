from app.domain.entities.catalogo import Servico
from app.domain.exceptions import NotFoundException, ConflictException


class GerenciarCatalogoUseCase:
    """Casos de uso do catálogo de serviços (CRUD com regras de negócio)."""

    def __init__(self, catalogo_repo):
        self._repo = catalogo_repo

    def criar(self, dados: dict) -> Servico:
        if self._repo.existe_nome(dados["nome"]):
            raise ConflictException("Já existe um serviço com esse nome")
        servico = Servico(**dados)
        self._repo.adicionar(servico)
        self._repo.commit()
        self._repo.refresh(servico)
        return servico

    def listar(self, skip: int = 0, limit: int = 100) -> list[Servico]:
        return self._repo.listar(skip, limit)

    def obter(self, servico_id) -> Servico:
        servico = self._repo.buscar_servico(servico_id)
        if not servico:
            raise NotFoundException("Serviço não encontrado")
        return servico

    def atualizar(self, servico_id, dados: dict) -> Servico:
        servico = self.obter(servico_id)
        if self._repo.existe_nome(dados["nome"], exclude_id=servico_id):
            raise ConflictException("Já existe um serviço com esse nome")
        for campo, valor in dados.items():
            setattr(servico, campo, valor)
        self._repo.commit()
        self._repo.refresh(servico)
        return servico

    def remover(self, servico_id) -> None:
        servico = self.obter(servico_id)
        if self._repo.possui_reserva_ativa(servico_id):
            raise ConflictException("Serviço em reserva ativa — não pode ser removido")
        self._repo.remover(servico)
        self._repo.commit()
