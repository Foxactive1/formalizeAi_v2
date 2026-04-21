import json
import logging
from validator import Validator
from scorer import Scorer
from groq_client import generate_with_fallback
from config import QUALITY_THRESHOLD, REQUIRED_SECTIONS, MAX_ORCHESTRATION_CYCLES
from cache import get_cache, set_cache
from prompt_engine import PromptEngine

log = logging.getLogger("formalizeai")


def _extract_sdd(text: str) -> str:
    if not text:
        return ""
    # Remove a tag de finalização se presente
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


class Orchestrator:
    MAX_CYCLES = MAX_ORCHESTRATION_CYCLES

    def __init__(self, model: str):
        self.model = model

    def run(self, messages: list) -> dict:
        # Cache baseado nas últimas mensagens (evita reprocessamento idêntico)
        cache_key = f"orch:{self.model}:{hash(json.dumps(messages[-5:], sort_keys=True))}"
        cached = get_cache(cache_key)
        if cached:
            log.info("Cache hit no Orchestrator")
            return json.loads(cached)

        sdd = ""
        score = 0
        validation = {"valid": False, "missing": REQUIRED_SECTIONS}
        last_response = ""

        for cycle in range(1, self.MAX_CYCLES + 1):
            log.info(f"Orchestrator: ciclo {cycle}/{self.MAX_CYCLES} — modelo preferido {self.model}")

            # Usa fallback automático em caso de falha do modelo preferido
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
            score = Scorer.score(sdd)

            log.info(
                f"Ciclo {cycle}: score={score}/{QUALITY_THRESHOLD} "
                f"valid={validation['valid']} missing={len(validation['missing'])}"
            )

            if validation["valid"] and score >= QUALITY_THRESHOLD:
                result = {
                    "response": last_response,
                    "sdd": sdd,
                    "score": score,
                    "validation": validation,
                    "status": "approved",
                    "cycles": cycle,
                }
                set_cache(cache_key, json.dumps(result))
                return _safe_json(result)

            if cycle < self.MAX_CYCLES:
                # Adiciona mensagem de correção para o próximo ciclo
                messages = messages + [
                    {"role": "assistant", "content": last_response},
                    {"role": "user", "content": self._fix_prompt(validation, score)},
                ]

        result = {
            "response": last_response,
            "sdd": sdd,
            "score": score,
            "validation": validation,
            "status": "needs_review",
            "cycles": self.MAX_CYCLES,
        }
        return _safe_json(result)

    def _fix_prompt(self, validation: dict, score: int) -> str:
        """Gera prompt de correção usando PromptEngine."""
        return PromptEngine.fix_prompt(validation, score, Scorer.MAX_SCORE)