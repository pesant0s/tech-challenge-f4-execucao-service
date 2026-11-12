import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.infrastructure.config import settings
from app.infrastructure.logging_config import ConsoleFormatter, JsonFormatter, obter_correlation_id
from app.infrastructure.database import SessionLocal, get_db
from app.infrastructure.trabalhador import TrabalhadorMensageria
from app.adapters.inbound.http.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from app.adapters.inbound.http.catalogo_routes import router as catalogo_router
from app.adapters.inbound.http.estoque_routes import router as estoque_router
from app.adapters.inbound.http.execucao_routes import router as execucao_router
from app.domain.exceptions import NotFoundException, ConflictException, BusinessRuleException

# Configurado no import para que os logs de startup já saiam no formato final.
_saida = logging.StreamHandler(sys.stdout)
_saida.setFormatter(JsonFormatter() if settings.LOG_FORMAT.lower() == "json" else ConsoleFormatter())
logging.basicConfig(handlers=[_saida], level=settings.LOG_LEVEL.upper(), force=True)
for _nome in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    logging.getLogger(_nome).handlers.clear()
    logging.getLogger(_nome).propagate = True
logging.getLogger("pika").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    trabalhador = None
    if settings.RABBITMQ_URL:
        trabalhador = TrabalhadorMensageria(settings.RABBITMQ_URL, SessionLocal)
        trabalhador.start()
    try:
        yield
    finally:
        if trabalhador:
            trabalhador.parar()


app = FastAPI(
    title="Tech Challenge — Oficina · Execução e Produção",
    description="""
Serviço de execução da oficina: catálogo de serviços, estoque de peças com reserva por OS e a fila de
produção (diagnóstico, reparo e finalização). As reservas e a entrada na fila chegam como comandos da
Saga da OS pelo RabbitMQ; as rotas abaixo atendem a oficina.

## Autenticação

Token de funcionário emitido pelo OS Service (`POST /auth/token`), enviado como
`Authorization: Bearer <token>`. Aqui só se confere a assinatura e os claims (`tipo`, `sub`, `role`).
Token de cliente recebe 403.

| Role | Descrição |
|---|---|
| `ADMIN` | Cadastra e altera catálogo e estoque |
| `ATENDENTE` | Consulta o catálogo e o estoque e conduz a fila de execução |

## Fila de execução

`NA_FILA` → `EM_DIAGNOSTICO` → `EM_EXECUCAO` → `FINALIZADA` (ou `CANCELADA` quando a Saga desfaz a OS
ainda na fila). Cada mudança publica o evento correspondente no RabbitMQ.

## Acesso público

| Rota | Descrição |
|---|---|
| `GET /health` | Liveness |
| `GET /health/ready` | Readiness — confirma o banco |
    """,
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True},
    redoc_url="/redoc",
)


def _erro(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, "correlation_id": obter_correlation_id()})


@app.exception_handler(NotFoundException)
async def not_found_handler(request: Request, exc: NotFoundException):
    return _erro(404, exc.detail)


@app.exception_handler(ConflictException)
async def conflict_handler(request: Request, exc: ConflictException):
    return _erro(409, exc.detail)


@app.exception_handler(BusinessRuleException)
async def business_rule_handler(request: Request, exc: BusinessRuleException):
    logging.getLogger("oficina.negocio").warning("Regra de negócio violada: %s", exc.detail, extra={"regra": exc.detail})
    return _erro(422, exc.detail)


# O último middleware registrado é o mais externo: a correlação envolve todos os outros.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,  # o token vai no cabeçalho, não em cookie
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CorrelationIdMiddleware)

app.include_router(catalogo_router)
app.include_router(estoque_router)
app.include_router(execucao_router)


@app.get("/health", tags=["Sistema"], summary="Liveness")
def health():
    """Sem I/O: uma queda do banco não deve fazer o Kubernetes reiniciar pods saudáveis."""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/health/ready", tags=["Sistema"], summary="Readiness")
def health_ready(db: Session = Depends(get_db)):
    """Confere o banco; sem ele o pod sai do balanceamento, mas segue vivo."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logging.getLogger("oficina.health").error("Readiness falhou: banco inacessível", exc_info=exc)
        return JSONResponse(status_code=503, content={
            "status": "degradado", "banco": "inacessivel", "correlation_id": obter_correlation_id(),
        })
    return {"status": "ok", "banco": "ok", "version": "1.0.0"}
