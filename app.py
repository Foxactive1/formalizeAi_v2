import os
import logging
import sys
from flask import Flask, render_template   # ← render_template adicionado
from flask_cors import CORS
from config import GROQ_API_KEY, DEFAULT_MODEL, AVAILABLE_MODELS, X_API_KEY, QUALITY_THRESHOLD, SUPABASE_URL, SUPABASE_KEY, REDIS_URL
from scorer import Scorer
from routes import api_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("formalizeai")


def create_app():
    app = Flask(__name__)
    CORS(app)

    # Registrar blueprint com prefixo /api
    # ⚠️ USE url_prefix="/api" SOMENTE se as rotas em routes.py
    # NÃO tiverem "/api" já no path (ex: @api_bp.route("/gerar"))
    app.register_blueprint(api_bp, url_prefix="/api")

    # Rota raiz para servir o frontend
    @app.route("/")
    def index():
        return render_template("index.html")

    return app


if __name__ == "__main__":
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY não encontrada!")
        print("   Crie um arquivo .env com: GROQ_API_KEY=gsk_...")
        sys.exit(1)

    import config as _cfg
    if _cfg.DEFAULT_MODEL not in AVAILABLE_MODELS:
        print(f"🤖 Modelo padrão  : {_cfg.DEFAULT_MODEL}")
        
        _cfg.DEFAULT_MODEL = AVAILABLE_MODELS[0]

    sb_status = "✅ Supabase configurado" if (SUPABASE_URL and SUPABASE_KEY) else "⚠️ Supabase não configurado — usando apenas /tmp"
    rd_status = "✅ Redis configurado" if REDIS_URL else "⚠️ Redis não configurado — cache em memória"

    print("✅ Groq API configurada")
    print(sb_status)
    print(rd_status)
    if X_API_KEY:
        print("🔐 API Key ativa — autenticação habilitada")
    print(f"🤖 Modelo padrão  : {DEFAULT_MODEL}")
    print(f"🎯 Quality threshold: {QUALITY_THRESHOLD}/{Scorer.MAX_SCORE}")
    env = "desenvolvimento" if os.environ.get("FLASK_ENV") == "development" else "produção"
    print(f"🚀 FormalizeAI v4.0 rodando em modo {env}")
    print("   Acesse: http://127.0.0.1:5000")
    print("   Produção: gunicorn -w 2 -b 0.0.0.0:$PORT app:create_app()")

    app = create_app()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "False").lower() == "true",
    )