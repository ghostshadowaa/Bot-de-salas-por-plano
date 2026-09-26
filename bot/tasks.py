import discord
from datetime import datetime,timezone
from discord.ext import tasks
from .db import pending_broadcasts,mark_broadcast_sent,get_key,get_config,db

def start_background(bot):
    @tasks.loop(minutes=1)
    async def worker():
        for item in pending_broadcasts():
            for guild in bot.guilds:
                k=get_key(guild.id)
                if not k:continue
                cfg=get_config(guild.id)
                channel_id=cfg.get("notify_channel_id")
                if channel_id:
                    channel=guild.get_channel(int(channel_id))
                    if channel:
                        try:await channel.send(f"📢 **Aviso Shadow Salas**\n{item['message']}")
                        except discord.HTTPException:pass
                try:await guild.owner.send(f"📢 **Aviso Shadow Salas — {guild.name}**\n{item['message']}")
                except discord.HTTPException:pass
            mark_broadcast_sent(item["id"])

        for guild in bot.guilds:
            k=get_key(guild.id)
            if not k:continue
            expires=k["key"].get("expires_at")
            if not expires:continue
            dt=datetime.fromisoformat(expires.replace("Z","+00:00"))
            hours=(dt-datetime.now(timezone.utc)).total_seconds()/3600
            cfg=get_config(guild.id)
            warning=cfg.get("expiry_warning")
            level="3d" if hours<=72 else "1d" if hours<=24 else None
            if level and warning!=level:
                msg=f"⚠️ Seu plano expira em aproximadamente {'3 dias' if level=='3d' else '24 horas'}."
                channel_id=cfg.get("notify_channel_id")
                channel=guild.get_channel(int(channel_id)) if channel_id else None
                if channel:
                    try:await channel.send(msg)
                    except discord.HTTPException:pass
                try:await guild.owner.send(f"{msg} Servidor: {guild.name}")
                except discord.HTTPException:pass
                db.table("guild_config").upsert({"guild_id":str(guild.id),"expiry_warning":level},on_conflict="guild_id").execute()
    worker.start()
    return worker
