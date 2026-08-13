# orchestrator.py — FormalizeAI v4.1
# FIX: substituído hash() nativo (não determinístico entre restarts) por sha256

import json
import logging
from hashlib import sha256  # FIX: hash() é PYTHONHASHSEED-dependente; sha256 é determinístico
from validator import Validator
from scorer import Scorer
from groq_client import generate_with_fallback
from config import QUALITY_THRESHOLD, REQUIRED_SECTIONS, MAX_ORCHESTRATION_CYCLES
from cache import get_cache, set_cache
from prompt_engine import PromptEngine

log = logging.getLogger(\"formalizeai\")


def _extract_sdd(text: str) -> str:
    \"\"\"Remove a tag de controle [FINALIZANDO SDD] e retorna apenas o conteúdo.\"\"\"\
    if not text:
        return \"\"
    if \"[FINALIZANDO SDD]\" in text:
        text = text.split(\"[FINALIZANDO SDD]\", 1)[1].strip()
    return text


def _safe_json(data: dict) -> dict:
    \"\"\"Garante que o dicionário seja serializável para JSON.\"\"\"\
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
    # FIX: usa sha256 (determinístico) em vez de hash() nativo do Python
    # hash() muda a cada restart por causa do PYTHONHASHSEED aleatório do Python 3.3+
    payload = json.dumps({\"messages\": messages[-5:], \"model\": model}, sort_keys=True)
    return f\"orch:{sha256(payload.encode()).hexdigest()}\"


class Orchestrator:
    MAX_CYCLES = MAX_ORCHESTRATION_CYCLES

    def __init__(self, model: str):
        self.model = model

    def run(self, messages: list) -> dict:
        # Cache baseado nas últimas mensagens (evita reprocessamento idêntico)
        cache_key = _cache_key(messages, self.model)
        cached = get_cache(cache_key)
        if cached:
            log.info(\"Cache hit no Orchestrator\")
            return json.loads(cached)

        sdd = \"\"
        score = 0
        validation = {\"valid\": False, \"missing\": REQUIRED_SECTIONS}
        last_response = \"\"

        for cycle in range(1, self.MAX_CYCLES + 1):
            log.info(f\"Orchestrator: ciclo {cycle}/{self.MAX_CYCLES} — modelo preferido {self.model}\")

            try:
                last_response = generate_with_fallback(messages, preferred_model=self.model)
            except RuntimeError as e:
                log.error(f\"Falha total na geração: {e}\")
                return _safe_json({
                    \"status\": \"error\",
                    \"message\": str(e),
                    \"cycles\": cycle,
                })

            sdd = _extract_sdd(last_response)
            validation = Validator.validate(sdd)
            score = Scorer.score(sdd)

            log.info(
                f\"Ciclo {cycle}: score={score}/{QUALITY_THRESHOLD} \"
                f\"valid={validation['valid']} missing={len(validation['missing'])}\"
            )

            if validation[\"valid\"] and score >= QUALITY_THRESHOLD:
                result = _safe_json({
                    \"status\": \"approved\",
                    \"sdd\": sdd,
                    \"score\": score,
                    \"max_score\": Scorer.MAX_SCORE,
                    \"cycles\": cycle,
                    \"validation\": validation,
                    \"breakdown\": Scorer.breakdown(sdd),
                })
                set_cache(cache_key, json.dumps(result))
                return result

            # Não atingiu o threshold: injeta prompt de correção para o próximo ciclo
            if cycle < self.MAX_CYCLES:
                fix_msg = PromptEngine.fix_prompt(validation, score, Scorer.MAX_SCORE)
                messages = messages + [{\"role\": \"user\", \"content\": fix_msg}]
                log.info(f\"Ciclo {cycle} insuficiente — injetando prompt de correção\")

        # Esgotou os ciclos sem aprovação
        return _safe_json({
            \"status\": \"needs_review\",
            \"sdd\": sdd,
            \"score\": score,
            \"max_score\": Scorer.MAX_SCORE,
            \"cycles\": self.MAX_CYCLES,
            \"validation\": validation,
            \"breakdown\": Scorer.breakdown(sdd),
            \"warning\": \"Score abaixo do threshold após todos os ciclos. Revisão manual recomendada.\",
        })
