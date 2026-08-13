# orchestrator.py — FormalizeAI v4.1
#
# MUDANÇAS v4.1:
# - hash() nativo substituído por sha256 (determinístico entre restarts)
# - use_llm=True no ciclo final: após aprovação heurística, o LLM avalia
#   as 5 seções críticas individualmente para enriquecer o score final
# - Threshold adaptativo: score heurístico usa MAX_SCORE (18);
#   score LLM usa MAX_SCORE_WITH_LLM (28) apenas como informação de qualidade

import json
import logging
from hashlib import sha256  # FIX: hash() nativo não é determinístico (PYTHONHASHSEED)
from validator import Validator
from scorer import Scorer
from groq_client import generate_with_fallback
from config import QUALITY_THRESHOLD, REQUIRED_SECTIONS, MAX_ORCHESTRATION_CYCLES
from cache import get_cache, set_cache
from prompt_engine import PromptEngine

log = logging.getLogger("formalizeai")


def _extract_sdd(text: str) -> str:
    """Remove a tag de controle [FINALIZANDO SDD] e retorna apenas o conteúdo."""
    if not text:
        return ""
    if "[FINALIZANDO SDD]" in text:
        text = text.split("[FINALIZANDO SDD]", 1)[1].strip()
    return text


def _safe_json(data: dict) -> dict:
    """Garante que o dicionário seja serializável para JSON."""
    try:
        json.dumps(data)
        return data
    except TypeError:
        clean = {}
        for k, v in data.items():
            try:
                json.dumps({k: v})
                clean[k] = v
            except TypeError:
                clean[k] = str(v)
        return clean


def _cache_key(messages: list, model: str) -> str:
    # FIX: sha256 é determinístico — hash() muda a cada restart por PYTHONHASHSEED
    payload = json.dumps({"messages": messages[-5:], "model": model}, sort_keys=True)
    return f"orch:{sha256(payload.encode()).hexdigest()}"


class Orchestrator:
    MAX_CYCLES = MAX_ORCHESTRATION_CYCLES

    def __init__(self, model: str):
        self.model = model

    def run(self, messages: list) -> dict:
        # Verifica cache antes de qualquer geração
        cache_key = _cache_key(messages, self.model)
        cached = get_cache(cache_key)
        if cached:
            log.info("Cache hit no Orchestrator")
            return json.loads(cached)

        sdd = ""
        score = 0
        validation = {"valid": False, "missing": REQUIRED_SECTIONS}
        last_response = ""

        for cycle in range(1, self.MAX_CYCLES + 1):
            log.info(f"Orchestrator: ciclo {cycle}/{self.MAX_CYCLES} — modelo {self.model}")

            try:
                last_response = generate_with_fallback(messages, preferred_model=self.model)
            except RuntimeError as e:
                log.error(f"Falha total na geração: {e}")
                return _safe_json({
                    "status": "error",
                    "message": str(e),
                    "cycles": cycle,
                })

            sdd = _extract_sdd(last_response)
            validation = Validator.validate(sdd)

            # Ciclos intermediários: usa apenas o score heurístico (rápido, sem custo LLM)
            score = Scorer.score(sdd, use_llm=False)

            log.info(
                f"Ciclo {cycle}: heuristic_score={score}/{Scorer.MAX_SCORE} "
                f"valid={validation['valid']} missing={len(validation['missing'])}"
            )

            if validation["valid"] and score >= QUALITY_THRESHOLD:
                # Aprovação heurística atingida — executa LLM scoring no ciclo final
                # O LLM scoring é mais lento/custoso, por isso só roda uma vez ao final
                log.info("Threshold heurístico atingido — executando LLM scoring final...")
                llm_result = Scorer.score_sections_with_llm(sdd)
                final_score = Scorer.score(sdd, use_llm=True)
                breakdown = Scorer.breakdown(sdd, use_llm=True)

                log.info(
                    f"LLM score: {llm_result['llm_total']}/{llm_result['llm_max']} | "
                    f"Score combinado final: {final_score}/{Scorer.MAX_SCORE_WITH_LLM}"
                )

                result = _safe_json({
                    "status": "approved",
                    "sdd": sdd,
                    "score": final_score,
                    "heuristic_score": score,
                    "llm_score": llm_result["llm_total"],
                    "max_score": Scorer.MAX_SCORE_WITH_LLM,
                    "cycles": cycle,
                    "validation": validation,
                    "breakdown": breakdown,
                    "llm_sections": llm_result["by_section"],
                })
                set_cache(cache_key, json.dumps(result))
                return result

            # Não atingiu o threshold — injeta prompt de correção para o próximo ciclo
            if cycle < self.MAX_CYCLES:
                fix_msg = PromptEngine.fix_prompt(validation, score, Scorer.MAX_SCORE)
                messages = messages + [{"role": "user", "content": fix_msg}]
                log.info(f"Ciclo {cycle} insuficiente — injetando prompt de correção")

        # Esgotou todos os ciclos sem aprovação — retorna o melhor resultado obtido
        breakdown = Scorer.breakdown(sdd, use_llm=False)
        return _safe_json({
            "status": "needs_review",
            "sdd": sdd,
            "score": score,
            "heuristic_score": score,
            "llm_score": 0,
            "max_score": Scorer.MAX_SCORE,
            "cycles": self.MAX_CYCLES,
            "validation": validation,
            "breakdown": breakdown,
            "warning": (
                f"Score {score}/{Scorer.MAX_SCORE} abaixo do threshold {QUALITY_THRESHOLD} "
                f"após {self.MAX_CYCLES} ciclos. Revisão manual recomendada."
            ),
        })
