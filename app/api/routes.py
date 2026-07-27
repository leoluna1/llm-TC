import asyncio
import os
import re
import uuid
import json
import mimetypes
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
import markdown as md_lib
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.background import BackgroundTasks
from typing import Dict, List, Optional, Any, AsyncGenerator

from app.api.models import (
    QuestionRequest, DocumentResponse, QuestionResponse,
    ChatMessage, RiskData, SessionHistoryItem, CompareRequest
)
from app.services.document_processor import document_processor
from app.services.llm_service import llm_service
from app.services.db_service import db
from app.config.settings import settings
from app.utils import simple_cache

router = APIRouter()

# ── In-memory stores ─────────────────────────────────────────────────────────
document_sessions: Dict[str, Dict[str, Any]] = {}
chat_sessions: Dict[str, List[Dict[str, Any]]] = {}
# Ordered list of session IDs for history (newest first)
session_history: List[str] = []

# ── Constants ─────────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
}
MAX_HISTORY = 20  # Keep last 20 sessions in history


# ── Helpers ──────────────────────────────────────────────────────────────────

def _validate_upload(file: UploadFile) -> None:
    """Validates file extension and content type. Raises HTTPException on failure."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Formato no soportado '{ext}'. Aceptamos: {', '.join(ALLOWED_EXTENSIONS)}",
        )
    # Check content-type header (best effort — not cryptographically verified)
    ct = file.content_type or ""
    # Some browsers send 'application/octet-stream' for binary files — allow it
    if ct and ct not in ALLOWED_MIME_TYPES and ct != "application/octet-stream":
        raise HTTPException(
            status_code=415,
            detail=f"Content-Type no permitido: {ct}",
        )


def _register_history(session_id: str) -> None:
    if session_id not in session_history:
        session_history.insert(0, session_id)
    if len(session_history) > MAX_HISTORY:
        old = session_history.pop()
        # Don't delete active sessions from memory, just remove from history list
        _ = old


def _risk_data_from_dict(d: Optional[dict]) -> Optional[RiskData]:
    if not d:
        return None
    try:
        return RiskData(**d)
    except Exception:
        return None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/analyze_text")
async def analyze_raw_text(
    background_tasks: BackgroundTasks,
    payload: dict,
):
    """Analiza texto plano directo — usado por la app de escritorio LTM Desktop."""
    text        = payload.get("text", "").strip()
    source_name = payload.get("source_name", "Instalador")

    if not text or len(text) < 100:
        raise HTTPException(status_code=400, detail="Texto demasiado corto para analizar")

    session_id = str(uuid.uuid4())
    document_sessions[session_id] = {
        "file_path": None,
        "file_name": source_name,
        "file_size": len(text.encode()),
        "document_text": text,
        "uploaded_at": datetime.now().isoformat(),
        "analysis": None,
        "risk_data": None,
        "source": "desktop",
    }
    chat_sessions[session_id] = []
    _register_history(session_id)
    db.save_session(session_id, document_sessions[session_id])
    background_tasks.add_task(_analyze_background, session_id)

    return {"success": True, "document_id": session_id,
            "message": "Análisis iniciado desde LTM Desktop"}


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    analyze: bool = Form(True),
):
    """Sube y opcionalmente analiza un documento de términos y condiciones."""
    _validate_upload(file)

    try:
        file_path = await document_processor.save_uploaded_file(file)
        session_id = str(uuid.uuid4())
        document_text = document_processor.extract_text_with_cache(file_path)

        document_sessions[session_id] = {
            "file_path": str(file_path),
            "file_name": file.filename,
            "file_size": os.path.getsize(file_path),
            "document_text": document_text,
            "uploaded_at": datetime.now().isoformat(),
            "analysis": None,
            "risk_data": None,
        }
        chat_sessions[session_id] = []
        _register_history(session_id)
        db.save_session(session_id, document_sessions[session_id])

        if analyze:
            background_tasks.add_task(_analyze_background, session_id)

        return DocumentResponse(
            success=True,
            message="Documento cargado. El análisis se está procesando.",
            document_id=session_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando el documento: {e}")


async def _analyze_background(session_id: str) -> None:
    if session_id not in document_sessions:
        return
    text = document_sessions[session_id]["document_text"]
    result = await asyncio.to_thread(llm_service.analyze_document, text)

    if result["success"]:
        document_sessions[session_id]["analysis"]  = result["content"]
        document_sessions[session_id]["risk_data"] = result.get("risk_data")
        rd = result.get("risk_data") or {}
        svc_name = rd.get("service_name")
        if svc_name:
            document_sessions[session_id]["service_name"] = svc_name
        db.update_analysis(session_id, result["content"], result.get("risk_data"), svc_name)
    else:
        document_sessions[session_id]["analysis_error"] = result.get("message", "Error desconocido")
        db.save_session(session_id, document_sessions[session_id])


@router.get("/document/{session_id}", response_model=DocumentResponse)
async def get_document_analysis(session_id: str):
    """Devuelve el análisis y los datos estructurados de riesgo."""
    if session_id not in document_sessions:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    session = document_sessions[session_id]
    raw_risk = session.get("risk_data")

    return DocumentResponse(
        success=True,
        document_id=session_id,
        summary=session.get("analysis") or "El análisis aún no está disponible",
        risk_data=_risk_data_from_dict(raw_risk) if raw_risk else None,
        message="OK",
    )


@router.post("/question", response_model=QuestionResponse)
async def ask_question(question_request: QuestionRequest):
    """Responde preguntas sobre el documento usando el historial de conversación."""
    sid = question_request.session_id
    if sid not in document_sessions:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    text = document_sessions[sid]["document_text"]
    ts_user = datetime.now().isoformat()
    chat_sessions[sid].append({"role": "user", "content": question_request.question, "timestamp": ts_user})
    db.save_message(sid, "user", question_request.question, ts_user)

    result = await asyncio.to_thread(llm_service.answer_question, text, question_request.question)
    if result["success"]:
        ts_ai = datetime.now().isoformat()
        chat_sessions[sid].append({"role": "assistant", "content": result["content"], "timestamp": ts_ai})
        db.save_message(sid, "assistant", result["content"], ts_ai)
        return QuestionResponse(success=True, question=question_request.question, answer=result["content"])

    return QuestionResponse(success=False, question=question_request.question,
                            message=result.get("message", "Error al generar respuesta"))


@router.get("/chat/{session_id}")
async def get_chat_history(session_id: str):
    if session_id not in chat_sessions:
        raise HTTPException(status_code=404, detail="Sesión de chat no encontrada")
    return {
        "success": True,
        "session_id": session_id,
        "messages": chat_sessions[session_id],
    }


@router.get("/stream_question")
async def stream_question_sse(request: Request, session_id: str, question: str):
    """Responde preguntas con streaming SSE — los tokens llegan en tiempo real."""
    if session_id not in document_sessions:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    text = document_sessions[session_id]["document_text"]
    ts_user = datetime.now().isoformat()
    chat_sessions[session_id].append({
        "role": "user",
        "content": question,
        "timestamp": ts_user,
    })
    db.save_message(session_id, "user", question, ts_user)

    collected: list[str] = []

    async def generate() -> AsyncGenerator[str, None]:
        try:
            async for token in llm_service.stream_question(text, question):
                if await request.is_disconnected():
                    break
                collected.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            if collected:
                ts_ai = datetime.now().isoformat()
                full = "".join(collected)
                chat_sessions[session_id].append({"role": "assistant", "content": full, "timestamp": ts_ai})
                db.save_message(session_id, "assistant", full, ts_ai)
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/simplify/{session_id}")
async def simplify_document(session_id: str):
    if session_id not in document_sessions:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    text = document_sessions[session_id]["document_text"]
    result = await asyncio.to_thread(llm_service.generate_simplified_version, text)
    if result["success"]:
        return {"success": True, "simplified_content": result["content"]}
    return {"success": False, "message": result.get("message", "Error al simplificar")}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    if session_id not in document_sessions:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    fp = document_sessions[session_id].get("file_path")
    if fp and os.path.exists(fp):
        try:
            os.remove(fp)
        except OSError:
            pass

    document_sessions.pop(session_id, None)
    chat_sessions.pop(session_id, None)
    if session_id in session_history:
        session_history.remove(session_id)
    db.delete_session(session_id)

    return {"success": True, "message": "Sesión eliminada correctamente"}


@router.get("/history")
async def get_history():
    """Devuelve el historial de sesiones desde la base de datos."""
    return {"success": True, "history": db.get_history(limit=20)}


@router.post("/compare")
async def compare_documents(req: CompareRequest):
    """Compara dos documentos legales e identifica diferencias clave."""
    for sid in (req.session_id_a, req.session_id_b):
        if sid not in document_sessions:
            raise HTTPException(status_code=404, detail=f"Sesión {sid} no encontrada")

    s_a = document_sessions[req.session_id_a]
    s_b = document_sessions[req.session_id_b]
    name_a = s_a.get("service_name") or s_a.get("file_name") or "Documento A"
    name_b = s_b.get("service_name") or s_b.get("file_name") or "Documento B"

    result = await asyncio.to_thread(
        llm_service.compare_documents,
        s_a["document_text"], name_a,
        s_b["document_text"], name_b,
    )
    if result["success"]:
        return {"success": True, "content": result["content"],
                "name_a": name_a, "name_b": name_b}
    raise HTTPException(status_code=500, detail=result.get("message", "Error en la comparación"))


@router.get("/export/{session_id}", response_class=HTMLResponse)
async def export_report(session_id: str):
    """Genera una página HTML imprimible del análisis (usá Ctrl+P para PDF)."""
    if session_id not in document_sessions:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    session = document_sessions[session_id]
    analysis = session.get("analysis", "")
    rd = session.get("risk_data") or {}
    file_name = session.get("file_name", "Documento")
    uploaded_at = session.get("uploaded_at", "")[:16].replace("T", " ")

    # Format risk summary chips
    rs = rd.get("risk_summary", {}) or {}
    chips_html = ""
    for level, label, color in [
        ("critical", "Crítico", "#dc2626"),
        ("high", "Alto", "#ea580c"),
        ("medium", "Medio", "#d97706"),
        ("low", "Bajo", "#16a34a"),
    ]:
        count = rs.get(level, 0)
        if count:
            chips_html += f'<span style="background:{color}15;color:{color};border:1px solid {color}40;padding:3px 10px;border-radius:4px;font-size:12px;font-weight:600;margin-right:8px">{count} {label}</span>'

    clauses_html = ""
    for c in (rd.get("clauses") or []):
        level_colors = {
            "critical": "#dc2626", "high": "#ea580c",
            "medium": "#d97706", "low": "#16a34a"
        }
        color = level_colors.get(c.get("level", "low"), "#6b7280")
        clauses_html += f"""
        <div style="border-left:3px solid {color};padding:10px 14px;margin:8px 0;background:{color}08;border-radius:0 6px 6px 0">
          <strong style="color:{color};font-size:11px;text-transform:uppercase;letter-spacing:.05em">{c.get('level','').upper()}</strong>
          <div style="font-weight:600;margin:4px 0 2px;color:#1c1917">{c.get('title','')}</div>
          <div style="font-size:13px;color:#5c5650;font-style:italic">"{c.get('excerpt','')}"</div>
          <div style="font-size:12px;color:#3f3a35;margin-top:4px">{c.get('explanation','')}</div>
        </div>"""

    rendered_analysis = md_lib.markdown(
        analysis or "",
        extensions=["tables", "fenced_code"],
    )

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>LTM — Reporte: {file_name}</title>
<style>
  body {{ font-family: 'Georgia', serif; max-width: 800px; margin: 40px auto; padding: 0 24px; color: #1c1917; line-height: 1.7; }}
  .header {{ border-bottom: 2px solid #0b1426; padding-bottom: 16px; margin-bottom: 24px; }}
  .ltm-brand {{ font-family: 'Georgia', serif; font-size: 22px; font-weight: 700; color: #0b1426; letter-spacing: .04em; }}
  .ltm-brand span {{ color: #d4a017; }}
  .doc-meta {{ font-size: 12px; color: #7e7870; margin-top: 4px; }}
  h1 {{ font-size: 22px; color: #0b1426; margin: 24px 0 8px; }}
  h2 {{ font-size: 14px; text-transform: uppercase; letter-spacing: .1em; color: #7e7870; margin: 28px 0 10px; border-bottom: 1px solid #e0dbd4; padding-bottom: 6px; }}
  h3 {{ font-size: 15px; font-weight: 700; color: #1c1917; margin: 16px 0 6px; }}
  p {{ margin: 0 0 12px; font-size: 14px; color: #3f3a35; }}
  li {{ font-size: 14px; color: #3f3a35; margin-bottom: 4px; }}
  blockquote {{ border-left: 3px solid #d4a017; padding: 8px 14px; background: #fdf6e3; margin: 12px 0; font-style: italic; color: #5c5650; }}
  strong {{ font-weight: 700; color: #1c1917; }}
  .verdict {{ background: #f2f0ec; border-radius: 6px; padding: 12px 16px; margin: 16px 0; font-weight: 600; font-size: 14px; }}
  .footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid #e0dbd4; font-size: 11px; color: #a39c93; text-align: center; }}
  @media print {{ body {{ margin: 20px; }} .no-print {{ display: none; }} }}
</style>
</head>
<body>
<div class="header">
  <div class="ltm-brand">LTM<span>.</span> Legal Terms Monitor</div>
  <div class="doc-meta">Reporte generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} · Documento: <strong>{file_name}</strong> · Analizado: {uploaded_at}</div>
</div>

<div class="no-print" style="background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:10px 14px;margin-bottom:20px;font-size:13px">
  <strong>Para exportar como PDF:</strong> Usá Ctrl+P (o Cmd+P en Mac) y seleccioná "Guardar como PDF".
</div>

{"<div style='margin-bottom:20px'>" + chips_html + "</div>" if chips_html else ""}
{"<div class='verdict'>🔍 " + rd.get("quick_verdict","") + "</div>" if rd.get("quick_verdict") else ""}

{"<h2>Cláusulas identificadas</h2>" + clauses_html if clauses_html else ""}

<h2>Análisis completo</h2>
{rendered_analysis}

<div class="footer">
  Generado por LTM Analyzer · Proyecto de tesis UTN FICA 2024 · Powered by Claude AI<br>
  Este reporte es informativo y no constituye asesoramiento legal profesional.
</div>
</body>
</html>"""

    return HTMLResponse(content=html)


# ── Cache endpoints ───────────────────────────────────────────────────────────

@router.get("/cache/stats")
async def get_cache_stats():
    return {"success": True, "stats": simple_cache.get_cache_stats()}


@router.delete("/cache/clear")
async def clear_cache(days: Optional[int] = None):
    deleted = simple_cache.clear_cache(days=days)
    return {"success": True, "message": f"Se eliminaron {deleted} archivos de caché", "deleted_count": deleted}


@router.post("/check_document")
async def check_document_in_cache(file: UploadFile = File(...)):
    try:
        temp_path = await document_processor.save_uploaded_file(file)
        doc_hash = document_processor.get_document_hash(temp_path)
        text_cached = simple_cache.get_from_cache(f"extract_text_{doc_hash}") is not None
        analysis_cached = simple_cache.get_from_cache(f"analyze_v2_{doc_hash}") is not None
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return {
            "success": True,
            "in_cache": text_cached or analysis_cached,
            "text_extracted": text_cached,
            "analysis_available": analysis_cached,
            "document_hash": doc_hash,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}
