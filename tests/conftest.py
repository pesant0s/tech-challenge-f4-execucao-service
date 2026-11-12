import pytest
from datetime import datetime, timedelta, timezone
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.main import app
from app.infrastructure.config import settings
from app.infrastructure.database import metadata, get_db

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def emitir_token():
    """Token no formato do OS Service; os claims podem ser sobrescritos para montar tokens inválidos."""
    def _emitir(minutos: int = 60, **claims) -> dict:
        corpo = {"sub": "ana", "role": "ATENDENTE", "tipo": "usuario",
                 "exp": datetime.now(timezone.utc) + timedelta(minutes=minutos), **claims}
        token = jwt.encode({k: v for k, v in corpo.items() if v is not None}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return {"Authorization": f"Bearer {token}"}
    return _emitir


@pytest.fixture(scope="function")
def auth_headers(emitir_token):
    """Token de ADMIN."""
    return emitir_token(sub="admin", role="ADMIN")


@pytest.fixture(scope="function")
def atendente_headers(emitir_token):
    """Token de ATENDENTE."""
    return emitir_token(sub="atendente", role="ATENDENTE")
