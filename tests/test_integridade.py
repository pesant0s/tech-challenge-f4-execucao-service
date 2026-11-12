"""Restrições CHECK e UNIQUE: o banco recusa o que a aplicação já não deixaria passar."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

OS = "'00000000-0000-0000-0000-000000000001'"


@pytest.mark.parametrize("sql", [
    "INSERT INTO pecas (id, nome, preco, quantidade, estoque_minimo, reservada) VALUES ('p1', 'Filtro', 10, -1, 0, 0)",
    "INSERT INTO pecas (id, nome, preco, quantidade, estoque_minimo, reservada) VALUES ('p1', 'Filtro', 10, 5, 0, -1)",
    "INSERT INTO pecas (id, nome, preco, quantidade, estoque_minimo, reservada) VALUES ('p1', 'Filtro', 10, 5, 0, 6)",
    "INSERT INTO servicos (id, nome, preco) VALUES ('s1', 'Revisão', 0)",
    "INSERT INTO movimentacoes_estoque (id, peca_id, tipo, quantidade) VALUES ('m1', 'p1', 'AJUSTE', 1)",
    f"INSERT INTO reservas (id, os_id, saga_id, estado) VALUES ('r1', {OS}, {OS}, 'ATIVA'), ('r2', {OS}, {OS}, 'ATIVA')",
    f"INSERT INTO ordens_execucao (id, os_id, saga_id, veiculo_id, status, enfileirada_em) VALUES "
    f"('o1', {OS}, {OS}, {OS}, 'NA_FILA', now()), ('o2', {OS}, {OS}, {OS}, 'NA_FILA', now())",
], ids=["estoque negativo", "reservada negativa", "reservada acima do estoque", "serviço sem preço",
        "movimentação desconhecida", "duas reservas da mesma OS", "duas ordens da mesma OS"])
def test_banco_recusa_dado_inconsistente(db, sql):
    with pytest.raises(IntegrityError):
        db.execute(text(sql.replace("now()", "CURRENT_TIMESTAMP")))
