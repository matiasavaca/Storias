from __future__ import annotations
from pydantic import BaseModel, EmailStr
from typing import Literal


class Employee(BaseModel):
    """Empleado de agencia — accede al panel de gestión."""
    id: str
    email: EmailStr
    name: str
    agency_id: str
    role: Literal["employee", "admin"]
    team_id: str | None = None


class ClientUser(BaseModel):
    """Cliente final — accede a su portal o aprueba por link."""
    id: str
    client_id: str
    agency_id: str
