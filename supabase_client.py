import json
import logging
from datetime import datetime
from pathlib import Path
from config import SUPABASE_URL, SUPABASE_KEY, PROJECTS_DIR, DEFAULT_MODEL

log = logging.getLogger("formalizeai")

_supabase_instance = None
SUPABASE_AVAILABLE = False

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    pass

def get_supabase():
    global _supabase_instance
    if _supabase_instance is not None:
        return _supabase_instance
    if not SUPABASE_AVAILABLE or not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        _supabase_instance = create_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase client inicializado")
        return _supabase_instance
    except Exception as e:
        log.warning(f"Falha ao conectar Supabase: {e}")
        return None

def _local_path(project_name: str) -> Path:
    return PROJECTS_DIR / f"{project_name}.json"

def load_project(project_name: str) -> dict:
    sb = get_supabase()
    if sb:
        try:
            proj = sb.table("projects").select("id, name, model, status, created_at, updated_at").eq("name", project_name).maybe_single().execute()
            if proj.data:
                project_id = proj.data["id"]
                msgs = sb.table("messages").select("role, content").eq("project_id", project_id).order("seq").execute()
                return {
                    "id": project_id,
                    "messages": [{"role": m["role"], "content": m["content"]} for m in (msgs.data or [])],
                    "model": proj.data["model"],
                    "status": proj.data["status"],
                    "created": proj.data["created_at"],
                    "_source": "supabase",
                }
        except Exception as e:
            log.warning(f"load_project Supabase falhou: {e}")

    local = _local_path(project_name)
    if local.exists():
        try:
            with open(local, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["_source"] = "local"
                return data
        except Exception as e:
            log.error(f"Erro ao ler {local}: {e}")

    return {
        "messages": [],
        "model": DEFAULT_MODEL,
        "status": "em_andamento",
        "created": datetime.now().isoformat(),
        "_source": "new",
    }

def save_project(project_name: str, data: dict) -> None:
    sb = get_supabase()
    project_id = data.get("id")

    if sb:
        try:
            messages = data.get("messages", [])
            if project_id:
                sb.table("projects").update({
                    "model": data.get("model", DEFAULT_MODEL),
                    "status": data.get("status", "em_andamento"),
                    "updated_at": datetime.now().isoformat(),
                }).eq("id", project_id).execute()
            else:
                result = sb.table("projects").insert({
                    "name": project_name,
                    "model": data.get("model", DEFAULT_MODEL),
                    "status": data.get("status", "em_andamento"),
                }).execute()
                if result.data:
                    project_id = result.data[0]["id"]
                    data["id"] = project_id

            if project_id and messages:
                rows = [{"project_id": project_id, "role": m["role"], "content": m["content"], "seq": i} for i, m in enumerate(messages)]
                sb.table("messages").delete().eq("project_id", project_id).execute()
                sb.table("messages").insert(rows).execute()
        except Exception as e:
            log.warning(f"save_project Supabase falhou: {e}")

    local = _local_path(project_name)
    try:
        with open(local, "w", encoding="utf-8") as f:
            clean = {k: v for k, v in data.items() if not k.startswith("_")}
            json.dump(clean, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"Erro ao salvar local {local}: {e}")

def save_sdd(project_name: str, sdd_content: str, data: dict) -> str:
    sb = get_supabase()
    project_id = data.get("id")

    if sb and project_id:
        try:
            result = sb.table("sdds").select("version").eq("project_id", project_id).order("version", desc=True).limit(1).execute()
            next_version = (result.data[0]["version"] + 1) if result.data else 1
            sb.table("sdds").insert({
                "project_id": project_id,
                "content": sdd_content,
                "version": next_version,
            }).execute()
            sb.table("projects").update({"status": "finalizado"}).eq("id", project_id).execute()
        except Exception as e:
            log.warning(f"save_sdd Supabase falhou: {e}")

    # FIX: try/except no write local — evita crash silencioso se /tmp sem espaço em disco
    md_file = PROJECTS_DIR / f"{project_name}_SDD.md"
    try:
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(sdd_content)
    except OSError as e:
        log.error(f"Falha ao salvar SDD local {md_file}: {e}")
    return str(md_file)