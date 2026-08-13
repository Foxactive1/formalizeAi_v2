# rate_limit.py — FormalizeAI v4.1
# FIX: rate limit agora usa Redis como backend quando disponível,
#      garantindo que os limites persistam entre restarts em produção.

import time
import logging
from collections import defaultdict
from flask import request, jsonify
from functools import wraps
from config import RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD

log = logging.getLogger("formalizeai")

# Import do cliente Redis reutilizado do cache.py para evitar segunda conexão
try:
    from cache import _redis_client
except ImportError:
    _redis_client = None

# Fallback em memória (desenvolvimento / sem Redis)
_limits: dict = defaultdict(list)


def _is_rate_limited_redis(key: str) -> bool:
    """
    Rate limit via Redis usando sliding window com sorted set.
    Atomicamente registra a requisição e verifica se ultrapassou o limite.
    Retorna True se a requisição deve ser bloqueada.
    """
    try:
        now = time.time()
        window_start = now - RATE_LIMIT_PERIOD
        redis_key = f"rl:{key}"

        pipe = _redis_client.pipeline()
        # Remove entradas fora da janela
        pipe.zremrangebyscore(redis_key, 0, window_start)
        # Conta requisições na janela atual
        pipe.zcard(redis_key)
        # Adiciona a requisição atual
        pipe.zadd(redis_key, {str(now): now})
        # Expira a chave após o período (limpeza automática)
        pipe.expire(redis_key, int(RATE_LIMIT_PERIOD * 2))
        results = pipe.execute()

        current_count = results[1]  # zcard antes do zadd desta requisição
        return current_count >= RATE_LIMIT_REQUESTS

    except Exception as e:
        log.warning(f"Redis rate limit falhou, usando memória: {e}")
        return _is_rate_limited_memory(key)


def _is_rate_limited_memory(key: str) -> bool:
    """Rate limit em memória (sliding window). Não persiste entre restarts."""
    now = time.time()
    window_start = now - RATE_LIMIT_PERIOD
    _limits[key] = [t for t in _limits[key] if t > window_start]
    if len(_limits[key]) >= RATE_LIMIT_REQUESTS:
        return True
    _limits[key].append(now)
    return False


def rate_limit(f):
    """
    Decorator de rate limiting.
    Identifica o cliente por X-Api-Key (se presente) ou IP remoto.
    Usa Redis em produção (se disponível) ou memória em desenvolvimento.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-Api-Key", request.remote_addr)

        if _redis_client:
            blocked = _is_rate_limited_redis(key)
        else:
            blocked = _is_rate_limited_memory(key)

        if blocked:
            log.warning(f"Rate limit excedido para: {key}")
            return jsonify({
                "error": "Rate limit exceeded. Try again later.",
                "retry_after": RATE_LIMIT_PERIOD,
            }), 429

        return f(*args, **kwargs)
    return decorated
