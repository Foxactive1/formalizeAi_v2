# auth.py — FormalizeAI v4.1
# FIX: SECRET_KEY agora tem origem exclusiva — nunca mais mistura com X_API_KEY.
#      X_API_KEY é chave de serviço; SECRET_KEY é segredo de assinatura JWT.
#      São responsabilidades distintas e não devem ser intercambiáveis.

import os
import jwt
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify
from config import X_API_KEY

log = logging.getLogger("formalizeai")

# FIX: SECRET_KEY derivado SOMENTE de SECRET_KEY no .env.
# Nunca use X_API_KEY como fallback — são chaves com propósitos diferentes.
# Em produção: gere com python -c "import secrets; print(secrets.token_hex(32))"
_SECRET_KEY = os.environ.get("SECRET_KEY", "")

if not _SECRET_KEY:
    # Em desenvolvimento, gera um valor temporário e avisa
    import secrets
    _SECRET_KEY = secrets.token_hex(32)
    log.warning(
        "SECRET_KEY não configurada no .env. "
        "Usando chave temporária — tokens JWT serão invalidados a cada restart. "
        "Configure SECRET_KEY em produção."
    )

# Em produção, substitua por Supabase Auth ou outro banco de usuários
USERS_DB: dict = {}


def generate_token(user_id: str) -> str:
    """Gera um token JWT com validade de 24h."""
    return jwt.encode(
        {
            "user_id": user_id,
            # FIX: datetime.utcnow() está deprecated no Python 3.12+
            # Use datetime.now(timezone.utc) para compatibilidade futura
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "iat": datetime.now(timezone.utc),
        },
        _SECRET_KEY,
        algorithm="HS256",
    )


def auth_required(f):
    """
    Decorator de autenticação dupla:
    1. Bearer JWT (para usuários autenticados via login)
    2. X-Api-Key (para integração entre serviços)
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. Tenta Bearer JWT
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            try:
                data = jwt.decode(token, _SECRET_KEY, algorithms=["HS256"])
                request.user_id = data["user_id"]
                return f(*args, **kwargs)
            except jwt.ExpiredSignatureError:
                return jsonify({"error": "Token expirado. Faça login novamente."}), 401
            except jwt.InvalidTokenError as e:
                log.warning(f"Token JWT inválido: {e}")

        # 2. Tenta API Key de serviço
        api_key = request.headers.get("X-Api-Key", "")
        if X_API_KEY and api_key == X_API_KEY:
            request.user_id = "service_account"
            return f(*args, **kwargs)

        return jsonify({"error": "Authentication required"}), 401

    return decorated
