import discord
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from discord import app_commands
from discord.ext import commands
from .config import DISCORD_TOKEN
from .db import get_key, activate_key, get_config, save_config, register_guild, usage, add_usage
from .nix_api import NixAPI, NixAPIError
from .tasks import start_background

MODES = {
    "cs1": "ap_padrao", "cs2": "gelo_inf", "cs3": "tatico",
    "cs4": "ap_fullcapa", "cs5": "capa_3", "cs6": "ap_uxd", "cs7": "ap_7r"
}

# Configuração fixa das salas Shadow Salas
ROOM_PASSWORD = "00"
ROOM_DELAY = 1
ROOM_MAP = "Bermuda"
ROOM_NAME = "Shadow Salas"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents)
nix = NixAPI()
worker_started = False


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"status":"online","service":"shadow-salas-bot"}')

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


threading.Thread(target=start_health_server, daemon=True).start()


async def permission(interaction):
    key = get_key(interaction.guild.id)
    if not key:
        return None, "Nenhum plano ativo. Use /ativar."

    plan = key.get("plan") or {}
    cfg = get_config(interaction.guild.id)
    role = cfg.get("room_role_id")
    unlimited = bool(role and any(r.id == int(role) for r in interaction.user.roles))
    limit = plan.get("room_limit")

    if not unlimited and limit is not None and usage(interaction.guild.id, key["key"]["id"]) >= limit:
        return None, f"Limite atingido: {limit} salas."

    return key, None


async def create(interaction, mode):
    await interaction.response.defer(ephemeral=True)

    key, err = await permission(interaction)
    if err:
        return await interaction.followup.send(err, ephemeral=True)

    data = {
        "password": ROOM_PASSWORD,
        "start_delay_minutes": ROOM_DELAY,
        "config_type": mode,
        "map_name": ROOM_MAP,
        "room_name": ROOM_NAME,
    }

    try:
        result = await nix.create_room(data)
        add_usage(interaction.guild.id, key["key"]["id"])

        embed = discord.Embed(title="🎮 Shadow Salas", color=0x7C3AED)
        embed.add_field(
            name="Sala",
            value=str(result.get("room_id") or result.get("session_id")),
            inline=True,
        )
        embed.add_field(
            name="Senha",
            value=ROOM_PASSWORD,
            inline=True,
        )
        embed.add_field(
            name="Mapa",
            value=ROOM_MAP,
            inline=True,
        )
        embed.add_field(
            name="Nome",
            value=ROOM_NAME,
            inline=True,
        )
        embed.add_field(
            name="Delay",
            value=f"{ROOM_DELAY} min",
            inline=True,
        )

        if result.get("region"):
            embed.add_field(name="Região", value=str(result["region"]), inline=True)

        if result.get("invite_link"):
            embed.add_field(name="Link", value=result["invite_link"], inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    except NixAPIError as exc:
        await interaction.followup.send(f"❌ Nix: {exc}", ephemeral=True)


async def slash_room(interaction: discord.Interaction):
    mode = MODES[interaction.command.name]
    await create(interaction, mode)


async def prefix_room(ctx):
    if ctx.guild is None:
        return await ctx.send("Use este comando dentro de um servidor.")

    key = get_key(ctx.guild.id)
    if not key:
        return await ctx.send("Nenhum plano ativo. Use /ativar.")

    plan = key.get("plan") or {}
    cfg = get_config(ctx.guild.id)
    role = cfg.get("room_role_id")
    unlimited = bool(role and any(r.id == int(role) for r in ctx.author.roles))
    limit = plan.get("room_limit")

    if not unlimited and limit is not None and usage(ctx.guild.id, key["key"]["id"]) >= limit:
        return await ctx.send(f"Limite atingido: {limit} salas.")

    mode = MODES[ctx.invoked_with.lower()]
    data = {
        "password": ROOM_PASSWORD,
        "start_delay_minutes": ROOM_DELAY,
        "config_type": mode,
        "map_name": ROOM_MAP,
        "room_name": ROOM_NAME,
    }

    try:
        result = await nix.create_room(data)
        add_usage(ctx.guild.id, key["key"]["id"])

        embed = discord.Embed(title="🎮 Shadow Salas", color=0x7C3AED)
        embed.add_field(name="Sala", value=str(result.get("room_id") or result.get("session_id")), inline=True)
        embed.add_field(name="Senha", value=ROOM_PASSWORD, inline=True)
        embed.add_field(name="Mapa", value=ROOM_MAP, inline=True)
        embed.add_field(name="Nome", value=ROOM_NAME, inline=True)
        embed.add_field(name="Delay", value=f"{ROOM_DELAY} min", inline=True)

        if result.get("region"):
            embed.add_field(name="Região", value=str(result["region"]), inline=True)
        if result.get("invite_link"):
            embed.add_field(name="Link", value=result["invite_link"], inline=False)

        await ctx.send(embed=embed)

    except NixAPIError as exc:
        await ctx.send(f"❌ Nix: {exc}")


# Comandos slash /cs1 até /cs7 e prefixo .cs1 até .cs7.
for name in MODES:
    command = app_commands.Command(
        name=name,
        description=f"Cria uma sala {name.upper()} com configuração Shadow Salas.",
        callback=slash_room,
    )
    bot.tree.add_command(command)

    bot.command(name)(prefix_room)


@bot.tree.command(name="ativar", description="Ativa uma key neste servidor.")
@app_commands.describe(key="Chave recebida")
async def ativar(interaction: discord.Interaction, key: str):
    if not interaction.guild:
        return await interaction.response.send_message("Use em um servidor.", ephemeral=True)
    if interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("Somente o dono pode ativar.", ephemeral=True)

    k, err = activate_key(interaction.guild.id, key)
    if err:
        return await interaction.response.send_message("❌ Key inválida, inativa ou expirada.", ephemeral=True)

    plan = k.get("plans") or {}
    await interaction.response.send_message(
        f"✅ Plano **{plan.get('name', 'Plano')}** ativado.",
        ephemeral=True,
    )


@bot.tree.command(name="config", description="Configura cargo autorizado e canal de avisos.")
@app_commands.describe(cargo="Cargo que pode criar sem limite", canal="Canal para avisos")
async def config_cmd(
    interaction: discord.Interaction,
    cargo: discord.Role = None,
    canal: discord.TextChannel = None,
):
    if interaction.user.id != interaction.guild.owner_id:
        return await interaction.response.send_message("Somente o dono pode configurar.", ephemeral=True)

    save_config(
        interaction.guild.id,
        cargo.id if cargo else None,
        canal.id if canal else None,
    )
    await interaction.response.send_message("⚙️ Configuração salva.", ephemeral=True)


@bot.tree.command(name="statusplano", description="Mostra o plano e o uso atual.")
async def status(interaction: discord.Interaction):
    key = get_key(interaction.guild.id)
    if not key:
        return await interaction.response.send_message("Nenhum plano ativo.", ephemeral=True)

    plan = key.get("plan") or {}
    used = usage(interaction.guild.id, key["key"]["id"])
    limit = plan.get("room_limit")

    await interaction.response.send_message(
        f"**{plan.get('name', 'Plano')}**\n"
        f"Salas: {used}/{limit if limit is not None else '∞'}\n"
        f"Expira: {key['key'].get('expires_at', '—')}",
        ephemeral=True,
    )


@bot.event
async def on_ready():
    global worker_started

    for guild in bot.guilds:
        register_guild(guild)

    await bot.tree.sync()

    if not worker_started:
        start_background(bot)
        worker_started = True

    print(f"Shadow Salas online como {bot.user} em {len(bot.guilds)} servidores.")


@bot.event
async def on_guild_join(guild):
    register_guild(guild)


bot.run(DISCORD_TOKEN)
