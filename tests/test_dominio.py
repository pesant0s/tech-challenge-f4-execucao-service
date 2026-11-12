"""Entidades sem banco, HTTP ou ORM: quebra aqui se o domínio voltar a depender da infraestrutura."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.entities.estoque import Peca
from app.domain.entities.execucao import OrdemExecucao, StatusExecucao
from app.domain.entities.reserva import Reserva, ReservaEstado, ReservaItem, TipoItem
from app.domain.exceptions import BusinessRuleException

AGORA = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)


def test_disponivel_desconta_o_reservado():
    assert Peca(quantidade=10, reservada=3).disponivel == 7


def test_reservar_e_liberar_movem_so_o_reservado():
    peca = Peca(quantidade=10)
    peca.reservar(4)
    assert (peca.quantidade, peca.reservada, peca.disponivel) == (10, 4, 6)
    peca.liberar(4)
    assert (peca.quantidade, peca.reservada) == (10, 0)


def test_reservar_acima_do_disponivel_e_recusado():
    peca = Peca(nome="Filtro", quantidade=5, reservada=3)
    with pytest.raises(BusinessRuleException, match="Filtro"):
        peca.reservar(3)
    assert peca.reservada == 3


def test_baixar_consome_a_reserva_e_repor_devolve_ao_estoque():
    peca = Peca(quantidade=10, reservada=4)
    peca.baixar(4)
    assert (peca.quantidade, peca.reservada) == (6, 0)
    peca.repor(4)
    assert peca.quantidade == 10


def test_reserva_nova_esta_ativa_e_sem_itens():
    reserva = Reserva()
    assert reserva.ativa and reserva.itens == [] and reserva.valor_total == 0


def test_reserva_soma_itens_com_precisao_decimal():
    reserva = Reserva(itens=[
        ReservaItem(tipo=TipoItem.SERVICO, quantidade=2, preco_unitario=Decimal("150.00")),
        ReservaItem(tipo=TipoItem.PECA, quantidade=3, preco_unitario=Decimal("0.10")),
    ])
    assert reserva.valor_total == Decimal("300.30")
    assert [i.tipo for i in reserva.pecas] == [TipoItem.PECA]


def test_reserva_liberada_ou_consumida_deixa_de_estar_ativa():
    reserva = Reserva()
    reserva.liberar()
    assert reserva.estado == ReservaEstado.LIBERADA and not reserva.ativa
    reserva.consumir()
    assert reserva.estado == ReservaEstado.CONSUMIDA and not reserva.ativa


def test_ordem_nova_nasce_na_fila():
    assert OrdemExecucao().status == StatusExecucao.NA_FILA


def test_fluxo_completo_da_ordem():
    ordem = OrdemExecucao()
    ordem.transicionar(StatusExecucao.EM_DIAGNOSTICO, AGORA)
    ordem.transicionar(StatusExecucao.EM_EXECUCAO, AGORA, "Troca de pastilhas")
    assert ordem.iniciada_em == AGORA and ordem.finalizada_em is None
    ordem.transicionar(StatusExecucao.FINALIZADA, AGORA)
    assert ordem.status == StatusExecucao.FINALIZADA and ordem.finalizada_em == AGORA
    assert ordem.observacao == "Troca de pastilhas"


def test_ordem_na_fila_pode_ser_cancelada():
    ordem = OrdemExecucao()
    ordem.transicionar(StatusExecucao.CANCELADA, AGORA)
    assert ordem.status == StatusExecucao.CANCELADA


@pytest.mark.parametrize("origem, destino", [
    (StatusExecucao.NA_FILA, StatusExecucao.EM_EXECUCAO),
    (StatusExecucao.NA_FILA, StatusExecucao.FINALIZADA),
    (StatusExecucao.EM_DIAGNOSTICO, StatusExecucao.NA_FILA),
    (StatusExecucao.EM_DIAGNOSTICO, StatusExecucao.CANCELADA),
    (StatusExecucao.EM_EXECUCAO, StatusExecucao.EM_DIAGNOSTICO),
    (StatusExecucao.FINALIZADA, StatusExecucao.EM_EXECUCAO),
    (StatusExecucao.CANCELADA, StatusExecucao.NA_FILA),
])
def test_transicao_fora_do_mapa_e_recusada(origem, destino):
    ordem = OrdemExecucao(status=origem)
    with pytest.raises(BusinessRuleException, match="Transição inválida"):
        ordem.transicionar(destino, AGORA)
    assert ordem.status == origem
