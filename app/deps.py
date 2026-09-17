"""
Dependencias de FastAPI (inyección en los endpoints).

Uso típico:
    @router.get("/portal")
    async def portal(user: Employee = Depends(require_employee)):
        ...
"""
from __future__ import annotations
from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from app.config import get_settings
from app.models.user import Employee, ClientUser

_bearer = HTTPBearer(auto_error=False)


def _decode_token(token: str) -> dict:
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key, algorithms=["HS256"])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def _get_token_from_request(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """
    Busca el JWT en:
    1. Header Authorization: Bearer <token>
    2. Cookie 'session'  (para el portal web)
    """
    if creds:
        return creds.credentials
    cookie = request.cookies.get("session")
    if cookie:
        return cookie
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_employee(
    token: Annotated[str, Depends(_get_token_from_request)],
) -> Employee:
    """
    Verifica que el request viene de un empleado de agencia autenticado.
    Inyectar en cualquier endpoint del panel de empleados.
    """
    payload = _decode_token(token)
    if payload.get("role") not in ("employee", "admin"):
        raise HTTPException(status_code=403, detail="Acceso restringido a empleados")
    return Employee(
        id=payload["sub"],
        email=payload["email"],
        name=payload.get("name", ""),
        agency_id=payload["agency_id"],
        role=payload["role"],
        team_id=payload.get("team_id"),
    )


async def require_admin(
    employee: Annotated[Employee, Depends(require_employee)],
) -> Employee:
    """Solo admins de agencia."""
    if employee.role != "admin":
        raise HTTPException(status_code=403, detail="Se requiere rol admin")
    return employee


async def require_client(
    token: Annotated[str, Depends(_get_token_from_request)],
) -> ClientUser:
    """
    Verifica que el request viene de un cliente final autenticado.
    Inyectar en los endpoints del portal del cliente (opción 1).
    """
    payload = _decode_token(token)
    if payload.get("role") != "client":
        raise HTTPException(status_code=403, detail="Acceso restringido a clientes")
    return ClientUser(
        id=payload["sub"],
        client_id=payload["client_id"],
        agency_id=payload["agency_id"],
    )


# Tipos anotados para usar en los endpoints
EmployeeDep = Annotated[Employee, Depends(require_employee)]
AdminDep = Annotated[Employee, Depends(require_admin)]
ClientDep = Annotated[ClientUser, Depends(require_client)]
