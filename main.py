"""
╔══════════════════════════════════════════════════════════════╗
║          🎀 NORTH HOSPITAL CENTER — ASSISTENTE VIRTUAL 🎀    ║
║        IA, TICKETS MÉDICOS, ANÚNCIOS E PAINÉIS DINÂMICOS     ║
║  COMANDOS: /painel_config /painel_set /painel_atendimento    ║
║            /painel_anuncio /ia                               ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import datetime
import os
import re
import json
import logging

import aiohttp
import aiosqlite
import discord
import pytz
from discord import app_commands
from discord.ext import commands, tasks

# ──────────────────────────────────────────────────────────────
# 🌸 CONFIGURAÇÃO DE LOGGING E DICIONÁRIOS
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%d/%m/%Y %H:%M:%S'
)
logger = logging.getLogger('NorthBot')

# Dicionário exato com os IDs que você forneceu! 🎀
DEPARTAMENTOS = {
    "psicologia": {"nome": "Psicologia", "cat_id": 1511033530636042472, "role_id": 1511033526785675288, "emoji": "🧠"},
    "obstetricia": {"nome": "Obstetrícia", "cat_id": 1511033530636042473, "role_id": 1511033526785675286, "emoji": "👶"},
    "pediatria": {"nome": "Pediatria", "cat_id": 1511033530636042474, "role_id": 1511033526785675290, "emoji": "🧸"},
    "cirurgia": {"nome": "Cirurgia", "cat_id": 1511033530636042475, "role_id": 1511033526785675285, "emoji": "⚕️"},
    "clinico_geral": {"nome": "Clínico Geral", "cat_id": 1511033530636042476, "role_id": 1511033526785675287, "emoji": "🩺"}
}

# ──────────────────────────────────────────────────────────────
# ✨ CONFIGURAÇÃO DA IA (GOOGLE GENAI)
# ──────────────────────────────────────────────────────────────
from google import genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
gemini_client = None

if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info(f"Cliente Gemini configurado com sucesso! 🎀")
    except Exception as e:
        logger.error(f"Erro ao configurar Gemini: {e}")
else:
    logger.warning("Chave API Gemini não encontrada. A IA não funcionará.")

# ──────────────────────────────────────────────────────────────
# 🎀 CONFIGURAÇÃO DO BOT
# ──────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
DB    = os.environ.get("DB_PATH", "north.db")
BR_TZ = pytz.timezone("America/Sao_Paulo")

STOPWORDS_PTBR = {
    'para', 'como', 'por', 'com', 'uma', 'sobre', 'quando', 'onde', 'qual', 'mais', 'muito', 'pode', 'isso',
    'você', 'aqui', 'este', 'esta', 'está', 'fazer', 'também', 'pelo', 'pela', 'dos', 'das', 'nas', 'nos'
}

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ──────────────────────────────────────────────────────────────
# 💖 GERENCIADOR DE BANCO DE DADOS
# ──────────────────────────────────────────────────────────────
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = None

    async def connect(self):
        if not self.conn:
            db_dir = os.path.dirname(os.path.abspath(self.db_path))
            if db_dir: os.makedirs(db_dir, exist_ok=True)
            self.conn = await aiosqlite.connect(self.db_path)
            
    async def execute(self, query, params=()):
        await self.connect()
        return await self.conn.execute(query, params)

    async def executescript(self, script):
        await self.connect()
        await self.conn.executescript(script)

    async def commit(self):
        if self.conn: await self.conn.commit()

    async def fetchone(self, query, params=()):
        await self.connect()
        async with self.conn.execute(query, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, query, params=()):
        await self.connect()
        async with self.conn.execute(query, params) as cursor:
            return await cursor.fetchall()

db = DatabaseManager(DB)

async def init_db():
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS conversation_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            message    TEXT NOT NULL,
            response   TEXT,
            rating     INTEGER DEFAULT 0,
            timestamp  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            message    TEXT NOT NULL,
            remind_at  TEXT NOT NULL,
            done       INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS ia_enabled_channels (
            channel_id TEXT PRIMARY KEY,
            enabled    INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            question   TEXT NOT NULL,
            answer     TEXT NOT NULL,
            upvotes    INTEGER DEFAULT 0,
            downvotes  INTEGER DEFAULT 0,
            score      INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used  TEXT
        );
        CREATE TABLE IF NOT EXISTS user_patterns (
            user_id    TEXT PRIMARY KEY,
            topics     TEXT,
            avg_rating REAL DEFAULT 0,
            total_interactions INTEGER DEFAULT 0
        );
    """)
    await db.commit()

# ──────────────────────────────────────────────────────────────
# 🛠️ SISTEMA DE CONFIGURAÇÃO DINÂMICA
# ──────────────────────────────────────────────────────────────
async def get_config_roles(key: str) -> list[int]:
    row = await db.fetchone("SELECT value FROM config WHERE key = ?", (key,))
    if row and row[0]: return [int(x) for x in json.loads(row[0])]
    return []

async def set_config_roles(key: str, roles: list[int]):
    await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, json.dumps(roles)))
    await db.commit()

async def get_config_channel(key: str) -> int:
    row = await db.fetchone("SELECT value FROM config WHERE key = ?", (key,))
    return int(row[0]) if row and row[0] else None

async def set_config_channel(key: str, channel_id: int):
    await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(channel_id)))
    await db.commit()

def now_br() -> datetime.datetime:
    return datetime.datetime.now(tz=BR_TZ)

# ──────────────────────────────────────────────────────────────
# 🏥 SISTEMA DE AGENDAMENTO DE CONSULTAS (TICKETS)
# ──────────────────────────────────────────────────────────────
class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(label="🔒 Fechar Atendimento", style=discord.ButtonStyle.danger, custom_id="north_close_ticket")
    async def close_btn(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)
        
        # Opcional: Se quiser que apenas médicos ou admins fechem, descomente a linha abaixo. 
        # (Mas geralmente o paciente também pode querer fechar)
        # if not is_admin: return await itx.response.send_message("❌ Apenas a equipe médica pode fechar o ticket.", ephemeral=True)
        
        await itx.response.send_message("🌸 O atendimento será encerrado e deletado em **5 segundos**...", ephemeral=False)
        await asyncio.sleep(5)
        try:
            await itx.channel.delete(reason=f"Ticket fechado por {itx.user.name}")
        except discord.NotFound:
            pass

class TicketModal(discord.ui.Modal):
    def __init__(self, dept_key: str):
        self.dept_key = dept_key
        dept_info = DEPARTAMENTOS[dept_key]
        super().__init__(title=f"Consulta: {dept_info['nome'][:15]} 🎀")
        
        self.nome_completo = discord.ui.TextInput(label="Nome completo", placeholder="Digite seu nome", style=discord.TextStyle.short, required=True)
        self.passaporte = discord.ui.TextInput(label="Passaporte", placeholder="Número do passaporte", style=discord.TextStyle.short, required=True)
        self.motivo = discord.ui.TextInput(label="Motivo do agendamento", placeholder="Descreva os sintomas ou motivo...", style=discord.TextStyle.paragraph, required=True)
        
        self.add_item(self.nome_completo)
        self.add_item(self.passaporte)
        self.add_item(self.motivo)

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        
        dept = DEPARTAMENTOS[self.dept_key]
        cat_id = dept["cat_id"]
        role_id = dept["role_id"]
        guild = itx.guild
        category = guild.get_channel(cat_id)
        
        if not category or not isinstance(category, discord.CategoryChannel):
            return await itx.followup.send("❌ Categoria não encontrada! A diretoria precisa corrigir os IDs no código.", ephemeral=True)
            
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            itx.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        
        try:
            ch_name = f"consulta-{self.passaporte.value}-{itx.user.name}"
            channel = await guild.create_text_channel(name=ch_name, category=category, overwrites=overwrites)
            
            embed = discord.Embed(title=f"{dept['emoji']} Central de Atendimento - {dept['nome']}", color=0xFF69B4)
            embed.add_field(name="🎀 Paciente", value=f"{itx.user.mention} (`{self.nome_completo.value}`)", inline=False)
            embed.add_field(name="🆔 Passaporte", value=self.passaporte.value, inline=False)
            embed.add_field(name="📄 Motivo", value=self.motivo.value, inline=False)
            embed.set_thumbnail(url=str(itx.user.display_avatar.url))
            
            # Marca o paciente e o cargo médico configurado
            await channel.send(
                content=f"|| {itx.user.mention} | <@&{role_id}> ||\n**Um novo agendamento foi solicitado!** Nossa equipe logo irá te atender. 🌸",
                embed=embed,
                view=CloseTicketView()
            )
            await itx.followup.send(f"🌸 Seu agendamento foi criado com sucesso no canal {channel.mention}!", ephemeral=True)
            
        except discord.Forbidden:
            await itx.followup.send("❌ O bot não tem permissão para criar canais na categoria indicada.", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro ao criar ticket: {e}")
            await itx.followup.send("❌ Ocorreu um erro interno ao criar seu ticket. Avise a administração.", ephemeral=True)

class AtendimentoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        # Cria os botões de acordo com o dicionário de departamentos
        for key, val in DEPARTAMENTOS.items():
            btn = discord.ui.Button(label=val["nome"], emoji=val["emoji"], style=discord.ButtonStyle.danger, custom_id=f"north_ticket_{key}")
            btn.callback = self.make_callback(key)
            self.add_item(btn)

    def make_callback(self, key: str):
        async def callback(itx: discord.Interaction):
            await itx.response.send_modal(TicketModal(key))
        return callback

# ──────────────────────────────────────────────────────────────
# 📢 SISTEMA DE ANÚNCIOS (BEM FOFINHO)
# ──────────────────────────────────────────────────────────────
class AnuncioPublishView(discord.ui.View):
    def __init__(self, embed: discord.Embed):
        super().__init__(timeout=None)
        self.embed = embed
        self.selected_role = None

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Selecione um cargo específico para marcar (Opcional)", min_values=1, max_values=1, custom_id="anuncio_select_role")
    async def select_role(self, itx: discord.Interaction, select: discord.ui.RoleSelect):
        self.selected_role = select.values[0]
        await itx.response.send_message(f"🎀 Cargo {self.selected_role.mention} selecionado! Agora clique em **Enviar**.", ephemeral=True)

    @discord.ui.button(label="Enviar Anúncio", style=discord.ButtonStyle.success, emoji="✨")
    async def btn_send(self, itx: discord.Interaction, btn: discord.ui.Button):
        content = f"|| {self.selected_role.mention} ||" if self.selected_role else ""
        await itx.channel.send(content=content, embed=self.embed)
        await itx.response.send_message("🌸 Anúncio enviado com muito sucesso!", ephemeral=True)
        # Desabilita o painel pra não enviar duplicado
        for child in self.children: child.disabled = True
        await itx.message.edit(view=self)

    @discord.ui.button(label="Enviar para @everyone", style=discord.ButtonStyle.danger, emoji="📢")
    async def btn_send_everyone(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.channel.send(content="|| @everyone ||", embed=self.embed)
        await itx.response.send_message("🌸 Anúncio enviado para todos com sucesso!", ephemeral=True)
        for child in self.children: child.disabled = True
        await itx.message.edit(view=self)

class AnuncioModal(discord.ui.Modal, title="📢 Criador de Anúncios"):
    titulo = discord.ui.TextInput(label="Título do Anúncio", placeholder="Ex: Nova Reunião Geral", style=discord.TextStyle.short, required=True)
    mensagem = discord.ui.TextInput(label="Mensagem", placeholder="Escreva o texto do anúncio aqui...", style=discord.TextStyle.paragraph, required=True)
    
    async def on_submit(self, itx: discord.Interaction):
        embed = discord.Embed(
            title=f"🎀 {self.titulo.value} 🎀",
            description=self.mensagem.value,
            color=0xFF1493, # Deep Pink
            timestamp=now_br()
        )
        embed.set_footer(text="NORTH HOSPITAL CENTER", icon_url=itx.guild.icon.url if itx.guild.icon else None)
        
        await itx.response.send_message(
            "✨ O seu anúncio está quase pronto! Selecione um cargo abaixo ou envie para `@everyone`.",
            embed=embed,
            view=AnuncioPublishView(embed),
            ephemeral=True
        )

class AnuncioPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(label="📢 Criar Novo Anúncio", style=discord.ButtonStyle.danger, custom_id="north_anuncio_btn")
    async def create_btn(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)
        
        if not is_admin:
            return await itx.response.send_message("❌ Apenas administradores podem criar anúncios.", ephemeral=True)
            
        await itx.response.send_modal(AnuncioModal())

# ──────────────────────────────────────────────────────────────
# 📝 SISTEMA DE PAINEL SET E CONFIG
# ──────────────────────────────────────────────────────────────
class RoleConfigSelect(discord.ui.RoleSelect):
    def __init__(self, key: str, placeholder: str):
        super().__init__(placeholder=placeholder, min_values=0, max_values=10, custom_id=f"conf_role_{key}")
        self.key = key

    async def callback(self, itx: discord.Interaction):
        if not itx.user.guild_permissions.administrator: return await itx.response.send_message("❌ Somente admins.", ephemeral=True)
        await set_config_roles(self.key, [role.id for role in self.values])
        await itx.response.send_message(f"🌸 Cargos salvos com muito sucesso!", ephemeral=True)

class ChannelConfigSelect(discord.ui.ChannelSelect):
    def __init__(self, key: str, placeholder: str):
        super().__init__(placeholder=placeholder, channel_types=[discord.ChannelType.text], min_values=1, max_values=1, custom_id=f"conf_chan_{key}")
        self.key = key

    async def callback(self, itx: discord.Interaction):
        if not itx.user.guild_permissions.administrator: return await itx.response.send_message("❌ Somente admins.", ephemeral=True)
        await set_config_channel(self.key, self.values[0].id)
        await itx.response.send_message(f"🎀 Canal configurado perfeitamente!", ephemeral=True)

class ConfigPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleConfigSelect("admin_roles", "👑 Selecione os Cargos Administrativos"))
        self.add_item(RoleConfigSelect("approved_roles", "💖 Selecione os Cargos para Membros Setados"))
        self.add_item(ChannelConfigSelect("set_logs", "📄 Selecione o Canal para os Logs de Set"))

def extract_user_id(text: str) -> int:
    match = re.search(r'<@!?(\d+)>', text)
    if match: return int(match.group(1))
    return None

class SetActionView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
        
    @discord.ui.button(label="🌸 Aprovar Set", style=discord.ButtonStyle.danger, custom_id="north_set_approve")
    async def btn_approve(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)
        if not is_admin: return await itx.response.send_message("❌ Sem permissão.", ephemeral=True)
            
        embed = itx.message.embeds[0]
        uid = extract_user_id(embed.fields[0].value)
        if uid:
            member = itx.guild.get_member(uid)
            if member:
                try:
                    approved_role_ids = await get_config_roles("approved_roles")
                    roles_to_add = [itx.guild.get_role(r) for r in approved_role_ids if itx.guild.get_role(r)]
                    if roles_to_add: await member.add_roles(*roles_to_add)
                except Exception as e: logger.error(f"Erro: {e}")
        
        embed.color = 0xFF69B4
        embed.title = "🌸 Solicitação de Set Aprovada"
        embed.set_footer(text=f"Aprovado por {itx.user.display_name} 🎀")
        for child in self.children: child.disabled = True
        await itx.message.edit(embed=embed, view=self)
        await itx.response.send_message("🌸 Membro aprovado e cargos entregues!", ephemeral=True)

    @discord.ui.button(label="❌ Recusar Set", style=discord.ButtonStyle.danger, custom_id="north_set_deny")
    async def btn_deny(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)
        if not is_admin: return await itx.response.send_message("❌ Sem permissão.", ephemeral=True)
            
        embed = itx.message.embeds[0]
        embed.color = 0xFF0000
        embed.title = "❌ Solicitação de Set Recusada"
        embed.set_footer(text=f"Recusado por {itx.user.display_name} 💔")
        for child in self.children: child.disabled = True
        await itx.message.edit(embed=embed, view=self)
        await itx.response.send_message("❌ Solicitação recusada.", ephemeral=True)

class SetModal(discord.ui.Modal, title="📝 Formulário de Registro"):
    nome_completo = discord.ui.TextInput(label="Nome completo", placeholder="Digite seu nome", style=discord.TextStyle.short, required=True)
    passaporte = discord.ui.TextInput(label="Passaporte", placeholder="Número do passaporte", style=discord.TextStyle.short, required=True)
    motivo_registro = discord.ui.TextInput(label="Motivo do registro", placeholder="Descreva o motivo", style=discord.TextStyle.paragraph, required=True)
    numero_contato = discord.ui.TextInput(label="Número de contato", placeholder="Telefone/WhatsApp", style=discord.TextStyle.short, required=True)
    cargo_desejado = discord.ui.TextInput(label="Cargo desejado", placeholder="Ex: Enfermeiro, Médico, etc.", style=discord.TextStyle.short, required=True)
    
    async def on_submit(self, itx: discord.Interaction):
        log_ch_id = await get_config_channel("set_logs")
        if not log_ch_id: return await itx.response.send_message("❌ Canal de logs não configurado (/painel_config).", ephemeral=True)

        log_channel = itx.guild.get_channel(log_ch_id)
        if log_channel:
            embed = discord.Embed(title="📄 Nova Solicitação de Set 🎀", color=0xFFB6C1, timestamp=now_br())
            embed.add_field(name="Usuário Discord", value=f"{itx.user.mention} (`{itx.user.name}`)", inline=False)
            embed.add_field(name="Nome Completo", value=self.nome_completo.value, inline=True)
            embed.add_field(name="Passaporte", value=self.passaporte.value, inline=True)
            embed.add_field(name="Contato", value=self.numero_contato.value, inline=True)
            embed.add_field(name="Cargo Desejado", value=self.cargo_desejado.value, inline=True)
            embed.add_field(name="Motivo do Registro", value=self.motivo_registro.value, inline=False)
            embed.set_thumbnail(url=str(itx.user.display_avatar.url))
            
            await log_channel.send(embed=embed, view=SetActionView())
            await itx.response.send_message("🌸 Seu formulário foi enviado com muito amor para a diretoria!", ephemeral=True)

class SetView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="📝 Solicitar Set", style=discord.ButtonStyle.danger, custom_id="north_set_btn")
    async def set_btn(self, itx: discord.Interaction, _: discord.ui.Button):
        await itx.response.send_modal(SetModal())

# ──────────────────────────────────────────────────────────────
# ✨ IA E OUTROS COMANDOS
# ──────────────────────────────────────────────────────────────
async def get_channel_history(channel_id: str, limit: int = 15) -> list:
    rows = await db.fetchall("SELECT user_id, message, response, rating, timestamp FROM conversation_history WHERE channel_id = ? ORDER BY timestamp DESC LIMIT ?", (channel_id, limit))
    return list(reversed(rows))

async def is_ia_enabled(channel_id: str) -> bool:
    row = await db.fetchone("SELECT enabled FROM ia_enabled_channels WHERE channel_id = ?", (channel_id,))
    return bool(row[0]) if row else False

def replace_channel_mentions(text: str, guild: discord.Guild) -> str:
    if not guild or not text: return text
    for channel in sorted(guild.channels, key=lambda c: len(c.name), reverse=True):
        pattern = re.compile(r'(?<![#<])' + re.escape(channel.name) + r'(?![#>])', re.IGNORECASE)
        text = pattern.sub(f"<#{channel.id}>", text)
    return text

@bot.tree.command(name="painel_config", description="[ADMIN] Configura cargos e canais do bot ⚙️")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_config(itx: discord.Interaction):
    embed = discord.Embed(title="⚙️ Painel de Configuração do NORTH 🎀", description="Utilize os menus para configurar o sistema de Set.", color=0xFF1493)
    await itx.response.send_message(embed=embed, view=ConfigPanelView(), ephemeral=True)

@bot.tree.command(name="painel_set", description="[ADMIN] Cria o painel de Registro neste canal 📢")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_set(itx: discord.Interaction):
    embed = discord.Embed(title="📢 Central de Registros - NORTH HOSPITAL 🎀", description="**Faça o seu registro!** 🌸\nPara solicitar o seu Set, clique no botão **'📝 Solicitar Set'**.\n⚠️ Nossa diretoria avaliará seu perfil e a aprovação será notificada.", color=0xFFB6C1)
    await itx.channel.send(embed=embed, view=SetView())
    await itx.response.send_message("🎀 Painel de Set criado!", ephemeral=True)

@bot.tree.command(name="painel_atendimento", description="[ADMIN] Cria a Central de Atendimentos (Tickets Médicos) 🏥")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_atendimento(itx: discord.Interaction):
    embed = discord.Embed(
        title="🏥 CENTRAL DE ATENDIMENTOS 🎀",
        description=(
            "Olá! Bem-vindo(a) ao **NORTH HOSPITAL CENTER**! 🌸\n\n"
            "Selecione o departamento abaixo para agendar a sua consulta.\n"
            "Um canal privado será criado imediatamente com a nossa equipe médica."
        ),
        color=0xFF69B4
    )
    embed.set_footer(text="NORTH HOSPITAL CENTER 💌")
    await itx.channel.send(embed=embed, view=AtendimentoView())
    await itx.response.send_message("🎀 Painel de Atendimento (Tickets) criado com sucesso!", ephemeral=True)

@bot.tree.command(name="painel_anuncio", description="[ADMIN] Cria um painel onde você pode criar anúncios fáceis 📢")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_anuncio(itx: discord.Interaction):
    embed = discord.Embed(
        title="📢 CENTRAL DE ANÚNCIOS 🎀",
        description="Clique no botão abaixo para redigir um lindo anúncio. Você poderá selecionar quem deseja marcar antes de enviar. ✨",
        color=0xFF1493
    )
    await itx.channel.send(embed=embed, view=AnuncioPanelView())
    await itx.response.send_message("🎀 Painel de Anúncios criado!", ephemeral=True)

@bot.tree.command(name="sync", description="[ADMIN] Sincroniza comandos ⚙️")
@app_commands.default_permissions(administrator=True)
async def cmd_sync(itx: discord.Interaction):
    await itx.response.defer(ephemeral=True)
    synced = await bot.tree.sync()
    await itx.followup.send(f"🌸 Sincronizados: {len(synced)} comandos", ephemeral=True)

# ──────────────────────────────────────────────────────────────
# 🚀 INICIALIZAÇÃO
# ──────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await init_db()

    # Views persistentes
    bot.add_view(ConfigPanelView())
    bot.add_view(SetView())
    bot.add_view(SetActionView())
    bot.add_view(AtendimentoView())
    bot.add_view(CloseTicketView())
    bot.add_view(AnuncioPanelView())

    try:
        synced = await bot.tree.sync()
        logger.info(f"Comandos sincronizados: {len(synced)}")
    except Exception as exc:
        logger.error(f"Erro ao sincronizar comandos: {exc}")

    logger.info(f"🌸 {bot.user} online e espalhando amor!")

if __name__ == "__main__":
    if not TOKEN: raise SystemExit("❌ DISCORD_TOKEN ausente.")
    bot.run(TOKEN)
