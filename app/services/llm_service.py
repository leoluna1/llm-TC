import anthropic
import hashlib
import json
import logging
import re
from typing import Dict, Any, AsyncGenerator
from app.config.settings import settings
from app.utils import simple_cache

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("llm_service")

MAX_CHARS = 150_000

# ── Prompt injection detection ────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    "ignore previous instructions", "ignore all previous", "disregard",
    "you are now", "act as if", "forget everything", "new instructions",
    "system prompt", "override instructions", "jailbreak", "do anything now",
    "ignore your training",
]

def _has_injection(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _INJECTION_PATTERNS)


# ── System prompts ────────────────────────────────────────────────────────────

SYSTEM_ANALYZE = (
    "Sos un experto en derecho tecnológico especializado en analizar términos y condiciones "
    "de software y servicios digitales. Identificás riesgos reales para el usuario final con "
    "lenguaje claro, directo y en español latinoamericano."
)

ANALYZE_TASK = """Analizá el documento anterior e identificá riesgos para el usuario final.

Respondé en DOS partes separadas por el delimitador exacto "---RISK_JSON---":

PARTE 1 — Reporte en Markdown con esta estructura:

# Análisis: [nombre inferido del servicio]

## Resumen ejecutivo
[2-3 párrafos. Qué es el servicio, a qué te comprometés al aceptar, evaluación general de riesgo]

## Hallazgos críticos
[Solo si hay cláusulas que eliminan derechos fundamentales. Si no hay, omitir esta sección.]

## Hallazgos de riesgo alto
[Arbitraje obligatorio, limitación total de responsabilidad, cambios sin notificación, etc.]

## Hallazgos de riesgo medio
[Recopilación de datos, compartir con terceros, terminación unilateral]

## Hallazgos de bajo riesgo
[Cláusulas estándar que vale la pena mencionar]

## Jurisdicción y ley aplicable
[Qué ley rige el contrato y dónde se dirimen disputas]

## Recomendaciones
[3-5 consejos concretos antes de aceptar]

---RISK_JSON---

{"service_name": "nombre del servicio o app", "risk_level_overall": "critical|high|medium|low", "risk_summary": {"critical": 0, "high": 0, "medium": 0, "low": 0}, "clauses": [{"title": "Título breve de la cláusula", "level": "critical|high|medium|low", "excerpt": "Cita textual breve o paráfrasis", "explanation": "Por qué es un riesgo en 1-2 oraciones"}], "jurisdiction": "país o estado aplicable", "quick_verdict": "Una oración que resume si es seguro aceptar o no"}"""

SYSTEM_QUESTION = (
    "Sos un experto en derecho tecnológico. Respondés preguntas sobre documentos legales "
    "basándote ÚNICAMENTE en el contenido del documento provisto. Sos claro, directo y "
    "usás español latinoamericano sin jerga legal innecesaria."
)

QUESTION_TASK = (
    "PREGUNTA: {question}\n\n"
    "Respondé de forma clara y directa. Si la información no está en el documento, indicalo "
    "explícitamente. Citá secciones relevantes cuando sea posible usando blockquotes (> texto)."
)

SYSTEM_SIMPLIFY = (
    "Sos un experto en simplificar documentos legales para el público general. Tu objetivo es "
    "hacer el contenido accesible para alguien sin formación legal, usando español latinoamericano claro."
)

SIMPLIFY_TASK = """Convertí el documento anterior en un resumen comprensible. Usá esta estructura en Markdown:

# Resumen simplificado

## En pocas palabras
[2-3 oraciones que explican qué es el servicio y qué implica aceptar]

## Lo que podés hacer
[Lista concreta de derechos y permisos del usuario]

## Lo que no podés hacer
[Restricciones importantes, claramente explicadas]

## Qué datos recopilan sobre vos
[Privacidad y datos personales en lenguaje claro]

## Cuándo pueden cerrar tu cuenta
[Causales de suspensión o terminación]

## Lo más importante antes de aceptar
[3-5 puntos clave. Sé directo: si hay algo preocupante, decilo]"""


class LLMService:
    def __init__(self):
        self.client       = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.async_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model        = settings.ANTHROPIC_MODEL
        self.max_tokens   = settings.MODEL_MAX_TOKENS
        self.enable_cache = settings.ENABLE_CACHE
        # Anthropic prompt caching beta header
        self._beta_headers = {"anthropic-beta": "prompt-caching-2024-07-31"}
        logger.info(f"LLMService — modelo: {self.model}, max_tokens: {self.max_tokens}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cache_key(self, prefix: str, text: str) -> str:
        return f"{prefix}_{hashlib.md5(text.encode()).hexdigest()}"

    def _truncate(self, text: str) -> str:
        if len(text) <= MAX_CHARS:
            return text
        half = MAX_CHARS // 2
        return text[:half] + "\n\n[... documento truncado por longitud ...]\n\n" + text[-half:]

    def _doc_block(self, document_text: str) -> dict:
        """Bloque del documento con Anthropic Prompt Caching activado.
        El documento se cachea en la infraestructura de Anthropic por 5 minutos,
        reduciendo costos hasta un 90% en preguntas repetidas sobre el mismo documento."""
        return {
            "type": "text",
            "text": f"DOCUMENTO:\n\n{self._truncate(document_text)}",
            "cache_control": {"type": "ephemeral"},
        }

    def _log_usage(self, usage) -> None:
        if not usage:
            return
        input_t  = getattr(usage, "input_tokens", 0)
        output_t = getattr(usage, "output_tokens", 0)
        cached_r = getattr(usage, "cache_read_input_tokens", 0)
        cached_c = getattr(usage, "cache_creation_input_tokens", 0)
        savings  = f" | ahorro aprox: {cached_r * 0.9:.0f} tokens" if cached_r > 0 else ""
        logger.info(
            f"Tokens — entrada: {input_t}, salida: {output_t}, "
            f"cache_leído: {cached_r}, cache_creado: {cached_c}{savings}"
        )

    def _parse_structured_response(self, raw: str) -> Dict[str, Any]:
        delimiter = "---RISK_JSON---"
        if delimiter not in raw:
            return {"markdown": raw, "risk_data": None}
        parts = raw.split(delimiter, 1)
        markdown_part = parts[0].strip()
        json_part = parts[1].strip()
        json_clean = re.sub(r"^```(?:json)?\s*", "", json_part)
        json_clean = re.sub(r"\s*```$", "", json_clean).strip()
        try:
            risk_data = json.loads(json_clean)
        except json.JSONDecodeError as e:
            logger.warning(f"No se pudo parsear el JSON de riesgo: {e}")
            risk_data = None
        return {"markdown": markdown_part, "risk_data": risk_data}

    # ── Public methods ────────────────────────────────────────────────────────

    def analyze_document(self, document_text: str) -> Dict[str, Any]:
        """Análisis completo con prompt caching y caché local de resultados."""
        key = self._cache_key("analyze_v3", document_text)
        if self.enable_cache:
            cached = simple_cache.get_from_cache(key)
            if cached:
                logger.info("Análisis obtenido desde caché local")
                return {
                    "success": True,
                    "content": cached.get("content", ""),
                    "risk_data": cached.get("risk_data"),
                }

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_ANALYZE,
                messages=[{
                    "role": "user",
                    "content": [
                        self._doc_block(document_text),
                        {"type": "text", "text": ANALYZE_TASK},
                    ],
                }],
                extra_headers=self._beta_headers,
            )
            self._log_usage(msg.usage)
        except Exception as e:
            logger.error(f"Error en análisis: {e}")
            return {"success": False, "message": str(e)}

        parsed = self._parse_structured_response(msg.content[0].text)

        if self.enable_cache:
            simple_cache.save_to_cache(key, {
                "content": parsed["markdown"],
                "risk_data": parsed["risk_data"],
            })

        return {
            "success": True,
            "content": parsed["markdown"],
            "risk_data": parsed["risk_data"],
        }

    def answer_question(self, document_text: str, question: str) -> Dict[str, Any]:
        """Responde preguntas con prompt caching sobre el documento."""
        if _has_injection(question):
            logger.warning(f"Posible prompt injection detectado: {question[:80]}")
            return {"success": False, "message": "La pregunta contiene patrones no permitidos."}

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_QUESTION,
                messages=[{
                    "role": "user",
                    "content": [
                        self._doc_block(document_text),
                        {"type": "text", "text": QUESTION_TASK.format(question=question)},
                    ],
                }],
                extra_headers=self._beta_headers,
            )
            self._log_usage(msg.usage)
            return {"success": True, "content": msg.content[0].text}
        except Exception as e:
            logger.error(f"Error en pregunta: {e}")
            return {"success": False, "message": str(e)}

    async def stream_question(
        self, document_text: str, question: str
    ) -> AsyncGenerator[str, None]:
        """Stream de tokens con prompt caching y detección de injection."""
        if _has_injection(question):
            logger.warning(f"Prompt injection detectado en stream: {question[:80]}")
            yield "Lo siento, esa pregunta no puede procesarse."
            return

        try:
            async with self.async_client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_QUESTION,
                messages=[{
                    "role": "user",
                    "content": [
                        self._doc_block(document_text),
                        {"type": "text", "text": QUESTION_TASK.format(question=question)},
                    ],
                }],
                extra_headers=self._beta_headers,
            ) as stream:
                async for token in stream.text_stream:
                    yield token
                final = await stream.get_final_message()
                self._log_usage(final.usage)
        except Exception as e:
            logger.error(f"Error en streaming: {e}")
            yield "\n\n[Error al generar la respuesta. Intentá de nuevo.]"

    def generate_simplified_version(self, document_text: str) -> Dict[str, Any]:
        """Versión simplificada con prompt caching y caché local."""
        key = self._cache_key("simplified_v3", document_text)
        if self.enable_cache:
            cached = simple_cache.get_from_cache(key)
            if cached:
                logger.info("Versión simplificada obtenida desde caché local")
                return {"success": True, "content": cached.get("content", "")}

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_SIMPLIFY,
                messages=[{
                    "role": "user",
                    "content": [
                        self._doc_block(document_text),
                        {"type": "text", "text": SIMPLIFY_TASK},
                    ],
                }],
                extra_headers=self._beta_headers,
            )
            self._log_usage(msg.usage)
            content = msg.content[0].text
            if self.enable_cache:
                simple_cache.save_to_cache(key, {"content": content})
            return {"success": True, "content": content}
        except Exception as e:
            logger.error(f"Error en simplificación: {e}")
            return {"success": False, "message": str(e)}


    def compare_documents(self, text_a: str, name_a: str,
                          text_b: str, name_b: str) -> Dict[str, Any]:
        """Compara dos documentos legales e identifica diferencias clave."""
        max_each = MAX_CHARS // 3
        ta = text_a[:max_each] if len(text_a) > max_each else text_a
        tb = text_b[:max_each] if len(text_b) > max_each else text_b

        prompt = (
            f"Sos un experto en derecho tecnológico. Comparás dos documentos legales.\n\n"
            f"DOCUMENTO A — {name_a}:\n{ta}\n\n"
            f"---\n\n"
            f"DOCUMENTO B — {name_b}:\n{tb}\n\n"
            f"---\n\n"
            f"Generá un análisis comparativo en Markdown:\n\n"
            f"# Comparación: {name_a} vs {name_b}\n\n"
            f"## Resumen comparativo\n"
            f"[2-3 párrafos sobre riesgo general de cada uno]\n\n"
            f"## Ventajas de {name_a} para el usuario\n\n"
            f"## Ventajas de {name_b} para el usuario\n\n"
            f"## Diferencias críticas\n"
            f"[Las diferencias más importantes]\n\n"
            f"## Tabla comparativa\n"
            f"| Aspecto | {name_a} | {name_b} |\n"
            f"|---------|---------|----------|\n"
            f"| Jurisdicción | ... | ... |\n"
            f"| Arbitraje | ... | ... |\n"
            f"| Datos personales | ... | ... |\n"
            f"| Modificaciones | ... | ... |\n"
            f"| Terminación | ... | ... |\n\n"
            f"## Veredicto final\n"
            f"[¿Cuál es más favorable para el usuario y por qué?]"
        )
        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            self._log_usage(msg.usage)
            return {"success": True, "content": msg.content[0].text}
        except Exception as e:
            logger.error(f"Error en comparación: {e}")
            return {"success": False, "message": str(e)}


llm_service = LLMService()
