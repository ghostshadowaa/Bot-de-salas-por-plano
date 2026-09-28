import hashlib
import os
import secrets
import time
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for
from supabase import create_client
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-render")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
NIX_API_TOKEN = os.environ.get("NIX_API_TOKEN", "")
NIX_ROOMS_URL = os.environ.get("NIX_ROOMS_URL", "https://salas.nixbot.vip/rooms")
NIX_AUTH_HEADER = os.environ.get("NIX_AUTH_HEADER", "Authorization")
NIX_AUTH_PREFIX = os.environ.get("NIX_AUTH_PREFIX", "Bearer ")
ADMIN_USERNAME = os.environ.get("PANEL_USERNAME", os.environ.get("ADMIN_USERNAME", "Shadow"))
ADMIN_PASSWORD_HASH = os.environ.get("PANEL_PASSWORD_HASH", os.environ.get("ADMIN_PASSWORD_HASH", ""))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL e SUPABASE_KEY precisam estar configurados.")

db = create_client(SUPABASE_URL, SUPABASE_KEY)

LOGIN_HTML = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{background:#0b0712;color:#eee;font-family:Arial;max-width:1100px;margin:30px auto;padding:15px}.card{background:#151020;border:1px solid #392450;border-radius:16px;padding:18px;margin:12px 0}input,button{padding:11px;margin:5px;border-radius:9px;background:#100b16;color:#fff;border:1px solid #493461}button{background:#7c3aed}.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.muted{color:#aaa}.key{word-break:break-all;color:#c4b5fd}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style><style>
*{box-sizing:border-box}body{margin:0;background:#08060d;color:#f5f3ff;font-family:Inter,system-ui,Arial;min-height:100vh}body{max-width:1200px;margin:auto;padding:22px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}a{color:#c4b5fd;text-decoration:none}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.card{background:#110d1b;border:1px solid #292033;border-radius:18px;padding:18px;margin:12px 0}.grid>.card{margin:0}input,button{padding:11px 13px;margin:5px 0;border-radius:10px;background:#0b0710;color:#fff;border:1px solid #3a2d48}input{width:100%}button{background:#7c3aed;cursor:pointer;font-weight:700}.muted{color:#a49caf}.key{word-break:break-all;color:#c4b5fd}.badge{padding:4px 8px;border-radius:20px;background:#173b27;color:#8ef0b1;font-size:12px}.danger{background:#642236}.row{display:flex;gap:10px;align-items:center;justify-content:space-between}.actions{display:flex;gap:7px;flex-wrap:wrap}.item{border-top:1px solid #292033;padding:14px 0}.item:first-child{border-top:0}.stat{font-size:28px;font-weight:800}@media(max-width:700px){.grid{grid-template-columns:1fr}body{padding:12px}}
</style><body><div class="card"><h2>Shadow API</h2><p class="muted">Painel administrativo</p><form method="post"><input name="username" placeholder="Usuário" required><input name="password" type="password" placeholder="Senha" required><button>Entrar</button></form>{% if error %}<p>{{error}}</p>{% endif %}</div></body></html>"""

DASHBOARD_HTML = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body>
<header><div><h1>🟣 Shadow API</h1><p class="muted">Painel de controle</p></div><a href="/admin/logout">Sair</a></header>
<div class="grid">
<div class="card"><h2>Criar chave</h2><form method="post" action="/admin/keys"><input name="label" placeholder="Nome do cliente" required><div><button type="button" onclick="d(1)">1 dia</button><button type="button" onclick="d(7)">1 semana</button><button type="button" onclick="d(30)">1 mês</button></div><input type="hidden" name="days" id="days" value="1"><input name="owner_user_id" placeholder="Discord User ID do dono"><input name="max_rooms" type="number" min="0" placeholder="Limite de salas (0 = ilimitado)"><button>Criar chave</button></form></div>
<div class="card"><h2>Produtos AG Solutions</h2><p class="muted">O product_id recebido no POST escolhe a duração.</p><form method="post" action="/admin/products"><input name="product_id" placeholder="ID do produto" required><input name="name" placeholder="Nome do produto" required><input name="duration_days" type="number" min="1" placeholder="Dias" required><button>Salvar produto</button></form>{% for p in products %}<p><b>{{p.name}}</b> — ID <span class="key">{{p.product_id}}</span> — {{p.duration_days}} dias — {{'ativo' if p.active else 'pausado'}} <form method="post" action="/admin/products/{{p.id}}/toggle"><button>Alternar</button></form></p>{% endfor %}</div>
</div>
{% if new_key %}<div class="card"><h2>🔑 Chave criada</h2><p class="key">{{new_key}}</p><button onclick="navigator.clipboard.writeText({{new_key|tojson}})">Copiar</button></div>{% endif %}
<div class="card"><h2>Chaves</h2>{% for k in keys %}<div class="card"><b>{{k.label}}</b> — {{'ATIVA' if k.active else 'PAUSADA'}}<br><span class="muted">Dono: {{k.owner_user_id or '—'}} · Produto: {{k.product_id or 'manual'}} · Expira: {{k.expires_at or '—'}}</span><br><span class="key">{{k.key_prefix}}••••••••</span><form method="post" action="/admin/keys/{{k.id}}/renew"><button>Renovar 30d</button></form><form method="post" action="/admin/keys/{{k.id}}/toggle"><button>{{'Ativar' if not k.active else 'Pausar'}}</button></form><form method="post" action="/admin/keys/{{k.id}}/delete"><button>Excluir</button></form></div>{% else %}<p>Nenhuma chave.</p>{% endfor %}</div>
<div class="card"><h2>Últimas vendas</h2>{% for s in sales %}<p><b>Produto:</b> {{s.product_id}} · <b>Dono:</b> {{s.buyer_user_id or '—'}} · <b>Chave:</b> {{s.api_key_id or '—'}} · {{s.status}}</p>{% else %}<p>Nenhuma venda.</p>{% endfor %}</div>
<script>function d(x){document.getElementById('days').value=x}</script></body></html>"""

def now(): return datetime.now(timezone.utc)
def iso(x): return x.isoformat()
def hash_key(x): return hashlib.sha256(x.encode()).hexdigest()
def make_key(): return "sk_" + secrets.token_urlsafe(30)
def valid_key(k):
    if not k or not k.get("active"): return False
    if not k.get("expires_at"): return True
    try: return datetime.fromisoformat(k["expires_at"].replace("Z","+00:00")) > now()
    except ValueError: return False
def body(): return request.get_json(silent=True) or {}
def get_path(data, paths):
    for path in paths:
        x=data
        for part in path.split("."):
            if not isinstance(x,dict) or part not in x: x=None; break
            x=x[part]
        if x not in (None,""): return x
    return None
def extract_sales(data):
    """
    Formato real da AG Solutions:
    data.order é um objeto onde cada chave é o ID do produto.
    Cada produto possui amount, productId, totalDays, totalPrice etc.
    """
    root = data.get("data") or {}
    order = root.get("order") or {}
    user = root.get("user") or {}
    guild = root.get("guild") or {}

    if not isinstance(order, dict):
        return []

    sales = []
    for order_key, item in order.items():
        if not isinstance(item, dict):
            continue

        product_id = item.get("productId") or order_key
        if not product_id:
            continue

        sales.append({
            "product_id": str(product_id),
            "buyer_user_id": str(user.get("id")) if user.get("id") else None,
            "buyer_name": user.get("name"),
            "guild_id": str(guild.get("id")) if guild.get("id") else None,
            "guild_name": guild.get("name"),
            "amount": item.get("totalPrice"),
            "quantity": item.get("amount", 1),
            "duration_days": item.get("totalDays") or item.get("unitDays"),
            "product_name": item.get("name"),
            "status": "paid" if data.get("type") == "payment" else str(data.get("type") or "unknown").lower(),
        })

    return sales

def authorized():
    secret=os.environ.get("AG_SOLUTIONS_WEBHOOK_SECRET", os.environ.get("OLIVERY_WEBHOOK_SECRET",""))
    supplied=request.headers.get("X-Automation-Secret","")
    if not supplied and request.headers.get("Authorization","").lower().startswith("bearer "): supplied=request.headers["Authorization"][7:].strip()
    return bool(secret) and secrets.compare_digest(supplied,secret)
def create_key(label,days,owner=None,product=None,max_rooms=None):
    raw=make_key(); t=now()
    row={"label":label,"key_prefix":raw[:12],"key_hash":hash_key(raw),"active":True,"created_at":iso(t),"expires_at":iso(t+timedelta(days=days)),"max_rooms":max_rooms,"rooms_used":0,"rate_limit_per_minute":30,"owner_user_id":str(owner) if owner else None,"product_id":str(product) if product else None}
    r=db.table("api_keys").insert(row).execute()
    return raw,r.data[0]
def log_event(kid,typ,code,payload,response=None):
    db.table("api_key_events").insert({"api_key_id":kid,"event_type":typ,"endpoint":request.path,"status_code":code,"request_body":payload,"response_body":response}).execute()

@app.get("/")
@app.get("/admin/")
def home():
    if session.get("admin"):
        return redirect("/admin")
    return render_template_string(LOGIN_HTML, error=None)
@app.get("/health")
def health(): return jsonify({"ok":True})
@app.post("/v1/rooms")
def rooms():
    raw=request.headers.get("X-API-Key","").strip()
    if not raw:return jsonify({"error":"X-API-Key ausente"}),401
    r=db.table("api_keys").select("*").eq("key_hash",hash_key(raw)).limit(1).execute(); k=(r.data or [None])[0]
    if not valid_key(k): return jsonify({"error":"API key inválida, pausada ou expirada"}),401
    if k.get("max_rooms") is not None and k.get("rooms_used",0)>=k["max_rooms"]: return jsonify({"error":"Limite de salas atingido"}),403
    payload=body()
    try:
        u=requests.post(NIX_ROOMS_URL,json=payload,headers={NIX_AUTH_HEADER:NIX_AUTH_PREFIX+NIX_API_TOKEN},timeout=30)
        try: out=u.json()
        except ValueError: out={"raw":u.text[:4000]}
        log_event(k["id"],"room_request",u.status_code,payload,out)
        if 200<=u.status_code<300: db.table("api_keys").update({"rooms_used":int(k.get("rooms_used") or 0)+1,"last_used_at":iso(now())}).eq("id",k["id"]).execute()
        return jsonify(out),u.status_code
    except requests.RequestException:
        return jsonify({"error":"Falha ao comunicar com o provedor"}),502

@app.post("/")
@app.post("/automation/ag-solutions")
def ag_solutions_automation():
    if not authorized():
        return jsonify({"ok": False, "error": "Automação AG Solutions não autorizada"}), 401

    payload = body()
    sales = extract_sales(payload)

    if not sales:
        return jsonify({"ok": False, "error": "Nenhum produto encontrado em data.order"}), 400

    results = []

    for sale in sales:
        product_result = db.table("api_products").select("*").eq(
            "product_id", sale["product_id"]
        ).eq("active", True).limit(1).execute()
        product = (product_result.data or [None])[0]

        # Se o produto ainda não estiver configurado, registra a venda sem criar chave.
        if not product:
            row = {
                "external_sale_id": None,
                "product_id": sale["product_id"],
                "buyer_user_id": sale["buyer_user_id"],
                "status": "product_not_configured",
                "amount": sale["amount"],
                "currency": "BRL",
                "request_body": payload,
            }
            saved = db.table("api_sales").insert(row).execute()
            results.append({
                "ok": False,
                "product_id": sale["product_id"],
                "product_name": sale["product_name"],
                "error": "Produto não configurado no painel",
                "sale_id": (saved.data or [{}])[0].get("id"),
            })
            continue

        if not sale["buyer_user_id"]:
            results.append({
                "ok": False,
                "product_id": sale["product_id"],
                "error": "data.user.id não encontrado",
            })
            continue

        # A duração configurada no painel tem prioridade.
        days = int(product["duration_days"])
        raw_key, key = create_key(
            f"{product['name']} • {sale['buyer_user_id']}",
            days,
            sale["buyer_user_id"],
            sale["product_id"],
        )

        saved = db.table("api_sales").insert({
            "external_sale_id": None,
            "product_id": sale["product_id"],
            "buyer_user_id": sale["buyer_user_id"],
            "api_key_id": key["id"],
            "status": "paid",
            "amount": sale["amount"],
            "currency": "BRL",
            "request_body": payload,
        }).execute()

        results.append({
            "ok": True,
            "product_id": sale["product_id"],
            "product_name": product["name"],
            "buyer_user_id": sale["buyer_user_id"],
            "guild_id": sale["guild_id"],
            "api_key_id": key["id"],
            "api_key": raw_key,
            "duration_days": days,
            "sale_id": (saved.data or [{}])[0].get("id"),
        })

    return jsonify({
        "ok": all(x.get("ok") for x in results),
        "type": payload.get("type"),
        "buyer": (payload.get("data") or {}).get("user"),
        "results": results,
    }), 201 if any(x.get("ok") for x in results) else 422

@app.get("/admin/login/")
def login_slash():
    return login()

@app.get("/admin/login")
def login():
    if session.get("admin"): return redirect("/admin")
    return render_template_string(LOGIN_HTML,error=None)
@app.post("/admin/login")
def login_post():
    user=request.form.get("username",""); pwd=request.form.get("password",""); ok=False
    if ADMIN_PASSWORD_HASH: ok=check_password_hash(ADMIN_PASSWORD_HASH,pwd)
    elif ADMIN_PASSWORD: ok=secrets.compare_digest(pwd,ADMIN_PASSWORD)
    if user==ADMIN_USERNAME and ok: session["admin"]=True; return redirect("/admin")
    return render_template_string(LOGIN_HTML,error="Usuário ou senha inválidos."),401
@app.get("/admin/logout")
def logout(): session.clear(); return redirect("/admin/login")
def admin(): return session.get("admin") is True
@app.get("/admin")
def dashboard():
    if not admin(): return redirect("/admin/login")
    keys=db.table("api_keys").select("*").order("created_at",desc=True).execute().data or []
    products=db.table("api_products").select("*").order("created_at",desc=True).execute().data or []
    sales=db.table("api_sales").select("*").order("created_at",desc=True).limit(20).execute().data or []
    return render_template_string(DASHBOARD_HTML,keys=keys,products=products,sales=sales,active_count=sum(valid_key(k) for k in keys),new_key=session.pop("new_key",None))
@app.post("/admin/keys")
def admin_key():
    if not admin(): return redirect("/admin/login")
    days=max(1,int(request.form.get("days","1"))); label=request.form.get("label","Cliente").strip() or "Cliente"; owner=request.form.get("owner_user_id","").strip() or None
    mr=request.form.get("max_rooms","").strip(); max_rooms=int(mr) if mr else None
    if max_rooms==0:max_rooms=None
    raw,_=create_key(label,days,owner,None,max_rooms); session["new_key"]=raw; return redirect("/admin")
@app.post("/admin/products")
def admin_product():
    if not admin(): return redirect("/admin/login")
    db.table("api_products").upsert({"product_id":request.form["product_id"].strip(),"name":request.form["name"].strip() or "API","duration_days":max(1,int(request.form["duration_days"])),"active":True},on_conflict="product_id").execute()
    return redirect("/admin")
@app.post("/admin/products/<int:pid>/toggle")
def toggle_product(pid):
    if not admin(): return redirect("/admin/login")
    r=db.table("api_products").select("active").eq("id",pid).limit(1).execute(); current=(r.data or [{"active":False}])[0]["active"]
    db.table("api_products").update({"active":not current}).eq("id",pid).execute(); return redirect("/admin")
@app.post("/admin/keys/<int:kid>/renew")
def renew(kid):
    if not admin(): return redirect("/admin/login")
    r=db.table("api_keys").select("expires_at").eq("id",kid).limit(1).execute(); row=(r.data or [None])[0]
    if row:
        base=now()
        if row.get("expires_at"):
            try: base=max(base,datetime.fromisoformat(row["expires_at"].replace("Z","+00:00")))
            except ValueError: pass
        db.table("api_keys").update({"expires_at":iso(base+timedelta(days=30)),"active":True}).eq("id",kid).execute()
    return redirect("/admin")
@app.post("/admin/keys/<int:kid>/toggle")
def toggle_key(kid):
    if not admin(): return redirect("/admin/login")
    r=db.table("api_keys").select("active").eq("id",kid).limit(1).execute(); current=(r.data or [{"active":False}])[0]["active"]
    db.table("api_keys").update({"active":not current}).eq("id",kid).execute(); return redirect("/admin")
@app.post("/admin/keys/<int:kid>/delete")
def delete_key(kid):
    if not admin(): return redirect("/admin/login")
    db.table("api_keys").delete().eq("id",kid).execute(); return redirect("/admin")
if __name__=="__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT","10000")))
