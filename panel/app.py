import os,secrets,string
from datetime import datetime,timezone,timedelta
from flask import Flask,request,redirect,session,render_template
from werkzeug.security import check_password_hash
from bot.config import PANEL_USERNAME,PANEL_PASSWORD_HASH
from bot.db import db

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(32))

def ok(): return session.get("admin") is True

def redirect_login(): return redirect("/painel-login")

@app.route("/")
def home(): return redirect("/painel")

@app.route("/painel-login",methods=["GET","POST"])
def login():
    error=None
    if request.method=="POST":
        if request.form.get("username")==PANEL_USERNAME and check_password_hash(PANEL_PASSWORD_HASH,request.form.get("password","")):
            session["admin"]=True
            return redirect("/painel")
        error="Usuário ou senha inválidos."
    return render_template("login.html",error=error)

@app.route("/logout")
def logout(): session.clear(); return redirect_login()

@app.route("/painel")
def painel():
    if not ok(): return redirect_login()
    plans=db.table("plans").select("*").eq("active",True).order("id").execute().data
    keys=db.table("keys").select("*, plans(name,room_limit)").order("created_at",desc=True).execute().data
    guilds=db.table("guilds").select("*").order("name").execute().data
    active_guild_keys=db.table("guild_keys").select("guild_id,key_id,active").eq("active",True).execute().data
    return render_template("dashboard.html",plans=plans,keys=keys,guilds=guilds,active_guild_keys=active_guild_keys)

@app.route("/painel/keys",methods=["POST"])
def new_key():
    if not ok(): return redirect_login()
    plan_id=int(request.form["plan_id"])
    rows=db.table("plans").select("*").eq("id",plan_id).eq("active",True).limit(1).execute().data
    if not rows:return redirect("/painel")
    p=rows[0]
    value="SHADOW-"+"-".join("".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(4)) for _ in range(3))
    expires=(datetime.now(timezone.utc)+timedelta(days=p["duration_days"])).isoformat()
    db.table("keys").insert({"key":value,"plan_id":plan_id,"expires_at":expires,"active":True}).execute()
    return redirect("/painel")

@app.route("/painel/keys/<int:key_id>/toggle",methods=["POST"])
def toggle(key_id):
    if not ok():return redirect_login()
    r=db.table("keys").select("active").eq("id",key_id).limit(1).execute()
    if r.data:db.table("keys").update({"active":not r.data[0]["active"]}).eq("id",key_id).execute()
    return redirect("/painel")

@app.route("/painel/keys/<int:key_id>/renew",methods=["POST"])
def renew(key_id):
    if not ok():return redirect_login()
    days=int(request.form.get("days","30"))
    if days not in (7,30,90): return redirect("/painel")
    r=db.table("keys").select("expires_at").eq("id",key_id).limit(1).execute()
    if r.data:
        current=r.data[0].get("expires_at")
        base=datetime.now(timezone.utc)
        if current:
            try: base=max(base,datetime.fromisoformat(current.replace("Z","+00:00")))
            except ValueError: pass
        db.table("keys").update({"expires_at":(base+timedelta(days=days)).isoformat(),"active":True}).eq("id",key_id).execute()
    return redirect("/painel")

@app.route("/painel/broadcast",methods=["POST"])
def broadcast():
    if not ok():return redirect_login()
    message=request.form.get("message","").strip()
    if message: db.table("broadcasts").insert({"message":message,"sent":False}).execute()
    return redirect("/painel")

@app.route("/health")
def health():return {"status":"ok"}
