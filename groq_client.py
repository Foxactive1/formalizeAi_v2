import json
import logging
import time
from hashlib import sha256
from functools import wraps
from groq import Groq
from config import GROQ_API_KEY, MAX_HISTORY_LENGTH, DEFAULT_MODEL, AVAILABLE_MODELS
from cache import get_cache, set_cache

log = logging.getLogger("formalizeai")

# Lista de fallback em caso de falha do modelo preferido
MODEL_FALLBACK_PRIORITY = [
    "llama-3.3-70b-versatile",
    "mixtral-8x7b-32768",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

def _get_client():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada")
    return Groq(api_key=GROQ_API_KEY)

def _trim_history(messages: list) -> list:
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]
    if len(other_msgs) <= MAX_HISTORY_LENGTH:
        return system_msgs + other_msgs
    return system_msgs + other_msgs[-MAX_HISTORY_LENGTH:]

def _cache_key(messages: list, model: str) -> str:
    payload = json.dumps({"messages": messages[-10:], "model": model}, sort_keys=True)
    return sha256(payload.encode()).hexdigest()

def retry_with_backoff(retries=3, backoff=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(retries):
                try:
                    return func(*args, **kwargs)
                except RuntimeError as e:
                    if "429" in str(e) and i < retries - 1:
                        wait = backoff ** i
                        log.warning(f"Groq 429, retrying in {wait}s...")
                        time.sleep(wait)
                    else:
                        raise
            return None
        return wrapper
    return decorator

@retry_with_backoff(retries=3, backoff=2)
def generate_response(messages: list, model: str = None) -> str:
    """Geração direta com um modelo específico (sem fallback)."""
    if model is None:
        model = DEFAULT_MODEL
    trimmed = _trim_history(messages)
    key = _cache_key(trimmed, model)
    cached = get_cache(key)
    if cached:
        log.info("Cache hit")
        return cached if isinstance(cached, str) else cached.get("response", "")

    try:
        client = _get_client()
        completion = client.chat.completions.create(
            model=model,
            messages=trimmed,
            temperature=0.7,
            max_tokens=4096,
        )
        response = completion.choices[0].message.content
        set_cache(key, response)
        return response

    except Exception as e:
        err_str = str(e)
        # Tratamento específico para rate limit (HTTP 429)
        if "429" in err_str or "rate_limit_exceeded" in err_str or "RateLimitError" in type(e).__name__:
            import re
            retry_match = re.search(r"try again in ([\d]+m[\d.]+s|[\d.]+s)", err_str, re.IGNORECASE)
            retry_info = retry_match.group(1) if retry_match else "alguns minutos"
            log.warning(f"Groq rate limit (429) — modelo={model} retry_in={retry_info}")
            raise RuntimeError(f"Limite diário de tokens atingido. Tente novamente em {retry_info}.") from e
        else:
            log.exception("Erro Groq")
            raise RuntimeError(f"Groq falhou: {e}") from e

def generate_with_fallback(messages: list, preferred_model: str = None) -> str:
    """
    Tenta gerar resposta usando uma lista de modelos em cascata.
    Se preferred_model for fornecido, ele é tentado primeiro.
    """
    models_to_try = []
    if preferred_model and preferred_model in AVAILABLE_MODELS:
        models_to_try.append(preferred_model)
    for m in MODEL_FALLBACK_PRIORITY:
        if m not in models_to_try and m in AVAILABLE_MODELS:
            models_to_try.append(m)

    last_error = None
    for model in models_to_try:
        try:
            log.info(f"Tentando modelo: {model}")
            return generate_response(messages, model)
        except Exception as e:
            log.warning(f"Falha no modelo {model}: {e}")
            last_error = e
            continue

    raise RuntimeError(f"Todos os modelos falharam. Último erro: {last_error}")