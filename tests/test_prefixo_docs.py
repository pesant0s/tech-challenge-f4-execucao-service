import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from app.infrastructure.config import settings

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _app_com_prefixo(monkeypatch, prefixo):
    """Carrega uma segunda instância do módulo, já que o prefixo é lido na criação do FastAPI."""
    monkeypatch.setattr(settings, "PREFIXO_DOCS", prefixo)
    spec = importlib.util.spec_from_file_location("app_main_prefixo", MAIN)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.app


def test_sem_prefixo_a_documentacao_fica_na_raiz(monkeypatch):
    cliente = TestClient(_app_com_prefixo(monkeypatch, ""))
    assert cliente.get("/openapi.json").status_code == 200
    assert cliente.get("/docs").status_code == 200


def test_com_prefixo_a_documentacao_sai_da_raiz(monkeypatch):
    cliente = TestClient(_app_com_prefixo(monkeypatch, "/execucao"))
    assert cliente.get("/execucao/openapi.json").status_code == 200
    assert cliente.get("/execucao/docs").status_code == 200
    assert cliente.get("/execucao/redoc").status_code == 200
    assert cliente.get("/openapi.json").status_code == 404
    assert cliente.get("/health").status_code == 200
