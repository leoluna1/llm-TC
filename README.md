# LTM Analyzer — Legal Terms Monitor

**Proyecto de tesis · UTN FICA · 2024**

Herramienta de análisis de términos y condiciones, contratos y políticas de privacidad usando Claude AI (Anthropic). Diseñada para abogados, estudiantes de derecho y usuarios finales que necesitan entender riesgos en documentos legales.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend | FastAPI + Python 3.13 |
| IA | Claude (Anthropic API) |
| Frontend | HTML/CSS/JS vanilla |
| Caché | Sistema de archivos local (JSON) |
| Servidor | Uvicorn |

---

## Arquitectura

```
proyecto_tesis/
├── app/
│   ├── api/
│   │   ├── models.py              # Modelos Pydantic (RiskData, Clause, etc.)
│   │   └── routes.py              # Endpoints REST
│   ├── config/
│   │   └── settings.py            # Variables de entorno y configuración
│   ├── services/
│   │   ├── document_processor.py  # Extracción de texto (PDF, DOCX, TXT)
│   │   └── llm_service.py         # Integración con Claude API
│   ├── static/
│   │   └── js/
│   │       ├── main.js            # Lógica principal (upload, análisis, export)
│   │       └── chat.js            # Interfaz de chat
│   ├── templates/
│   │   └── index.html             # SPA principal
│   └── main.py                    # App FastAPI + rate limiting
├── tests/
│   └── test_routes.py             # Tests de integración
├── uploads/                       # Archivos subidos (gitignored)
├── cache/                         # Caché de análisis (gitignored)
├── .env                           # Variables de entorno (no commitear)
└── requirements.txt
```

---

## Setup local

### 1. Clonar y crear entorno virtual

```bash
git clone <repo-url>
cd proyecto_tesis
python3 -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Variables de entorno

Crear `.env` en la raíz del proyecto:

```env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
LOG_LEVEL=INFO
```

> **Modelos recomendados:**
> - `claude-haiku-4-5-20251001` — rápido y económico (desarrollo)
> - `claude-sonnet-4-6` — mayor calidad de análisis (producción)

### 4. Ejecutar

```bash
python -m uvicorn app.main:app --reload --host localhost --port 8000
```

Abrí `http://localhost:8000`.

---

## API Reference

### `POST /api/upload`
Sube y analiza un documento.

**Body:** `multipart/form-data` — `file` (PDF/DOCX/TXT, máx. 50MB), `analyze` (bool)

**Response:**
```json
{ "success": true, "document_id": "uuid", "message": "..." }
```

---

### `GET /api/document/{session_id}`
Devuelve análisis completo + datos de riesgo estructurados.

```json
{
  "success": true,
  "summary": "# Análisis...",
  "risk_data": {
    "service_name": "Netflix",
    "risk_level_overall": "high",
    "risk_summary": { "critical": 0, "high": 3, "medium": 5, "low": 8 },
    "clauses": [
      {
        "title": "Arbitraje obligatorio",
        "level": "high",
        "excerpt": "Cualquier disputa se resolverá mediante arbitraje...",
        "explanation": "El usuario renuncia al derecho de litigar en tribunales."
      }
    ],
    "jurisdiction": "California, EE.UU.",
    "quick_verdict": "Aceptable con precauciones."
  }
}
```

---

### `POST /api/question`
Pregunta sobre el documento.

```json
{ "session_id": "uuid", "question": "¿Puedo cancelar en cualquier momento?" }
```

---

### `GET /api/simplify/{session_id}`
Versión simplificada del documento en lenguaje claro.

### `GET /api/export/{session_id}`
Reporte HTML imprimible (Ctrl+P → PDF).

### `GET /api/history`
Historial de sesiones recientes (máx. 20).

### `DELETE /api/session/{session_id}`
Elimina la sesión y el archivo del servidor.

### `GET /health`
Health check.

---

## Tests

```bash
source .venv/bin/activate
pip install pytest httpx
pytest tests/ -v
```

> Si el venv tiene paths de otra máquina, recrealo:
> `python3 -m venv .venv && pip install -r requirements.txt`

---

## Niveles de riesgo detectados

| Nivel | Ejemplos |
|-------|----------|
| **Crítico** | Cláusulas que eliminan derechos fundamentales |
| **Alto** | Arbitraje obligatorio, limitación total de responsabilidad |
| **Medio** | Recopilación de datos, compartir con terceros |
| **Bajo** | Cláusulas estándar de uso aceptable |

---

## Límites técnicos

- **Tamaño máximo:** 50MB por archivo
- **Formatos:** PDF, DOCX, DOC, TXT
- **Rate limiting:** 60 requests/minuto por IP
- **Caché:** 7 días para análisis de documentos idénticos
- **Contexto máximo:** 150.000 caracteres (~37k tokens); documentos más largos se truncan inteligentemente
- **Sesiones:** En memoria (se pierden al reiniciar). En producción usar Redis o SQLite.

---

## Autor

Proyecto de tesis — UTN FICA · 2024  
Powered by [Claude AI](https://anthropic.com) (Anthropic)
