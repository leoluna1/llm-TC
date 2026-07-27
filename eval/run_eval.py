#!/usr/bin/env python3
"""
Suite de evaluación para LTM Analyzer.

Uso:
    # Evaluar todos los casos del dataset:
    python3 eval/run_eval.py

    # Solo análisis, sin LLM-judge (más rápido y sin costo):
    python3 eval/run_eval.py --no-judge

    # Guardar reporte JSON:
    python3 eval/run_eval.py --output eval/results/reporte.json

    # Evaluar solo Q&A:
    python3 eval/run_eval.py --type qa

    # Ver ayuda:
    python3 eval/run_eval.py --help
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Agregar raíz del proyecto al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.metrics import (
    risk_level_accuracy, json_validity, section_coverage,
    clause_detection, keyword_coverage, aggregate,
)
from eval.judge import judge_qa_relevance, judge_analysis_quality, judge_risk_justification

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s"
)
logger = logging.getLogger("eval.runner")


# ── Colores ANSI ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BLUE   = "\033[94m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def color_score(score: float) -> str:
    """Colorea el score: verde ≥0.8, amarillo ≥0.6, rojo <0.6."""
    pct = f"{score*100:.1f}%"
    if score >= 0.8:
        return f"{GREEN}{pct}{RESET}"
    elif score >= 0.6:
        return f"{YELLOW}{pct}{RESET}"
    return f"{RED}{pct}{RESET}"

def fmt_5(score_or_none) -> str:
    if score_or_none is None:
        return f"{DIM}—{RESET}"
    s = float(score_or_none)
    pct = f"{s:.1f}/5"
    if s >= 4:   return f"{GREEN}{pct}{RESET}"
    elif s >= 3: return f"{YELLOW}{pct}{RESET}"
    return f"{RED}{pct}{RESET}"


# ── Carga del dataset ─────────────────────────────────────────────────────────

DATASET_DIR = Path(__file__).parent / "dataset"

def load_dataset(types: list[str] | None = None) -> list[dict]:
    cases = []
    for jsonl_file in sorted(DATASET_DIR.glob("*.jsonl")):
        with open(jsonl_file, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    case = json.loads(line)
                    if types and case.get("type") not in types:
                        continue
                    case["_source_file"] = jsonl_file.name
                    case["_line"] = line_no
                    cases.append(case)
                except json.JSONDecodeError as e:
                    logger.warning(f"{jsonl_file.name}:{line_no} JSON inválido: {e}")
    return cases


def load_document(path_str: str) -> str:
    """Carga el documento desde disco. Soporta .txt y .pdf."""
    path = Path(path_str)
    if not path.is_absolute():
        # Buscar relativo al directorio del proyecto
        project_root = Path(__file__).parent.parent
        path = project_root / path_str

    if not path.exists():
        raise FileNotFoundError(f"Documento no encontrado: {path}")

    if path.suffix.lower() == ".pdf":
        from app.services.document_processor import extract_text
        return extract_text(str(path))

    return path.read_text(encoding="utf-8", errors="replace")


# ── Evaluadores por tipo ──────────────────────────────────────────────────────

def evaluate_analysis(case: dict, use_judge: bool) -> dict:
    """Evalúa un caso de tipo 'analysis'."""
    from app.services.llm_service import llm_service

    doc_text = load_document(case["document_path"])
    expected = case.get("expected", {})

    # ── Llamar al LLMService ──────────────────────────────────────────────
    t0 = time.time()
    result = llm_service.analyze_document(doc_text)
    latency_ms = round((time.time() - t0) * 1000)

    if not result.get("success"):
        return {
            "id": case.get("id"), "type": "analysis",
            "error": result.get("message", "error desconocido"),
            "score": 0.0, "latency_ms": latency_ms
        }

    markdown  = result.get("content", "")
    risk_data = result.get("risk_data")

    # ── Métricas ──────────────────────────────────────────────────────────
    m_json     = json_validity(risk_data)
    m_sections = section_coverage(markdown, expected.get("required_sections"))
    m_clauses  = clause_detection(risk_data, expected.get("expected_clauses", []))

    m_risk = None
    if expected.get("risk_level") and risk_data:
        m_risk = risk_level_accuracy(
            risk_data.get("risk_level_overall"),
            expected["risk_level"]
        )

    # ── LLM-as-Judge ─────────────────────────────────────────────────────
    j_analysis  = None
    j_risk_just = None
    if use_judge:
        j_analysis = judge_analysis_quality(markdown, risk_data, doc_text)
        if risk_data:
            j_risk_just = judge_risk_justification(
                risk_data.get("risk_level_overall", "?"),
                risk_data.get("clauses", []),
                doc_text
            )

    # ── Score combinado ───────────────────────────────────────────────────
    component_scores = [
        m_json["score"],
        m_sections["score"],
        m_clauses["score"],
    ]
    if m_risk:
        component_scores.append(m_risk["score"])
    if j_analysis:
        component_scores.append(j_analysis["score"])

    overall = round(sum(component_scores) / len(component_scores), 3)

    return {
        "id":           case.get("id", "?"),
        "type":         "analysis",
        "document":     case["document_path"],
        "score":        overall,
        "latency_ms":   latency_ms,
        "json":         m_json,
        "sections":     m_sections,
        "clauses":      m_clauses,
        "risk_level":   m_risk,
        "judge_analysis":  j_analysis,
        "judge_risk_just": j_risk_just,
    }


def evaluate_qa(case: dict, use_judge: bool) -> dict:
    """Evalúa un caso de tipo 'qa'."""
    from app.services.llm_service import llm_service

    doc_text = load_document(case["document_path"])
    question = case["question"]

    # ── Llamar al LLMService (modo no-streaming) ──────────────────────────
    t0 = time.time()
    result = llm_service.answer_question(doc_text, question)
    latency_ms = round((time.time() - t0) * 1000)

    if not result.get("success"):
        return {
            "id": case.get("id"), "type": "qa",
            "error": result.get("message", "error desconocido"),
            "score": 0.0, "latency_ms": latency_ms
        }

    response = result.get("content", "")

    # ── Métricas ──────────────────────────────────────────────────────────
    m_keywords = keyword_coverage(response, case.get("expected_keywords", []))

    j_qa = None
    if use_judge:
        j_qa = judge_qa_relevance(question, response, doc_text)

    component_scores = [m_keywords["score"]]
    if j_qa:
        component_scores.append(j_qa["score"])

    overall = round(sum(component_scores) / len(component_scores), 3)

    return {
        "id":           case.get("id", "?"),
        "type":         "qa",
        "document":     case["document_path"],
        "question":     question,
        "response_preview": response[:200],
        "score":        overall,
        "latency_ms":   latency_ms,
        "keywords":     m_keywords,
        "judge_qa":     j_qa,
    }


# ── Runner principal ──────────────────────────────────────────────────────────

def run(
    types: list[str] | None = None,
    use_judge: bool = True,
    output_path: str | None = None,
    verbose: bool = False,
) -> dict:
    cases = load_dataset(types)
    if not cases:
        print(f"{YELLOW}No se encontraron casos en {DATASET_DIR}{RESET}")
        print("Agregá archivos .jsonl en eval/dataset/ para comenzar.")
        return {}

    print(f"\n{BOLD}{BLUE}{'═'*56}{RESET}")
    print(f"{BOLD}{BLUE}   EVALUACIÓN LTM Analyzer — {datetime.now().strftime('%Y-%m-%d %H:%M')}{RESET}")
    print(f"{BOLD}{BLUE}{'═'*56}{RESET}")
    print(f"{DIM}Casos encontrados: {len(cases)} | LLM-judge: {'sí' if use_judge else 'no'}{RESET}\n")

    results = []
    for i, case in enumerate(cases, 1):
        case_id   = case.get("id", f"caso_{i}")
        case_type = case.get("type", "?")

        print(f"[{i}/{len(cases)}] {BOLD}{case_id}{RESET} ({case_type}) ", end="", flush=True)

        try:
            if case_type == "analysis":
                r = evaluate_analysis(case, use_judge)
            elif case_type == "qa":
                r = evaluate_qa(case, use_judge)
            else:
                print(f"{YELLOW}tipo desconocido, omitido{RESET}")
                continue

            emoji = "✅" if r["score"] >= 0.7 else ("⚠️ " if r["score"] >= 0.5 else "❌")
            print(f"→ {emoji} {color_score(r['score'])}  {DIM}({r['latency_ms']}ms){RESET}")

            if verbose and r.get("error"):
                print(f"   {RED}Error: {r['error']}{RESET}")

        except FileNotFoundError as e:
            print(f"{RED}archivo no encontrado: {e}{RESET}")
            r = {"id": case_id, "type": case_type, "error": str(e), "score": 0.0}
        except Exception as e:
            print(f"{RED}error: {e}{RESET}")
            r = {"id": case_id, "type": case_type, "error": str(e), "score": 0.0}
            if verbose:
                import traceback; traceback.print_exc()

        results.append(r)

    # ── Reporte ────────────────────────────────────────────────────────────
    _print_report(results, use_judge)

    summary = _build_summary(results)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "results": results}, f, ensure_ascii=False, indent=2)
        print(f"\n{DIM}Reporte guardado en: {out}{RESET}")

    return summary


def _print_report(results: list[dict], use_judge: bool) -> None:
    analysis_results = [r for r in results if r.get("type") == "analysis" and not r.get("error")]
    qa_results       = [r for r in results if r.get("type") == "qa" and not r.get("error")]
    errors           = [r for r in results if r.get("error")]

    print(f"\n{BOLD}{'─'*56}{RESET}")
    print(f"{BOLD}RESUMEN{RESET}")
    print(f"{'─'*56}")

    if analysis_results:
        print(f"\n{BOLD}Análisis de documentos ({len(analysis_results)} casos){RESET}")
        _print_metric("Validez JSON",          aggregate([r["json"]     for r in analysis_results]))
        _print_metric("Cobertura secciones",   aggregate([r["sections"] for r in analysis_results]))
        _print_metric("Detección cláusulas",   aggregate([r["clauses"]  for r in analysis_results]))

        risk_results = [r["risk_level"] for r in analysis_results if r.get("risk_level")]
        if risk_results:
            _print_metric("Nivel de riesgo",   aggregate(risk_results))

        if use_judge:
            judge_results = [r["judge_analysis"] for r in analysis_results if r.get("judge_analysis")]
            if judge_results:
                avg_scores = {
                    "completitud": sum(j.get("completitud", 0) for j in judge_results) / len(judge_results),
                    "precision":   sum(j.get("precision", 0)   for j in judge_results) / len(judge_results),
                    "utilidad":    sum(j.get("utilidad", 0)    for j in judge_results) / len(judge_results),
                }
                print(f"  LLM-judge análisis:")
                for dim, val in avg_scores.items():
                    print(f"    · {dim:<14}: {fmt_5(val)}")

        latencies = [r["latency_ms"] for r in analysis_results]
        print(f"  Latencia:          {DIM}p50={sorted(latencies)[len(latencies)//2]}ms  "
              f"p95={sorted(latencies)[int(len(latencies)*.95)]}ms{RESET}")

    if qa_results:
        print(f"\n{BOLD}Preguntas y Respuestas ({len(qa_results)} casos){RESET}")
        _print_metric("Cobertura palabras clave", aggregate([r["keywords"] for r in qa_results]))

        if use_judge:
            judge_qa = [r["judge_qa"] for r in qa_results if r.get("judge_qa")]
            if judge_qa:
                for dim in ("relevancia", "precision", "claridad", "fundamento"):
                    avg = sum(j.get(dim, 0) for j in judge_qa) / len(judge_qa)
                    print(f"  LLM-judge {dim:<12}: {fmt_5(avg)}")

        latencies = [r["latency_ms"] for r in qa_results]
        if latencies:
            print(f"  Latencia:          {DIM}p50={sorted(latencies)[len(latencies)//2]}ms{RESET}")

    if errors:
        print(f"\n{RED}Errores: {len(errors)}{RESET}")
        for r in errors:
            print(f"  · {r['id']}: {r['error'][:80]}")

    all_scores = [r["score"] for r in results if not r.get("error")]
    if all_scores:
        global_score = sum(all_scores) / len(all_scores)
        passed = sum(1 for s in all_scores if s >= 0.7)
        print(f"\n{'─'*56}")
        print(f"{BOLD}Score global: {color_score(global_score)}  "
              f"Aprobados: {passed}/{len(all_scores)}{RESET}")
    print(f"{'─'*56}\n")


def _print_metric(name: str, agg: dict) -> None:
    bar = "█" * int(agg["mean"] * 20) + "░" * (20 - int(agg["mean"] * 20))
    print(f"  {name:<26}: {color_score(agg['mean'])}  {DIM}{bar}{RESET}")


def _build_summary(results: list[dict]) -> dict:
    valid = [r for r in results if not r.get("error")]
    return {
        "timestamp": datetime.now().isoformat(),
        "total_cases": len(results),
        "successful": len(valid),
        "errors": len(results) - len(valid),
        "global_score": round(sum(r["score"] for r in valid) / len(valid), 3) if valid else 0.0,
        "pass_rate": round(sum(1 for r in valid if r["score"] >= 0.7) / len(valid), 3) if valid else 0.0,
        "by_type": {
            t: aggregate([r for r in valid if r.get("type") == t])
            for t in set(r.get("type") for r in valid)
        }
    }


# ── Punto de entrada ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Suite de evaluación para LTM Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--type", choices=["analysis", "qa"],
                        help="Evaluar solo este tipo de caso")
    parser.add_argument("--no-judge", action="store_true",
                        help="Saltar LLM-as-Judge (más rápido, sin costo de tokens)")
    parser.add_argument("--output", metavar="FILE",
                        help="Guardar reporte en archivo JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Mostrar detalles de errores")
    args = parser.parse_args()

    run(
        types=[args.type] if args.type else None,
        use_judge=not args.no_judge,
        output_path=args.output,
        verbose=args.verbose,
    )
