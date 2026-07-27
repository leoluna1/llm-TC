"""
LLM-as-Judge usando Claude Haiku para evaluar calidad de respuestas.
Usa temperatura 0 para resultados reproducibles.
"""
from __future__ import annotations
import json
import logging
import sys
import os

logger = logging.getLogger("eval.judge")

# ── Importar cliente Anthropic desde el proyecto ──────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from app.config.settings import settings
    _API_KEY = settings.ANTHROPIC_API_KEY
except Exception:
    _API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

try:
    import anthropic as _anthropic_module
    _client = _anthropic_module.Anthropic(api_key=_API_KEY) if _API_KEY else None
except ImportError:
    _client = None

JUDGE_MODEL = "claude-haiku-4-5-20251001"


def _smart_excerpt(document_text: str, query_keywords: list[str], max_chars: int = 2000) -> str:
    """
    Extrae un fragmento del documento que contenga las palabras clave relevantes.
    Evita devolver solo la introducción o el índice de documentos largos.
    """
    if len(document_text) <= max_chars:
        return document_text

    doc_lower = document_text.lower()
    best_pos = 0
    best_hits = 0

    # Buscar la ventana con más keywords
    step = max_chars // 2
    for start in range(0, min(len(document_text) - max_chars, 80_000), step):
        window = doc_lower[start:start + max_chars]
        hits = sum(1 for kw in query_keywords if kw.lower() in window)
        if hits > best_hits:
            best_hits = hits
            best_pos = start

    # Si no encontramos nada relevante, tomar el tercio medio del documento
    if best_hits == 0:
        mid = len(document_text) // 3
        best_pos = mid

    excerpt = document_text[best_pos:best_pos + max_chars]
    prefix = f"[...extracto desde posición {best_pos}...]\n" if best_pos > 0 else ""
    return prefix + excerpt


def _call_judge(prompt: str, max_tokens: int = 512) -> str | None:
    if _client is None:
        logger.error("Cliente Anthropic no disponible para LLM-judge")
        return None
    try:
        msg = _client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.error(f"LLM-judge error: {e}")
        return None


def _parse_json_response(raw: str | None) -> dict | None:
    if not raw:
        return None
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Intentar extraer el primer bloque JSON
        match = __import__("re").search(r"\{.*\}", clean, __import__("re").DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return None


# ── Jueces públicos ───────────────────────────────────────────────────────────

def judge_qa_relevance(
    question: str,
    response: str,
    document_text: str,
    max_excerpt: int = 2000,
) -> dict:
    """
    Evalúa la calidad de una respuesta de Q&A sobre un documento legal.
    Retorna dict con scores 1-5 para 4 dimensiones y un promedio.
    """
    # Extraer fragmento del documento relevante para la pregunta
    question_keywords = [w for w in question.lower().split() if len(w) > 4]
    document_excerpt = _smart_excerpt(document_text, question_keywords, max_excerpt)

    prompt = f"""Sos un evaluador experto en calidad de sistemas de análisis legal.
Evaluá la respuesta del sistema a esta pregunta sobre el documento.

PREGUNTA DEL USUARIO:
{question}

FRAGMENTO DEL DOCUMENTO (contexto relevante):
{document_excerpt}

RESPUESTA DEL SISTEMA:
{response[:1500]}

Evaluá en JSON usando escala 1-5 (1=muy malo, 5=excelente):
{{
  "relevancia": <¿responde concretamente la pregunta?>,
  "precision": <¿la información es correcta según el documento?>,
  "claridad": <¿es fácil de entender para alguien sin formación legal?>,
  "fundamento": <¿se basa en el documento o inventa información?>,
  "promedio": <promedio decimal de los 4>,
  "razonamiento": "<una oración explicando el puntaje>"
}}

Respondé SOLO con el JSON, sin texto extra."""

    raw = _call_judge(prompt)
    result = _parse_json_response(raw)

    if result is None:
        return {
            "relevancia": 0, "precision": 0, "claridad": 0, "fundamento": 0,
            "promedio": 0.0, "razonamiento": "No se pudo obtener evaluación",
            "score": 0.0, "error": True
        }

    promedio = result.get("promedio", 0.0)
    result["score"] = round(float(promedio) / 5.0, 3)  # normalizar a 0-1
    result["error"] = False
    return result


def judge_analysis_quality(
    analysis_markdown: str,
    risk_data: dict | None,
    document_text: str,
    max_excerpt: int = 2000,
) -> dict:
    """
    Evalúa la calidad del análisis completo de un documento legal.
    """
    risk_summary = ""
    if risk_data:
        risk_summary = (
            f"\nRiesgo general: {risk_data.get('risk_level_overall', '?')}\n"
            f"Cláusulas detectadas: {len(risk_data.get('clauses', []))}\n"
            f"Veredicto rápido: {risk_data.get('quick_verdict', '?')}"
        )

    # Extracto inteligente: buscar secciones de riesgo/términos
    analysis_keywords = ["riesgo", "cláusula", "datos", "arbitraje", "responsabilidad", "terminaci"]
    document_excerpt = _smart_excerpt(document_text, analysis_keywords, max_excerpt)

    prompt = f"""Sos un evaluador experto en calidad de sistemas de análisis legal con IA.

FRAGMENTO DEL DOCUMENTO ANALIZADO:
{document_excerpt}

ANÁLISIS GENERADO POR EL SISTEMA:
{analysis_markdown[:3000]}
{risk_summary}

Evaluá en JSON usando escala 1-5 (1=muy malo, 5=excelente):
{{
  "completitud": <¿cubre todos los aspectos importantes del documento?>,
  "precision": <¿las observaciones son correctas y fundadas?>,
  "utilidad": <¿es útil para alguien que debe decidir si aceptar el contrato?>,
  "coherencia": <¿el nivel de riesgo asignado es coherente con los hallazgos?>,
  "promedio": <promedio decimal>,
  "razonamiento": "<una oración explicando el puntaje>"
}}

Respondé SOLO con el JSON."""

    raw = _call_judge(prompt)
    result = _parse_json_response(raw)

    if result is None:
        return {
            "completitud": 0, "precision": 0, "utilidad": 0, "coherencia": 0,
            "promedio": 0.0, "razonamiento": "No se pudo obtener evaluación",
            "score": 0.0, "error": True
        }

    promedio = result.get("promedio", 0.0)
    result["score"] = round(float(promedio) / 5.0, 3)
    result["error"] = False
    return result


def judge_risk_justification(
    risk_level: str,
    clauses: list[dict],
    document_text: str,
    max_excerpt: int = 2000,
) -> dict:
    """
    Evalúa si el nivel de riesgo general está bien justificado por las cláusulas detectadas.
    """
    clauses_summary = "\n".join([
        f"- [{c.get('level', '?').upper()}] {c.get('title', '?')}: {c.get('explanation', '')[:100]}"
        for c in (clauses or [])[:10]
    ])

    risk_keywords = ["riesgo", "cláusula", "arbitraje", "responsabilidad", "datos", "terminaci"]
    document_excerpt = _smart_excerpt(document_text, risk_keywords, max_excerpt)

    prompt = f"""Evaluá si la clasificación de riesgo de este análisis legal está bien justificada.

FRAGMENTO DEL DOCUMENTO:
{document_excerpt}

NIVEL DE RIESGO ASIGNADO: {risk_level.upper()}

CLÁUSULAS DETECTADAS:
{clauses_summary or "(ninguna)"}

¿El nivel de riesgo general es coherente con las cláusulas detectadas y el contenido del documento?

Respondé en JSON:
{{
  "justificado": <true/false>,
  "confianza": <1-5, qué tan seguro estás>,
  "nivel_esperado": "<low|medium|high|critical según tu criterio>",
  "razonamiento": "<una oración>",
  "score": <0.0-1.0, donde 1.0 = perfectamente justificado>
}}"""

    raw = _call_judge(prompt)
    result = _parse_json_response(raw)

    if result is None:
        return {
            "justificado": False, "confianza": 0,
            "nivel_esperado": "?", "razonamiento": "Error en evaluación",
            "score": 0.0, "error": True
        }

    result.setdefault("score", 0.8 if result.get("justificado") else 0.2)
    result["error"] = False
    return result
