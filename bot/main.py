import discord
from discord import app_commands
from discord.ext import commands
from .config import DISCORD_TOKEN
from .db import get_key,activate_key,get_config,save_config,register_guild,usage,add_usage
from .nix_api import NixAPI,NixAPIError
from .tasks import start_background

MODES={"cs1":"ap_padrao","cs2":"gelo_inf","cs3":"tatico","cs4":"ap_fullcapa","cs5":"capa_3","cs6":"ap_uxd","cs7":"ap_7r"}
intents=discord.Intents.default()
bot=commands.Bot(command_prefix="!",intents=intents)
nix=NixAPI()
worker_started=False

async def permission(interaction):
    k=get_key(interaction.guild.id)
    if not k:return None,"Nenhum plano ativo. Use /ativar."
    plan=k.get("plan") or {}; cfg=get_config(interaction.guild.id)
    role=cfg.get("room_role_id")
    unlimited=bool(role and any(r.id==int(role) for r in interaction.user.roles))
    limit=plan.get("room_limit")
    if not unlimited and limit is not None and usage(interaction.guild.id,k["key"]["id"])>=limit:
        return None,f"Limite atingido: {limit} salas."
    return k,None

async def create(interaction,mode,password,delay,mapa,nome="",**extra):
    await interaction.response.defer(ephemeral=True)
    k,err=await permission(interaction)
    if err:return await interaction.followup.send(err,ephemeral=True)
    data={"password":password,"start_delay_minutes":delay,"config_type":mode,"map_name":mapa}
    if nome:data["room_name"]=nome
    data.update(extra)
    try:
        result=await nix.create_room(data)
        add_usage(interaction.guild.id,k["key"]["id"])
        embed=discord.Embed(title="🎮 Sala criada",color=0x7c3aed)
        embed.add_field(name="Sala",value=str(result.get("room_id") or result.get("session_id")),inline=True)
        embed.add_field(name="Senha",value=str(result.get("password",password)),inline=True)
        embed.add_field(name="Região",value=str(result.get("region","—")),inline=True)
        if result.get("invite_link"):embed.add_field(name="Link",value=result["invite_link"],inline=False)
        await interaction.followup.send(embed=embed,ephemeral=True)
    except NixAPIError as e:
        await interaction.followup.send(f"❌ Nix: {e}",ephemeral=True)

async def cs_callback(interaction:discord.Interaction,password:str,delay:int=1,mapa:str="Bermuda",nome:str=""):
    await create(interaction,MODES[interaction.command.name],password,delay,mapa,nome)

for name in MODES:
    bot.tree.add_command(app_commands.Command(name=name,description=f"Cria uma sala {name.upper()}",callback=cs_callback))

@app_commands.command(name="br",description="Cria uma sala Battle Royale.")
async def br(interaction:discord.Interaction,password:str,delay:int=1,mapa:str="Bermuda",equipe:str="squad",espectadores:int=8,nome:str=""):
    await create(interaction,"br_padrao",password,delay,mapa,nome,equipe=equipe,espectadores=espectadores)
bot.tree.add_command(br)

@bot.tree.command(name="ativar",description="Ativa uma key neste servidor.")
@app_commands.describe(key="Chave recebida")
async def ativar(interaction:discord.Interaction,key:str):
    if not interaction.guild:return await interaction.response.send_message("Use em um servidor.",ephemeral=True)
    if interaction.user.id!=interaction.guild.owner_id:return await interaction.response.send_message("Somente o dono pode ativar.",ephemeral=True)
    k,err=activate_key(interaction.guild.id,key)
    if err:return await interaction.response.send_message("❌ Key inválida, inativa ou expirada.",ephemeral=True)
    await interaction.response.send_message(f"✅ Plano **{(k.get('plans') or {}).get('name','Plano')}** ativado.",ephemeral=True)

@bot.tree.command(name="config",description="Configura cargo autorizado e canal de avisos.")
@app_commands.describe(cargo="Cargo que pode criar sem limite",canal="Canal para avisos")
async def config_cmd(interaction:discord.Interaction,cargo:discord.Role=None,canal:discord.TextChannel=None):
    if interaction.user.id!=interaction.guild.owner_id:return await interaction.response.send_message("Somente o dono pode configurar.",ephemeral=True)
    save_config(interaction.guild.id,cargo.id if cargo else None,canal.id if canal else None)
    await interaction.response.send_message("⚙️ Configuração salva.",ephemeral=True)

@bot.tree.command(name="statusplano",description="Mostra o plano e o uso atual.")
async def status(interaction:discord.Interaction):
    k=get_key(interaction.guild.id)
    if not k:return await interaction.response.send_message("Nenhum plano ativo.",ephemeral=True)
    p=k.get("plan") or {}; used=usage(interaction.guild.id,k["key"]["id"]); limit=p.get("room_limit")
    await interaction.response.send_message(f"**{p.get('name','Plano')}**\nSalas: {used}/{limit if limit is not None else '∞'}\nExpira: {k['key'].get('expires_at','—')}",ephemeral=True)

@bot.event
async def on_ready():
    global worker_started
    for guild in bot.guilds:register_guild(guild)
    await bot.tree.sync()
    if not worker_started:
        start_background(bot)
        worker_started=True
    print(f"Shadow Salas online como {bot.user} em {len(bot.guilds)} servidores.")

@bot.event
async def on_guild_join(guild): register_guild(guild)

bot.run(DISCORD_TOKEN)
