"""Comandos da Saga da OS: cada um muda o estado, grava a resposta no outbox e marca o message_id na mesma transação."""
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from app.application.mensagens import publicar_evento
from app.domain.entities.execucao import OrdemExecucao, StatusExecucao
from app.domain.entities.reserva import Reserva, ReservaItem, TipoItem

logger = logging.getLogger("oficina.execucao")

COMANDOS = frozenset(("ReservarPecas", "LiberarReserva", "EnfileirarOS"))


def dinheiro(valor: Decimal) -> str:
    return str(valor.quantize(Decimal("0.01")))


class ProcessarComandoUseCase:
    """Aplica um comando do OS Service uma única vez por message_id."""

    def __init__(self, estoque_repo, catalogo_repo, reserva_repo, ordem_repo, outbox_repo, inbox_repo):
        self._estoque = estoque_repo
        self._catalogo = catalogo_repo
        self._reservas = reserva_repo
        self._ordens = ordem_repo
        self._outbox = outbox_repo
        self._inbox = inbox_repo

    def executar(self, envelope: dict, agora: datetime | None = None) -> bool:
        """False quando a mensagem já tinha sido processada."""
        agora = agora or datetime.now(timezone.utc)
        tipo = envelope["tipo"]
        if not self._inbox.registrar(envelope["message_id"], tipo):
            logger.info("Mensagem %s repetida, ignorada", envelope["message_id"], extra={"evento": "mensagem_repetida", "tipo": tipo})
            return False
        os_id, saga_id = uuid.UUID(envelope["os_id"]), uuid.UUID(envelope["saga_id"])
        tratar = {"ReservarPecas": self._reservar, "LiberarReserva": self._liberar, "EnfileirarOS": self._enfileirar}[tipo]
        resposta, payload = tratar(os_id, saga_id, envelope["payload"], agora)
        publicar_evento(self._outbox, resposta, saga_id, os_id, payload, agora)
        self._reservas.commit()
        logger.info("%s · %s → %s", os_id, tipo, resposta, extra={
            "evento": "comando_processado", "saga_id": str(saga_id), "os_id": str(os_id), "tipo": tipo, "resposta": resposta,
        })
        return True

    def _reservar(self, os_id, saga_id, payload, agora):
        reserva = self._reservas.buscar_por_os_para_escrita(os_id)
        if reserva:
            return "PecasReservadas", self._itens_reservados(reserva)
        pedidos = defaultdict(int)
        for item in payload["itens"]:
            pedidos[(TipoItem(item["tipo"]), uuid.UUID(item["item_id"]))] += item["quantidade"]
        pedidos = dict(sorted(pedidos.items(), key=lambda pedido: pedido[0][1]))
        servicos = self._catalogo.buscar_servicos([i for t, i in pedidos if t == TipoItem.SERVICO])
        pecas = self._estoque.buscar_pecas_para_escrita([i for t, i in pedidos if t == TipoItem.PECA])
        catalogo = {TipoItem.SERVICO: servicos, TipoItem.PECA: pecas}

        inexistentes = [{"item_id": str(i), "detalhe": f"{t.value.lower()} inexistente"}
                        for (t, i) in pedidos if i not in catalogo[t]]
        if inexistentes:
            return "ReservaRecusada", {"motivo": "ITEM_INEXISTENTE", "itens": inexistentes}
        sem_estoque = [{"item_id": str(i), "detalhe": f"disponível {pecas[i].disponivel}, pedido {q}"}
                       for (t, i), q in pedidos.items() if t == TipoItem.PECA and pecas[i].disponivel < q]
        if sem_estoque:
            return "ReservaRecusada", {"motivo": "ESTOQUE_INSUFICIENTE", "itens": sem_estoque}

        itens = []
        for (tipo, item_id), quantidade in pedidos.items():
            origem = catalogo[tipo][item_id]
            if tipo == TipoItem.PECA:
                origem.reservar(quantidade)
            itens.append(ReservaItem(tipo=tipo, item_id=item_id, descricao=origem.nome,
                                     quantidade=quantidade, preco_unitario=origem.preco))
        reserva = Reserva(os_id=os_id, saga_id=saga_id, itens=itens)
        self._reservas.adicionar(reserva)
        return "PecasReservadas", self._itens_reservados(reserva)

    @staticmethod
    def _itens_reservados(reserva: Reserva) -> dict:
        return {
            "itens": [{
                "tipo": i.tipo.value, "item_id": str(i.item_id), "descricao": i.descricao, "quantidade": i.quantidade,
                "preco_unitario": dinheiro(i.preco_unitario), "subtotal": dinheiro(i.subtotal),
            } for i in reserva.itens],
            "valor_total": dinheiro(reserva.valor_total),
        }

    def _liberar(self, os_id, saga_id, payload, agora):
        reserva = self._reservas.buscar_por_os_para_escrita(os_id)
        if reserva and reserva.ativa:
            pecas = self._estoque.buscar_pecas_para_escrita([i.item_id for i in reserva.pecas])
            for item in reserva.pecas:
                pecas[item.item_id].liberar(item.quantidade)
            reserva.liberar()
        elif reserva:
            self._estornar_se_na_fila(os_id, reserva, agora)
        return "ReservaLiberada", {}

    def _estornar_se_na_fila(self, os_id, reserva, agora) -> None:
        """Reserva já consumida: enquanto a OS ainda está na fila, as peças voltam ao estoque."""
        ordem = self._ordens.buscar_por_os_para_escrita(os_id)
        if ordem and ordem.status == StatusExecucao.NA_FILA:
            ordem.transicionar(StatusExecucao.CANCELADA, agora)
            pecas = self._estoque.buscar_pecas_para_escrita([i.item_id for i in reserva.pecas])
            for item in reserva.pecas:
                pecas[item.item_id].repor(item.quantidade)
                self._estoque.registrar_movimentacao(item.item_id, "ENTRADA", item.quantidade, f"Estorno da OS {os_id}")

    def _enfileirar(self, os_id, saga_id, payload, agora):
        ordem = self._ordens.buscar_por_os(os_id)
        if ordem:
            return "OSEnfileirada", {"posicao": self._ordens.posicao(ordem)}
        reserva = self._reservas.buscar_por_os_para_escrita(os_id)
        if not reserva or not reserva.ativa:
            return "EnfileiramentoRecusado", {"motivo": "RESERVA_INEXISTENTE"}
        pecas = self._estoque.buscar_pecas_para_escrita([i.item_id for i in reserva.pecas])
        for item in reserva.pecas:
            pecas[item.item_id].baixar(item.quantidade)
            self._estoque.registrar_movimentacao(item.item_id, "SAIDA", item.quantidade, f"Baixa da OS {os_id}")
        reserva.consumir()
        ordem = OrdemExecucao(os_id=os_id, saga_id=saga_id, veiculo_id=uuid.UUID(payload["veiculo_id"]), enfileirada_em=agora)
        self._ordens.adicionar(ordem)
        return "OSEnfileirada", {"posicao": self._ordens.posicao(ordem)}
