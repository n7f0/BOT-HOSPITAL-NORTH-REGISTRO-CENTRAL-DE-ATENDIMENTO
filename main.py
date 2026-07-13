"""
╔══════════════════════════════════════════════════════════════╗
║          🎀 NORTH HOSPITAL CENTER — ASSISTENTE VIRTUAL 🎀    ║
║        SISTEMA DE SET, RECRUTAMENTO E PAINÉIS DINÂMICOS      ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import re
import json
import logging
import datetime
import asyncio
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
# 🎀 CONFIGURAÇÃO DO BOT
# ──────────────────────────────────────────────────────────────
TOKEN = os.environ.get("DISCORD_TOKEN")
DB    = os.environ.get("DB_PATH", "north.db")
BR_TZ = pytz.timezone("America/Sao_Paulo")

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

async def get_config_int(key: str) -> int:
    row = await db.fetchone("SELECT value FROM config WHERE key = ?", (key,))
    return int(row[0]) if row and row[0] else None

async def set_config_int(key: str, value: int):
    await db.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
    await db.commit()

def extract_user_id(text: str) -> int:
    match = re.search(r'<@!?(\d+)>', text)
    if match: return int(match.group(1))
    return None

def now_br() -> datetime.datetime:
    return datetime.datetime.now(tz=BR_TZ)

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

class CategoryConfigSelect(discord.ui.ChannelSelect):
    def __init__(self, key: str, placeholder: str):
        super().__init__(placeholder=placeholder, channel_types=[discord.ChannelType.category], min_values=1, max_values=1, custom_id=f"conf_cat_{key}")
        self.key = key

    async def callback(self, itx: discord.Interaction):
        if not itx.user.guild_permissions.administrator:
            return await itx.response.send_message("❌ Só administradores podem usar isso.", ephemeral=True)
        await set_config_channel(self.key, self.values[0].id)
        await itx.response.send_message(f"🎀 Categoria configurada perfeitamente!", ephemeral=True)

class ConfigPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleConfigSelect("admin_roles", "👑 Selecione os Cargos Administrativos"))
        self.add_item(RoleConfigSelect("approved_roles", "💖 Selecione os Cargos para Membros Setados"))
        self.add_item(ChannelConfigSelect("set_logs", "📄 Selecione o Canal para os Logs de Set"))
        self.add_item(CategoryConfigSelect("ticket_category", "📁 Categoria p/ Tickets de Recrutamento/Exames"))

# ──────────────────────────────────────────────────────────────
# 📢 SISTEMA DE PAINEL SET
# ──────────────────────────────────────────────────────────────
class SetActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🌸 Aprovar Set", style=discord.ButtonStyle.success, custom_id="north_set_approve")
    async def btn_approve(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)

        if not is_admin:
            return await itx.response.send_message("❌ Você não tem os cargos de permissão para isso flor.", ephemeral=True)

        embed = itx.message.embeds[0]
        uid = extract_user_id(embed.fields[0].value)
        nome = embed.fields[1].value
        passaporte = embed.fields[2].value

        if uid:
            member = itx.guild.get_member(uid)
            if member:
                try:
                    # Entrega de Cargos
                    approved_role_ids = await get_config_roles("approved_roles")
                    roles_to_add = [itx.guild.get_role(r) for r in approved_role_ids if itx.guild.get_role(r)]
                    if roles_to_add: await member.add_roles(*roles_to_add)
                    
                    # Alteração de Apelido (Muda para "Nome | ID")
                    await member.edit(nick=f"{nome} | {passaporte}")
                except discord.Forbidden:
                    logger.warning("Bot não tem permissão para alterar o apelido deste usuário (cargo superior).")
                except Exception as e:
                    logger.error(f"Erro ao setar membro: {e}")

        embed.color = 0x00FF00
        embed.title = "🌸 Solicitação de Set Aprovada"
        embed.set_footer(text=f"Aprovado por {itx.user.display_name} 🎀")

        for child in self.children: child.disabled = True
        await itx.message.edit(embed=embed, view=self)
        await itx.response.send_message("🌸 Membro aprovado, cargos do Set entregues e apelido alterado!", ephemeral=True)

    @discord.ui.button(label="❌ Recusar Set", style=discord.ButtonStyle.danger, custom_id="north_set_deny")
    async def btn_deny(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)

        if not is_admin:
            return await itx.response.send_message("❌ Você não tem permissão para isso.", ephemeral=True)

        embed = itx.message.embeds[0]
        embed.color = 0xFF0000
        embed.title = "❌ Solicitação de Set Recusada"
        embed.set_footer(text=f"Recusado por {itx.user.display_name} 💔")

        for child in self.children: child.disabled = True
        await itx.message.edit(embed=embed, view=self)
        await itx.response.send_message("❌ Solicitação de Set recusada.", ephemeral=True)

class SetModal(discord.ui.Modal, title="📝 Formulário de Registro"):
    nome_completo = discord.ui.TextInput(label="Nome completo", style=discord.TextStyle.short, required=True)
    passaporte = discord.ui.TextInput(label="Passaporte", style=discord.TextStyle.short, required=True)
    motivo_registro = discord.ui.TextInput(label="Motivo do registro", style=discord.TextStyle.paragraph, required=True)
    numero_contato = discord.ui.TextInput(label="Número de contato", style=discord.TextStyle.short, required=True)
    cargo_desejado = discord.ui.TextInput(label="Cargo desejado", style=discord.TextStyle.short, required=True)

    async def on_submit(self, itx: discord.Interaction):
        log_ch_id = await get_config_channel("set_logs")
        if not log_ch_id:
            return await itx.response.send_message("❌ O canal de logs de Set ainda não foi configurado pelos admins! `/painel_config`.", ephemeral=True)

        log_channel = itx.guild.get_channel(log_ch_id)
        if log_channel:
            embed = discord.Embed(title="📄 Nova Solicitação de Set 🎀", color=0xFFB6C1, timestamp=now_br())
            embed.add_field(name="Usuário Discord", value=f"{itx.user.mention} (`{itx.user.name}`)", inline=False)
            embed.add_field(name="Nome Completo", value=self.nome_completo.value, inline=True)
            embed.add_field(name="Passaporte", value=self.passaporte.value, inline=True)
            embed.add_field(name="Contato", value=self.numero_contato.value, inline=True)
            embed.add_field(name="Cargo Desejado", value=self.cargo_desejado.value, inline=True)
            embed.add_field(name="Motivo do Registro", value=self.motivo_registro.value, inline=False)

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
# 💼 PAINEL DE RECRUTAMENTO (ENTREVISTA INTERATIVA)
# ──────────────────────────────────────────────────────────────
class RecrutamentoTicketView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="✅ Aprovar Candidato", style=discord.ButtonStyle.success, custom_id="rec_approve")
    async def btn_approve(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)
        if not is_admin:
            return await itx.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        
        await itx.response.send_message("✅ **Candidato Aprovado!** Favor continuar o processo (entrevista/avaliação psicológica) por aqui.")
        btn.disabled = True
        self.children[1].disabled = True
        await itx.message.edit(view=self)

    @discord.ui.button(label="❌ Reprovar Candidato", style=discord.ButtonStyle.danger, custom_id="rec_deny")
    async def btn_deny(self, itx: discord.Interaction, btn: discord.ui.Button):
        admin_roles = await get_config_roles("admin_roles")
        is_admin = itx.user.guild_permissions.administrator or any(r.id in admin_roles for r in itx.user.roles)
        if not is_admin:
            return await itx.response.send_message("❌ Você não tem permissão.", ephemeral=True)
        
        await itx.response.send_message("❌ **Candidato Reprovado.** Infelizmente não seguiremos com o processo no momento.")
        btn.disabled = True
        self.children[0].disabled = True
        await itx.message.edit(view=self)

    @discord.ui.button(label="🔒 Fechar Ticket", style=discord.ButtonStyle.secondary, custom_id="rec_close")
    async def btn_close(self, itx: discord.Interaction, btn: discord.ui.Button):
        await itx.response.send_message("⚠️ Fechando este chat temporário em 5 segundos...", ephemeral=False)
        channel = itx.guild.get_channel(self.channel_id)
        if channel:
            await discord.utils.sleep_until(now_br() + datetime.timedelta(seconds=5))
            await channel.delete()

async def run_interview(channel: discord.TextChannel, user: discord.Member):
    perguntas = [
        "1️⃣ **Nome Completo***\n*(Digite seu nome completo)*",
        "2️⃣ **Idade***\n*(Digite sua idade)*",
        "3️⃣ **ID***\n*(Digite o número do seu Passaporte no servidor)*",
        "4️⃣ **Já tem experiência na área da saúde anteriormente?***\n*(Responda com Sim ou Não e detalhes se houver)*",
        "5️⃣ **Área de Interesse***\n*(Ex: Clínica Geral, Enfermagem, Obstetrícia, Psicologia, Paramédico, Cirurgia, Pediatria)*",
        "6️⃣ **Qual a sua disponibilidade de horário?***\n*(Ex: Todos os dias a noite, Seg a Sex a tarde, etc)*",
        "7️⃣ **Porque deseja fazer parte da equipa do Hospital North?***\n*(Descreva sua motivação)*",
        "8️⃣ **Como lida com situações de pressão e trabalho em equipa?***\n*(Seja sincero na sua resposta)*"
    ]

    respostas = []

    def check(m):
        return m.author == user and m.channel == channel

    await channel.send(f"Olá {user.mention}! Vamos começar o preenchimento do seu currículo. 📝\n\nPor favor, responda as perguntas abaixo uma a uma enviando a mensagem aqui no chat.\n*(Se você demorar mais de 10 minutos em uma pergunta, o formulário será cancelado)*")

    for pergunta in perguntas:
        await channel.send(pergunta)
        try:
            msg = await bot.wait_for('message', check=check, timeout=600.0)
            respostas.append(msg.content)
        except asyncio.TimeoutError:
            await channel.send("⏳ **Tempo esgotado!** Você demorou muito para responder. Este ticket será fechado.")
            await asyncio.sleep(5)
            await channel.delete()
            return

    # Limpando o canal ou apenas postando o embed (neste caso postamos no final para ficar visível)
    embed = discord.Embed(title="📋 Formulário de Recrutamento Concluído", color=0x4169E1, timestamp=now_br())
    embed.add_field(name="Nome Completo", value=respostas[0], inline=True)
    embed.add_field(name="Idade", value=respostas[1], inline=True)
    embed.add_field(name="ID (Passaporte)", value=respostas[2], inline=True)
    embed.add_field(name="Tem experiência?", value=respostas[3], inline=True)
    embed.add_field(name="Área de Interesse", value=respostas[4], inline=True)
    embed.add_field(name="Disponibilidade", value=respostas[5], inline=True)
    embed.add_field(name="Por que deseja entrar?", value=respostas[6], inline=False)
    embed.add_field(name="Como lida com pressão e trabalho em equipe?", value=respostas[7], inline=False)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text=f"Candidato: {user.name}")

    # Renomeando o ticket
    try:
        nome_curto = respostas[0].split()[0].lower()
        id_user = respostas[2].strip()
        await channel.edit(name=f"recrutamento-{nome_curto}-{id_user}")
    except:
        pass

    admin_roles = await get_config_roles("admin_roles")
    admin_mentions = " ".join([f"<@&{r}>" for r in admin_roles])

    await channel.send(
        content=f"🔔 **Atenção Administração:** {admin_mentions}\nO candidato {user.mention} finalizou o preenchimento!", 
        embed=embed, 
        view=RecrutamentoTicketView(channel.id)
    )

class RecrutamentoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📝 Enviar Currículo", style=discord.ButtonStyle.primary, custom_id="rec_btn")
    async def recrutamento_btn(self, itx: discord.Interaction, _: discord.ui.Button):
        await itx.response.defer(ephemeral=True)

        channel_name = f"recrutamento-{itx.user.name.lower()}"
        admin_roles = await get_config_roles("admin_roles")
        
        overwrites = {
            itx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            itx.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        }
        for role_id in admin_roles:
            role = itx.guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        cat_id = await get_config_channel("ticket_category")
        category = itx.guild.get_channel(cat_id) if cat_id else None

        try:
            channel = await itx.guild.create_text_channel(name=channel_name[:30], category=category, overwrites=overwrites)
            await itx.followup.send(f"✅ Seu chat de recrutamento foi criado: {channel.mention}. Vá até lá e responda às perguntas!", ephemeral=True)
            
            # Inicia o loop de perguntas em segundo plano
            bot.loop.create_task(run_interview(channel, itx.user))
        except Exception as e:
            logger.error(f"Erro ao criar chat de recrutamento: {e}")
            await itx.followup.send("❌ Erro ao criar o chat. Verifique as permissões do bot.", ephemeral=True)


# ──────────────────────────────────────────────────────────────
# 💉 SOLICITAÇÃO DE EXAMES
# ──────────────────────────────────────────────────────────────
class ExamesModal(discord.ui.Modal, title="📅 Solicitação de Exames"):
    nome_completo = discord.ui.TextInput(label="Nome completo do paciente", style=discord.TextStyle.short, required=True)
    identificacao = discord.ui.TextInput(label="Número de identificação (ID)", style=discord.TextStyle.short, required=True)
    motivo = discord.ui.TextInput(label="Exame Solicitado / Motivo", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        channel_name = f"exame-{self.nome_completo.value.replace(' ', '-').lower()[:20]}"
        
        overwrites = {
            itx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            itx.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        }
        
        cat_id = await get_config_channel("ticket_category")
        category = itx.guild.get_channel(cat_id) if cat_id else None

        try:
            channel = await itx.guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
            embed = discord.Embed(
                title="📋 Nova Solicitação de Exames",
                description=f"**Paciente:** {self.nome_completo.value}\n**ID:** {self.identificacao.value}\n**Detalhes:** {self.motivo.value}",
                color=0xFFB6C1,
                timestamp=now_br()
            )
            await channel.send(content=itx.user.mention, embed=embed)
            close_view = discord.ui.View()
            close_view.add_item(CloseChannelButton(channel.id))
            await channel.send("🔒 **Para encerrar esta solicitação, clique no botão abaixo.**", view=close_view)
            await itx.followup.send(f"🌸 Solicitação de exame enviada! Acompanhe em: {channel.mention}", ephemeral=True)
        except Exception as e:
            await itx.followup.send("❌ Erro ao criar o canal.", ephemeral=True)

class SolicitarExamesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="📅 Solicitar Exame", style=discord.ButtonStyle.danger, custom_id="solicitar_exames_btn")
    async def btn(self, itx: discord.Interaction, _: discord.ui.Button):
        await itx.response.send_modal(ExamesModal())

# ──────────────────────────────────────────────────────────────
# 🏥 AGENDAR CONSULTA
# ──────────────────────────────────────────────────────────────
SPECIALTIES = {
    "psicologia": {"emoji": "🧠", "label": "Psicologia"},
    "obstetricia": {"emoji": "🤰", "label": "Obstetrícia"},
    "pediatria": {"emoji": "👶", "label": "Pediatria"},
    "cirurgia": {"emoji": "🔪", "label": "Cirurgia"},
    "clinico_geral": {"emoji": "🩺", "label": "Clínico Geral"}
}

class PatientModal(discord.ui.Modal):
    def __init__(self, specialty_key: str):
        super().__init__(title=f"📝 Agendar: {SPECIALTIES[specialty_key]['label']}")
        self.specialty_key = specialty_key

    nome_paciente = discord.ui.TextInput(label="Nome do paciente", style=discord.TextStyle.short, required=True)
    descricao = discord.ui.TextInput(label="Motivo da Consulta", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        specialty = SPECIALTIES[self.specialty_key]
        
        overwrites = {
            itx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            itx.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        }
        
        cat_id = await get_config_channel("ticket_category")
        category = itx.guild.get_channel(cat_id) if cat_id else None
        channel_name = f"consulta-{self.specialty_key}-{self.nome_paciente.value.replace(' ', '-').lower()[:10]}"

        try:
            channel = await itx.guild.create_text_channel(name=channel_name, category=category, overwrites=overwrites)
            embed = discord.Embed(
                title=f"{specialty['emoji']} Consulta Agendada - {specialty['label']}",
                description=f"**Paciente:** {self.nome_paciente.value}\n**Solicitado por:** {itx.user.mention}\n**Motivo:** {self.descricao.value or 'Não informado'}",
                color=0xFF69B4,
                timestamp=now_br()
            )
            await channel.send(content=itx.user.mention, embed=embed)
            close_view = discord.ui.View()
            close_view.add_item(CloseChannelButton(channel.id))
            await channel.send("🔒 **Para encerrar esta consulta, clique no botão abaixo.**", view=close_view)
            await itx.followup.send(f"🌸 Consulta criada com sucesso! {channel.mention}", ephemeral=True)
        except Exception as e:
            await itx.followup.send("❌ Erro ao criar o canal.", ephemeral=True)

class AgendarConsultaMultiView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key, spec in SPECIALTIES.items():
            btn = discord.ui.Button(label=spec["label"], emoji=spec["emoji"], style=discord.ButtonStyle.danger, custom_id=f"agendar_{key}")
            btn.callback = self.create_callback(key)
            self.add_item(btn)
            
    def create_callback(self, specialty_key):
        async def callback(itx: discord.Interaction):
            await itx.response.send_modal(PatientModal(specialty_key))
        return callback

class CloseChannelButton(discord.ui.Button):
    def __init__(self, channel_id: int):
        super().__init__(label="🔒 Fechar Ticket", style=discord.ButtonStyle.danger, custom_id=f"close_{channel_id}")
        self.channel_id = channel_id

    async def callback(self, itx: discord.Interaction):
        channel = itx.guild.get_channel(self.channel_id)
        if channel:
            await itx.response.send_message("🌸 O canal será deletado em 5 segundos...", ephemeral=False)
            await discord.utils.sleep_until(now_br() + datetime.timedelta(seconds=5))
            await channel.delete()

# ──────────────────────────────────────────────────────────────
# 📢 PAINEL DE ANÚNCIO
# ──────────────────────────────────────────────────────────────
class AnnouncementModal(discord.ui.Modal, title="📢 Criar Anúncio"):
    titulo = discord.ui.TextInput(label="Título do anúncio", style=discord.TextStyle.short, required=True)
    descricao = discord.ui.TextInput(label="Descrição / Mensagem", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, itx: discord.Interaction):
        embed = discord.Embed(title=self.titulo.value, description=self.descricao.value, color=0xFF69B4, timestamp=now_br())
        await itx.channel.send(embed=embed)
        await itx.response.send_message("🌸 Anúncio enviado com sucesso!", ephemeral=True)

# ──────────────────────────────────────────────────────────────
# 🎀 COMANDOS DE BARRA
# ──────────────────────────────────────────────────────────────
@bot.tree.command(name="painel_config", description="[ADMIN] Configura as permissões e categorias ⚙️")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_config(itx: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ Painel de Configuração do NORTH 🎀",
        description="Defina quem controla os painéis e onde os tickets serão criados.",
        color=0xFF1493
    )
    await itx.response.send_message(embed=embed, view=ConfigPanelView(), ephemeral=True)

@bot.tree.command(name="painel_set", description="[ADMIN] Cria o painel de Registro (Set) 📢")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_set(itx: discord.Interaction):
    embed = discord.Embed(
        title="📢 Central de Registros - NORTH HOSPITAL 🎀",
        description="**Faça o seu registro em nossa equipe!** 🌸\n\nClique no botão abaixo para solicitar seu Set.",
        color=0xFFB6C1
    )
    await itx.channel.send(embed=embed, view=SetView())
    await itx.response.send_message("🎀 Painel de Set criado!", ephemeral=True)

@bot.tree.command(name="painel_recrutamento", description="[ADMIN] Cria o painel de Trabalhe Conosco 💼")
@app_commands.default_permissions(administrator=True)
async def cmd_painel_recrutamento(itx: discord.Interaction):
    texto = (
        "📋 **Formulário Recrutamento – Hospital North**\n\n"
        "📌 **Processo de Recrutamento**\n"
        "Após a submissão deste formulário, a sua candidatura será analisada pela Direção do Hospital North. Os candidatos selecionados serão contactados para participar numa avaliação psicológica, seguida de uma entrevista, caso aprovados.\n\n"
        "Os candidatos que demonstrarem aptidão para a função poderão ingressar num período experimental antes da contratação definitiva.\n\n"
        "⚠️ O preenchimento deste formulário não garante a contratação.\n"
        "*(Seus dados estão protegidos e não serão compartilhados com terceiros)*"
    )
    embed = discord.Embed(description=texto, color=0x4169E1)
    await itx.channel.send(embed=embed, view=RecrutamentoView())
    await itx.response.send_message("🎀 Painel de Recrutamento criado!", ephemeral=True)

@bot.tree.command(name="solicitar_exames", description="Envia o painel para solicitação de exames 💉")
async def cmd_solicitar_exames(itx: discord.Interaction):
    embed = discord.Embed(
        title="💉 Solicitação de Exames - NORTH HOSPITAL",
        description="Para solicitar seus exames, clique no botão abaixo. Um chat temporário será criado.",
        color=0xFF69B4
    )
    await itx.response.send_message(embed=embed, view=SolicitarExamesView())

@bot.tree.command(name="agendarconsulta", description="Envia o painel para agendar consulta médica 🏥")
async def cmd_agendarconsulta(itx: discord.Interaction):
    embed = discord.Embed(
        title="🏥 Agendar Consulta - NORTH HOSPITAL",
        description="Selecione sua especialidade abaixo para agendarmos sua consulta.",
        color=0xFF69B4
    )
    await itx.response.send_message(embed=embed, view=AgendarConsultaMultiView())

@bot.tree.command(name="anuncio", description="[ADMIN] Crie um anúncio 📢")
@app_commands.default_permissions(administrator=True)
async def cmd_anuncio(itx: discord.Interaction):
    await itx.response.send_modal(AnnouncementModal())

# ──────────────────────────────────────────────────────────────
# 🚀 INICIALIZAÇÃO
# ──────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await init_db()

    bot.add_view(ConfigPanelView())
    bot.add_view(SetView())
    bot.add_view(SetActionView())
    bot.add_view(RecrutamentoView())
    bot.add_view(SolicitarExamesView())
    bot.add_view(AgendarConsultaMultiView())

    try:
        synced = await bot.tree.sync()
        logger.info(f"Comandos sincronizados: {len(synced)}")
    except Exception as exc:
        logger.error(f"Erro ao sincronizar comandos: {exc}")

    logger.info(f"🌸 {bot.user} online! Todos os painéis carregados.")

if __name__ == "__main__":
    if not TOKEN: raise SystemExit("❌ DISCORD_TOKEN ausente.")
    bot.run(TOKEN)
