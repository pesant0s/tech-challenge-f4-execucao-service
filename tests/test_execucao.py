"""Rotas da fila de execução e do catálogo/estoque com reserva."""
import uuid

import pytest

from app.domain.entities.execucao import OrdemExecucao, StatusExecucao
from tests.apoio import comando, criar_peca, processar, publicadas, reservar


def enfileirar_os(db, peca, veiculo_id=None) -> uuid.UUID:
    os_id, saga_id = uuid.uuid4(), uuid.uuid4()
    processar(db, reservar(os_id, saga_id, ("PECA", peca, 1)))
    processar(db, comando("EnfileirarOS", os_id, saga_id, {"veiculo_id": str(veiculo_id or uuid.uuid4())}))
    return os_id


@pytest.fixture
def peca(db):
    return criar_peca(db, quantidade=50)


def eventos_de_execucao(db):
    return [m for m in publicadas(db) if m["tipo"].startswith(("Diagnostico", "Execucao"))]


def test_fila_vazia(client, atendente_headers):
    assert client.get("/execucao/fila", headers=atendente_headers).json() == []


def test_fila_ordena_por_andamento_e_depois_pela_mais_antiga(client, db, atendente_headers, peca):
    na_fila = [enfileirar_os(db, peca) for _ in range(3)]
    ordens = {o.os_id: o for o in db.query(OrdemExecucao)}
    ordens[na_fila[2]].status = StatusExecucao.EM_EXECUCAO
    ordens[na_fila[1]].status = StatusExecucao.EM_DIAGNOSTICO
    finalizada = enfileirar_os(db, peca)
    db.query(OrdemExecucao).filter_by(os_id=finalizada).one().status = StatusExecucao.FINALIZADA
    cancelada = enfileirar_os(db, peca)
    db.query(OrdemExecucao).filter_by(os_id=cancelada).one().status = StatusExecucao.CANCELADA
    db.commit()
    fila = client.get("/execucao/fila", headers=atendente_headers).json()
    assert [(o["os_id"], o["status"]) for o in fila] == [
        (str(na_fila[2]), "EM_EXECUCAO"), (str(na_fila[1]), "EM_DIAGNOSTICO"), (str(na_fila[0]), "NA_FILA")]


def test_dentro_da_prioridade_a_mais_antiga_vem_primeiro(client, db, atendente_headers, peca):
    primeira, segunda = enfileirar_os(db, peca), enfileirar_os(db, peca)
    fila = client.get("/execucao/fila", headers=atendente_headers).json()
    assert [o["os_id"] for o in fila] == [str(primeira), str(segunda)]


def test_obter_ordem_da_os(client, db, atendente_headers, peca):
    os_id = enfileirar_os(db, peca)
    corpo = client.get(f"/execucao/os/{os_id}", headers=atendente_headers).json()
    assert (corpo["os_id"], corpo["status"], corpo["iniciada_em"]) == (str(os_id), "NA_FILA", None)
    assert client.get(f"/execucao/os/{uuid.uuid4()}", headers=atendente_headers).status_code == 404


def test_proxima_pega_a_mais_antiga_e_publica_diagnostico_iniciado(client, db, atendente_headers, peca):
    primeira, _ = enfileirar_os(db, peca), enfileirar_os(db, peca)
    resposta = client.post("/execucao/fila/proxima", headers=atendente_headers)
    assert resposta.status_code == 200
    assert (resposta.json()["os_id"], resposta.json()["status"]) == (str(primeira), "EM_DIAGNOSTICO")
    evento = eventos_de_execucao(db)[-1]
    assert (evento["tipo"], evento["os_id"], evento["payload"]) == ("DiagnosticoIniciado", str(primeira), {"observacao": None})


def test_proxima_com_fila_vazia_e_404(client, atendente_headers):
    assert client.post("/execucao/fila/proxima", headers=atendente_headers).status_code == 404


def test_fluxo_pelas_rotas_publica_um_evento_por_passo(client, db, atendente_headers, peca):
    os_id = enfileirar_os(db, peca)
    base = f"/execucao/os/{os_id}"
    assert client.post(f"{base}/diagnostico", headers=atendente_headers).json()["status"] == "EM_DIAGNOSTICO"
    reparo = client.post(f"{base}/reparo", json={"observacao": "Troca de pastilhas"}, headers=atendente_headers).json()
    assert (reparo["status"], reparo["observacao"]) == ("EM_EXECUCAO", "Troca de pastilhas")
    assert reparo["iniciada_em"] is not None
    final = client.post(f"{base}/finalizacao", json={"observacao": "Pronto"}, headers=atendente_headers).json()
    assert (final["status"], final["observacao"]) == ("FINALIZADA", "Pronto") and final["finalizada_em"]
    assert [(e["tipo"], e["payload"]) for e in eventos_de_execucao(db)] == [
        ("DiagnosticoIniciado", {"observacao": None}),
        ("ExecucaoIniciada", {"observacao": "Troca de pastilhas"}),
        ("ExecucaoFinalizada", {"observacao": "Pronto"}),
    ]
    assert eventos_de_execucao(db)[0]["saga_id"] == str(db.query(OrdemExecucao).one().saga_id)


@pytest.mark.parametrize("rota", ["reparo", "finalizacao"])
def test_transicao_invalida_e_422_e_nao_publica(client, db, atendente_headers, peca, rota):
    os_id = enfileirar_os(db, peca)
    resposta = client.post(f"/execucao/os/{os_id}/{rota}", headers=atendente_headers)
    assert resposta.status_code == 422 and "Transição inválida" in resposta.json()["detail"]
    assert eventos_de_execucao(db) == []
    assert client.get(f"/execucao/os/{os_id}", headers=atendente_headers).json()["status"] == "NA_FILA"


def test_diagnostico_repetido_e_422(client, db, atendente_headers, peca):
    os_id = enfileirar_os(db, peca)
    client.post(f"/execucao/os/{os_id}/diagnostico", headers=atendente_headers)
    assert client.post(f"/execucao/os/{os_id}/diagnostico", headers=atendente_headers).status_code == 422
    assert len(eventos_de_execucao(db)) == 1


def test_transicao_de_os_sem_ordem_e_404(client, atendente_headers):
    assert client.post(f"/execucao/os/{uuid.uuid4()}/diagnostico", headers=atendente_headers).status_code == 404


def test_peca_mostra_reservada_e_disponivel(client, db, auth_headers, peca):
    processar(db, reservar(uuid.uuid4(), uuid.uuid4(), ("PECA", peca, 8)))
    corpo = client.get(f"/estoque/pecas/{peca.id}", headers=auth_headers).json()
    assert (corpo["quantidade"], corpo["reservada"], corpo["disponivel"]) == (50, 8, 42)


def test_remover_peca_com_reserva_ativa_e_409(client, db, auth_headers, peca):
    processar(db, reservar(uuid.uuid4(), uuid.uuid4(), ("PECA", peca, 1)))
    assert client.delete(f"/estoque/pecas/{peca.id}", headers=auth_headers).status_code == 409


def test_remover_peca_com_movimentacao_e_409(client, db, auth_headers):
    peca = criar_peca(db, nome="Correia")
    client.post(f"/estoque/pecas/{peca.id}/entrada", json={"quantidade": 1}, headers=auth_headers)
    assert client.delete(f"/estoque/pecas/{peca.id}", headers=auth_headers).status_code == 409


def test_remover_servico_em_reserva_ativa_e_409_e_liberada_e_204(client, db, auth_headers):
    from tests.apoio import criar_servico
    servico = criar_servico(db, nome="Alinhamento")
    os_id, saga_id = uuid.uuid4(), uuid.uuid4()
    processar(db, reservar(os_id, saga_id, ("SERVICO", servico, 1)))
    assert client.delete(f"/catalogo/servicos/{servico.id}", headers=auth_headers).status_code == 409
    processar(db, comando("LiberarReserva", os_id, saga_id, {"motivo": "PRAZO_ESGOTADO"}))
    assert client.delete(f"/catalogo/servicos/{servico.id}", headers=auth_headers).status_code == 204


def test_atualizar_peca_abaixo_do_reservado_e_422(client, db, auth_headers, peca):
    processar(db, reservar(uuid.uuid4(), uuid.uuid4(), ("PECA", peca, 10)))
    corpo = {"nome": peca.nome, "preco": 35, "quantidade": 5, "estoque_minimo": 1}
    assert client.put(f"/estoque/pecas/{peca.id}", json=corpo, headers=auth_headers).status_code == 422
    assert client.put(f"/estoque/pecas/{peca.id}", json={**corpo, "quantidade": 10}, headers=auth_headers).status_code == 200
