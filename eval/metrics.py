"""
Métricas de evaluación para LTM Analyzer.
Todas las funciones son puras (sin efectos secundarios) y retornan dicts con 'score' (0.0-1.0).
"""
from __future__ import annotations
import re
from typing import Any


# ── Orden de niveles de riesgo ────────────────────────────────────────────────
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def risk_level_accuracy(predicted: str | None, expected: str) -> dict:
    """
    Compara el nivel de riesgo predicho con el esperado.
    - Coincidencia exacta:  1.0
    - Un nivel de distancia: 0.5
    - Más de un nivel:       0.0
    """
    if predicted is None:
        return {"score": 0.0, "predicted": None, "expected": expected, "exact": False}

    predicted = str(predicted).lower().strip()
    expected  = str(expected).lower().strip()

    if predicted == expected:
        return {"score": 1.0, "predicted": predicted, "expected": expected, "exact": True}

    p_idx = _RISK_ORDER.get(predicted, -99)
    e_idx = _RISK_ORDER.get(expected, -99)
    distance = abs(p_idx - e_idx)
    score = 0.5 if distance == 1 else 0.0

    return {"score": score, "predicted": predicted, "expected": expected, "exact": False, "distance": distance}


def json_validity(risk_data: Any, required_fields: list[str] | None = None) -> dict:
    """
    Verifica que risk_data sea un dict válido con todos los campos requeridos.
    También valida tipos internos (clauses debe ser lista).
    """
    required_fields = required_fields or [
        "service_name", "risk_level_overall",
        "risk_summary", "clauses", "quick_verdict"
    ]

    if risk_data is None:
        return {
            "score": 0.0, "valid": False,
            "missing_fields": required_fields,
            "clause_count": 0, "issues": ["risk_data es None"]
        }

    issues = []
    missing = [f for f in required_fields if f not in risk_data]

    if "clauses" in risk_data:
        if not isinstance(risk_data["clauses"], list):
            issues.append("'clauses' no es una lista")
        else:
            for i, c in enumerate(risk_data["clauses"]):
                for key in ("title", "level", "explanation"):
                    if key not in c:
                        issues.append(f"clauses[{i}] falta '{key}'")

    if "risk_summary" in risk_data and isinstance(risk_data["risk_summary"], dict):
        for lvl in ("critical", "high", "medium", "low"):
            if lvl not in risk_data["risk_summary"]:
                issues.append(f"risk_summary falta '{lvl}'")

    total_checks = len(required_fields) + len(issues)
    score = max(0.0, (len(required_fields) - len(missing)) / len(required_fields)) if required_fields else 1.0
    if issues:
        score *= 0.85  # penalización por issues de tipo

    return {
        "score": round(score, 3),
        "valid": len(missing) == 0 and len(issues) == 0,
        "missing_fields": missing,
        "issues": issues,
        "clause_count": len(risk_data.get("clauses", [])) if isinstance(risk_data, dict) else 0
    }


def section_coverage(markdown: str, required_sections: list[str] | None = None) -> dict:
    """
    Verifica que el markdown del análisis contenga las secciones esperadas.
    Busca en los encabezados H2/H3.
    """
    required_sections = required_sections or [
        "resumen ejecutivo",
        "recomendaciones",
        "jurisdicción",
    ]

    headers_raw = re.findall(r"#{1,3}\s+(.+)", markdown, re.IGNORECASE)
    headers = [h.lower().strip() for h in headers_raw]

    found, missing = [], []
    for section in required_sections:
        section_lower = section.lower()
        if any(section_lower in h for h in headers):
            found.append(section)
        else:
            missing.append(section)

    score = len(found) / len(required_sections) if required_sections else 1.0
    return {
        "score": round(score, 3),
        "found": found,
        "missing": missing,
        "headers_detected": headers_raw[:10]
    }


def clause_detection(risk_data: Any, expected_clauses: list[dict]) -> dict:
    """
    Verifica si el modelo detectó las cláusulas esperadas y si las clasificó bien.

    expected_clauses: lista de {"keyword": str, "level": str (opcional)}
    Retorna detection_rate y level_accuracy por separado.
    """
    if not expected_clauses:
        return {"score": 1.0, "detection_rate": 1.0, "level_accuracy": 1.0, "details": []}

    if not risk_data or not isinstance(risk_data.get("clauses"), list):
        details = [{"keyword": e["keyword"], "detected": False, "actual_level": None} for e in expected_clauses]
        return {"score": 0.0, "detection_rate": 0.0, "level_accuracy": 0.0, "details": details}

    actual_clauses = risk_data["clauses"]

    details = []
    detected_count = 0
    level_correct_count = 0
    level_checkable = 0

    for expected in expected_clauses:
        keyword = expected["keyword"].lower()
        exp_level = expected.get("level", "").lower()

        found_clause = None
        for c in actual_clauses:
            clause_blob = " ".join([
                str(c.get("title", "")),
                str(c.get("excerpt", "")),
                str(c.get("explanation", "")),
            ]).lower()
            if keyword in clause_blob:
                found_clause = c
                break

        detected = found_clause is not None
        if detected:
            detected_count += 1

        actual_level = found_clause.get("level", "").lower() if found_clause else None
        level_match = None
        if exp_level and detected:
            level_checkable += 1
            level_match = actual_level == exp_level
            if level_match:
                level_correct_count += 1

        details.append({
            "keyword": keyword,
            "expected_level": exp_level or "—",
            "detected": detected,
            "actual_level": actual_level,
            "level_match": level_match,
        })

    n = len(expected_clauses)
    detection_rate = detected_count / n
    level_accuracy = level_correct_count / level_checkable if level_checkable > 0 else None
    score = detection_rate * (0.7 + 0.3 * (level_accuracy or 0.0))

    return {
        "score": round(score, 3),
        "detection_rate": round(detection_rate, 3),
        "level_accuracy": round(level_accuracy, 3) if level_accuracy is not None else None,
        "details": details
    }


def keyword_coverage(response: str, expected_keywords: list[str]) -> dict:
    """
    Fracción de palabras clave esperadas que aparecen en la respuesta.
    Útil para validar respuestas de Q&A sin LLM-judge.
    """
    if not expected_keywords:
        return {"score": 1.0, "found": [], "missing": []}

    response_lower = response.lower()
    found   = [kw for kw in expected_keywords if kw.lower() in response_lower]
    missing = [kw for kw in expected_keywords if kw.lower() not in response_lower]

    return {
        "score": round(len(found) / len(expected_keywords), 3),
        "found": found,
        "missing": missing
    }


def aggregate(results: list[dict]) -> dict:
    """
    Agrega una lista de resultados individuales en un resumen global.
    Cada resultado debe tener al menos 'score' (0.0-1.0).
    """
    if not results:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "count": 0, "pass_rate": 0.0}

    scores = [r.get("score", 0.0) for r in results]
    passed = sum(1 for s in scores if s >= 0.7)

    return {
        "mean":      round(sum(scores) / len(scores), 3),
        "min":       round(min(scores), 3),
        "max":       round(max(scores), 3),
        "count":     len(scores),
        "pass_rate": round(passed / len(scores), 3),
    }
