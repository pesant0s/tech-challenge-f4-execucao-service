def _criar_peca(client, auth_headers, nome="Filtro de óleo", preco=35.00, quantidade=10, estoque_minimo=2):
    return client.post("/estoque/pecas", json={
        "nome": nome, "preco": preco, "quantidade": quantidade, "estoque_minimo": estoque_minimo
    }, headers=auth_headers).json()


def test_criar_peca(client, auth_headers):
    r = client.post("/estoque/pecas", json={
        "nome": "Filtro de óleo", "preco": 35.00, "quantidade": 10, "estoque_minimo": 2
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["quantidade"] == 10


def test_criar_peca_preco_invalido(client, auth_headers):
    r = client.post("/estoque/pecas", json={
        "nome": "Peça", "preco": -10.00, "quantidade": 5, "estoque_minimo": 1
    }, headers=auth_headers)
    assert r.status_code == 422


def test_criar_peca_quantidade_negativa(client, auth_headers):
    r = client.post("/estoque/pecas", json={
        "nome": "Peça", "preco": 10.00, "quantidade": -1, "estoque_minimo": 1
    }, headers=auth_headers)
    assert r.status_code == 422


def test_listar_pecas(client, auth_headers):
    _criar_peca(client, auth_headers, "Peça A")
    _criar_peca(client, auth_headers, "Peça B")
    r = client.get("/estoque/pecas", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_listar_pecas_paginacao(client, auth_headers):
    for i in range(3):
        _criar_peca(client, auth_headers, nome=f"Peça {i}")
    r = client.get("/estoque/pecas?skip=0&limit=2", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_obter_peca(client, auth_headers):
    p = _criar_peca(client, auth_headers)
    r = client.get(f"/estoque/pecas/{p['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == p["id"]


def test_obter_peca_nao_encontrada(client, auth_headers):
    r = client.get("/estoque/pecas/00000000-0000-0000-0000-000000000000", headers=auth_headers)
    assert r.status_code == 404


def test_atualizar_peca(client, auth_headers):
    p = _criar_peca(client, auth_headers, nome="Nome Antigo")
    r = client.put(f"/estoque/pecas/{p['id']}", json={
        "nome": "Nome Novo", "preco": 50.00, "quantidade": 10, "estoque_minimo": 2
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["nome"] == "Nome Novo"


def test_deletar_peca(client, auth_headers):
    p = _criar_peca(client, auth_headers, nome="Peça para deletar")
    r = client.delete(f"/estoque/pecas/{p['id']}", headers=auth_headers)
    assert r.status_code == 204


def test_entrada_estoque(client, auth_headers):
    peca = _criar_peca(client, auth_headers, nome="Correia", quantidade=5)
    r = client.post(f"/estoque/pecas/{peca['id']}/entrada",
        json={"quantidade": 10, "motivo": "Compra NF 123"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["quantidade"] == 15


def test_entrada_estoque_quantidade_zero(client, auth_headers):
    peca = _criar_peca(client, auth_headers)
    r = client.post(f"/estoque/pecas/{peca['id']}/entrada",
        json={"quantidade": 0}, headers=auth_headers)
    assert r.status_code == 422


def test_entrada_estoque_quantidade_negativa(client, auth_headers):
    peca = _criar_peca(client, auth_headers)
    r = client.post(f"/estoque/pecas/{peca['id']}/entrada",
        json={"quantidade": -5}, headers=auth_headers)
    assert r.status_code == 422
