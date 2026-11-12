"""Consumidor, relay e topologia com um canal falso; a prova contra um RabbitMQ real só roda se houver um."""
import json
import os as sistema
import socket
import time
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from pika.exceptions import UnroutableError
from sqlalchemy import select

from app.adapters.inbound.mensageria import tratar_mensagem
from app.adapters.outbound.mensageria import FILA_COMANDOS, declarar_topologia, publicar_pendentes
from app.application.mensagens import publicar_evento
from app.adapters.outbound.persistence.outbox_repository import OutboxRepositoryAdapter
from app.infrastructure.orm_mapping import outbox
from app.infrastructure.rastreamento import cabecalhos_de_rastreamento, consumo_rastreado
from tests.apoio import comando, criar_peca, publicadas, reservar


class CanalFalso:
    def __init__(self, recusar_rotas=()):
        self.publicadas, self.acks, self.nacks, self.chamadas = [], [], [], []
        self._recusar = recusar_rotas

    def basic_publish(self, exchange, rota, corpo, propriedades, mandatory):
        if rota in self._recusar:
            raise UnroutableError([])
        self.publicadas.append((exchange, rota, json.loads(corpo), propriedades))

    def basic_ack(self, tag):
        self.acks.append(tag)

    def basic_nack(self, tag, requeue):
        self.nacks.append((tag, requeue))

    def __getattr__(self, nome):
        return lambda *args, **kwargs: self.chamadas.append((nome, args, kwargs))


@pytest.fixture
def sessoes(db):
    @contextmanager
    def fabrica():
        yield db
    return fabrica


@pytest.fixture
def pedido(db):
    os_id, saga_id = uuid.uuid4(), uuid.uuid4()
    return reservar(os_id, saga_id, ("PECA", criar_peca(db), 2))


def entregar(canal, corpo, sessoes, headers=None):
    tratar_mensagem(canal, SimpleNamespace(delivery_tag=7), SimpleNamespace(headers=headers), corpo, sessoes)


def test_comando_valido_e_confirmado_depois_do_processamento(pedido, sessoes, db):
    canal = CanalFalso()
    entregar(canal, json.dumps(pedido), sessoes, headers={"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"})
    assert canal.acks == [7] and canal.nacks == []
    assert [m["tipo"] for m in publicadas(db)] == ["PecasReservadas"]


def test_comando_entregue_duas_vezes_responde_uma_so(pedido, sessoes, db):
    canal = CanalFalso()
    entregar(canal, json.dumps(pedido), sessoes)
    entregar(canal, json.dumps(pedido), sessoes)
    assert canal.acks == [7, 7] and len(publicadas(db)) == 1


@pytest.mark.parametrize("corpo", [
    b"{nao e json",
    json.dumps({"tipo": "ReservarPecas"}),
    json.dumps({"tipo": "GerarOrcamento", "message_id": str(uuid.uuid4()), "saga_id": str(uuid.uuid4()), "os_id": str(uuid.uuid4())}),
    json.dumps({"tipo": "ReservarPecas", "message_id": "x", "saga_id": str(uuid.uuid4()), "os_id": str(uuid.uuid4())}),
], ids=["não é json", "sem campos", "comando de outro serviço", "message_id inválido"])
def test_mensagem_ilegivel_vai_direto_para_a_dlq(corpo, sessoes):
    canal = CanalFalso()
    entregar(canal, corpo, sessoes)
    assert canal.nacks == [(7, False)] and canal.acks == []


def test_falha_inesperada_devolve_a_mensagem_para_a_fila(pedido, sessoes, db):
    pedido["payload"] = {"itens": "quebrado"}
    canal = CanalFalso()
    entregar(canal, json.dumps(pedido), sessoes)
    assert canal.nacks == [(7, True)] and canal.acks == []
    assert publicadas(db) == []


def test_relay_publica_o_outbox_com_as_propriedades_do_contrato(pedido, sessoes, db):
    entregar(CanalFalso(), json.dumps(pedido), sessoes)
    canal = CanalFalso()
    assert publicar_pendentes(canal, sessoes) == 1
    exchange, rota, corpo, propriedades = canal.publicadas[0]
    assert (exchange, rota, corpo["tipo"]) == ("oficina.eventos", "execucao.pecas-reservadas", "PecasReservadas")
    assert propriedades.message_id == corpo["message_id"] and propriedades.type == "PecasReservadas"
    assert propriedades.correlation_id == pedido["saga_id"] and propriedades.delivery_mode == 2
    assert db.execute(select(outbox)).one().publicado_em is not None
    assert publicar_pendentes(canal, sessoes) == 0


def test_relay_para_quando_o_broker_recusa_e_tenta_de_novo_depois(pedido, sessoes, db):
    entregar(CanalFalso(), json.dumps(pedido), sessoes)
    assert publicar_pendentes(CanalFalso(recusar_rotas={"execucao.pecas-reservadas"}), sessoes) == 0
    assert db.execute(select(outbox)).one().publicado_em is None
    assert publicar_pendentes(CanalFalso(), sessoes) == 1


@pytest.mark.parametrize("tipo, rota", [
    ("PecasReservadas", "execucao.pecas-reservadas"),
    ("ReservaRecusada", "execucao.reserva-recusada"),
    ("ReservaLiberada", "execucao.reserva-liberada"),
    ("OSEnfileirada", "execucao.os-enfileirada"),
    ("EnfileiramentoRecusado", "execucao.enfileiramento-recusado"),
    ("DiagnosticoIniciado", "execucao.diagnostico-iniciado"),
    ("ExecucaoIniciada", "execucao.execucao-iniciada"),
    ("ExecucaoFinalizada", "execucao.execucao-finalizada"),
])
def test_chave_de_roteamento_segue_o_contrato(db, tipo, rota):
    from datetime import datetime, timezone
    publicar_evento(OutboxRepositoryAdapter(db), tipo, uuid.uuid4(), uuid.uuid4(), {}, datetime.now(timezone.utc))
    linha = db.execute(select(outbox)).one()
    assert (linha.exchange, linha.rota) == ("oficina.eventos", rota)
    assert linha.corpo["ocorrido_em"].endswith("Z")


def test_topologia_declara_fila_quorum_com_limite_e_dlq():
    canal = CanalFalso()
    declarar_topologia(canal)
    filas = {args[0]: kwargs["arguments"] for nome, args, kwargs in canal.chamadas if nome == "queue_declare"}
    assert filas[FILA_COMANDOS] == {"x-queue-type": "quorum", "x-delivery-limit": 5,
                                    "x-dead-letter-exchange": "oficina.dlx", "x-dead-letter-routing-key": FILA_COMANDOS}
    ligacoes = {(args[0], args[1], args[2]) for nome, args, _ in canal.chamadas if nome == "queue_bind"}
    assert ligacoes == {(FILA_COMANDOS, "oficina.comandos", "execucao.#"), (f"{FILA_COMANDOS}.dlq", "oficina.dlx", FILA_COMANDOS)}


def test_rastreamento_sem_agente_nao_interfere():
    assert cabecalhos_de_rastreamento() == {}
    with consumo_rastreado("ReservarPecas", None):
        pass


RABBITMQ_URL = sistema.environ.get("RABBITMQ_URL_TESTE", "amqp://oficina:oficina@localhost:5672/%2F")


def rabbitmq_disponivel():
    try:
        socket.create_connection(("localhost", 5672), timeout=0.5).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not rabbitmq_disponivel(), reason="RabbitMQ local não está no ar")
def test_trabalhador_contra_rabbitmq_real(pedido, sessoes, db):
    """Publica o ReservarPecas como o OS Service e confere a PecasReservadas que a Execução devolve."""
    import pika
    from app.infrastructure.trabalhador import TrabalhadorMensageria

    trabalhador = TrabalhadorMensageria(RABBITMQ_URL, sessoes)
    conexao = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    canal = conexao.channel()
    declarar_topologia(canal)
    fila_teste = canal.queue_declare("", exclusive=True).method.queue
    canal.queue_bind(fila_teste, "oficina.eventos", "execucao.#")
    trabalhador.start()
    try:
        canal.basic_publish("oficina.comandos", "execucao.reservar-pecas", json.dumps(pedido).encode())
        resposta = None
        for _ in range(100):
            metodo, _, corpo = canal.basic_get(fila_teste, auto_ack=True)
            if metodo:
                resposta = json.loads(corpo)
                break
            time.sleep(0.1)
        assert resposta and resposta["tipo"] == "PecasReservadas"
        assert (resposta["saga_id"], resposta["os_id"]) == (pedido["saga_id"], pedido["os_id"])
        assert resposta["payload"]["valor_total"] == "70.00"
    finally:
        trabalhador.parar()
        canal.queue_delete(FILA_COMANDOS)
        canal.queue_delete(f"{FILA_COMANDOS}.dlq")
        conexao.close()
