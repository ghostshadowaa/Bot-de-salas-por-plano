import discord
from discord.ext import tasks
from .db import pending_broadcasts,mark_broadcast_sent,get_key,get_config

def start_background(bot):
    @tasks.loop(minutes=1)
    async def worker():
        for item in pending_broadcasts():
            for guild in bot.guilds:
                k=get_key(guild.id)
                if not k: continue
                cfg=get_config(guild.id)
                channel_id=cfg.get("notify_channel_id")
                if channel_id:
                    channel=guild.get_channel(int(channel_id))
                    if channel:
                        try: await channel.send(f"📢 **Aviso Shadow Salas**\n{item['message']}")
                        except discord.HTTPException: pass
                try:
                    await guild.owner.send(f"📢 **Aviso Shadow Salas — {guild.name}**\n{item['message']}")
                except discord.HTTPException: pass
            mark_broadcast_sent(item["id"])
    worker.start()
    return worker
