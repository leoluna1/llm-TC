import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pathlib import Path

from app.api.routes import router as api_router, document_sessions, chat_sessions, session_history
from app.services.db_service import db

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="LTM Analyzer",
    description="Análisis de Términos y Condiciones mediante IA — Proyecto de tesis UTN FICA",
    version="2.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static + templates ────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ── Routes ────────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """Carga sesiones persistidas desde SQLite al iniciar el servidor."""
    stored = db.load_all_sessions()
    document_sessions.update(stored)
    for sid in stored:
        msgs = db.load_messages(sid)
        chat_sessions[sid] = msgs
        if sid not in session_history:
            session_history.insert(0, sid)
    import logging
    logging.getLogger("startup").info(
        f"Sesiones restauradas desde DB: {len(stored)}"
    )

app.include_router(api_router, prefix="/api")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "LTM Analyzer", "version": "2.0.0"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="localhost", port=8000, reload=True)
