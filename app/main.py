"""
Storias — FastAPI app principal.

Seguridad aplicada por capas:
  1. HTTPS forzado en producción (TrustedHostMiddleware)
  2. CORS restringido a orígenes permitidos
  3. CSP + headers de seguridad en cada response
  4. Rate limiting global (slowapi)
  5. Session cookie httponly + secure
  6. JWT en cada endpoint protegido (ver deps.py)
  7. RLS en Supabase (cada usuario ve solo sus datos)
  8. API keys de clientes cifradas en DB (ver encryption.py)
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.routers import auth, aprobar, demo, portal

s = get_settings()


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"\n{'═'*50}")
    print(f"  Storias — {s.environment.upper()}")
    print(f"  http://localhost:5001")
    print(f"{'═'*50}\n")
    yield


# ── App ───────────────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{s.rate_limit_per_minute}/minute"])

app = FastAPI(
    title="Storias API",
    version="2.0.0",
    docs_url="/docs" if not s.is_production else None,   # Swagger off en prod
    redoc_url="/redoc" if not s.is_production else None,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Middlewares (orden importa) ────────────────────────────────────────────────

# 1. Hosts permitidos — previene host header injection
if s.is_production:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["storias.app", "*.storias.app"])

# 2. Sesiones firmadas (para el flujo OAuth)
app.add_middleware(SessionMiddleware, secret_key=s.secret_key, https_only=s.is_production, session_cookie="oauth_session")

# 3. CORS — solo orígenes explícitamente permitidos
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# 4. Security headers en cada response
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if s.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    elif request.url.path.startswith("/static/"):
        # In dev, portal.js/portal.html-adjacent assets change every few
        # minutes and are served fresh from disk with no cache-busted
        # filename — without this, browsers keep running a stale cached
        # copy after an edit and "nothing changed" even though it did.
        response.headers["Cache-Control"] = "no-store"
    return response


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(aprobar.router)
app.include_router(demo.router)
app.include_router(portal.router)

# Same-origin assets let the portal API receive the HTTP-only session cookie.
_STATIC_DIR = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Read-only exposure of the engine's bundled .ttf files so the portal can
# render each typography choice in its own font before an employee picks it.
# Serves the same files app.engine.imaging already uses server-side — this
# mount adds no new files and changes no engine behavior.
_ENGINE_FONTS_DIR = Path(__file__).parent / "engine" / "assets"
app.mount("/fonts", StaticFiles(directory=str(_ENGINE_FONTS_DIR)), name="engine-fonts")


# ── Páginas principales ───────────────────────────────────────────────────────
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _render_template(template_name: str, **ctx) -> str:
    """Mini-render de templates sin usar Jinja2Templates (evita bug de caché en starlette 1.x)."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)
    return env.get_template(template_name).render(**ctx)


@app.get("/")
async def landing(request: Request):
    # En dev redirigimos directo al portal para no tener que hacer login
    if not s.is_production:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/portal")
    from fastapi.responses import HTMLResponse
    html = _render_template("landing.html", logged_in=False)
    return HTMLResponse(html)


@app.get("/portal")
async def portal_page(request: Request):
    """Render the employee shell after validating the HTTP-only session."""
    from fastapi.responses import HTMLResponse, RedirectResponse
    from app.deps import _decode_token

    token = request.cookies.get("session")
    if not token:
        return RedirectResponse("/login")
    try:
        payload = _decode_token(token)
    except Exception:
        return RedirectResponse("/login")
    if payload.get("role") not in ("employee", "admin"):
        return RedirectResponse("/login")
    return HTMLResponse(_render_template("portal.html"))


@app.get("/login")
async def login_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/auth/google")


@app.get("/logout")
async def logout_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/auth/logout")


# ── Health check (para Railway / Render) ──────────────────────────────────────
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


# ── Dev runner ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=5001, reload=True)
