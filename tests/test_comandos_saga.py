"""Os três comandos da Saga contra o banco de testes: estado, resposta no outbox e idempotência."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.domain.entities.execucao import OrdemExecucao, StatusExecucao
from app.domain.entities.estoque import MovimentacaoEstoque
from app.domain.entities.reserva import Reserva, ReservaEstado
from app.infrastructure.orm_mapping import mensagens_processadas
from tests.apoio import comando, criar_peca, criar_servico, processar, publicadas, reservar

AGORA = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def ids():
    return uuid.uuid4(), uuid.uuid4()  # os_id, saga_id


@pytest.fixture
def servico(db):
    return criar_servico(db)


@pytest.fixture
def peca(db):
    return criar_peca(db, quantidade=10)


def enfileirar(os_id, saga_id, veiculo_id=None):
    return comando("EnfileirarOS", os_id, saga_id, {"veiculo_id": str(veiculo_id or uuid.uuid4())})


def liberar(os_id, saga_id, motivo="PAGAMENTO_RECUSADO"):
    return comando("LiberarReserva", os_id, saga_id, {"motivo": motivo})


def ultima(db):
    return publicadas(db)[-1]


# ─── ReservarPecas ──────────────────────────────────────────────────────────

def test_reserva_precifica_os_itens_e_separa_as_pecas(db, ids, servico, peca):
    os_id, saga_id = ids
    assert processar(db, reservar(os_id, saga_id, ("SERVICO", servico, 1), ("PECA", peca, 3)))
    evento = ultima(db)
    assert (evento["tipo"], evento["origem"], evento["versao"]) == ("PecasReservadas", "execucao-service", 1)
    assert (evento["os_id"], evento["saga_id"]) == (str(os_id), str(saga_id))
    assert evento["payload"]["valor_total"] == "255.00"
    por_tipo = {i["tipo"]: i for i in evento["payload"]["itens"]}
    assert por_tipo["PECA"] == {"tipo": "PECA", "item_id": str(peca.id), "descricao": "Filtro de óleo", "quantidade": 3,
                                "preco_unitario": "35.00", "subtotal": "105.00"}
    assert por_tipo["SERVICO"]["subtotal"] == "150.00"
    db.refresh(peca)
    assert (peca.quantidade, peca.reservada, peca.disponivel) == (10, 3, 7)
    assert db.query(Reserva).one().estado == ReservaEstado.ATIVA


def test_reserva_so_de_servico_nao_mexe_no_estoque(db, ids, servico, peca):
    processar(db, reservar(*ids, ("SERVICO", servico, 2)))
    assert ultima(db)["payload"]["valor_total"] == "300.00"
    db.refresh(peca)
    assert peca.reservada == 0


def test_itens_repetidos_somam_a_quantidade(db, ids, peca):
    processar(db, reservar(*ids, ("PECA", peca, 2), ("PECA", peca, 3)))
    assert [i["quantidade"] for i in ultima(db)["payload"]["itens"]] == [5]


def test_item_inexistente_recusa_sem_reservar_nada(db, ids, peca):
    fantasma = uuid.uuid4()
    envelope = reservar(*ids, ("PECA", peca, 1))
    envelope["payload"]["itens"].append({"tipo": "SERVICO", "item_id": str(fantasma), "quantidade": 1})
    processar(db, envelope)
    assert ultima(db)["tipo"] == "ReservaRecusada"
    assert ultima(db)["payload"] == {"motivo": "ITEM_INEXISTENTE",
                                     "itens": [{"item_id": str(fantasma), "detalhe": "servico inexistente"}]}
    db.refresh(peca)
    assert peca.reservada == 0 and db.query(Reserva).count() == 0


def test_estoque_insuficiente_recusa_sem_reserva_parcial(db, ids, servico, peca):
    pouca = criar_peca(db, nome="Pastilha", quantidade=2)
    processar(db, reservar(*ids, ("PECA", peca, 4), ("PECA", pouca, 3), ("SERVICO", servico, 1)))
    assert ultima(db)["payload"] == {"motivo": "ESTOQUE_INSUFICIENTE",
                                     "itens": [{"item_id": str(pouca.id), "detalhe": "disponível 2, pedido 3"}]}
    db.refresh(peca)
    assert peca.reservada == 0 and db.query(Reserva).count() == 0


def test_reservas_de_outras_os_reduzem_o_disponivel(db, servico, peca):
    processar(db, reservar(uuid.uuid4(), uuid.uuid4(), ("PECA", peca, 8)))
    processar(db, reservar(uuid.uuid4(), uuid.uuid4(), ("PECA", peca, 3)))
    assert ultima(db)["payload"]["itens"][0]["detalhe"] == "disponível 2, pedido 3"


def test_reservar_de_novo_a_mesma_os_responde_igual_sem_reservar_outra_vez(db, ids, servico, peca):
    processar(db, reservar(*ids, ("SERVICO", servico, 1), ("PECA", peca, 3)))
    preco_original = ultima(db)["payload"]
    servico.preco = Decimal("999.00")
    db.commit()
    processar(db, reservar(*ids, ("SERVICO", servico, 1), ("PECA", peca, 3)))
    segunda = ultima(db)
    assert segunda["tipo"] == "PecasReservadas" and segunda["payload"] == preco_original
    assert segunda["message_id"] != publicadas(db)[0]["message_id"]
    db.refresh(peca)
    assert peca.reservada == 3 and db.query(Reserva).count() == 1


def test_mensagem_repetida_por_message_id_nao_tem_efeito(db, ids, peca):
    envelope = reservar(*ids, ("PECA", peca, 3))
    assert processar(db, envelope) is True
    assert processar(db, envelope) is False
    assert len(publicadas(db)) == 1
    db.refresh(peca)
    assert peca.reservada == 3
    assert db.scalar(select(func.count()).select_from(mensagens_processadas)) == 1


# ─── LiberarReserva ─────────────────────────────────────────────────────────

def test_liberar_reserva_ativa_devolve_o_reservado(db, ids, peca):
    processar(db, reservar(*ids, ("PECA", peca, 3)))
    processar(db, liberar(*ids))
    assert (ultima(db)["tipo"], ultima(db)["payload"]) == ("ReservaLiberada", {})
    db.refresh(peca)
    assert (peca.quantidade, peca.reservada) == (10, 0)
    assert db.query(Reserva).one().estado == ReservaEstado.LIBERADA


def test_liberar_duas_vezes_devolve_uma_so(db, ids, peca):
    processar(db, reservar(*ids, ("PECA", peca, 3)))
    processar(db, liberar(*ids))
    processar(db, liberar(*ids))
    assert [m["tipo"] for m in publicadas(db)] == ["PecasReservadas", "ReservaLiberada", "ReservaLiberada"]
    db.refresh(peca)
    assert peca.reservada == 0


def test_liberar_reserva_inexistente_confirma_mesmo_assim(db, ids):
    processar(db, liberar(*ids))
    evento = ultima(db)
    assert (evento["tipo"], evento["os_id"]) == ("ReservaLiberada", str(ids[0]))


def test_liberar_reserva_consumida_com_ordem_na_fila_estorna_as_pecas(db, ids, servico, peca):
    os_id, saga_id = ids
    processar(db, reservar(os_id, saga_id, ("SERVICO", servico, 1), ("PECA", peca, 3)))
    processar(db, enfileirar(os_id, saga_id))
    db.refresh(peca)
    assert (peca.quantidade, peca.reservada) == (7, 0)
    processar(db, liberar(os_id, saga_id, "ENFILEIRAMENTO_RECUSADO"))
    assert ultima(db)["tipo"] == "ReservaLiberada"
    db.refresh(peca)
    assert (peca.quantidade, peca.reservada) == (10, 0)
    assert db.query(OrdemExecucao).one().status == StatusExecucao.CANCELADA
    motivos = [(m.tipo, m.quantidade, m.motivo) for m in db.query(MovimentacaoEstoque).order_by(MovimentacaoEstoque.tipo)]
    assert motivos == [("ENTRADA", 3, f"Estorno da OS {os_id}"), ("SAIDA", 3, f"Baixa da OS {os_id}")]


def test_liberar_reserva_consumida_com_ordem_em_andamento_nao_estorna(db, ids, peca):
    processar(db, reservar(*ids, ("PECA", peca, 3)))
    processar(db, enfileirar(*ids))
    ordem = db.query(OrdemExecucao).one()
    ordem.status = StatusExecucao.EM_DIAGNOSTICO
    db.commit()
    processar(db, liberar(*ids))
    assert ultima(db)["tipo"] == "ReservaLiberada"
    db.refresh(peca)
    assert peca.quantidade == 7
    assert db.query(OrdemExecucao).one().status == StatusExecucao.EM_DIAGNOSTICO


# ─── EnfileirarOS ───────────────────────────────────────────────────────────

def test_enfileirar_baixa_o_estoque_e_cria_a_ordem(db, ids, servico, peca):
    os_id, saga_id = ids
    veiculo_id = uuid.uuid4()
    processar(db, reservar(os_id, saga_id, ("SERVICO", servico, 1), ("PECA", peca, 3)))
    processar(db, enfileirar(os_id, saga_id, veiculo_id), AGORA)
    evento = ultima(db)
    assert (evento["tipo"], evento["payload"], evento["os_id"], evento["saga_id"]) == \
        ("OSEnfileirada", {"posicao": 1}, str(os_id), str(saga_id))
    db.refresh(peca)
    assert (peca.quantidade, peca.reservada) == (7, 0)
    ordem = db.query(OrdemExecucao).one()
    assert (ordem.status, ordem.veiculo_id, ordem.saga_id) == (StatusExecucao.NA_FILA, veiculo_id, saga_id)
    assert db.query(Reserva).one().estado == ReservaEstado.CONSUMIDA
    saida = db.query(MovimentacaoEstoque).one()
    assert (saida.tipo, saida.quantidade, saida.motivo) == ("SAIDA", 3, f"Baixa da OS {os_id}")


def test_posicao_conta_as_ordens_que_entraram_antes(db, peca):
    for dias, esperada in ((0, 1), (1, 2), (2, 3)):
        os_id, saga_id = uuid.uuid4(), uuid.uuid4()
        processar(db, reservar(os_id, saga_id, ("PECA", peca, 1)))
        processar(db, enfileirar(os_id, saga_id), AGORA + timedelta(days=dias))
        assert ultima(db)["payload"] == {"posicao": esperada}


def test_enfileirar_sem_reserva_ativa_e_recusado(db, ids, peca):
    processar(db, enfileirar(*ids))
    assert (ultima(db)["tipo"], ultima(db)["payload"]) == ("EnfileiramentoRecusado", {"motivo": "RESERVA_INEXISTENTE"})
    processar(db, reservar(*ids, ("PECA", peca, 1)))
    processar(db, liberar(*ids))
    processar(db, enfileirar(*ids))
    assert ultima(db)["tipo"] == "EnfileiramentoRecusado"
    assert db.query(OrdemExecucao).count() == 0


def test_enfileirar_de_novo_publica_a_posicao_atual(db, ids, peca):
    os_id, saga_id = ids
    processar(db, reservar(os_id, saga_id, ("PECA", peca, 1)))
    processar(db, enfileirar(os_id, saga_id), AGORA)
    outra = (uuid.uuid4(), uuid.uuid4())
    processar(db, reservar(*outra, ("PECA", peca, 1)))
    processar(db, enfileirar(*outra), AGORA + timedelta(hours=1))
    processar(db, enfileirar(*outra))
    assert ultima(db)["payload"] == {"posicao": 2}
    processar(db, enfileirar(os_id, saga_id))
    assert ultima(db)["payload"] == {"posicao": 1}
    db.refresh(peca)
    assert peca.quantidade == 8 and db.query(OrdemExecucao).count() == 2
