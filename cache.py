from datetime import datetime
from config import CACHE_TTL, CACHE_MAX_ITEMS, REDIS_URL

_redis_client = None
CACHE: dict = {}

if REDIS_URL:
    try:
        import redis as _redis_lib
        _redis_client = _redis_lib.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
        print("Redis conectado")
    except Exception as e:
        print(f"Redis indisponível: {e}")

def get_cache(key: str):
    if _redis_client:
        return _redis_client.get(key)
    entry = CACHE.get(key)
    if entry and (datetime.now().timestamp() - entry["time"]) < CACHE_TTL:
        return entry["response"]
    return None

def set_cache(key: str, value: str):
    if _redis_client:
        _redis_client.setex(key, CACHE_TTL, value)
    else:
        CACHE[key] = {"response": value, "time": datetime.now().timestamp()}
        _cleanup_cache()

def _cleanup_cache():
    if _redis_client:
        return
    now = datetime.now().timestamp()
    expired = [k for k, v in CACHE.items() if now - v["time"] > CACHE_TTL]
    for k in expired:
        del CACHE[k]
    if len(CACHE) > CACHE_MAX_ITEMS:
        oldest = sorted(CACHE.items(), key=lambda x: x[1]["time"])
        for k, _ in oldest[:len(CACHE) - CACHE_MAX_ITEMS]:
            del CACHE[k]