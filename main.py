"""
╔══════════════════════════════════════════════════════════════╗
║          🎀 NORTH HOSPITAL CENTER — ASSISTENTE VIRTUAL 🎀    ║
║        IA, SISTEMA DE SET E CONFIGURAÇÃO POR PAINEL DINÂMICO ║
║        COMANDOS: /painel_config /painel_set /ia              ║
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
# 🌸 CONFIGURAÇÃO DE LOGGING
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%d/%m/%Y %H:%M:%S'
)
logger = logging.getLogger('NorthBot')

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
    'você', 'aqui', 'este', 'esta', 'está', 'fazer', 'também', 'pelo', 'pela', 'dos', 'das', 'nas', 'nos', 
    'mas', 'que', 'não', 'sim', 'quem', 'seja', 'isso', 'esse', 'essa', 'qualquer', 'mesmo', 'porque', 'quais'
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
    if row and row[0]:
        return [int(x) for x in json.loads(row[0])]
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

# ──────────────────────────────────────────────────────────────
# 🧠 FUNÇÕES AUXILIARES DA IA & MEMÓRIA
# ──────────────────────────────────────────────────────────────
async def save_conversation(user_id: str, channel_id: str, message: str, response: str = None):
    await db.execute(
        "INSERT INTO conversation_history (user_id, channel_id, message, response, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, channel_id, message, response, datetime.datetime.now(BR_TZ).isoformat())
    )
    await db.commit()
    row = await db.fetchone("SELECT last_insert_rowid()")
    return row[0] if row else 0

async def rate_response(conversation_id: int, rating: int):
    await db.execute("UPDATE conversation_history SET rating = ? WHERE id = ?", (rating, conversation_id))
    await db.commit()

async def save_knowledge(question: str, answer: str):
    row = await db.fetchone("SELECT id FROM knowledge_base WHERE question = ?", (question,))
    if row:
        await db.execute("UPDATE knowledge_base SET usage_count = usage_count + 1, last_used = ? WHERE id = ?",
                        (datetime.datetime.now(BR_TZ).isoformat(), row[0]))
    else:
        await db.execute(
            "INSERT INTO knowledge_base (question, answer, last_used) VALUES (?, ?, ?)",
            (question, answer, datetime.datetime.now(BR_TZ).isoformat())
        )
    await db.commit()

async def get_knowledge(question: str) -> list:
    return await db.fetchall(
        "SELECT id, question, answer, upvotes, downvotes, usage_count FROM knowledge_base WHERE question LIKE ? ORDER BY (upvotes - downvotes) DESC, usage_count DESC LIMIT 3",
        (f"%{question}%",)
    )

async def update_user_pattern(user_id: str, topic: str):
    row = await db.fetchone("SELECT topics, total_interactions FROM user_patterns WHERE user_id = ?", (user_id,))
    if row:
        topics = json.loads(row[0]) if row[0] else []
        topics.append(topic)
        topics = topics[-20:]
        await db.execute("UPDATE user_patterns SET topics = ?, total_interactions = ? WHERE user_id = ?",
                        (json.dumps(topics), row[1] + 1, user_id))
    else:
        await db.execute("INSERT INTO user_patterns (user_id, topics, total_interactions) VALUES (?, ?, ?)",
                        (user_id, json.dumps([topic]), 1))
    await db.commit()

async def get_user_patterns(user_id: str) -> dict:
    row = await db.fetchone("SELECT topics, total_interactions, avg_rating FROM user_patterns WHERE user_id = ?", (user_id,))
    if row:
        return {"topics": json.loads(row[0]) if row[0] else [], "total_interactions": row[1] or 0}
    return {"topics": [], "total_interactions": 0}

async def get_channel_history(channel_id: str, limit: int = 15) -> list:
    rows = await db.fetchall(
        "SELECT user_id, message, response, rating, timestamp FROM conversation_history WHERE channel_id = ? ORDER BY timestamp DESC LIMIT ?",
        (channel_id, limit)
    )
    return list(reversed(rows))

async def is_ia_enabled(channel_id: str) -> bool:
    row = await db.fetchone("SELECT enabled FROM ia_enabled_channels WHERE channel_id = ?", (channel_id,))
    return bool(row[0]) if row else False

def replace_channel_mentions(text: str, guild: discord.Guild) -> str:
    if not guild or not text: return text
    channels = sorted(guild.channels, key=lambda c: len(c.name), reverse=True)
    for channel in channels:
        escaped_name = re.escape(channel.name)
        pattern = re.compile(r'(?<![#<])' + escaped_name + r'(?![#>])', re.IGNORECASE)
        text = pattern.sub(f"<#{channel.id}>", text)
    return text

def extract_user_id(text: str) -> int:
    match = re.search(r'<@!?(\d+)>', text)
    if match: return int(match.group(1))
    return None

def now_br() -> datetime.datetime:
    return datetime.datetime.now(tz=BR_TZ)

# ──────────────────────────────────────────────────────────────
# 🕒 TASKS RECORRENTES
# ──────────────────────────────────────────────────────────────
@tasks.loop(seconds=30)
async def check_reminders():
    now = now_br().isoformat()
    reminders = await db.fetchall("SELECT id, user_id, channel_id, message, remind_at FROM reminders WHERE done = 0 AND remind_at <= ?", (now,))
    
    for rid, uid, cid, msg, remind_at in reminders:
        user = bot.get_user(int(uid))
        if user:
            channel_obj = bot.get_channel(int(cid))
            guild = channel_obj.guild if channel_obj else None
            msg_processed = replace_channel_mentions(msg, guild)

            embed = discord.Embed(
                title="⏰ Lembrete Fofinho!",
                description=f"Oiii {user.mention}, você pediu para eu te lembrar disso:\n\n**{msg_processed}**",
                color=0xFF69B4,
                timestamp=now_br()
            )
            embed.set_footer(text=f"Agendado para {remind_at}")
            try:
                await user.send(embed=embed)
                if channel_obj:
                    await channel_obj.send(f"{user.mention} 🌸 Lembrete: {msg_processed}")
            except Exception as e:
                logger.warning(f"Erro ao enviar lembrete para {user.id}: {e}")
                
        await db.execute("UPDATE reminders SET done = 1 WHERE id = ?", (rid,))
        await db.commit()

@tasks.loop(hours=24)
async def cleanup_database():
    thirty_days_ago = (now_br() - datetime.timedelta(days=30)).isoformat()
    try:
        await db.execute("DELETE FROM conversation_history WHERE timestamp < ?", (thirty_days_ago,))
        await db.commit()
    except Exception as e:
        logger.error(f"Erro na limpeza do banco: {e}")

# ──────────────────────────────────────────────────────────────
# ⚙️ MENUS DE CONFIGURAÇÃO (BOTÕES MÁGICOS)
# ──────────────────────────────────────────────────────────────
class RoleConfigSelect(discord.ui.RoleSelect):
    def __init__(self, key: str, placeholder: str):
        super().__init__(placeholder=placeholder, min_values=0, max_values=10, custom_id=f"conf_role_{key}")
        self.key = key

    async def callback(self, itx: discord.Interaction):
        if not itx.user.guild_permissions.administrator:
            return await itx.response.send_message("❌ Só administradores podem usar isso, anjo.", ephemeral=True)
        
        role_ids = [role.id for role in self.values]
        await set_config_roles(self.key, role_ids)
        await itx.response.send_message(f"🌸 Cargos salvos com muito sucesso!", ephemeral=True)

class ChannelConfigSelect(discord.ui.ChannelSelect):
    def __init__(self, key: str, placeholder: str):
        super().__init__(placeholder=placeholder, channel_types=[discord.ChannelType.text], min_values=1, max_values=1, custom_id=f"conf_chan_{key}")
        self.key = key

    async def callback(self, itx: discord.Interaction):
        if not itx.user.guild_permissions.administrator:
            return await itx.response.send_message("❌ Só administradores podem usar isso, anjo.", ephemeral=True)
        
        channel_id = self.values[0].id
        await set_config_channel(self.key, channel_id)
        await itx.response.send_message(f"🎀 Canal configurado perfeitamente!", ephemeral=True)

class ConfigPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleConfigSelect("admin_roles", "👑 Selecione os Cargos Administrativos"))
        self.add_item(RoleConfigSelect("approved_roles", "💖 Selecione os Cargos para Membros Setados"))
        self.add_item(ChannelConfigSelect("set_logs", "📄 Selecione o Canal para os Logs de Set"))

# ──────────────────────────────────────────────────────────────
# 📢 SISTEMA DE PAINEL SET (FORMULÁRIO EXATO)
# ──────────────────────────────────────────────────────────────
class SetActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(label="🌸 Aprovar Set", style=discord.ButtonStyle.danger, custom_id="north_set_approve")
    async def btn_approve(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)
        
        if not is_admin:
            return await itx.response.send_message("❌ Você não tem os cargos de permissão para isso flor.", ephemeral=True)
            
        embed = itx.message.embeds[0]
        uid = extract_user_id(embed.fields[0].value)
        
        if uid:
            member = itx.guild.get_member(uid)
            if member:
                try:
                    approved_role_ids = await get_config_roles("approved_roles")
                    roles_to_add = [itx.guild.get_role(r) for r in approved_role_ids if itx.guild.get_role(r)]
                    if roles_to_add: await member.add_roles(*roles_to_add)
                except Exception as e:
                    logger.error(f"Erro ao dar cargos: {e}")
        
        embed.color = 0xFF69B4 # Rosa Sucesso
        embed.title = "🌸 Solicitação de Set Aprovada"
        embed.set_footer(text=f"Aprovado por {itx.user.display_name} 🎀")
        
        for child in self.children: child.disabled = True
        await itx.message.edit(embed=embed, view=self)
        await itx.response.send_message("🌸 Membro aprovado e cargos do Set entregues!", ephemeral=True)

    @discord.ui.button(label="❌ Recusar Set", style=discord.ButtonStyle.danger, custom_id="north_set_deny")
    async def btn_deny(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)
        
        if not is_admin:
            return await itx.response.send_message("❌ Você não tem permissão para isso.", ephemeral=True)
            
        embed = itx.message.embeds[0]
        embed.color = 0xFF0000 # Vermelho
        embed.title = "❌ Solicitação de Set Recusada"
        embed.set_footer(text=f"Recusado por {itx.user.display_name} 💔")
        
        for child in self.children: child.disabled = True
        await itx.message.edit(embed=embed, view=self)
        await itx.response.send_message("❌ Solicitação de Set recusada.", ephemeral=True)

class SetModal(discord.ui.Modal, title="📝 Formulário de Registro"):
    nome_completo = discord.ui.TextInput(
        label="Nome completo", 
        placeholder="Digite seu nome", 
        style=discord.TextStyle.short, 
        required=True
    )
    passaporte = discord.ui.TextInput(
        label="Passaporte", 
        placeholder="Número do passaporte", 
        style=discord.TextStyle.short, 
        required=True
    )
    motivo_registro = discord.ui.TextInput(
        label="Motivo do registro", 
        placeholder="Descreva o motivo", 
        style=discord.TextStyle.paragraph, 
        required=True
    )
    numero_contato = discord.ui.TextInput(
        label="Número de contato", 
        placeholder="Telefone/WhatsApp", 
        style=discord.TextStyle.short, 
        required=True
    )
    cargo_desejado = discord.ui.TextInput(
        label="Cargo desejado", 
        placeholder="Ex: Enfermeiro, Médico, etc.", 
        style=discord.TextStyle.short, 
        required=True
    )
    
    async def on_submit(self, itx: discord.Interaction):
        log_ch_id = await get_config_channel("set_logs")
        if not log_ch_id:
            return await itx.response.send_message("❌ O canal de logs de Set ainda não foi configurado pelos admins! Peça para eles usarem o `/painel_config`.", ephemeral=True)

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
            await itx.response.send_message("🌸 Seu formulário de Set foi enviado e será analisado com muito amor pela diretoria!", ephemeral=True)
        else:
            await itx.response.send_message("❌ O canal de logs configurado não foi encontrado.", ephemeral=True)

class SetView(discord.ui.View):
    def __init__(self): 
        super().__init__(timeout=None)
        
    @discord.ui.button(label="📝 Solicitar Set", style=discord.ButtonStyle.danger, custom_id="north_set_btn")
    async def set_btn(self, itx: discord.Interaction, _: discord.ui.Button):
        await itx.response.send_modal(SetModal())

# ──────────────────────────────────────────────────────────────
# ✨ SISTEMA DA IA (MENSAGENS) E COMANDOS
# ──────────────────────────────────────────────────────────────
class RatingView(discord.ui.View):
    def __init__(self, conversation_id: int):
        super().__init__(timeout=3600)
        self.conversation_id = conversation_id

    @discord.ui.button(label="👍 Amei!", style=discord.ButtonStyle.danger, custom_id="rate_up")
    async def rate_up(self, itx: discord.Interaction, _: discord.ui.Button):
        await rate_response(self.conversation_id, 1)
        await itx.response.send_message("💖 Obrigada pelo feedback fofo!", ephemeral=True)
        for child in self.children: child.disabled = True
        await itx.message.edit(view=self)

    @discord.ui.button(label="👎 Não gostei", style=discord.ButtonStyle.danger, custom_id="rate_down")
    async def rate_down(self, itx: discord.Interaction, _: discord.ui.Button):
        await rate_response(self.conversation_id, -1)
        await itx.response.send_message("🌸 Feedback registrado! Prometo melhorar.", ephemeral=True)
        for child in self.children: child.disabled = True
        await itx.message.edit(view=self)

async def fetch_gemini_fallback(contexto: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": contexto}]}]}
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=30) as response:
            if response.status == 200:
                data = await response.json()
                if "candidates" in data and data["candidates"]:
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    return None

@bot.tree.command(name="ia", description="Faça uma pergunta para a IA do NORTH (com contexto do chat)")
@app_commands.describe(pergunta="Sua perguntinha")
async def cmd_ia(itx: discord.Interaction, pergunta: str):
    if not gemini_client or not GEMINI_MODELS:
        return await itx.response.send_message("❌ IA não configurada.", ephemeral=True)

    await itx.response.defer(ephemeral=False)
    try:
        channel_history = await get_channel_history(str(itx.channel_id), limit=15)
        user_patterns = await get_user_patterns(str(itx.user.id))
        knowledge = await get_knowledge(pergunta)

        contexto = "Você é um assistente virtual super fofo e educado do Hospital NORTH. Responda de forma carinhosa, útil e objetiva.\n\n"
        if user_patterns["topics"]:
            contexto += f"Tópicos do usuário: {', '.join(user_patterns['topics'][-5:])}\n\n"
        if channel_history:
            contexto += "--- Histórico ---\n" + "".join([f"{entry[1]}\nBot:{entry[2]}\n" for entry in channel_history if entry[2]]) + "\n"
        if knowledge:
            contexto += "--- Base de Dados ---\n" + "".join([f"Q: {k[1]}\nA: {k[2]}\n" for k in knowledge if k[3]-k[4] >= 0]) + "\n"
            
        contexto += f"Pergunta de {itx.user.display_name}: {pergunta}"

        resposta_texto = None
        for modelo in GEMINI_MODELS:
            try:
                resposta = await gemini_client.aio.models.generate_content(model=modelo, contents=contexto)
                resposta_texto = resposta.text.strip()
                break
            except Exception: continue

        if not resposta_texto: resposta_texto = await fetch_gemini_fallback(contexto)
        if not resposta_texto: return await itx.followup.send("❌ Falha ao conectar com a IA, me perdoe!")

        resposta_texto = replace_channel_mentions(resposta_texto, itx.guild)
        conv_id = await save_conversation(str(itx.user.id), str(itx.channel_id), pergunta, resposta_texto)
        
        palavras = set(re.findall(r'\b[a-záéíóúâêôãõç]{4,}\b', pergunta.lower()))
        topicos = [p for p in palavras if p not in STOPWORDS_PTBR]
        for t in topicos[:3]: await update_user_pattern(str(itx.user.id), t)
        await save_knowledge(pergunta, resposta_texto)

        embed = discord.Embed(description=resposta_texto[:4000], color=0xFF69B4)
        await itx.followup.send(embed=embed, view=RatingView(conv_id))
    except Exception as e:
        logger.error(f"Erro no comando /ia: {e}", exc_info=True)
        await itx.followup.send("❌ Ocorreu um erro interno ao processar.")

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot or msg.content.startswith(("/", "!")):
        return await bot.process_commands(msg)
        
    if not await is_ia_enabled(str(msg.channel.id)) or not gemini_client:
        return await bot.process_commands(msg)

    async with msg.channel.typing():
        try:
            channel_history = await get_channel_history(str(msg.channel.id), limit=10)
            contexto = "Você é um assistente fofo do Hospital NORTH. Responda com amor, até 400 caracteres.\n\n"
            if channel_history:
                contexto += "\n".join([f"Msg: {entry[1]}\nBot: {entry[2]}\n" for entry in channel_history if entry[2]])
            contexto += f"\nUsuário {msg.author.display_name}: {msg.content}"

            resposta_texto = None
            for modelo in GEMINI_MODELS:
                try:
                    resposta = await gemini_client.aio.models.generate_content(model=modelo, contents=contexto)
                    resposta_texto = resposta.text.strip()
                    break
                except Exception: continue

            if not resposta_texto: resposta_texto = await fetch_gemini_fallback(contexto)
            if resposta_texto:
                resposta_texto = replace_channel_mentions(resposta_texto, msg.guild)
                conv_id = await save_conversation(str(msg.author.id), str(msg.channel.id), msg.content, resposta_texto)
                
                embed = discord.Embed(description=resposta_texto[:1900], color=0xFF69B4)
                await msg.reply(embed=embed, view=RatingView(conv_id), mention_author=False)
        except Exception as e:
            logger.error(f"Erro on_message IA: {e}")

    await bot.process_commands(msg)

# ──────────────────────────────────────────────────────────────
# 🎀 COMANDOS DE BARRA (ADMIN E UTILITÁRIOS)
# ──────────────────────────────────────────────────────────────
@bot.tree.command(name="painel_config", description="[ADMIN] Abre o painel para configurar cargos e canais ⚙️")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_config(itx: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Painel de Configuração do NORTH 🎀",
        description="Utilize os menus abaixo para configurar como o bot vai funcionar no seu servidor.\n\n"
                    "👑 **Cargos Administrativos:** Quem pode aprovar solicitações de Set.\n"
                    "💖 **Cargos Aprovados:** Quais cargos os membros ganham ao receberem o Set.\n"
                    "📄 **Canal de Logs:** Onde as respostas do Set serão enviadas para aprovação.",
        color=0xFF1493
    )
    await itx.response.send_message(embed=embed, view=ConfigPanelView(), ephemeral=True)

@bot.tree.command(name="painel_set", description="[ADMIN] Cria o painel de Set (Registro) neste canal 📢")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_set(itx: discord.Interaction):
    embed = discord.Embed(
        title="📢 Central de Registros - NORTH HOSPITAL 🎀",
        description=(
            "**Faça o seu registro em nossa equipe!** 🌸\n\n"
            "Para solicitar o seu Set no NORTH HOSPITAL, clique no botão **'📝 Solicitar Set'** abaixo.\n"
            "Preencha o formulário com suas informações perfeitamente de acordo com o seu passaporte na cidade.\n\n"
            "⚠️ **Atenção:** Nossa diretoria avaliará seu perfil e a aprovação será notificada aos responsáveis."
        ),
        color=0xFFB6C1
    )
    embed.set_footer(text="Diretoria NORTH HOSPITAL 💌")
    await itx.channel.send(embed=embed, view=SetView())
    await itx.response.send_message("🎀 Painel de Set criado com sucesso neste canal!", ephemeral=True)

@bot.tree.command(name="ativar_ia", description="[ADMIN] Ativa IA no canal atual 🎀")
@app_commands.default_permissions(administrator=True)
async def cmd_ativar_ia(itx: discord.Interaction):
    await db.execute("INSERT OR REPLACE INTO ia_enabled_channels (channel_id, enabled) VALUES (?, ?)", (str(itx.channel_id), 1))
    await db.commit()
    await itx.response.send_message("🌸 Inteligência Artificial Ativada com sucesso neste canal.", ephemeral=True)

@bot.tree.command(name="desativar_ia", description="[ADMIN] Desativa IA no canal atual 💔")
@app_commands.default_permissions(administrator=True)
async def cmd_desativar_ia(itx: discord.Interaction):
    await db.execute("INSERT OR REPLACE INTO ia_enabled_channels (channel_id, enabled) VALUES (?, ?)", (str(itx.channel_id), 0))
    await db.commit()
    await itx.response.send_message("❌ Inteligência Artificial Desativada neste canal.", ephemeral=True)

@bot.tree.command(name="lembrar", description="Define um lembrete (DD/MM/AAAA HH:MM) 💌")
@app_commands.describe(data_hora="Ex: 25/12/2026 15:30", mensagem="Sua mensagem")
async def cmd_lembrar(itx: discord.Interaction, data_hora: str, mensagem: str):
    try:
        remind_dt = BR_TZ.localize(datetime.datetime.strptime(data_hora, "%d/%m/%Y %H:%M"))
    except ValueError:
        return await itx.response.send_message("❌ Formato inválido anjo. Use DD/MM/AAAA HH:MM", ephemeral=True)
    
    if remind_dt <= now_br():
        return await itx.response.send_message("❌ A data precisa ser no futuro.", ephemeral=True)
    
    await db.execute("INSERT INTO reminders (user_id, channel_id, message, remind_at) VALUES (?, ?, ?, ?)",
                     (str(itx.user.id), str(itx.channel_id), mensagem, remind_dt.isoformat()))
    await db.commit()
    await itx.response.send_message(f"🌸 Lembrete marcado para **{remind_dt.strftime('%d/%m/%Y às %H:%M')}**!", ephemeral=True)

@bot.tree.command(name="sync", description="[ADMIN] Sincroniza comandos ⚙️")
@app_commands.default_permissions(administrator=True)
async def cmd_sync(itx: discord.Interaction):
    await itx.response.defer(ephemeral=True)
    synced = await bot.tree.sync()
    await itx.followup.send(f"🌸 Sincronizados com amor: {len(synced)} comandos", ephemeral=True)

# ──────────────────────────────────────────────────────────────
# 🚀 INICIALIZAÇÃO
# ──────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await init_db()

    # Registra as views estáticas para que os botões não parem de funcionar se o bot reiniciar
    bot.add_view(ConfigPanelView())
    bot.add_view(SetView())
    bot.add_view(SetActionView())

    check_reminders.start()
    cleanup_database.start()

    try:
        synced = await bot.tree.sync()
        logger.info(f"Comandos sincronizados: {len(synced)}")
    except Exception as exc:
        logger.error(f"Erro ao sincronizar comandos: {exc}")

    logger.info(f"🌸 {bot.user} online e pronto para espalhar amor!")

if __name__ == "__main__":
    if not TOKEN: raise SystemExit("❌ DISCORD_TOKEN ausente.")
    bot.run(TOKEN)
