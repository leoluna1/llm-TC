"""
Tests de integración básicos para LTM Analyzer API.

Uso:
    cd proyecto_tesis
    pytest tests/ -v
"""
import io
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_txt_file(content: str = "Términos y condiciones de prueba. El usuario acepta todo.") -> tuple:
    """Devuelve (filename, file-like, content-type) para subir como TXT."""
    return ("test.txt", io.BytesIO(content.encode()), "text/plain")


def _upload_doc(content: str = "Prueba de términos de servicio.") -> str:
    """Sube un documento y devuelve el session_id."""
    fname, fbytes, ftype = _make_txt_file(content)
    resp = client.post(
        "/api/upload",
        files={"file": (fname, fbytes, ftype)},
        data={"analyze": "false"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"]
    return data["document_id"]


# ── Health ────────────────────────────────────────────────────────────────────

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── Upload ────────────────────────────────────────────────────────────────────

def test_upload_txt_success():
    fname, fbytes, ftype = _make_txt_file()
    resp = client.post(
        "/api/upload",
        files={"file": (fname, fbytes, ftype)},
        data={"analyze": "false"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "document_id" in data


def test_upload_invalid_extension():
    resp = client.post(
        "/api/upload",
        files={"file": ("malware.exe", io.BytesIO(b"MZ"), "application/octet-stream")},
        data={"analyze": "false"},
    )
    assert resp.status_code == 415
    assert "Formato no soportado" in resp.json()["detail"]


def test_upload_no_file():
    resp = client.post("/api/upload", data={"analyze": "false"})
    assert resp.status_code == 422  # Validation error — missing file field


# ── Document ──────────────────────────────────────────────────────────────────

def test_get_document_not_found():
    resp = client.get("/api/document/nonexistent-session-id")
    assert resp.status_code == 404


def test_get_document_pending_analysis():
    sid = _upload_doc()
    resp = client.get(f"/api/document/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    # Analysis not ready yet (background task didn't run in tests)
    assert data["summary"] is not None


# ── Chat ──────────────────────────────────────────────────────────────────────

def test_get_chat_history_not_found():
    resp = client.get("/api/chat/nonexistent-id")
    assert resp.status_code == 404


def test_get_chat_history_empty():
    sid = _upload_doc()
    resp = client.get(f"/api/chat/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["messages"], list)


# ── History ───────────────────────────────────────────────────────────────────

def test_get_history_returns_list():
    _upload_doc()  # Ensure at least one session exists
    resp = client.get("/api/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert isinstance(data["history"], list)


# ── Export ────────────────────────────────────────────────────────────────────

def test_export_not_found():
    resp = client.get("/api/export/nonexistent-id")
    assert resp.status_code == 404


def test_export_returns_html():
    sid = _upload_doc()
    resp = client.get(f"/api/export/{sid}")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert b"LTM" in resp.content


# ── Session delete ────────────────────────────────────────────────────────────

def test_delete_session_success():
    sid = _upload_doc()
    resp = client.delete(f"/api/session/{sid}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # Session no longer exists
    resp2 = client.get(f"/api/document/{sid}")
    assert resp2.status_code == 404


def test_delete_session_not_found():
    resp = client.delete("/api/session/nonexistent-id")
    assert resp.status_code == 404


# ── Cache ─────────────────────────────────────────────────────────────────────

def test_cache_stats():
    resp = client.get("/api/cache/stats")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
