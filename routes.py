import io
import re
import logging
from functools import wraps
from prompt_engine import PromptEngine
from groq_client import generate_with_fallback  # opcional, pois o Orchestrator já usaort wraps
from datetime import datetime
from hashlib import sha256
from flask import Blueprint, jsonify, request, render_template, render_template_string, send_file
from config import AVAILABLE_MODELS, DEFAULT_MODEL, X_API_KEY, QUALITY_THRESHOLD, MAX_MESSAGE_LENGTH, SYSTEM_PROMPT, PROJECTS_DIR, GROQ_API_KEY, CACHE_TTL
from supabase_client import load_project, save_project, save_sdd, get_supabase
from groq_client import generate_response
from orchestrator import Orchestrator
from scorer import Scorer
from validator import Validator
from cache import CACHE, _redis_client
from rate_limit import rate_limit

log = logging.getLogger("formalizeai")
api_bp = Blueprint("api", __name__)   # sem url_prefix
# ---------------------------------------------------------------------------
# Template HTML para geração de PDF (suporte a Mermaid via Playwright)
# ---------------------------------------------------------------------------
PDF_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{{ title }}</title>
    <style>
        body {
            font-family: 'Segoe UI', Helvetica, Arial, sans-serif;
            max-width: 1200px;
            margin: 2em auto;
            padding: 1.5em;
            line-height: 1.6;
            color: #1e1e1e;
        }
        h1, h2, h3, h4 {
            color: #0b5e42;
            border-bottom: 1px solid #eaecef;
            padding-bottom: 0.3em;
        }
        code {
            background: #f4f4f4;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-family: 'Consolas', 'Monaco', monospace;
        }
        pre {
            background: #f6f8fa;
            padding: 1em;
            overflow-x: auto;
            border-radius: 6px;
        }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 1em 0;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 8px 12px;
            text-align: left;
        }
        th {
            background: #f1f1f1;
        }
        .mermaid {
            text-align: center;
            margin: 1.5em 0;
        }
        @media print {
            body { margin: 0; }
            h1, h2, h3, h4 { page-break-after: avoid; }
            pre, .mermaid { page-break-inside: avoid; }
        }
    </style>
    <!-- Mermaid.js via ESM -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({
            startOnLoad: true,
            theme: 'default',
            securityLevel: 'loose',
            fontFamily: 'Segoe UI'
        });
        // Expõe função global para ser chamada pelo Playwright após carregamento
        window.renderMermaid = async function() {
            await mermaid.run({ querySelector: '.mermaid' });
        };
    </script>
</head>
<body>
    {{ content|safe }}
    <script>
        // Fallback: aguarda módulo ESM carregar e chama renderização
        (function() {
            if (typeof window.renderMermaid === 'undefined') {
                console.warn("Mermaid module not loaded yet, waiting...");
                setTimeout(() => {
                    if (window.renderMermaid) window.renderMermaid();
                }, 200);
            } else {
                window.renderMermaid();
            }
        })();
    </script>
</body>
</html>
"""

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if X_API_KEY:
            if request.headers.get("X-Api-Key", "") != X_API_KEY:
                return jsonify({"error": "Unauthorized — X-Api-Key inválida"}), 401
        return f(*args, **kwargs)
    return decorated

def _validate_message(message: str) -> str:
    if not message or not isinstance(message, str):
        raise ValueError("Mensagem inválida ou vazia")
    msg = message.strip()
    if len(msg) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Mensagem excede {MAX_MESSAGE_LENGTH} caracteres")
    return msg

# ------------------------- Models -------------------------
@api_bp.route("/models", methods=["GET"])
def list_models():
    return jsonify({"models": AVAILABLE_MODELS, "default": DEFAULT_MODEL})

# ------------------------- Projects CRUD -------------------------
@api_bp.route("/projects", methods=["GET"])
@require_api_key
@rate_limit
def list_projects():
    sb = get_supabase()
    if sb:
        try:
            result = sb.table("v_projects_summary").select("*").order("updated_at", desc=True).execute()
            return jsonify({"projects": result.data or [], "source": "supabase"})
        except Exception as e:
            log.warning(f"list_projects Supabase falhou: {e}")

    from config import PROJECTS_DIR
    import json
    projects = []
    for f in PROJECTS_DIR.glob("*.json"):
        name = f.stem
        try:
            with open(f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
                status = d.get("status", "desconhecido")
                updated = d.get("updated_at") or d.get("created") or ""
        except Exception:
            status, updated = "erro", ""
        projects.append({"name": name, "status": status, "updated_at": updated})
    return jsonify({"projects": projects, "source": "local"})

@api_bp.route("/projects", methods=["POST"])
@require_api_key
@rate_limit
def create_project():
    data = request.json or {}
    project_name = (data.get("name") or f"projeto-{datetime.now().strftime('%Y%m%d-%H%M')}").strip()
    model = data.get("model", DEFAULT_MODEL)
    if model not in AVAILABLE_MODELS:
        return jsonify({"error": f"Modelo inválido. Escolha: {AVAILABLE_MODELS}"}), 400
    project_data = load_project(project_name)
    if not project_data["messages"]:
        project_data["messages"].append({"role": "system", "content": SYSTEM_PROMPT})
        project_data["model"] = model
        save_project(project_name, project_data)
    return jsonify({"project": project_name, "model": model, "status": "created", "source": project_data.get("_source", "unknown")})

@api_bp.route("/projects/<project_name>", methods=["GET"])
@require_api_key
@rate_limit
def get_project(project_name):
    data = load_project(project_name)
    return jsonify({k: v for k, v in data.items() if not k.startswith("_")})

@api_bp.route("/projects/<project_name>", methods=["PATCH"])
@require_api_key
@rate_limit
def update_project(project_name):
    body = request.json or {}
    project_data = load_project(project_name)
    if "model" in body:
        if body["model"] not in AVAILABLE_MODELS:
            return jsonify({"error": f"Modelo inválido. Escolha: {AVAILABLE_MODELS}"}), 400
        project_data["model"] = body["model"]
    if "status" in body:
        project_data["status"] = body["status"]
    save_project(project_name, project_data)
    return jsonify({"project": project_name, "model": project_data["model"], "status": project_data["status"]})

@api_bp.route("/projects/<project_name>", methods=["DELETE"])
@require_api_key
@rate_limit
def delete_project(project_name):
    sb = get_supabase()
    if sb:
        try:
            sb.table("projects").delete().eq("name", project_name).execute()
        except Exception as e:
            log.warning(f"delete Supabase falhou: {e}")
    from config import PROJECTS_DIR
    for suffix in [".json", "_SDD.md"]:
        f = PROJECTS_DIR / f"{project_name}{suffix}"
        if f.exists():
            try:
                f.unlink()
            except Exception as e:
                log.warning(f"Falha ao remover {f}: {e}")
    return jsonify({"status": "deleted", "project": project_name})

# ------------------------- Chat (with Orchestrator) -------------------------
@api_bp.route("/projects/<project_name>/chat", methods=["POST"])
@require_api_key
@rate_limit
def chat(project_name):
    try:
        body = request.json or {}
        user_message = _validate_message(body.get("message", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    project_data = load_project(project_name)
    messages = project_data["messages"]
    model = project_data["model"]
    messages.append({"role": "user", "content": user_message})

    try:
        assistant_response = generate_response(messages, model)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    is_final = "[FINALIZANDO SDD]" in assistant_response
    sdd_content = None
    sdd_path = None
    orch_result = None

    if is_final:
        from orchestrator import _extract_sdd
        from validator import Validator
        sdd_content = _extract_sdd(assistant_response) or None
        if sdd_content:
            from scorer import Scorer as _Scorer
            score   = _Scorer.score(sdd_content)
            validation = Validator.validate(sdd_content)
            orch_result = {
                "response":   assistant_response,
                "sdd":        sdd_content,
                "score":      score,
                "validation": validation,
                "status":     "approved" if (validation["valid"] and score >= QUALITY_THRESHOLD) else "needs_review",
                "cycles":     1,
            }
            project_data["status"] = "finalizado"
            sdd_path = save_sdd(project_name, sdd_content, project_data)
        else:
            sdd_content = None

    messages.append({"role": "assistant", "content": assistant_response})
    save_project(project_name, project_data)

    response_payload = {
        "project": project_name,
        "response": assistant_response,
        "is_final": is_final,
        "sdd_path": sdd_path,
        "sdd_content": sdd_content,
    }
    if orch_result:
        response_payload["orchestrator"] = {
            "score": orch_result["score"],
            "max_score": Scorer.MAX_SCORE,
            "status": orch_result["status"],
            "cycles": orch_result["cycles"],
            "validation": orch_result["validation"],
            "breakdown": Scorer.breakdown(orch_result.get("sdd", "")),
        }
    return jsonify(response_payload)

# ------------------------- Direct Generation -------------------------
@api_bp.route("/generate", methods=["POST"])
@require_api_key
@rate_limit
def generate_sdd():
    body = request.json or {}
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Campo 'prompt' obrigatório"}), 400
    model = body.get("model", DEFAULT_MODEL)
    if model not in AVAILABLE_MODELS:
        return jsonify({"error": f"Modelo inválido. Escolha: {AVAILABLE_MODELS}"}), 400

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    orch = Orchestrator(model)
    result = orch.run(messages)
    project_id = sha256(prompt.encode()).hexdigest()[:16]
    return jsonify({
        "project_id": project_id,
        "sdd": result["sdd"],
        "score": result["score"],
        "max_score": Scorer.MAX_SCORE,
        "status": result["status"],
        "cycles": result["cycles"],
        "validation": result["validation"],
        "breakdown": Scorer.breakdown(result.get("sdd", "")),
    })

# ------------------------- Regenerate -------------------------
@api_bp.route("/projects/<project_name>/regenerate-sdd", methods=["POST"])
@require_api_key
@rate_limit
def regenerate_sdd(project_name):
    project_data = load_project(project_name)
    if not project_data["messages"]:
        return jsonify({"error": "Projeto sem histórico"}), 400

    # Usa PromptEngine para forçar geração do SDD
    force_prompt = PromptEngine.force_generation()
    regen_messages = project_data["messages"] + [{
        "role": "user",
        "content": force_prompt
    }]

    orch = Orchestrator(project_data["model"])

    try:
        result = orch.run(regen_messages)
    except RuntimeError as e:
        log.error(f"regenerate_sdd falhou para '{project_name}': {e}")
        return jsonify({"error": str(e)}), 503

    sdd_path = None
    if result["sdd"]:
        sdd_path = save_sdd(project_name, result["sdd"], project_data)
        project_data["status"] = "finalizado"
        save_project(project_name, project_data)

    return jsonify({
        "project": project_name,
        "sdd_content": result["sdd"],
        "sdd_path": sdd_path,
        "score": result["score"],
        "max_score": Scorer.MAX_SCORE,
        "status": result["status"],
        "cycles": result["cycles"],
        "validation": result["validation"],
        "breakdown": Scorer.breakdown(result.get("sdd", "")),
    })

# ------------------------- Export PDF -------------------------
@api_bp.route("/projects/<project_name>/sdd/pdf", methods=["GET"])
@require_api_key
@rate_limit
def export_sdd_pdf(project_name):
    """
    Exporta o SDD do projeto como PDF.
    Suporta renderização de diagramas Mermaid via Playwright (modo headless).
    Caso o Playwright não esteja disponível, utiliza WeasyPrint (sem diagramas).
    """
    # 1. Buscar o conteúdo do SDD
    sdd_content = None
    project_data = load_project(project_name)

    # Tenta buscar do Supabase primeiro
    if project_data.get("id"):
        sb = get_supabase()
        if sb:
            try:
                result = (
                    sb.table("sdds")
                    .select("content")
                    .eq("project_id", project_data["id"])
                    .order("version", desc=True)
                    .limit(1)
                    .execute()
                )
                if result.data:
                    sdd_content = result.data[0]["content"]
            except Exception as e:
                log.warning(f"Erro ao buscar SDD do Supabase: {e}")

    # Fallback para arquivo local
    if not sdd_content:
        md_file = PROJECTS_DIR / f"{project_name}_SDD.md"
        if md_file.exists():
            try:
                sdd_content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                log.error(f"Erro ao ler arquivo local {md_file}: {e}")

    if not sdd_content:
        return jsonify({"error": "Nenhum SDD encontrado para este projeto"}), 404

    # 2. Converter Markdown para HTML
    try:
        import markdown

        html_body = markdown.markdown(
            sdd_content,
            extensions=[
                "tables",
                "fenced_code",
                "codehilite",
                "toc",
                "nl2br",
                "sane_lists",
            ],
        )

        def convert_mermaid_blocks(html):
            """Converte <pre><code class="language-mermaid"> para <pre class="mermaid">
            para que o Mermaid.js detecte e renderize os diagramas corretamente."""
            pattern = re.compile(
                r'<pre><code class="language-mermaid">(.*?)</code></pre>', re.DOTALL
            )
            return pattern.sub(r'<pre class="mermaid">\1</pre>', html)

        html_body = convert_mermaid_blocks(html_body)

    except ImportError:
        # Fallback mínimo: exibir como texto pré-formatado
        html_body = f"<pre>{sdd_content}</pre>"

    # 3. Renderizar HTML completo com template Jinja2
    try:
        html_content = render_template_string(
            PDF_HTML_TEMPLATE, title=f"SDD - {project_name}", content=html_body
        )
    except Exception as e:
        log.exception("Erro ao renderizar template HTML")
        return jsonify({"error": f"Erro ao preparar HTML: {str(e)}"}), 500

    # 4. Gerar PDF
    pdf_bytes = None

    # Tentativa principal: Playwright (recomendado — suporta Mermaid via JS)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.set_content(html_content, wait_until="networkidle")

            # Aguarda o módulo Mermaid carregar e executa a renderização
            page.wait_for_function("typeof window.renderMermaid === 'function'", timeout=5000)
            page.evaluate("window.renderMermaid()")
            # Pausa para garantir que os diagramas SVG sejam desenhados
            page.wait_for_timeout(1500)

            pdf_bytes = page.pdf(
                format="A4",
                margin={"top": "20mm", "right": "15mm", "bottom": "20mm", "left": "15mm"},
                print_background=True,
            )
            browser.close()
            log.info(f"PDF gerado com Playwright para projeto '{project_name}'")

    except ImportError:
        log.warning(
            "Playwright não instalado. Utilizando WeasyPrint "
            "(diagramas Mermaid não serão renderizados)."
        )
    except Exception as e:
        log.error(
            f"Falha ao gerar PDF com Playwright para '{project_name}': {e}. "
            "Tentando fallback WeasyPrint."
        )

    # Fallback: WeasyPrint (não executa JS — diagramas Mermaid ficam em branco)
    if pdf_bytes is None:
        try:
            from weasyprint import HTML

            pdf_file = io.BytesIO()
            HTML(string=html_content).write_pdf(pdf_file)
            pdf_bytes = pdf_file.getvalue()
            log.info(f"PDF gerado com WeasyPrint para projeto '{project_name}'")

        except ImportError:
            return (
                jsonify(
                    {
                        "error": (
                            "Nenhuma biblioteca de PDF disponível. "
                            "Instale 'playwright' ou 'weasyprint'."
                        )
                    }
                ),
                500,
            )
        except Exception as e:
            log.exception("Erro ao gerar PDF com WeasyPrint")
            return jsonify({"error": f"Falha na geração do PDF: {str(e)}"}), 500

    # 5. Enviar o arquivo PDF ao cliente
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{project_name}_SDD.pdf",
    )

# ------------------------- Analytics -------------------------
@api_bp.route("/analytics", methods=["GET"])
@require_api_key
@rate_limit
def analytics():
    sb = get_supabase()
    if not sb:
        return jsonify({"error": "Supabase não configurado"}), 503
    try:
        result = sb.table("v_projects_summary").select("*").order("updated_at", desc=True).execute()
        projects = result.data or []
        total = len(projects)
        finalized = sum(1 for p in projects if p.get("status") == "finalizado")
        return jsonify({
            "total_projects": total,
            "finalizados": finalized,
            "em_andamento": total - finalized,
            "projects": projects,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------------------- Health -------------------------
@api_bp.route("/health", methods=["GET"])
def health():
    groq_ok = bool(GROQ_API_KEY)
    sb = get_supabase()
    sb_ok = False
    if sb:
        try:
            sb.table("projects").select("id").limit(1).execute()
            sb_ok = True
        except Exception:
            pass
    redis_ok = False
    from cache import _redis_client
    if _redis_client:
        try:
            _redis_client.ping()
            redis_ok = True
        except Exception:
            pass
    status_code = 200 if groq_ok else 503
    return jsonify({
        "status": "ok" if groq_ok else "missing_groq_key",
        "version": "4.1",
        "groq_key": "configurada" if groq_ok else "AUSENTE",
        "supabase": "conectado" if sb_ok else "não configurado / erro",
        "redis": "conectado" if redis_ok else "não configurado (cache em memória)",
        "model": DEFAULT_MODEL,
        "quality_threshold": QUALITY_THRESHOLD,
        "quality_max_score": Scorer.MAX_SCORE,
        "storage": "supabase+local" if sb_ok else "local_only",
        "cache": {
            "backend": "redis" if redis_ok else "memory",
            "ttl_seconds": CACHE_TTL,
            "current_size": "gerenciado pelo Redis" if _redis_client else len(CACHE),
        },
        "time": datetime.now().isoformat(),
    }), status_code

# ------------------------- Frontend -------------------------
@api_bp.route("/")
def index():
    return render_template("index.html")