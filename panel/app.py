import os,secrets,string
from datetime import datetime,timezone,timedelta
from flask import Flask,request,redirect,session,render_template
from werkzeug.security import check_password_hash
from bot.config import PANEL_USERNAME,PANEL_PASSWORD_HASH
from bot.db import db

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(32))

def ok(): return session.get("admin") is True

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
def logout(): session.clear(); return redirect("/painel-login")

@app.route("/painel")
def painel():
    if not ok(): return redirect("/painel-login")
    plans=db.table("plans").select("*").eq("active",True).order("id").execute().data
    keys=db.table("keys").select("*, plans(name,room_limit)").order("created_at",desc=True).execute().data
    guilds=db.table("guilds").select("*").order("name").execute().data
    return render_template("dashboard.html",plans=plans,keys=keys,guilds=guilds)

@app.route("/painel/keys",methods=["POST"])
def new_key():
    if not ok(): return redirect("/painel-login")
    plan_id=int(request.form["plan_id"])
    rows=db.table("plans").select("*").eq("id",plan_id).limit(1).execute().data
    if not rows:return redirect("/painel")
    p=rows[0]
    value="SHADOW-"+"-".join("".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(4)) for _ in range(3))
    expires=(datetime.now(timezone.utc)+timedelta(days=p["duration_days"])).isoformat()
    db.table("keys").insert({"key":value,"plan_id":plan_id,"expires_at":expires,"active":True}).execute()
    return redirect("/painel")

@app.route("/painel/keys/<int:key_id>/toggle",methods=["POST"])
def toggle(key_id):
    if not ok():return redirect("/painel-login")
    r=db.table("keys").select("active").eq("id",key_id).limit(1).execute()
    if r.data:db.table("keys").update({"active":not r.data[0]["active"]}).eq("id",key_id).execute()
    return redirect("/painel")

@app.route("/painel/broadcast",methods=["POST"])
def broadcast():
    if not ok():return redirect("/painel-login")
    db.table("broadcasts").insert({"message":request.form["message"]}).execute()
    return redirect("/painel")

@app.route("/health")
def health():return {"status":"ok"}
