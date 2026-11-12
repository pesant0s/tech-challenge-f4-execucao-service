"""Autenticação só pelos claims do token do OS Service, sem banco de usuários."""
import pytest


@pytest.mark.parametrize("claims", [
    {"tipo": None},
    {"tipo": "outro"},
    {"sub": None},
    {"role": "GERENTE"},
    {"role": None},
], ids=["sem tipo", "tipo desconhecido", "sem sub", "role desconhecida", "sem role"])
def test_token_sem_os_claims_de_funcionario_e_recusado(client, emitir_token, claims):
    assert client.get("/catalogo/servicos", headers=emitir_token(**claims)).status_code == 401


def test_sem_token_ou_com_token_invalido_e_401(client):
    assert client.get("/catalogo/servicos").status_code == 401
    assert client.get("/catalogo/servicos", headers={"Authorization": "Bearer lixo"}).status_code == 401


def test_token_expirado_e_401(client, emitir_token):
    assert client.get("/catalogo/servicos", headers=emitir_token(minutos=-5)).status_code == 401


def test_token_de_cliente_e_403(client, emitir_token):
    resposta = client.get("/catalogo/servicos", headers=emitir_token(tipo="cliente", role=None, cpf_cnpj="52998224725"))
    assert resposta.status_code == 403


def test_atendente_le_mas_nao_escreve(client, atendente_headers):
    assert client.get("/catalogo/servicos", headers=atendente_headers).status_code == 200
    assert client.get("/estoque/pecas", headers=atendente_headers).status_code == 200
    resposta = client.post("/catalogo/servicos", json={"nome": "Alinhamento", "preco": 80}, headers=atendente_headers)
    assert resposta.status_code == 403


def test_admin_escreve(client, auth_headers):
    resposta = client.post("/catalogo/servicos", json={"nome": "Alinhamento", "preco": 80}, headers=auth_headers)
    assert resposta.status_code == 201


def test_rotas_de_execucao_exigem_funcionario(client, emitir_token):
    assert client.get("/execucao/fila").status_code == 401
    assert client.get("/execucao/fila", headers=emitir_token(tipo="cliente", role=None)).status_code == 403
