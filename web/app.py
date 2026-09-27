import hashlib
import json
import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from supabase import create_client

app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
SHADOW_API_KEY = os.getenv("SHADOW_API_KEY", "").strip()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None


def unauthorized():
    return jsonify({"success": False, "message": "API key inválida."}), 401


def check_auth():
    # The API can run without a key while being configured.
    # In production, set SHADOW_API_KEY on Render.
    if not SHADOW_API_KEY:
        return True

    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {SHADOW_API_KEY}"


def make_event_id(event_type, payload):
    supplied = payload.get("event_id") or payload.get("id")
    if supplied:
        return f"{event_type}:{supplied}"

    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{event_type}:{digest}"


def receive_event(event_type, payload):
    if not check_auth():
        return unauthorized()

    if not isinstance(payload, dict):
        return jsonify({"success": False, "message": "O corpo deve ser um JSON."}), 400

    event_id = make_event_id(event_type, payload)

    if supabase is None:
        return jsonify({
            "success": False,
            "message": "API configurada, mas o Supabase não está configurado no ambiente."
        }), 503

    row = {
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = (
            supabase
            .table("api_events")
            .upsert(row, on_conflict="event_id")
            .execute()
        )

        return jsonify({
            "success": True,
            "message": "Evento recebido.",
            "event_id": event_id,
            "event_type": event_type,
            "stored": bool(result.data),
        }), 200

    except Exception as exc:
        app.logger.exception("Falha ao salvar evento %s", event_id)
        return jsonify({
            "success": False,
            "message": "Não foi possível registrar o evento.",
            "error": str(exc)[:300],
        }), 500


@app.get("/")
def home():
    return jsonify({
        "service": "shadow-salas-api",
        "status": "online",
        "endpoints": [
            "POST /api/v1/venda",
            "POST /api/v1/cargo",
            "GET /health",
        ],
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "online",
        "service": "shadow-salas-api",
        "supabase": "configured" if supabase else "missing",
        "api_key": "enabled" if SHADOW_API_KEY else "disabled",
    })


@app.post("/api/v1/venda")
def venda():
    payload = request.get_json(silent=True)
    return receive_event("venda", payload)


@app.post("/api/v1/cargo")
def cargo():
    payload = request.get_json(silent=True)
    return receive_event("cargo", payload)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
