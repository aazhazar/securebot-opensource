import discord
from discord import app_commands
import time
from collections import defaultdict
import re
import json
import os
from dotenv import load_dotenv
import uuid
import urllib.parse
from aiohttp import web
import aiohttp
import asyncio

load_dotenv()

# ================= Configuration =================
TOKEN = os.getenv("TOKEN")
LOGO_URL = ""

# Bad words list for chat automod
BAD_WORDS = ["badword1", "badword2"] 
INVITE_REGEX = re.compile(r"(discord\.gg/|discord\.com/invite/|discordapp\.com/invite/)")
CONFIG_FILE = "security_config.json"
GLOBAL_CONFIG_FILE = "global_config.json"
# =================================================

intents = discord.Intents.all() # Enabling all intents for maximum protection

class SecurityClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Sync the global commands to Discord
        await self.tree.sync()
        print("Synced commands globally.")
        
        # Start API
        self.loop.create_task(start_web_server())

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        print("Activity Check Security Bot is running with MAX protection.")
        print(f"Currently in {len(self.guilds)} servers.")
        try:
            activity = discord.Game(name="/setup | securebot.top")
            await self.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            print(f"Failed to set presence: {e}")

        # Setup Global Webhook
        target_guild = self.get_guild(1505879959170973799)
        if target_guild:
            log_channel = discord.utils.get(target_guild.channels, name="global-logs")
            if not log_channel:
                try: log_channel = await target_guild.create_text_channel("global-logs")
                except: pass
            if log_channel:
                try:
                    webhooks = await log_channel.webhooks()
                    bot_webhook = discord.utils.get(webhooks, name="Secure Bot Global Webhook")
                    if not bot_webhook: bot_webhook = await log_channel.create_webhook(name="Secure Bot Global Webhook")
                    if global_config.get("global_webhook") != bot_webhook.url:
                        global_config["global_webhook"] = bot_webhook.url
                        save_global_config()
                except Exception as e: print(f"Webhook setup failed: {e}")

    async def on_guild_join(self, guild):
        print(f"Joined new server: {guild.name} (ID: {guild.id})")
        embed = discord.Embed(title="🟢 Joined New Server", description=f"**Name:** {guild.name}\n**ID:** {guild.id}\n**Members:** {guild.member_count}\n**Total Servers:** {len(self.guilds)}", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=guild.icon.url if guild.icon else LOGO_URL)
        await send_global_log(embed)

    async def on_guild_remove(self, guild):
        print(f"Left server: {guild.name} (ID: {guild.id})")
        embed = discord.Embed(title="🔴 Left Server", description=f"**Name:** {guild.name}\n**ID:** {guild.id}\n**Members:** {guild.member_count}\n**Total Servers:** {len(self.guilds)}", color=discord.Color.red(), timestamp=discord.utils.utcnow())
        embed.set_thumbnail(url=guild.icon.url if guild.icon else LOGO_URL)
        await send_global_log(embed)

client = SecurityClient(intents=intents)

# ---- DASHBOARD API ----
sessions = {} # token -> user dict

async def handle_options(request):
    return web.Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "*"})

def cors_response(data, status=200):
    return web.json_response(data, status=status, headers={"Access-Control-Allow-Origin": "*"})

async def api_login(request):
    client_id = os.getenv("DISCORD_CLIENT_ID")
    redirect_uri = urllib.parse.quote("http://localhost:5173/auth/callback")
    url = f"https://discord.com/api/oauth2/authorize?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope=identify%20guilds"
    return cors_response({"url": url})

async def api_callback(request):
    data = await request.json()
    code = data.get("code")
    client_id = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    redirect_uri = "http://localhost:5173/auth/callback"

    if client_id == "YOUR_CLIENT_ID_HERE" or client_secret == "YOUR_CLIENT_SECRET_HERE" or not client_id:
         # Development fallback if user hasn't set env vars yet
         token = str(uuid.uuid4())
         sessions[token] = {"id": "123", "username": "Admin", "access_token": "dummy"}
         return cors_response({"token": token, "user": sessions[token]})

    async with aiohttp.ClientSession() as session:
        resp = await session.post("https://discord.com/api/oauth2/token", data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri
        })
        token_data = await resp.json()
        if "access_token" not in token_data:
            return cors_response({"error": "Failed to authenticate"}, status=400)
            
        access_token = token_data["access_token"]
        
        user_resp = await session.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {access_token}"})
        user_data = await user_resp.json()
        
        token = str(uuid.uuid4())
        sessions[token] = {"id": user_data["id"], "username": user_data["username"], "access_token": access_token}
        
        return cors_response({"token": token, "user": sessions[token]})

async def api_guilds(request):
    token = request.headers.get("Authorization")
    if token not in sessions: return cors_response({"error": "Unauthorized"}, status=401)
    
    session_data = sessions[token]
    
    # Dummy data fallback
    if session_data["access_token"] == "dummy":
        guilds = []
        for g in client.guilds:
            guilds.append({"id": str(g.id), "name": g.name, "icon": getattr(g.icon, 'url', None), "is_admin": True})
        return cors_response({"guilds": guilds})

    async with aiohttp.ClientSession() as http_session:
        guilds_resp = await http_session.get("https://discord.com/api/users/@me/guilds", headers={"Authorization": f"Bearer {session_data['access_token']}"})
        user_guilds = await guilds_resp.json()
        
        valid_guilds = []
        bot_guild_ids = [str(g.id) for g in client.guilds]
        for g in user_guilds:
            if (int(g.get("permissions", 0)) & 0x8) == 0x8 and str(g["id"]) in bot_guild_ids:
                valid_guilds.append({
                    "id": g["id"],
                    "name": g["name"],
                    "icon": f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png" if g.get("icon") else None,
                    "is_admin": True
                })
                
        return cors_response({"guilds": valid_guilds})

async def api_get_settings(request):
    guild_id = request.match_info.get("id")
    token = request.headers.get("Authorization")
    if token not in sessions: return cors_response({"error": "Unauthorized"}, status=401)
    
    config = get_guild_config(guild_id)
    return cors_response({"config": config})

async def api_save_settings(request):
    guild_id = request.match_info.get("id")
    token = request.headers.get("Authorization")
    if token not in sessions: return cors_response({"error": "Unauthorized"}, status=401)
    
    data = await request.json()
    config_cache[guild_id] = data
    save_config(config_cache)
    return cors_response({"status": "success"})

async def start_web_server():
    app = web.Application()
    app.add_routes([
        web.get('/api/auth/login', api_login),
        web.post('/api/auth/callback', api_callback),
        web.get('/api/user/guilds', api_guilds),
        web.get('/api/guilds/{id}/settings', api_get_settings),
        web.post('/api/guilds/{id}/settings', api_save_settings),
        
        web.options('/api/auth/login', handle_options),
        web.options('/api/auth/callback', handle_options),
        web.options('/api/user/guilds', handle_options),
        web.options('/api/guilds/{id}/settings', handle_options)
    ])
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    await site.start()
    print("Dashboard API running on http://0.0.0.0:5000")
# -----------------------------

# --- Trackers ---
action_trackers = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
spam_tracker = defaultdict(lambda: defaultdict(list))
security_history = [] # Stores last 20 events: {"time": timestamp, "event": str, "user": str}
recent_punishments = defaultdict(lambda: defaultdict(float)) # Prevents duplicate punishment/logs during mass events

# --- Config Management ---
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

def load_global_config():
    if os.path.exists(GLOBAL_CONFIG_FILE):
        try:
            with open(GLOBAL_CONFIG_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError: pass
    return {"total_automod_rules": 0, "global_webhook": None}

def save_global_config():
    with open(GLOBAL_CONFIG_FILE, "w") as f:
        json.dump(global_config, f, indent=4)

global_config = load_global_config()

async def send_global_log(embed):
    webhook_url = global_config.get("global_webhook")
    if not webhook_url: return
    try:
        async with aiohttp.ClientSession() as session:
            webhook = discord.Webhook.from_url(webhook_url, session=session)
            await webhook.send(embed=embed, username="Secure Bot Globals", avatar_url=client.user.avatar.url if client.user.avatar else None)
    except Exception as e:
        print(f"Failed to send global log: {e}")

config_cache = load_config()

DEFAULT_GUILD_CONFIG = {
    "modules": {
        "mass_ban": {"enabled": True, "punishment": "ban", "limits": {"60": 5, "3600": 10}},
        "mass_kick": {"enabled": True, "punishment": "ban", "limits": {"60": 5, "3600": 10}},
        "mass_channel_delete": {"enabled": True, "punishment": "ban", "limits": {"60": 3}},
        "mass_role_delete": {"enabled": True, "punishment": "ban", "limits": {"60": 3}},
        "anti_bot": {"enabled": True, "punishment": "ban"},
        "anti_webhook": {"enabled": True, "punishment": "ban"},
        "anti_guild_update": {"enabled": True, "punishment": "ban"},
        "anti_vanity_change": {"enabled": True, "punishment": "ban"},
        "anti_integration": {"enabled": True, "punishment": "ban"},
        "anti_emoji_delete": {"enabled": True, "punishment": "ban", "limits": {"60": 5}},
        "anti_sticker_delete": {"enabled": True, "punishment": "ban", "limits": {"60": 5}},
        "anti_dangerous_permissions": {"enabled": True, "punishment": "ban"},
        "automod": {"enabled": True},
        "anti_spam": {"enabled": True, "limit": 5, "interval": 5},
        "age_gate": {"enabled": False, "min_days": 7},
        "scam_detection": {"enabled": False, "channel_id": None}
    },
    "logs": {
        "mod": None,
        "security": None
    }
}

def get_guild_config(guild_id):
    gid = str(guild_id)
    if gid not in config_cache:
        config_cache[gid] = json.loads(json.dumps(DEFAULT_GUILD_CONFIG)) # Deep copy
        save_config(config_cache)
    else:
        # Self-healing: Ensure all modules from default exist in current config
        changed = False
        for mod, data in DEFAULT_GUILD_CONFIG["modules"].items():
            if mod not in config_cache[gid]["modules"]:
                config_cache[gid]["modules"][mod] = data.copy()
                changed = True
        
        # Self-healing: Ensure log channels are set
        if "logs" not in config_cache[gid]:
            config_cache[gid]["logs"] = {}
            changed = True
        for key, val in DEFAULT_GUILD_CONFIG["logs"].items():
            if key not in config_cache[gid]["logs"] or config_cache[gid]["logs"][key] is None:
                config_cache[gid]["logs"][key] = val
                changed = True
                
        if changed:
            save_config(config_cache)
    return config_cache[gid]

async def log_security(guild, embed):
    g_config = get_guild_config(guild.id)
    sec_id = g_config["logs"].get("security")
    if sec_id:
        channel = guild.get_channel(sec_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except:
                pass

async def log_mod(guild, embed):
    g_config = get_guild_config(guild.id)
    mod_id = g_config["logs"].get("mod")
    if mod_id:
        channel = guild.get_channel(mod_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except:
                pass

def is_authorized_user():
    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)

# --- Helper for Punishment ---
async def take_punishment(guild, user, reason, action_type):
    now = time.time()
    if now - recent_punishments[guild.id][user.id] < 10:
        return # Prevent duplicate logs and rate limits if already punished recently
    recent_punishments[guild.id][user.id] = now

    g_config = get_guild_config(guild.id)
    module_config = g_config["modules"].get(action_type, {})
    if not module_config.get("enabled", True): return
    
    # Add to history
    security_history.insert(0, {"time": time.time(), "event": action_type.replace('_', ' ').title(), "user": f"{user} ({user.id})", "reason": reason})
    if len(security_history) > 20: security_history.pop()

    punishment = module_config.get("punishment", "ban")
    try:
        if punishment == "ban" and guild.me.guild_permissions.ban_members: 
            await guild.ban(user, reason=reason)
        elif punishment == "kick" and guild.me.guild_permissions.kick_members: 
            await guild.kick(user, reason=reason)
        elif punishment == "strip" and guild.me.guild_permissions.manage_roles and isinstance(user, discord.Member):
            roles_to_remove = [r for r in user.roles if r.name != "@everyone" and r < guild.me.top_role]
            if roles_to_remove: await user.remove_roles(*roles_to_remove, reason=reason)
        
        # Log the action
        embed = discord.Embed(title="🛡️ Instant Protection Triggered", description=f"**Action:** {punishment.upper()}\n**User:** {user.mention} ({user.id})\n**Module:** {action_type.replace('_', ' ').title()}\n**Reason:** {reason}", color=discord.Color.red())
        embed.set_thumbnail(url=LOGO_URL)
        await log_security(guild, embed)
        
        # DM the Server Owner
        try:
            if guild.owner:
                await guild.owner.send(embed=embed)
        except: pass
    except: pass

# --- Events ---
@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Activity Check Security Bot is running with MAX protection.")
    print(f"Currently in {len(client.guilds)} servers. Cleaning up duplicate commands...")
    
    cleaned_count = 0
    for guild in client.guilds:
        try:
            client.tree.clear_commands(guild=guild)
            await client.tree.sync(guild=guild)
            cleaned_count += 1
        except Exception as e:
            print(f"Failed to clean commands for {guild.id}: {e}")
            
    print(f"Successfully cleaned duplicate commands from {cleaned_count}/{len(client.guilds)} servers.")

@client.event
async def on_guild_join(guild):
    print(f"Joined new server: {guild.name} (ID: {guild.id})")

@client.event
async def on_member_join(member):
    g_config = get_guild_config(member.guild.id)
    
    # 1. Age Gate Check
    if g_config["modules"]["age_gate"]["enabled"]:
        min_days = g_config["modules"]["age_gate"].get("min_days", 7)
        account_age = (discord.utils.utcnow() - member.created_at).days
        if account_age < min_days:
            try:
                await member.send(f"⚠️ Your account is too new to join **{member.guild.name}**. Minimum age: {min_days} days.")
            except: pass
            await member.kick(reason=f"Security: Age Gate ({account_age}d < {min_days}d)")
            return

    # 2. Anti-Bot Check
    if member.bot and g_config["modules"]["anti_bot"]["enabled"]:
        try:
            if member.guild.me.guild_permissions.view_audit_log:
                async for entry in member.guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=1):
                    if entry.target.id == member.id:
                        adder = entry.user
                        if adder.id != member.guild.owner_id:
                            await take_punishment(member.guild, adder, f"Unauthorized bot added: {member.name}", "anti_bot")
                            if member.top_role < member.guild.me.top_role:
                                await member.ban(reason="Unauthorized bot.")
                        break
        except discord.Forbidden:
            pass

    if member.bot: return
    # Log member join
    try:
        embed = discord.Embed(description=f"📥 {member.mention} joined the server.", color=discord.Color.green(), timestamp=discord.utils.utcnow())
        embed.set_author(name=member.name, icon_url=member.display_avatar.url if member.display_avatar else member.default_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        await log_mod(member.guild, embed)
    except: pass

@client.event
async def on_guild_update(before, after):
    g_config = get_guild_config(after.id)
    if not g_config["modules"]["anti_guild_update"]["enabled"]: return
    
    try:
        async for entry in after.audit_logs(action=discord.AuditLogAction.guild_update, limit=1):
            if entry.user.id != after.owner_id:
                # Revert changes immediately if possible
                if before.name != after.name: await after.edit(name=before.name)
                if before.icon != after.icon: await after.edit(icon=before.icon)
                if before.vanity_url_code != after.vanity_url_code:
                    # Special handling for vanity change
                    await take_punishment(after, entry.user, "Unauthorized Vanity URL change.", "anti_vanity_change")
                else:
                    await take_punishment(after, entry.user, "Unauthorized server update.", "anti_guild_update")
            break
    except: pass

@client.event
async def on_webhooks_update(channel):
    g_config = get_guild_config(channel.guild.id)
    if not g_config["modules"]["anti_webhook"]["enabled"]: return
    
    try:
        async for entry in channel.guild.audit_logs(limit=1):
            if entry.action in [discord.AuditLogAction.webhook_create, discord.AuditLogAction.webhook_delete, discord.AuditLogAction.webhook_update]:
                if entry.user.id != channel.guild.owner_id:
                    await take_punishment(channel.guild, entry.user, "Unauthorized Webhook manipulation.", "anti_webhook")
                    if entry.action == discord.AuditLogAction.webhook_create:
                        # Attempt to delete the malicious webhook
                        try:
                            webhooks = await channel.webhooks()
                            for wh in webhooks:
                                if wh.id == entry.target.id: await wh.delete(reason="Security: Unauthorized webhook.")
                        except: pass
                break
    except: pass

@client.event
async def on_member_update(before, after):
    g_config = get_guild_config(after.guild.id)
    
    # Anti Dangerous Permissions
    if g_config["modules"]["anti_dangerous_permissions"]["enabled"]:
        if before.roles != after.roles:
            added_roles = [role for role in after.roles if role not in before.roles]
            for role in added_roles:
                dangerous_perms = [
                    role.permissions.administrator,
                    role.permissions.manage_guild,
                    role.permissions.manage_roles,
                    role.permissions.manage_channels,
                    role.permissions.ban_members,
                    role.permissions.kick_members
                ]
                if any(dangerous_perms):
                    try:
                        async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_role_update, limit=1):
                            if entry.target.id == after.id and entry.user.id != after.guild.owner_id:
                                # Revert the role add
                                await after.remove_roles(role, reason="Security: Unauthorized dangerous role grant.")
                                await take_punishment(after.guild, entry.user, f"Attempted to grant dangerous role ({role.name}) to {after.name}", "anti_dangerous_permissions")
                            break
                    except: pass

    # Original logging
    if before.roles != after.roles:
        added_roles = [role for role in after.roles if role not in before.roles]
        removed_roles = [role for role in before.roles if role not in after.roles]
        if added_roles or removed_roles:
            embed = discord.Embed(title="🏷️ Member Roles Updated", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
            embed.set_author(name=f"{after.name} ({after.id})", icon_url=after.display_avatar.url if after.display_avatar else after.default_avatar.url)
            if added_roles: embed.add_field(name="Roles Added", value=", ".join([r.mention for r in added_roles]), inline=False)
            if removed_roles: embed.add_field(name="Roles Removed", value=", ".join([r.mention for r in removed_roles]), inline=False)
            await log_mod(after.guild, embed)

    if before.nick != after.nick:
        try:
            embed = discord.Embed(title="👤 Nickname Changed", description=f"**User:** {after.mention}\n**Before:** `{before.nick or 'None'}`\n**After:** `{after.nick or 'None'}`", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
            embed.set_author(name=f"{after.name} ({after.id})", icon_url=after.display_avatar.url if after.display_avatar else after.default_avatar.url)
            await log_mod(after.guild, embed)
        except: pass

@client.event
async def on_audit_log_entry(entry):
    action_type = None
    if entry.action == discord.AuditLogAction.ban: action_type = "mass_ban"
    elif entry.action == discord.AuditLogAction.kick: action_type = "mass_kick"
    elif entry.action == discord.AuditLogAction.channel_delete: action_type = "mass_channel_delete"
    elif entry.action == discord.AuditLogAction.role_delete: action_type = "mass_role_delete"
    elif entry.action == discord.AuditLogAction.emoji_delete: action_type = "anti_emoji_delete"
    elif entry.action == discord.AuditLogAction.sticker_delete: action_type = "anti_sticker_delete"
    elif entry.action == discord.AuditLogAction.integration_create: action_type = "anti_integration"
    
    if not action_type: return
    
    guild, admin = entry.guild, entry.user
    if admin.id == guild.owner_id or admin.id == client.user.id: return

    g_config = get_guild_config(guild.id)
    module_config = g_config["modules"].get(action_type, {})
    if not module_config.get("enabled", True): return

    # Check for immediate one-time actions
    if action_type in ["anti_integration"]:
        await take_punishment(guild, admin, "Unauthorized integration added.", action_type)
        return

    now = time.time()
    tracker = action_trackers[guild.id][action_type][admin.id]
    tracker.append(now)
    
    limits = module_config.get("limits", {})
    if not limits: 
        # If no limits defined but module enabled, act on first trigger
        await take_punishment(guild, admin, f"Unauthorized {action_type.replace('_', ' ')} detected.", action_type)
        return

    max_time = max([int(k) for k in limits.keys()] + [86400])
    tracker = [t for t in tracker if now - t <= max_time]
    action_trackers[guild.id][action_type][admin.id] = tracker
    
    for timeframe_str, limit_count in sorted(limits.items(), key=lambda x: int(x[0])):
        timeframe = int(timeframe_str)
        count = sum(1 for t in tracker if now - t <= timeframe)
        if count >= limit_count:
            await take_punishment(guild, admin, f"Mass {action_type.replace('_', ' ')} detected ({limit_count}+ in {timeframe}s).", action_type)
            action_trackers[guild.id][action_type][admin.id] = []
            break

@client.event
async def on_member_remove(member):
    embed = discord.Embed(description=f"❌ {member.mention} has left the server.", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.set_author(name=member.name, icon_url=member.display_avatar.url if member.display_avatar else member.default_avatar.url)
    embed.set_footer(text=f"User ID: {member.id}")
    await log_security(member.guild, embed)

@client.event
async def on_member_ban(guild, user):
    embed = discord.Embed(title="Member Banned", description=f"🔨 {user.mention} has been banned.", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url if user.display_avatar else user.default_avatar.url)
    await log_mod(guild, embed)

@client.event
async def on_member_unban(guild, user):
    embed = discord.Embed(title="Member Unbanned", description=f"🔓 {user.mention} has been unbanned.", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url if user.display_avatar else user.default_avatar.url)
    await log_mod(guild, embed)

@client.event
async def on_message(message):
    if message.author.bot or message.guild is None: return
    if message.author.id == message.guild.owner_id: return

    g_config = get_guild_config(message.guild.id)

    # --- Scam Detection Module ---
    scam_config = g_config["modules"].get("scam_detection", {})
    if scam_config.get("enabled", False):
        trap_channel_id = scam_config.get("channel_id")
        if trap_channel_id and message.channel.id == trap_channel_id:
            member = message.author
            guild = message.guild

            # Send DM first
            try:
                dm_text = f"We kicked you from activity check for sending message on scam detection channel you can rejoin https://discord.gg/activitycheck"
                await member.send(dm_text)
            except Exception as e:
                print(f"Failed to DM user: {e}")

            # Delete message
            try:
                await message.delete()
            except Exception as e:
                print(f"Failed to delete message: {e}")

            # Soft-ban member to delete all their messages from the last 7 days, then unban so they can rejoin
            action_taken = "KICK"
            try:
                await guild.ban(member, reason="Scam Detection: Soft-ban to purge messages", delete_message_seconds=604800)
                await guild.unban(member, reason="Scam Detection: Unbanned after message purge")
                action_taken = "SOFT-BAN (Kicked & Messages Purged)"
            except Exception as e:
                print(f"Failed to soft-ban: {e}. Attempting standard kick...")
                try:
                    await guild.kick(member, reason="Sent message in scam detection channel")
                except Exception as kick_err:
                    print(f"Failed to kick user: {kick_err}")
                    action_taken = "FAILED TO PUNISH"

            # Log action
            embed = discord.Embed(
                title="🛡️ Scam Detection Triggered",
                description=f"**User:** {member.mention} ({member.id})\n**Channel:** {message.channel.mention}\n**Action:** {action_taken}\n**Message Content:** {message.content[:1000]}",
                color=discord.Color.red()
            )
            embed.set_thumbnail(url=LOGO_URL)
            await log_security(guild, embed)

            # Add to history
            security_history.insert(0, {
                "time": time.time(),
                "event": "Scam Detection",
                "user": f"{member} ({member.id})",
                "reason": "Sent message in scam detection channel"
            })
            if len(security_history) > 20:
                security_history.pop()

            # DM the Server Owner
            try:
                if guild.owner:
                    await guild.owner.send(embed=embed)
            except:
                pass

            return

    
    if g_config["modules"]["anti_spam"]["enabled"]:
        now = time.time()
        tracker = spam_tracker[message.guild.id][message.author.id]
        tracker.append(now)
        interval = g_config["modules"]["anti_spam"].get("interval", 5)
        limit = g_config["modules"]["anti_spam"].get("limit", 5)
        tracker = [t for t in tracker if now - t <= interval]
        spam_tracker[message.guild.id][message.author.id] = tracker
        
        if len(tracker) >= limit:
            try:
                await message.author.timeout(discord.utils.utcnow() + discord.utils.timedelta(minutes=5), reason="Anti-Spam")
                await message.channel.send(f"⚠️ {message.author.mention}, you have been timed out due to spamming.", delete_after=10)
                return
            except: pass

    if g_config["modules"]["automod"]["enabled"]:
        content = message.content.lower()
        if INVITE_REGEX.search(content) or any(word in content for word in BAD_WORDS):
            try:
                await message.delete()
                await message.channel.send(f"⚠️ {message.author.mention}, your message was blocked by Automod.", delete_after=5)
                return
            except: pass

async def fetch_audit_log_actor(guild, action, target_id=None):
    if not guild.me.guild_permissions.view_audit_log:
        return None
    try:
        async for entry in guild.audit_logs(action=action, limit=3):
            if target_id is None or entry.target.id == target_id:
                return entry.user
    except:
        pass
    return None

@client.event
async def on_message_delete(message):
    if message.author.bot or message.guild is None: return
    actor = await fetch_audit_log_actor(message.guild, discord.AuditLogAction.message_delete, message.author.id)
    actor_text = f"\n**Deleted By (Likely):** {actor.mention} ({actor.id})" if actor and actor.id != message.author.id else ""
    embed = discord.Embed(title="🗑️ Message Deleted", description=f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}{actor_text}\n**Content:**\n{message.content or '*No text content*'}", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"{message.author.name} ({message.author.id})", icon_url=message.author.display_avatar.url if message.author.display_avatar else message.author.default_avatar.url)
    await log_mod(message.guild, embed)

@client.event
async def on_message_edit(before, after):
    if before.author.bot or before.guild is None: return
    if before.content == after.content: return
    embed = discord.Embed(title="📝 Message Edited", description=f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}\n**Before:**\n{before.content or '*No text*'}\n**After:**\n{after.content or '*No text*'}", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
    embed.set_author(name=f"{before.author.name} ({before.author.id})", icon_url=before.author.display_avatar.url if before.author.display_avatar else before.author.default_avatar.url)
    await log_mod(before.guild, embed)

@client.event
async def on_guild_role_update(before, after):
    changes = []
    if before.name != after.name:
        changes.append(f"• Name: `{before.name}` ➔ `{after.name}`")
    if before.color != after.color:
        changes.append(f"• Color: `{before.color}` ➔ `{after.color}`")
    if before.permissions != after.permissions:
        added_perms = [p[0] for p in after.permissions if p[1] and not getattr(before.permissions, p[0])]
        removed_perms = [p[0] for p in before.permissions if p[1] and not getattr(after.permissions, p[0])]
        if added_perms:
            changes.append(f"• Added Perms: {', '.join(added_perms)}")
        if removed_perms:
            changes.append(f"• Removed Perms: {', '.join(removed_perms)}")
    if not changes: return
    
    actor = await fetch_audit_log_actor(after.guild, discord.AuditLogAction.role_update, after.id)
    actor_text = f"\n**Updated By:** {actor.mention} ({actor.id})" if actor else ""
    
    embed = discord.Embed(title="🛡️ Server Role Updated", description=f"**Role:** {after.mention} ({after.id}){actor_text}\n\n**Changes:**\n" + "\n".join(changes), color=discord.Color.blue(), timestamp=discord.utils.utcnow())
    await log_security(after.guild, embed)

@client.event
async def on_voice_state_update(member, before, after):
    if before.channel != after.channel:
        embed = discord.Embed(color=discord.Color.light_grey(), timestamp=discord.utils.utcnow())
        embed.set_author(name=f"{member.name} ({member.id})", icon_url=member.display_avatar.url if member.display_avatar else member.default_avatar.url)
        if before.channel is None:
            embed.title = "🔊 Joined Voice Channel"
            embed.description = f"{member.mention} joined {after.channel.mention}"
        elif after.channel is None:
            embed.title = "🔇 Left Voice Channel"
            embed.description = f"{member.mention} left {before.channel.mention}"
        else:
            embed.title = "🔄 Moved Voice Channel"
            embed.description = f"{member.mention} moved from {before.channel.mention} to {after.channel.mention}"
        await log_mod(member.guild, embed)

@client.event
async def on_guild_channel_create(channel):
    actor = await fetch_audit_log_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
    actor_text = f"\n**Created By:** {actor.mention} ({actor.id})" if actor else ""
    embed = discord.Embed(title="📁 Channel Created", description=f"**Name:** {channel.name} ({channel.mention})\n**ID:** {channel.id}{actor_text}", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    await log_security(channel.guild, embed)

@client.event
async def on_guild_channel_delete(channel):
    actor = await fetch_audit_log_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
    actor_text = f"\n**Deleted By:** {actor.mention} ({actor.id})" if actor else ""
    embed = discord.Embed(title="🗑️ Channel Deleted", description=f"**Name:** {channel.name}\n**ID:** {channel.id}{actor_text}", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    await log_security(channel.guild, embed)

@client.event
async def on_guild_role_create(role):
    actor = await fetch_audit_log_actor(role.guild, discord.AuditLogAction.role_create, role.id)
    actor_text = f"\n**Created By:** {actor.mention} ({actor.id})" if actor else ""
    embed = discord.Embed(title="🏷️ Role Created", description=f"**Name:** {role.name} ({role.mention})\n**ID:** {role.id}{actor_text}", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    await log_security(role.guild, embed)

@client.event
async def on_guild_role_delete(role):
    actor = await fetch_audit_log_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
    actor_text = f"\n**Deleted By:** {actor.mention} ({actor.id})" if actor else ""
    embed = discord.Embed(title="🗑️ Role Deleted", description=f"**Name:** {role.name}\n**ID:** {role.id}{actor_text}", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    await log_security(role.guild, embed)

# --- App Commands ---
@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        try:
            await interaction.response.send_message("❌ This command is restricted to server **Administrators** only.", ephemeral=True)
        except:
            try: await interaction.followup.send("❌ This command is restricted to server **Administrators** only.", ephemeral=True)
            except: pass
    else:
        print(f"Command Error: {error}")
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠️ **Internal Error:** {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ **Internal Error:** {error}", ephemeral=True)
        except: pass

MODULE_CHOICES = [
    app_commands.Choice(name="Mass Ban", value="mass_ban"),
    app_commands.Choice(name="Mass Kick", value="mass_kick"),
    app_commands.Choice(name="Mass Channel Delete", value="mass_channel_delete"),
    app_commands.Choice(name="Mass Role Delete", value="mass_role_delete"),
    app_commands.Choice(name="Anti Bot", value="anti_bot"),
    app_commands.Choice(name="Anti Webhook", value="anti_webhook"),
    app_commands.Choice(name="Anti Server Update", value="anti_guild_update"),
    app_commands.Choice(name="Anti Vanity Change", value="anti_vanity_change"),
    app_commands.Choice(name="Anti Integration", value="anti_integration"),
    app_commands.Choice(name="Anti Emoji Delete", value="anti_emoji_delete"),
    app_commands.Choice(name="Anti Sticker Delete", value="anti_sticker_delete"),
    app_commands.Choice(name="Anti Dangerous Permissions", value="anti_dangerous_permissions"),
    app_commands.Choice(name="Automod", value="automod"),
    app_commands.Choice(name="Anti Spam", value="anti_spam"),
    app_commands.Choice(name="Age Gate", value="age_gate"),
    app_commands.Choice(name="Scam Detection", value="scam_detection")
]

@client.tree.command(name="disable", description="Disable a security module")
@app_commands.choices(action=MODULE_CHOICES)
@is_authorized_user()
async def disable_action(interaction: discord.Interaction, action: str):
    await interaction.response.defer(ephemeral=True)
    g_config = get_guild_config(interaction.guild_id)
    g_config["modules"][action]["enabled"] = False
    save_config(config_cache)
    await interaction.followup.send(f"✅ **{action.replace('_', ' ').title()}** module disabled.")

@client.tree.command(name="enable", description="Enable a security module")
@app_commands.choices(action=MODULE_CHOICES)
@is_authorized_user()
async def enable_action(interaction: discord.Interaction, action: str):
    await interaction.response.defer(ephemeral=True)
    g_config = get_guild_config(interaction.guild_id)
    g_config["modules"][action]["enabled"] = True
    save_config(config_cache)
    await interaction.followup.send(f"✅ **{action.replace('_', ' ').title()}** module enabled.")

@client.tree.command(name="setlimit", description="Change the rate limit of an action")
@app_commands.choices(action=[
    app_commands.Choice(name="Mass Ban", value="mass_ban"),
    app_commands.Choice(name="Mass Kick", value="mass_kick"),
    app_commands.Choice(name="Mass Channel Delete", value="mass_channel_delete"),
    app_commands.Choice(name="Mass Role Delete", value="mass_role_delete"),
    app_commands.Choice(name="Anti Emoji Delete", value="anti_emoji_delete"),
    app_commands.Choice(name="Anti Sticker Delete", value="anti_sticker_delete")
])
@is_authorized_user()
async def set_limit(interaction: discord.Interaction, action: str, seconds: int, limit: int):
    await interaction.response.defer(ephemeral=True)
    if seconds <= 0 or limit <= 0: return await interaction.followup.send("❌ Must be > 0.")
    g_config = get_guild_config(interaction.guild_id)
    if "limits" not in g_config["modules"][action]: g_config["modules"][action]["limits"] = {}
    g_config["modules"][action]["limits"][str(seconds)] = limit
    save_config(config_cache)
    await interaction.followup.send(f"✅ Limit updated for **{action}**: {limit} in {seconds}s.")

@client.tree.command(name="setpunishment", description="Change the punishment type for a module")
@app_commands.choices(action=MODULE_CHOICES)
@app_commands.choices(punishment=[
    app_commands.Choice(name="Ban", value="ban"),
    app_commands.Choice(name="Kick", value="kick"),
    app_commands.Choice(name="Strip Roles", value="strip")
])
@is_authorized_user()
async def set_punishment(interaction: discord.Interaction, action: str, punishment: str):
    await interaction.response.defer(ephemeral=True)
    g_config = get_guild_config(interaction.guild_id)
    g_config["modules"][action]["punishment"] = punishment
    save_config(config_cache)
    await interaction.followup.send(f"✅ Punishment for **{action}** set to **{punishment.upper()}**.")

@client.tree.command(name="settings", description="View current security settings")
@is_authorized_user()
async def settings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    g_config = get_guild_config(interaction.guild_id)
    embed = discord.Embed(title="🛡️ Security Configuration", color=discord.Color.purple())
    embed.set_thumbnail(url=LOGO_URL)
    
    sec_log = g_config["logs"].get("security")
    mod_log = g_config["logs"].get("mod")
    log_desc = f"**Security Logs:** <#{sec_log}>\n" if sec_log else "**Security Logs:** Not Set\n"
    log_desc += f"**Mod Logs:** <#{mod_log}>\n" if mod_log else "**Mod Logs:** Not Set\n"
    embed.add_field(name="📋 Logging Channels", value=log_desc, inline=False)
    
    for mod, data in g_config["modules"].items():
        status = "✅" if data.get("enabled", True) else "❌"
        desc = f"Status: {status}\n"
        if "punishment" in data: desc += f"Punishment: {data['punishment'].upper()}\n"
        if "limits" in data:
            for s, c in data["limits"].items(): desc += f"• {c} in {s}s\n"
        if mod == "scam_detection":
            chan_id = data.get("channel_id")
            desc += f"Channel: <#{chan_id}>\n" if chan_id else "Channel: None\n"
        embed.add_field(name=mod.replace("_", " ").title(), value=desc, inline=True)
    await interaction.followup.send(embed=embed)

class SetupConfirmView(discord.ui.View):
    def __init__(self, author_id):
        super().__init__(timeout=60)
        self.author_id = author_id

    @discord.ui.button(label="Confirm Setup", style=discord.ButtonStyle.success, custom_id="setup_confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ You cannot confirm this setup.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        g_config = get_guild_config(guild.id)
        issues = []
        
        # 1. Enable all security modules
        for mod, data in g_config["modules"].items():
            if not data.get("enabled", True): 
                issues.append(f"⚠️ **{mod.replace('_', ' ').title()}** was disabled (Enabled it now).")
            g_config["modules"][mod]["enabled"] = True
            
        # 2. Permission Audit
        me = guild.me
        if not me.guild_permissions.administrator: issues.append("❌ Bot lacks **Administrator** permission. Please grant it for full protection.")
        if not me.guild_permissions.view_audit_log: issues.append("❌ Bot cannot **View Audit Log**.")

        # 3. Setup Scam Trap
        scam_channel_created = False
        trap_channel_id = g_config["modules"].get("scam_detection", {}).get("channel_id")
        trap_channel = guild.get_channel(trap_channel_id) if trap_channel_id else None

        if not trap_channel:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
                }
                trap_channel = await guild.create_text_channel(name="scam-trap-do-not-type", overwrites=overwrites, reason="Security: Scam Trap Setup")
                
                warning_text = (
                    "# WARNING: DO NOT SEND ANY MESSAGES HERE \n"
                    "This is a Scam Detection Trap channel.\n\n"
                    "Why? Accounts hijacked by scammers or automated bots will try to post links in every channel they can find.\n"
                    "What happens? If you send any message in this channel, you will be kicked instantly and your message will be deleted.\n"
                    "If you are a human: Simply ignore/mute this channel and do not type anything.\n"
                    "(If you get kicked by mistake, you can rejoin using the invite link in your DMs)."
                )
                await trap_channel.send(warning_text)
                g_config["modules"]["scam_detection"]["channel_id"] = trap_channel.id
                scam_channel_created = True
            except Exception as e:
                issues.append(f"❌ Failed to create scam trap channel: {e}")

        # 4. Setup Logs Channel
        log_channel_created = False
        log_channel_id = g_config["logs"].get("security") or g_config["logs"].get("mod")
        log_channel = guild.get_channel(log_channel_id) if log_channel_id else None

        if not log_channel:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True)
                }
                log_channel = await guild.create_text_channel(name="security-logs", overwrites=overwrites, reason="Security: Logs Channel Setup")
                g_config["logs"]["security"] = log_channel.id
                g_config["logs"]["mod"] = log_channel.id
                log_channel_created = True
            except Exception as e:
                issues.append(f"❌ Failed to create security logs channel: {e}")

        # 5. Create AutoMod Rules
        automod_rules_created = 0
        try:
            import aiohttp
            actions = [discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message, custom_message="Blocked by Secure Bot")]
            
            # Anti Scam Links
            try:
                scam_words = ["*free-nitro*", "*discord-nítro*", "*steamdiscord.com*", "*gift-nitro*", "*nitro-drop*", "*discord-app.net*"]
                await guild.create_automod_rule(name="Secure Bot: Anti Scam", event_type=discord.AutoModRuleEventType.message_send, trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword, keyword_filter=scam_words), actions=actions, enabled=True, reason="Secure Bot Auto Setup")
                automod_rules_created += 1
            except: pass
            
            # Anti Spam
            try:
                await guild.create_automod_rule(name="Secure Bot: Spam Filter", event_type=discord.AutoModRuleEventType.message_send, trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.spam), actions=actions, enabled=True, reason="Secure Bot Auto Setup")
                automod_rules_created += 1
            except: pass
            
            # Mention Raid Protection
            try:
                await guild.create_automod_rule(name="Secure Bot: Anti Mention Raid", event_type=discord.AutoModRuleEventType.message_send, trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.mention_spam, mention_limit=7), actions=actions, enabled=True, reason="Secure Bot Auto Setup")
                automod_rules_created += 1
            except: pass

            # Load Bad Words from local file
            try:
                import json
                import os
                if os.path.exists("badword.json"):
                    with open("badword.json", "r", encoding="utf-8") as f:
                        words = json.load(f)
                    # Discord allows max 1000 keywords per rule. Chunk them into sizes of 800
                    chunks = [words[i:i + 800] for i in range(0, min(len(words), 2400), 800)]
                    for i, chunk in enumerate(chunks):
                        filter_words = [f"*{w}*" for w in chunk if len(w) > 2][:1000]
                        try:
                            await guild.create_automod_rule(
                                name=f"Secure Bot: Bad Words Filter {i+1}", 
                                event_type=discord.AutoModRuleEventType.message_send, 
                                trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword, keyword_filter=filter_words), 
                                actions=actions, 
                                enabled=True, 
                                reason="Secure Bot Auto Setup local list"
                            )
                            automod_rules_created += 1
                        except Exception: pass
            except Exception as e:
                issues.append(f"⚠️ Failed to load bad words from local file: {e}")
                
        except Exception as e:
            issues.append(f"⚠️ Failed to create AutoMod rules: {e}")

        save_config(config_cache)

        if automod_rules_created > 0:
            global_config["total_automod_rules"] += automod_rules_created
            save_global_config()
            
            total_rules = global_config["total_automod_rules"]
            remaining = max(0, 100 - total_rules)
            log_embed = discord.Embed(title="⚙️ Setup Completed", description=f"**Server:** {guild.name} ({guild.id})\n**Rules Created:** {automod_rules_created}\n**Total Rules Globally:** {total_rules}\n**Badge Progress:** {total_rules}/100 ({remaining} remaining to unlock AutoMod Badge)", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
            try:
                self.author_id # Just to check if we're in the class
                asyncio.create_task(send_global_log(log_embed))
            except: pass
        embed = discord.Embed(title="⚙️ Automatic Setup & Scan Complete", color=discord.Color.green())
        embed.set_thumbnail(url=LOGO_URL)
        
        desc = "**Setup Actions Performed:**\n"
        desc += "✅ Enabled all security modules.\n"
        
        if scam_channel_created: desc += f"✅ Created scam trap channel: {trap_channel.mention}\n"
        else: desc += f"✅ Scam trap channel is already set up: {trap_channel.mention if trap_channel else 'N/A'}\n"
            
        if log_channel_created: desc += f"✅ Created logs channel: {log_channel.mention}\n"
        else: desc += f"✅ Logs channel is already set up: {log_channel.mention if log_channel else 'N/A'}\n"
        
        desc += f"✅ Created **{automod_rules_created}** Discord AutoMod rules (helps unlock the AutoMod badge).\n"
        
        if issues: desc += "\n**Findings & Actions:**\n" + "\n".join(issues)
        else: desc += "\n✅ **Server security is optimal!**"

        embed.description = desc
        try:
            await interaction.edit_original_response(embed=embed, view=None)
        except Exception:
            await interaction.followup.edit_message(interaction.message.id, embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="setup_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ You cannot cancel this setup.", ephemeral=True)
        await interaction.response.edit_message(content="❌ Setup cancelled.", embed=None, view=None)

@client.tree.command(name="setup", description="Analyze the server, enable modules, and setup a scam trap")
@is_authorized_user()
async def setup_server(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚠️ Server Setup Confirmation",
        description=(
            "**Welcome to Secure Bot Setup!**\n\n"
            "This automated process will instantly secure your server by performing the following actions:\n"
            "1. **Enable all security modules** (Anti-Nuke, Anti-Spam, etc.).\n"
            "2. **Create a Scam Trap Channel** (to automatically catch and kick compromised accounts).\n"
            "3. **Create a Security Logs Channel** (to keep track of all administrative actions).\n"
            "4. **Create Discord AutoMod Rules** (Anti-Spam, Anti-Scam, Mention Raid protection).\n\n"
            "Do you wish to proceed?"
        ),
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=LOGO_URL)
    view = SetupConfirmView(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@client.tree.command(name="scan", description="Perform a deep security scan of the server")
@is_authorized_user()
async def scan_server(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    g_config, issues = get_guild_config(interaction.guild_id), []
    for mod, data in g_config["modules"].items():
        if not data.get("enabled", True): issues.append(f"⚠️ **{mod.replace('_', ' ').title()}** is disabled.")
    
    # Permission Audit
    me = interaction.guild.me
    if not me.guild_permissions.administrator: issues.append("❌ Bot lacks **Administrator** permission.")
    if not me.guild_permissions.view_audit_log: issues.append("❌ Bot cannot **View Audit Log**.")
    
    embed = discord.Embed(title="🔍 Deep Security Audit", color=discord.Color.blue())
    embed.set_thumbnail(url=LOGO_URL)
    embed.description = "**Security Findings:**\n" + "\n".join(issues) if issues else "✅ **Server security is optimal!**"
    await interaction.followup.send(embed=embed)

@client.tree.command(name="lockdown", description="Lock or unlock the entire server")
@app_commands.describe(status="True to lock, False to unlock")
@is_authorized_user()
async def lockdown(interaction: discord.Interaction, status: bool):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    everyone = guild.default_role
    perms = everyone.permissions
    perms.update(send_messages=not status, add_reactions=not status, create_public_threads=not status)
    
    try:
        await everyone.edit(permissions=perms, reason="Security: Server Lockdown")
        state = "LOCKED" if status else "UNLOCKED"
        color = discord.Color.red() if status else discord.Color.green()
        embed = discord.Embed(title=f"🔒 Server {state}", description=f"The server has been {state.lower()} by the administrator.", color=color)
        await interaction.followup.send(f"✅ Server {state.lower()} successfully.")
        await log_security(guild, embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to lockdown: {e}")

@client.tree.command(name="panic", description="Triggers a full lockdown and clears all server invites")
@is_authorized_user()
async def panic_button(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    
    # 1. Lockdown
    everyone = guild.default_role
    perms = everyone.permissions
    perms.update(send_messages=False, add_reactions=False, connect=False)
    await everyone.edit(permissions=perms, reason="PANIC BUTTON TRIGGERED")
    
    # 2. Clear Invites
    invite_count = 0
    try:
        invites = await guild.invites()
        for inv in invites:
            await inv.delete(reason="PANIC BUTTON TRIGGERED")
            invite_count += 1
    except: pass
    
    embed = discord.Embed(title="🚨 PANIC SYSTEM ACTIVATED", description=f"**Action:** Full Lockdown\n**Invites Deleted:** {invite_count}\n**Status:** Server is now isolated.", color=discord.Color.dark_red())
    embed.set_thumbnail(url=LOGO_URL)
    await interaction.followup.send("🚨 **PANIC SYSTEM ACTIVATED.** Server is locked and isolated.")
    await log_security(guild, embed)

@client.tree.command(name="clearinvites", description="Instantly delete all server invites")
@is_authorized_user()
async def clear_invites(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    count = 0
    try:
        invites = await guild.invites()
        for inv in invites:
            await inv.delete(reason="Security: Manual Invite Purge")
            count += 1
        await interaction.followup.send(f"✅ Deleted **{count}** invites.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}")

@client.tree.command(name="quarantine", description="Isolate a user by stripping roles and adding a quarantine role")
@is_authorized_user()
async def quarantine_user(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    
    # Create quarantine role if not exists
    role = discord.utils.get(guild.roles, name="Quarantined")
    if not role:
        try:
            role = await guild.create_role(name="Quarantined", color=discord.Color.dark_grey(), reason="Security: Quarantine System")
            for channel in guild.channels:
                await channel.set_permissions(role, send_messages=False, connect=False, add_reactions=False)
        except: return await interaction.followup.send("❌ Failed to create Quarantine role.")

    try:
        # Strip roles
        roles_to_remove = [r for r in user.roles if r.name != "@everyone" and r < guild.me.top_role]
        await user.remove_roles(*roles_to_remove, reason="Quarantined")
        await user.add_roles(role, reason="Quarantined")
        await interaction.followup.send(f"✅ {user.mention} has been quarantined.")
        
        embed = discord.Embed(title="☣️ User Quarantined", description=f"**User:** {user.mention}\n**Admin:** {interaction.user.mention}", color=discord.Color.orange())
        await log_security(guild, embed)
    except:
        await interaction.followup.send("❌ Failed to quarantine user. Check permissions.")

@client.tree.command(name="agegate", description="Set the minimum account age (in days) to join")
@is_authorized_user()
async def set_agegate(interaction: discord.Interaction, days: int, enabled: bool):
    await interaction.response.defer(ephemeral=True)
    g_config = get_guild_config(interaction.guild_id)
    g_config["modules"]["age_gate"]["enabled"] = enabled
    g_config["modules"]["age_gate"]["min_days"] = days
    save_config(config_cache)
    status = "Enabled" if enabled else "Disabled"
    await interaction.followup.send(f"✅ Age Gate **{status}**. Minimum age: **{days} days**.")

@client.tree.command(name="setscamchannel", description="Set the channel used for scam detection (trap channel)")
@app_commands.describe(channel="The channel to use as a scam detection trap")
@is_authorized_user()
async def set_scam_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    g_config = get_guild_config(interaction.guild_id)
    g_config["modules"]["scam_detection"]["channel_id"] = channel.id
    save_config(config_cache)
    await interaction.followup.send(f"✅ Scam detection trap channel set to {channel.mention}.")

@client.tree.command(name="setlogchannel", description="Set the channel used for logging security or mod actions")
@app_commands.choices(log_type=[
    app_commands.Choice(name="Security", value="security"),
    app_commands.Choice(name="Moderation", value="mod")
])
@app_commands.describe(channel="The channel to send logs to")
@is_authorized_user()
async def set_log_channel(interaction: discord.Interaction, log_type: str, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    g_config = get_guild_config(interaction.guild_id)
    g_config["logs"][log_type] = channel.id
    save_config(config_cache)
    await interaction.followup.send(f"✅ **{log_type.title()}** log channel set to {channel.mention}.")

@client.tree.command(name="history", description="View the last 20 security events")
@is_authorized_user()
async def view_history(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not security_history:
        return await interaction.followup.send("📭 No security events recorded yet.")
    
    embed = discord.Embed(title="📜 Security Event History", color=discord.Color.blue())
    for item in security_history[:10]: # Show last 10 in embed
        t = f"<t:{int(item['time'])}:R>"
        embed.add_field(name=f"{item['event']} | {t}", value=f"**User:** {item['user']}\n**Reason:** {item['reason']}", inline=False)
    
    await interaction.followup.send(embed=embed)

@client.tree.command(name="audit", description="Perform a deep permission and vulnerability audit")
@is_authorized_user()
async def audit_permissions(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    vulnerabilities = []
    
    # 1. Administrator Check
    admin_roles = [r.mention for r in guild.roles if r.permissions.administrator and r.name != "@everyone"]
    if admin_roles:
        vulnerabilities.append(f"🚩 **Dangerous Roles:** {', '.join(admin_roles)} have Administrator permissions.")
    
    # 2. @everyone checks
    everyone = guild.default_role
    if everyone.permissions.mention_everyone:
        vulnerabilities.append("🚩 **@everyone** can mention everyone.")
    if everyone.permissions.manage_messages:
        vulnerabilities.append("🚩 **@everyone** can manage messages.")
    
    # 3. Hierarchy check
    if guild.me.top_role.position < guild.roles[-1].position:
        vulnerabilities.append(f"🚩 **Hierarchy:** There are roles above {client.user.mention} that I cannot moderate.")

    embed = discord.Embed(title="🛡️ System Vulnerability Report", color=discord.Color.red())
    embed.description = "\n".join(vulnerabilities) if vulnerabilities else "✅ No major vulnerabilities found!"
    await interaction.followup.send(embed=embed)

@client.tree.command(name="purge", description="Purge messages from the channel or server-wide for a specific user")
@app_commands.describe(
    amount="Number of messages to delete in this channel (default 100)",
    user="Only delete messages from this specific user",
    server_wide_user_purge="If True and a user is selected, soft-bans them to delete all their messages server-wide"
)
@is_authorized_user()
async def purge_messages(
    interaction: discord.Interaction,
    amount: int = 100,
    user: discord.Member = None,
    server_wide_user_purge: bool = False
):
    await interaction.response.defer(ephemeral=True)
    
    if server_wide_user_purge:
        if not user:
            return await interaction.followup.send("❌ You must specify a `user` to perform a server-wide message purge.")
        
        try:
            # Soft-ban user (ban + unban) to purge all messages across the entire server
            await interaction.guild.ban(user, reason="Purged all messages server-wide", delete_message_seconds=604800)
            await interaction.guild.unban(user, reason="Cleaned up messages server-wide")
            
            await interaction.followup.send(f"✅ Successfully purged all messages from {user.mention} server-wide (soft-banned and unbanned).")
            
            # Log action
            embed = discord.Embed(title="🧹 Server-Wide Message Purge", description=f"**User:** {user.mention} ({user.id})\n**Moderator:** {interaction.user.mention}\n**Action:** Soft-ban to delete messages from last 7 days", color=discord.Color.red(), timestamp=discord.utils.utcnow())
            await log_mod(interaction.guild, embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to perform server-wide purge: {e}")
        return

    # Standard channel purge
    if amount <= 0 or amount > 1000:
        return await interaction.followup.send("❌ Amount must be between 1 and 1000.")

    try:
        def check(m):
            return user is None or m.author.id == user.id

        deleted = await interaction.channel.purge(limit=amount, check=check)
        msg_text = f"✅ Deleted {len(deleted)} messages."
        if user:
            msg_text += f" (Filtered to messages from {user.mention})"
        await interaction.followup.send(msg_text)

        # Log action
        embed = discord.Embed(
            title="🧹 Messages Purged",
            description=f"**Moderator:** {interaction.user.mention}\n**Channel:** {interaction.channel.mention}\n**Amount Requested:** {amount}\n**Amount Deleted:** {len(deleted)}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        if user:
            embed.add_field(name="Filtered User", value=f"{user.mention} ({user.id})")
        await log_mod(interaction.guild, embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to purge messages: {e}")

@client.tree.command(name="ban", description="Ban a user from the server")
@app_commands.describe(user="The member to ban", reason="The reason for the ban", delete_message_days="Number of days of messages to delete (0-7)")
@is_authorized_user()
async def ban_user(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided", delete_message_days: int = 0):
    await interaction.response.defer(ephemeral=True)
    if delete_message_days < 0 or delete_message_days > 7:
        return await interaction.followup.send("❌ Message deletion days must be between 0 and 7.")
    
    try:
        # Send DM
        try:
            await user.send(f"🔨 You have been banned from **{interaction.guild.name}**\n**Reason:** {reason}")
        except: pass
        
        await interaction.guild.ban(user, reason=reason, delete_message_seconds=delete_message_days * 86400)
        await interaction.followup.send(f"✅ Successfully banned {user.mention} ({user.id}) for: {reason}")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to ban user: {e}")

@client.tree.command(name="kick", description="Kick a user from the server")
@app_commands.describe(user="The member to kick", reason="The reason for the kick")
@is_authorized_user()
async def kick_user(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    await interaction.response.defer(ephemeral=True)
    try:
        # Send DM
        try:
            await user.send(f"👢 You have been kicked from **{interaction.guild.name}**\n**Reason:** {reason}")
        except: pass
        
        await interaction.guild.kick(user, reason=reason)
        await interaction.followup.send(f"✅ Successfully kicked {user.mention} ({user.id}) for: {reason}")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to kick user: {e}")

@client.tree.command(name="mute", description="Timeout/mute a member")
@app_commands.describe(user="The member to mute", duration_minutes="Duration in minutes", reason="The reason for the mute")
@is_authorized_user()
async def mute_user(interaction: discord.Interaction, user: discord.Member, duration_minutes: int, reason: str = "No reason provided"):
    await interaction.response.defer(ephemeral=True)
    if duration_minutes <= 0:
        return await interaction.followup.send("❌ Duration must be greater than 0 minutes.")
    
    try:
        until = discord.utils.utcnow() + discord.utils.timedelta(minutes=duration_minutes)
        await user.timeout(until, reason=reason)
        
        # Send DM
        try:
            await user.send(f"🔇 You have been muted/timed out in **{interaction.guild.name}** for {duration_minutes} minutes.\n**Reason:** {reason}")
        except: pass
        
        await interaction.followup.send(f"✅ Successfully muted {user.mention} for {duration_minutes} minutes. Reason: {reason}")
        
        # Log action
        embed = discord.Embed(title="🔇 Member Muted (Timeout)", description=f"**User:** {user.mention} ({user.id})\n**Moderator:** {interaction.user.mention}\n**Duration:** {duration_minutes} minutes\n**Reason:** {reason}", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
        await log_mod(interaction.guild, embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to mute user: {e}")

@client.tree.command(name="help", description="List all available commands and their functions")
@is_authorized_user()
async def help_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
    embed = discord.Embed(
        title="🛡️ Security Bot Help", 
        description="Here is the list of all available commands and their functions. Note that all commands require server **Administrator** permission.",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=LOGO_URL)
    
    # Setup & Config
    setup_cmds = (
        "**`/setup`** - Analyze server, enable modules, and setup a scam trap automatically.\n"
        "**`/settings`** - View the current security settings for all modules.\n"
        "**`/enable <module>`** - Enable a specific security module.\n"
        "**`/disable <module>`** - Disable a specific security module.\n"
        "**`/setlimit <module> <seconds> <limit>`** - Set trigger limits (e.g., 5 bans in 60s).\n"
        "**`/setpunishment <module> <type>`** - Change the automated punishment (ban, kick, strip).\n"
        "**`/agegate <days> <enabled>`** - Set minimum account age to join the server.\n"
        "**`/setscamchannel <channel>`** - Manually set the scam detection trap channel.\n"
        "**`/setlogchannel <type> <channel>`** - Set where security or moderation logs are sent."
    )
    embed.add_field(name="⚙️ Configuration & Setup", value=setup_cmds, inline=False)
    
    # Audit & History
    audit_cmds = (
        "**`/scan`** - Perform a deep security scan of the server configuration.\n"
        "**`/audit`** - Perform a deep permission and vulnerability audit of server roles.\n"
        "**`/history`** - View the last 20 security events and triggers."
    )
    embed.add_field(name="🔍 Audit & History", value=audit_cmds, inline=False)
    
    # Emergency Actions
    emergency_cmds = (
        "**`/panic`** - **EMERGENCY:** Triggers full lockdown and deletes ALL server invites.\n"
        "**`/lockdown <status>`** - Lock (True) or unlock (False) the entire server.\n"
        "**`/clearinvites`** - Instantly delete all server invites to stop a raid."
    )
    embed.add_field(name="🚨 Emergency Actions", value=emergency_cmds, inline=False)
    
    # Moderation
    mod_cmds = (
        "**`/purge <amount> [user] [server_wide]`** - Delete messages in a channel, or server-wide for a user.\n"
        "**`/quarantine <user>`** - Isolate a user by stripping roles and assigning a quarantine role.\n"
        "**`/ban <user> [reason] [days]`** - Ban a user from the server.\n"
        "**`/kick <user> [reason]`** - Kick a user from the server.\n"
        "**`/mute <user> <minutes> [reason]`** - Timeout/mute a user for a specific duration."
    )
    embed.add_field(name="🔨 Moderation", value=mod_cmds, inline=False)
    
    await interaction.followup.send(embed=embed)

client.run(TOKEN)
