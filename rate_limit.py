import time
from collections import defaultdict
from flask import request, jsonify
from functools import wraps
from config import RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD

_limits = defaultdict(list)

def rate_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get('X-Api-Key', request.remote_addr)
        now = time.time()
        window_start = now - RATE_LIMIT_PERIOD
        _limits[key] = [t for t in _limits[key] if t > window_start]
        if len(_limits[key]) >= RATE_LIMIT_REQUESTS:
            return jsonify({"error": "Rate limit exceeded. Try again later."}), 429
        _limits[key].append(now)
        return f(*args, **kwargs)
    return decorated