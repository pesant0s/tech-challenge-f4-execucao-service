def _criar_servico(client, auth_headers, nome="Troca de óleo", preco=150.00):
    return client.post("/catalogo/servicos", json={
        "nome": nome, "preco": preco
    }, headers=auth_headers).json()


def test_criar_servico(client, auth_headers):
    r = client.post("/catalogo/servicos", json={
        "nome": "Alinhamento", "preco": 80.00, "descricao": "Alinhamento das quatro rodas"
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["nome"] == "Alinhamento"


def test_criar_servico_preco_invalido(client, auth_headers):
    r = client.post("/catalogo/servicos", json={
        "nome": "Serviço Inválido", "preco": 0
    }, headers=auth_headers)
    assert r.status_code == 422


def test_criar_servico_preco_negativo(client, auth_headers):
    r = client.post("/catalogo/servicos", json={
        "nome": "Serviço Inválido", "preco": -50.00
    }, headers=auth_headers)
    assert r.status_code == 422


def test_criar_servico_nome_curto(client, auth_headers):
    r = client.post("/catalogo/servicos", json={
        "nome": "A", "preco": 50.00
    }, headers=auth_headers)
    assert r.status_code == 422


def test_listar_servicos(client, auth_headers):
    _criar_servico(client, auth_headers, "Balanceamento")
    _criar_servico(client, auth_headers, "Geometria")
    r = client.get("/catalogo/servicos", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_listar_servicos_paginacao(client, auth_headers):
    for nome in ["Serviço A", "Serviço B", "Serviço C"]:
        _criar_servico(client, auth_headers, nome)
    r = client.get("/catalogo/servicos?skip=0&limit=2", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_obter_servico(client, auth_headers):
    s = _criar_servico(client, auth_headers, "Revisão completa")
    r = client.get(f"/catalogo/servicos/{s['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == s["id"]


def test_obter_servico_nao_encontrado(client, auth_headers):
    r = client.get("/catalogo/servicos/00000000-0000-0000-0000-000000000000", headers=auth_headers)
    assert r.status_code == 404


def test_atualizar_servico(client, auth_headers):
    s = _criar_servico(client, auth_headers, "Nome Antigo", preco=100.00)
    r = client.put(f"/catalogo/servicos/{s['id']}", json={
        "nome": "Nome Novo", "preco": 120.00
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["nome"] == "Nome Novo"
    assert float(r.json()["preco"]) == 120.00


def test_deletar_servico(client, auth_headers):
    s = _criar_servico(client, auth_headers, "Serviço para deletar")
    r = client.delete(f"/catalogo/servicos/{s['id']}", headers=auth_headers)
    assert r.status_code == 204
    r2 = client.get(f"/catalogo/servicos/{s['id']}", headers=auth_headers)
    assert r2.status_code == 404


def test_catalogo_requer_auth(client):
    r = client.get("/catalogo/servicos")
    assert r.status_code == 401
