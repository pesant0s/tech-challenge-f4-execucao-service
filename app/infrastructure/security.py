from dataclasses import dataclass
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from app.infrastructure.config import settings

# O token é emitido pelo OS Service (e pela Lambda, para clientes) com a mesma SECRET_KEY; aqui só se
# confere a assinatura e os claims, sem banco de usuários.
bearer_funcionario = HTTPBearer(scheme_name="TokenFuncionario", description="Token de funcionário, obtido em POST /auth/token do OS Service", auto_error=False)

PAPEIS = ("ADMIN", "ATENDENTE")


@dataclass(frozen=True)
class Funcionario:
    username: str
    role: str


def _credenciais_invalidas() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas ou token expirado",
                         {"WWW-Authenticate": "Bearer"})


def get_current_user(credenciais: HTTPAuthorizationCredentials | None = Depends(bearer_funcionario)) -> Funcionario:
    """Token de cliente é reconhecido e recusado com 403; ausente, inválido ou sem os claims esperados, 401."""
    if credenciais is None:
        raise _credenciais_invalidas()
    try:
        claims = jwt.decode(credenciais.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        raise _credenciais_invalidas()
    if claims.get("tipo") == "cliente":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token de cliente não dá acesso às rotas da oficina")
    if claims.get("tipo") != "usuario" or not claims.get("sub") or claims.get("role") not in PAPEIS:
        raise _credenciais_invalidas()
    return Funcionario(username=claims["sub"], role=claims["role"])


def require_admin(current_user: Funcionario = Depends(get_current_user)) -> Funcionario:
    if current_user.role != "ADMIN":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito a administradores")
    return current_user
