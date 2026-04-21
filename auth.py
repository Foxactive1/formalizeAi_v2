import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
from config import X_API_KEY  # FIX: config.py exporta variáveis de módulo, não classe Config

# Chave secreta derivada do X_API_KEY ou valor padrão (em produção usar SECRET_KEY própria)
import os
_SECRET_KEY = os.environ.get("SECRET_KEY", X_API_KEY or "dev-secret-change-in-prod")

# Em produção, substitua por um banco de verdade
USERS_DB = {}

def generate_token(user_id: str) -> str:
    return jwt.encode(
        {"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=1)},
        _SECRET_KEY,
        algorithm="HS256"
    )

def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Tenta Bearer JWT
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                data = jwt.decode(token, _SECRET_KEY, algorithms=["HS256"])
                request.user_id = data["user_id"]
                return f(*args, **kwargs)
            except jwt.InvalidTokenError:
                pass

        # 2. Tenta API Key (serviço)
        api_key = request.headers.get("X-Api-Key")
        if X_API_KEY and api_key == X_API_KEY:
            request.user_id = "service_account"
            return f(*args, **kwargs)

        return jsonify({"error": "Authentication required"}), 401
    return decorated