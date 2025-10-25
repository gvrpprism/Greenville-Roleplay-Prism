import discord
from discord.ext import commands
from discord.ui import Button, View
from PIL import Image, ImageDraw, ImageFont
import os
from flask import Flask
from threading import Thread
from io import BytesIO
from datetime import datetime, timedelta, timezone
import asyncio
import random
import json
import re

# ========================
# IDs and constants
# ========================
ANNOUNCEMENTS_CHANNEL_ID = 1429028560168816681
TICKET_CATEGORY_ID = None
TICKET_CHANNEL_ID = 1429030206689120306
STAFF_LOG_CHANNEL_ID = 1429052870371835944
WELCOME_CHANNEL_ID = 1429040704486637599
STAFF_ROLE_ID = 1429035155158208532
BANNER_IMAGE_PATH = "GreenvilleSpringUpdateBanner(2025)(1).png"

WARNING_ROLE_1 = 1429197544499576903
WARNING_ROLE_2 = 1429197737097822388
WARNING_ROLE_3 = 1429197812012290178
WARNING_STAFF_CHANNEL = 1429197895747371008
RELEASE_LOG_CHANNEL = 1429198290833903840

SESSION_CHANNEL_ID = 1429026313007665172
SESSION_HOST_ROLE_ID = 1429081183148445806
STARTUP_PING_ROLES = [1429032286623498240, 1429414667226320989]
RELEASE_PING_ROLES = [1429080620742742168, 1429035519337168976]

APPLICATION_CHANNEL_ID = 1429185516649320469
APPLICATION_REVIEWER_ROLE_ID = 1429035691026808832

REACTION_ROLE_CHANNEL_ID = 1429382680633413662
REACTION_ROLE_MESSAGE_ID = 1429892266616553582
REACTION_ROLE_EMOJI = "✅"
REACTION_ROLE_ID = 1429032286623498240

TICKET_ACCESS_ROLE_ID = 1429050967881416757  # Role allowed to see tickets and close them

TOKEN = os.environ.get('DISCORD_BOT_TOKEN') or os.environ.get('TOKEN')

# ========================
# Bot setup
# ========================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='?', intents=intents)
bot.remove_command('help')

# ========================
# Globals
# ========================
ticket_last_activity = {}
ticket_extra_viewers = {}  # Tracks additional users who can see ticket but not close
user_warnings = {}
active_applications = {}
active_giveaways = {}
session_message_id = None
session_cohosts = []
latest_startup_message_id = None
latest_startup_host_id = None
user_levels = {}
user_economy = {}
reaction_roles = {}
starboard_messages = {}
user_afk = {}
active_polls = {}
suggestion_counter = 0
bad_words = ['badword1', 'badword2']
STARBOARD_CHANNEL_ID = None
SUGGESTION_CHANNEL_ID = None
ticket_warnings_sent = {}

# ========================
# Flask app for uptime
# ========================
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=5000)

Thread(target=run).start()

# ========================
# Helper for EET timezone
# ========================
EET = timezone(timedelta(hours=2))  # UTC+2

# ========================
# Inactive ticket checker
# ========================
async def check_inactive_tickets():
    """Check for tickets with no activity for 5 hours"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            guild = bot.guilds[0]
            ticket_category = guild.get_channel(TICKET_CATEGORY_ID)
            
            if ticket_category:
                now = datetime.now(EET)
                
                for channel in ticket_category.channels:
                    if channel.id in ticket_last_activity:
                        last_activity = ticket_last_activity[channel.id]
                        time_since_activity = now - last_activity
                        
                        if time_since_activity >= timedelta(hours=5):
                            if channel.id not in ticket_warnings_sent:
                                embed = discord.Embed(
                                    title="⏰ Inactive Ticket",
                                    description="This ticket has been inactive for 5 hours. Should it be closed?\n\nReact with ✅ to close this ticket.",
                                    color=discord.Color.orange()
                                )
                                message = await channel.send(embed=embed)
                                await message.add_reaction("✅")
                                
                                ticket_warnings_sent[channel.id] = now
        except Exception as e:
            print(f"Error checking inactive tickets: {e}")
        
        await asyncio.sleep(3600)

# ========================
# Bot events
# ========================
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
    
    bot.loop.create_task(check_inactive_tickets())

# Track last activity in tickets
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.channel.category and message.channel.category.id == TICKET_CATEGORY_ID:
        ticket_last_activity[message.channel.id] = datetime.now(EET)
    await bot.process_commands(message)

# ========================
# Ticket commands
# ========================

# ?ticketbutton command
@bot.command()
async def ticketbutton(ctx):
    embed = discord.Embed(
        title="Create a Ticket",
        description="Press the button below to create a ticket.",
        color=discord.Color.orange()
    )
    button = Button(label="Create Ticket", style=discord.ButtonStyle.green)

    async def button_callback(interaction):
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.get_role(TICKET_ACCESS_ROLE_ID): discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )

        ticket_last_activity[ticket_channel.id] = datetime.now(EET)
        ticket_extra_viewers[ticket_channel.id] = set()

        await ticket_channel.send(f"<@&{STAFF_ROLE_ID}> {interaction.user.mention} created a ticket!")

        if STAFF_LOG_CHANNEL_ID:
            log_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
            await log_channel.send(f"Ticket created by {interaction.user} in {ticket_channel.mention}")

        await interaction.response.send_message(f"Ticket created: {ticket_channel.mention}", ephemeral=True)

    button.callback = button_callback
    view = View(timeout=None)
    view.add_item(button)
    await ctx.send(embed=embed, view=view)

# ?ticketclose command
@bot.command()
async def ticketclose(ctx):
    role = ctx.guild.get_role(TICKET_ACCESS_ROLE_ID)
    if role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to close tickets.")
        return

    if not ctx.channel.category or ctx.channel.category.id != TICKET_CATEGORY_ID:
        await ctx.send("❌ This command can only be used in a ticket channel.")
        return

    await ctx.send("🔒 Closing ticket in 3 seconds...")
    await asyncio.sleep(3)
    await ctx.channel.delete()
    ticket_last_activity.pop(ctx.channel.id, None)
    ticket_extra_viewers.pop(ctx.channel.id, None)

# ?ticketadd command
@bot.command()
async def ticketadd(ctx, member: discord.Member):
    if not ctx.channel.category or ctx.channel.category.id != TICKET_CATEGORY_ID:
        await ctx.send("❌ This command can only be used in a ticket channel.")
        return

    await ctx.channel.set_permissions(member, view_channel=True, send_messages=False)
    if ctx.channel.id not in ticket_extra_viewers:
        ticket_extra_viewers[ctx.channel.id] = set()
    ticket_extra_viewers[ctx.channel.id].add(member.id)
    await ctx.send(f"✓ {member.mention} can now see this ticket, but cannot close it.")

    # ---- REACTION ROLE CODE ----
    reaction_role_channel = bot.get_channel(REACTION_ROLE_CHANNEL_ID)
    if reaction_role_channel:
        try:
            messages = await reaction_role_channel.history(limit=50).flatten()
            target_message = None
            for msg in messages:
                if msg.author == bot.user and "Welcome and thank you for joining Greenville Roleplay Prism!" in msg.content:
                    target_message = msg
                    break

            if target_message:
                await target_message.delete()
                print(f"Deleted old reaction role message {target_message.id}")

            new_message = await reaction_role_channel.send(
                "Welcome and thank you for joining Greenville Roleplay Prism!\nTo verify - react below!"
            )

            await new_message.add_reaction(REACTION_ROLE_EMOJI)
            reaction_roles[(new_message.id, REACTION_ROLE_EMOJI)] = REACTION_ROLE_ID
            print(f"Sent new reaction role message with ID {new_message.id} and added reaction role")

        except discord.NotFound:
            print(f"Reaction role channel {REACTION_ROLE_CHANNEL_ID} or message not found")
        except Exception as e:
            print(f"Error creating reaction role message: {e}")
@bot.event
async def on_member_join(member):
    if member.bot:
        return
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    try:
        if os.path.exists("welcome_banner.png"):
            banner = Image.open("welcome_banner.png").convert("RGBA")
            avatar_bytes = await member.display_avatar.read()
            avatar_io = BytesIO(avatar_bytes)
            avatar = Image.open(avatar_io).resize((200, 200)).convert("RGBA")
            
            mask = Image.new('L', (200, 200), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0, 200, 200], fill=255)
            
            circular_avatar = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
            circular_avatar.paste(avatar, (0, 0))
            circular_avatar.putalpha(mask)
            
            outline_size = 210
            avatar_with_outline = Image.new('RGBA', (outline_size, outline_size), (0, 0, 0, 0))
            outline_draw = ImageDraw.Draw(avatar_with_outline)
            outline_draw.ellipse([0, 0, outline_size-1, outline_size-1], fill=(88, 101, 242, 255))
            avatar_with_outline.paste(circular_avatar, (5, 5), circular_avatar)
            
            position = ((banner.width - outline_size) // 2, (banner.height - outline_size) // 2)
            banner.paste(avatar_with_outline, position, avatar_with_outline)
            banner.save("welcome_final.png")
            
            file = discord.File("welcome_final.png")
            embed = discord.Embed(
                title="Thank you for joining Greenville Roleplay Prism",
                description=f"{member.mention}",
                color=discord.Color.orange()
            )
            embed.set_image(url="attachment://welcome_final.png")
            await channel.send(embed=embed, file=file)
        else:
            embed = discord.Embed(
                title="Thank you for joining Greenville Roleplay Prism",
                description=f"{member.mention}",
                color=discord.Color.orange()
            )
            await channel.send(embed=embed)
    except Exception as e:
        print(f"Error in welcome message: {e}")

@bot.event
async def on_member_remove(member):
    if member.bot:
        return
    channel = bot.get_channel(WELCOME_CHANNEL_ID)
    try:
        if os.path.exists("welcome_banner.png"):
            banner = Image.open("welcome_banner.png").convert("RGBA")
            avatar_bytes = await member.display_avatar.read()
            avatar_io = BytesIO(avatar_bytes)
            avatar = Image.open(avatar_io).resize((200, 200)).convert("RGBA")
            
            mask = Image.new('L', (200, 200), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0, 200, 200], fill=255)
            
            circular_avatar = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
            circular_avatar.paste(avatar, (0, 0))
            circular_avatar.putalpha(mask)
            
            outline_size = 210
            avatar_with_outline = Image.new('RGBA', (outline_size, outline_size), (0, 0, 0, 0))
            outline_draw = ImageDraw.Draw(avatar_with_outline)
            outline_draw.ellipse([0, 0, outline_size-1, outline_size-1], fill=(88, 101, 242, 255))
            avatar_with_outline.paste(circular_avatar, (5, 5), circular_avatar)
            
            position = ((banner.width - outline_size) // 2, (banner.height - outline_size) // 2)
            banner.paste(avatar_with_outline, position, avatar_with_outline)
            banner.save("goodbye_final.png")
            
            file = discord.File("goodbye_final.png")
            embed = discord.Embed(
                title="We hope you had a great time in Greenville Roleplay Prism!",
                description=f"{member.name} has left the server",
                color=discord.Color.orange()
            )
            embed.set_image(url="attachment://goodbye_final.png")
            await channel.send(embed=embed, file=file)
        else:
            embed = discord.Embed(
                title="We hope you had a great time in Greenville Roleplay Prism!",
                description=f"{member.name} has left the server",
                color=discord.Color.orange()
            )
            await channel.send(embed=embed)
    except Exception as e:
        print(f"Error in leave message: {e}")

async def on_message_leveling(message):
    if message.author.id not in user_levels:
        user_levels[message.author.id] = {'xp': 0, 'level': 1}
    
    xp_gain = random.randint(10, 25)
    user_levels[message.author.id]['xp'] += xp_gain
    
    current_level = user_levels[message.author.id]['level']
    xp_needed = current_level * 100
    
    if user_levels[message.author.id]['xp'] >= xp_needed:
        user_levels[message.author.id]['level'] += 1
        user_levels[message.author.id]['xp'] = 0
        await message.channel.send(f"🎉 {message.author.mention} leveled up to level {user_levels[message.author.id]['level']}!", delete_after=5)

async def on_message_economy(message):
    if message.author.id not in user_economy:
        user_economy[message.author.id] = {'wallet': 0, 'bank': 0, 'last_daily': None, 'last_work': None}
    
    coins_gain = random.randint(5, 15)
    user_economy[message.author.id]['wallet'] += coins_gain

async def on_message_afk_check(message):
    if message.author.id in user_afk:
        reason = user_afk[message.author.id]
        del user_afk[message.author.id]
        await message.channel.send(f"Welcome back {message.author.mention}! I removed your AFK status.", delete_after=5)
    
    for mention in message.mentions:
        if mention.id in user_afk:
            reason = user_afk[mention.id]
            await message.channel.send(f"{mention.display_name} is currently AFK: {reason}", delete_after=10)

async def on_message_automod(message):
    if any(word in message.content.lower() for word in bad_words):
        await message.delete()
        await message.channel.send(f"{message.author.mention}, please watch your language!", delete_after=5)

@bot.event
async def on_message(message):
    """Track ticket activity and call all message handlers"""
    if message.author.bot:
        await bot.process_commands(message)
        return
    
    if message.channel.category_id == TICKET_CATEGORY_ID:
        ticket_last_activity[message.channel.id] = datetime.now(datetime.timezone.utc)
        if message.channel.id in ticket_warnings_sent:
            del ticket_warnings_sent[message.channel.id]
    
    await on_message_leveling(message)
    await on_message_economy(message)
    await on_message_afk_check(message)
    await on_message_automod(message)
    
    await bot.process_commands(message)

@bot.event
async def on_reaction_add(reaction, user):
    """Handle ticket close reaction and reaction roles"""
    if user.bot:
        return
    
    if (reaction.emoji == "✅" and 
        reaction.message.author == bot.user and 
        reaction.message.embeds and 
        any("inactive" in embed.title.lower() for embed in reaction.message.embeds)):
        
        channel = reaction.message.channel
        
        await channel.send("🔒 Ticket closed due to inactivity.")
        await asyncio.sleep(3)
        await channel.delete()
        
        if channel.id in ticket_last_activity:
            del ticket_last_activity[channel.id]
        if channel.id in ticket_warnings_sent:
            del ticket_warnings_sent[channel.id]
    
    if (reaction.message.id, str(reaction.emoji)) in reaction_roles:
        role_id = reaction_roles[(reaction.message.id, str(reaction.emoji))]
        role = reaction.message.guild.get_role(role_id)
        if role:
            await user.add_roles(role)

@bot.event
async def on_reaction_remove(reaction, user):
    """Handle reaction role removal"""
    if user.bot:
        return
    
    if (reaction.message.id, str(reaction.emoji)) in reaction_roles:
        role_id = reaction_roles[(reaction.message.id, str(reaction.emoji))]
        role = reaction.message.guild.get_role(role_id)
        if role:
            await user.remove_roles(role)

@bot.command()
async def announce(ctx, *, message):
    channel = bot.get_channel(ANNOUNCEMENTS_CHANNEL_ID)
    embed = discord.Embed(description=message, color=discord.Color.orange())
    await channel.send(embed=embed)
    await ctx.send("✓ Announcement sent!", delete_after=3)

@bot.command()
async def type(ctx, channel: discord.TextChannel, *, message):
    await channel.send(message)
    await ctx.send(f"✓ Message sent to {channel.mention}!", delete_after=3)

@bot.command()
async def ticketbutton(ctx):
    channel = bot.get_channel(TICKET_CHANNEL_ID)
    embed = discord.Embed(
        title="Create a Ticket",
        description="Press the button below to create a ticket.",
        color=discord.Color.orange()
    )
    button = Button(label="Create Ticket", style=discord.ButtonStyle.green)
    async def button_callback(interaction):
        modal = Modal(title="Ticket Reason")
        reason_input = TextInput(label="Reason", placeholder="Why are you opening this ticket?")
        modal.add_item(reason_input)

        async def modal_callback(modal_interaction):
            import datetime
            guild = interaction.guild
            category = guild.get_channel(TICKET_CATEGORY_ID)
            ticket_channel = await guild.create_text_channel(
                name=f"ticket-{interaction.user.name}",
                category=category
            )
            
            ticket_last_activity[ticket_channel.id] = datetime.datetime.now(datetime.timezone.utc)
            
            await ticket_channel.send(f"<@&{STAFF_ROLE_ID}> {interaction.user.mention} created a ticket!\nReason: {reason_input.value}")
            if STAFF_LOG_CHANNEL_ID:
                log_channel = guild.get_channel(STAFF_LOG_CHANNEL_ID)
                await log_channel.send(f"Ticket created by {interaction.user} in {ticket_channel.mention}")
            await modal_interaction.response.send_message(f"Ticket created: {ticket_channel.mention}", ephemeral=True)

        modal.on_submit = modal_callback
        await interaction.response.send_modal(modal)

    button.callback = button_callback
    view = View(timeout=None)
    view.add_item(button)
    await channel.send(embed=embed, view=view)
    await ctx.send("✓ Ticket button sent!", delete_after=3)

@bot.command(name="ticketclose")
async def ticketclose(ctx):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to close tickets.")
        return
    
    if not ctx.channel.category or ctx.channel.category.id != TICKET_CATEGORY_ID:
        await ctx.send("❌ This command can only be used in a ticket channel.")
        return
    
    await ctx.send("🔒 Closing ticket in 3 seconds...")
    
    if STAFF_LOG_CHANNEL_ID:
        try:
            log_channel = ctx.guild.get_channel(STAFF_LOG_CHANNEL_ID)
            messages = [m async for m in ctx.channel.history(limit=100)]
            history_text = "\n".join([f"{m.author}: {m.content}" for m in reversed(messages)])
            await log_channel.send(f"Ticket {ctx.channel.name} closed by {ctx.author}. History:\n```{history_text[:1900]}```")
        except:
            pass
    
    if ctx.channel.id in ticket_last_activity:
        del ticket_last_activity[ctx.channel.id]
    if ctx.channel.id in ticket_warnings_sent:
        del ticket_warnings_sent[ctx.channel.id]
    
    await asyncio.sleep(3)
    try:
        await ctx.channel.delete()
    except:
        pass

@bot.command()
async def timeout(ctx, member: discord.Member, duration: int, *, reason: str = "No reason provided"):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to use this command.")
        return
    
    await member.timeout(timedelta(minutes=duration), reason=reason)
    await ctx.send(f"✓ {member.mention} has been timed out for {duration} minutes. Reason: {reason}")
    
    if STAFF_LOG_CHANNEL_ID:
        log_channel = ctx.guild.get_channel(STAFF_LOG_CHANNEL_ID)
        await log_channel.send(f"🔇 {member.mention} was timed out by {ctx.author.mention} for {duration} minutes.\nReason: {reason}")

@bot.command()
async def untimeout(ctx, member: discord.Member):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to use this command.")
        return
    
    await member.timeout(None)
    await ctx.send(f"✓ {member.mention} has been removed from timeout.")
    
    if STAFF_LOG_CHANNEL_ID:
        log_channel = ctx.guild.get_channel(STAFF_LOG_CHANNEL_ID)
        await log_channel.send(f"🔊 {member.mention} was removed from timeout by {ctx.author.mention}.")

@bot.command()
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to use this command.")
        return
    
    await member.kick(reason=reason)
    await ctx.send(f"✓ {member.mention} has been kicked. Reason: {reason}")
    
    if STAFF_LOG_CHANNEL_ID:
        log_channel = ctx.guild.get_channel(STAFF_LOG_CHANNEL_ID)
        await log_channel.send(f"👢 {member.mention} was kicked by {ctx.author.mention}.\nReason: {reason}")

@bot.command()
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to use this command.")
        return
    
    await member.ban(reason=reason)
    await ctx.send(f"✓ {member.mention} has been banned. Reason: {reason}")
    
    if STAFF_LOG_CHANNEL_ID:
        log_channel = ctx.guild.get_channel(STAFF_LOG_CHANNEL_ID)
        await log_channel.send(f"🔨 {member.mention} was banned by {ctx.author.mention}.\nReason: {reason}")

@bot.command()
async def clear(ctx, amount: int = 10):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to use this command.")
        return
    
    deleted = await ctx.channel.purge(limit=amount + 1)
    confirm = await ctx.send(f"✓ Deleted {len(deleted) - 1} messages.")
    await confirm.delete(delay=3)
    
    if STAFF_LOG_CHANNEL_ID:
        log_channel = ctx.guild.get_channel(STAFF_LOG_CHANNEL_ID)
        await log_channel.send(f"🗑️ {ctx.author.mention} cleared {len(deleted) - 1} messages in {ctx.channel.mention}.")

@bot.hybrid_command()
async def startup(ctx):
    host_role = ctx.guild.get_role(SESSION_HOST_ROLE_ID)
    if host_role not in ctx.author.roles:
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message("❌ You need the Session Host role to start a session!", ephemeral=True)
        else:
            await ctx.send("❌ You need the Session Host role to start a session!", ephemeral=True)
        return

    modal = Modal(title="Session Startup")
    reaction_input = TextInput(label="Reaction Count", placeholder="How many reactions to start?")
    modal.add_item(reaction_input)

    async def modal_callback(modal_interaction):
        global latest_startup_message_id, latest_startup_host_id
        session_channel = bot.get_channel(SESSION_CHANNEL_ID)
        ping_mention = " ".join([f"<@&{role_id}>" for role_id in STARTUP_PING_ROLES])
        
        embed = discord.Embed(
            title="🚗 Greenville Roleplay Prism Session Startup!",
            description=f"{ctx.author.mention} is now hosting a session! If you intend on joining, react below. If you react without joining, you could face strikes from the staff team!\n\n**Before Joining:**\nRead <#1429027329782583407>\nCheck <#1429027259280261150>\n\n**The startup must reach {reaction_input.value} reactions to start the session.**",
            color=discord.Color.orange()
        )

        try:
            file = discord.File("startup.png", filename="startup.png")
            embed.set_image(url="attachment://startup.png")
            message = await session_channel.send(content=ping_mention, embed=embed, file=file)
        except FileNotFoundError:
            message = await session_channel.send(content=ping_mention, embed=embed)
        
        await message.add_reaction("✅")
        
        latest_startup_message_id = message.id
        latest_startup_host_id = ctx.author.id
        
        log_channel = bot.get_channel(RELEASE_LOG_CHANNEL)
        if log_channel:
            log_embed = discord.Embed(
                title="🚗 Session Startup",
                description=f"**Host:** {ctx.author.mention} ({ctx.author.name})\n**Required Reactions:** {reaction_input.value}",
                color=discord.Color.orange(),
                timestamp=modal_interaction.created_at
            )
            await log_channel.send(embed=log_embed)
        
        await modal_interaction.response.send_message(f"✓ Session startup announced in {session_channel.mention}!", ephemeral=True)

    modal.on_submit = modal_callback
    
    class StartupView(View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="Start Session", style=discord.ButtonStyle.blurple)
        async def startup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(modal)
    
    view = StartupView()
    
    if isinstance(ctx, discord.Interaction):
        await ctx.response.send_message("Click the button below to start a session:", view=view, ephemeral=True)
    else:
        try:
            await ctx.message.delete()
        except:
            pass
        await ctx.send("Click the button below to start a session:", view=view, ephemeral=True)

@bot.hybrid_command()
async def release_early(ctx):
    host_role = ctx.guild.get_role(SESSION_HOST_ROLE_ID)
    if host_role not in ctx.author.roles:
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message("❌ You need the Session Host role to release early access!", ephemeral=True)
        else:
            await ctx.send("❌ You need the Session Host role to release early access!", ephemeral=True)
        return

    modal = Modal(title="Early Access Release")
    link_input = TextInput(label="Session Link", placeholder="Enter the session link")
    modal.add_item(link_input)

    async def modal_callback(modal_interaction):
        global session_message_id, session_cohosts
        session_channel = bot.get_channel(SESSION_CHANNEL_ID)
        ping_mentions = " ".join([f"<@&{role_id}>" for role_id in RELEASE_PING_ROLES])
        
        embed = discord.Embed(
            title="🌟 Early Access Released!",
            description=f"<@&{STARTUP_PING_ROLES[0]}>\n\n{ctx.author.mention} has released Early Access! Click the button below to get the session link.",
            color=discord.Color.orange()
        )

        class LinkButton(View):
            def __init__(self, allowed_roles, link):
                super().__init__(timeout=None)
                self.allowed_roles = allowed_roles
                self.link = link

            @discord.ui.button(label="Get Session Link", style=discord.ButtonStyle.green)
            async def get_link(self, interaction: discord.Interaction, button: discord.ui.Button):
                member_roles = [role.id for role in interaction.user.roles]
                if any(role in member_roles for role in self.allowed_roles):
                    await interaction.response.send_message(f"🔗 Your session link: {self.link}", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ You don't have permission to get this link.", ephemeral=True)

        view = LinkButton(allowed_roles=RELEASE_PING_ROLES, link=link_input.value)
        
        try:
            file = discord.File("early_release.png", filename="early_release.png")
            embed.set_image(url="attachment://early_release.png")
            message = await session_channel.send(content=ping_mentions, embed=embed, file=file, view=view)
        except FileNotFoundError:
            message = await session_channel.send(content=ping_mentions, embed=embed, view=view)
        
        session_message_id = message.id
        session_cohosts = []
        
        log_channel = bot.get_channel(RELEASE_LOG_CHANNEL)
        if log_channel:
            log_embed = discord.Embed(
                title="📝 Early Access Released",
                description=f"**Host:** {ctx.author.mention} ({ctx.author.name})\n**Link:** {link_input.value}",
                color=discord.Color.blue(),
                timestamp=modal_interaction.created_at
            )
            await log_channel.send(embed=log_embed)
        
        await modal_interaction.response.send_message("✓ Early access released!", ephemeral=True)

    modal.on_submit = modal_callback
    
    class ReleaseEarlyView(View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="Release Early Access", style=discord.ButtonStyle.blurple)
        async def release_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(modal)
    
    view = ReleaseEarlyView()
    
    if isinstance(ctx, discord.Interaction):
        await ctx.response.send_message("Click to release early access:", view=view, ephemeral=True)
    else:
        try:
            await ctx.message.delete()
        except:
            pass
        await ctx.send("Click to release early access:", view=view, ephemeral=True)

@bot.hybrid_command()
async def release(ctx):
    host_role = ctx.guild.get_role(SESSION_HOST_ROLE_ID)
    if host_role not in ctx.author.roles:
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message("❌ You need the Session Host role to release a session!", ephemeral=True)
        else:
            await ctx.send("❌ You need the Session Host role to release a session!", ephemeral=True)
        return

    modal = Modal(title="Session Release")
    link_input = TextInput(label="Session Link", placeholder="Enter the session link")
    peacetime_input = TextInput(label="Peacetime Status", placeholder="Enabled/Disabled")
    frp_speeds_input = TextInput(label="FRP Speeds", placeholder="Enter FRP speed limits")
    law_enforcement_input = TextInput(label="Law Enforcement", placeholder="Enabled/Disabled")
    
    modal.add_item(link_input)
    modal.add_item(peacetime_input)
    modal.add_item(frp_speeds_input)
    modal.add_item(law_enforcement_input)

    async def modal_callback(modal_interaction):
        global session_message_id, session_cohosts
        session_channel = bot.get_channel(SESSION_CHANNEL_ID)
        ping_mentions = "<@&1429414667226320989> <@&1429032286623498240>"
        
        embed = discord.Embed(
            title="🎮 Session Released!",
            description=f"{ctx.author.mention} has released a session! Click the button below to get the session link.",
            color=discord.Color.orange()
        )
        embed.add_field(name="🕊️ Peacetime", value=peacetime_input.value, inline=True)
        embed.add_field(name="🚗 FRP Speeds", value=frp_speeds_input.value, inline=True)
        embed.add_field(name="👮 Law Enforcement", value=law_enforcement_input.value, inline=True)

        class LinkButton(View):
            def __init__(self, link):
                super().__init__(timeout=None)
                self.link = link

            @discord.ui.button(label="Get Session Link", style=discord.ButtonStyle.green)
            async def get_link(self, interaction: discord.Interaction, button: discord.ui.Button):
                await interaction.response.send_message(f"🔗 Your session link: {self.link}", ephemeral=True)

        view = LinkButton(link=link_input.value)
        
        try:
            file = discord.File("release.png", filename="release.png")
            embed.set_image(url="attachment://release.png")
            message = await session_channel.send(content=ping_mentions, embed=embed, file=file, view=view)
        except FileNotFoundError:
            message = await session_channel.send(content=ping_mentions, embed=embed, view=view)
        
        session_message_id = message.id
        session_cohosts = []
        
        log_channel = bot.get_channel(RELEASE_LOG_CHANNEL)
        if log_channel:
            log_embed = discord.Embed(
                title="📝 Session Released",
                description=f"**Host:** {ctx.author.mention} ({ctx.author.name})\n**Link:** {link_input.value}\n**Peacetime:** {peacetime_input.value}\n**FRP Speeds:** {frp_speeds_input.value}\n**Law Enforcement:** {law_enforcement_input.value}",
                color=discord.Color.green(),
                timestamp=modal_interaction.created_at
            )
            await log_channel.send(embed=log_embed)
        
        await modal_interaction.response.send_message("✓ Session released!", ephemeral=True)

    modal.on_submit = modal_callback
    
    class ReleaseView(View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="Release Session", style=discord.ButtonStyle.blurple)
        async def release_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(modal)
    
    view = ReleaseView()
    
    if isinstance(ctx, discord.Interaction):
        await ctx.response.send_message("Click to release session:", view=view, ephemeral=True)
    else:
        try:
            await ctx.message.delete()
        except:
            pass
        await ctx.send("Click to release session:", view=view, ephemeral=True)

@bot.command()
async def addcohost(ctx, member: discord.Member):
    host_role = ctx.guild.get_role(SESSION_HOST_ROLE_ID)
    if host_role not in ctx.author.roles:
        await ctx.send("❌ You need the Session Host role to add co-hosts!")
        return
    
    global session_cohosts
    if member.id not in session_cohosts:
        session_cohosts.append(member.id)
        await ctx.send(f"✓ {member.mention} has been added as a co-host!", delete_after=5)
        
        log_channel = bot.get_channel(RELEASE_LOG_CHANNEL)
        if log_channel:
            log_embed = discord.Embed(
                title="➕ Co-host Added",
                description=f"**Added by:** {ctx.author.mention} ({ctx.author.name})\n**Co-host:** {member.mention} ({member.name})",
                color=discord.Color.green(),
                timestamp=ctx.message.created_at
            )
            await log_channel.send(embed=log_embed)
    else:
        await ctx.send(f"❌ {member.mention} is already a co-host!", delete_after=5)

@bot.command()
async def removecohost(ctx, member: discord.Member):
    host_role = ctx.guild.get_role(SESSION_HOST_ROLE_ID)
    if host_role not in ctx.author.roles:
        await ctx.send("❌ You need the Session Host role to remove co-hosts!")
        return
    
    global session_cohosts
    if member.id in session_cohosts:
        session_cohosts.remove(member.id)
        await ctx.send(f"✓ {member.mention} has been removed as a co-host!", delete_after=5)
        
        log_channel = bot.get_channel(RELEASE_LOG_CHANNEL)
        if log_channel:
            log_embed = discord.Embed(
                title="➖ Co-host Removed",
                description=f"**Removed by:** {ctx.author.mention} ({ctx.author.name})\n**Co-host:** {member.mention} ({member.name})",
                color=discord.Color.red(),
                timestamp=ctx.message.created_at
            )
            await log_channel.send(embed=log_embed)
    else:
        await ctx.send(f"❌ {member.mention} is not a co-host!", delete_after=5)

@bot.hybrid_command()
async def session_end(ctx):
    host_role = ctx.guild.get_role(SESSION_HOST_ROLE_ID)
    if host_role not in ctx.author.roles:
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message("❌ You need the Session Host role to end a session!", ephemeral=True)
        else:
            await ctx.send("❌ You need the Session Host role to end a session!", ephemeral=True)
        return
    
    global session_cohosts
    session_channel = bot.get_channel(SESSION_CHANNEL_ID)
    
    embed = discord.Embed(
        title="🛑 Session Ended",
        description=f"{ctx.author.mention} has ended the session. Thank you for playing!",
        color=discord.Color.red()
    )
    
    try:
        file = discord.File("session_end.png", filename="session_end.png")
        embed.set_image(url="attachment://session_end.png")
        await session_channel.send(embed=embed, file=file)
    except FileNotFoundError:
        await session_channel.send(embed=embed)
    
    session_cohosts = []
    
    log_channel = bot.get_channel(RELEASE_LOG_CHANNEL)
    if log_channel:
        log_embed = discord.Embed(
            title="🛑 Session Ended",
            description=f"**Ended by:** {ctx.author.mention} ({ctx.author.name})",
            color=discord.Color.red(),
            timestamp=ctx.message.created_at if hasattr(ctx, 'message') else discord.utils.utcnow()
        )
        await log_channel.send(embed=log_embed)
    
    try:
        if hasattr(ctx, 'message'):
            await ctx.message.delete()
    except:
        pass
    
    await ctx.send("✓ Session ended!", delete_after=5, ephemeral=True)

@bot.hybrid_command()
async def cohost(ctx):
    """React to the soonest release and become a cohost"""
    global session_cohosts
    
    if len(session_cohosts) >= 3:
        await ctx.send("❌ Maximum of 3 co-hosts reached!", delete_after=5)
        return
    
    session_channel = bot.get_channel(SESSION_CHANNEL_ID)
    if not session_channel:
        await ctx.send("❌ Session channel not found!", delete_after=5)
        return
    
    release_message = None
    async for message in session_channel.history(limit=50):
        if message.author == bot.user and message.embeds:
            for embed in message.embeds:
                if any(keyword in embed.title.lower() for keyword in ["released", "early access", "session"]):
                    release_message = message
                    break
            if release_message:
                break
    
    if not release_message:
        await ctx.send("❌ No recent session release found!", delete_after=5)
        return
    
    if ctx.author.id not in session_cohosts:
        session_cohosts.append(ctx.author.id)
    else:
        await ctx.send("❌ You're already a co-host!", delete_after=5)
        return
    
    try:
        await release_message.add_reaction("🎉")
    except:
        pass
    
    try:
        file = discord.File("cohost.png", filename="cohost.png")
        embed = discord.Embed(
            title="🎉 New Co-Host!",
            description=f"{ctx.author.mention} is now cohosting this session!",
            color=discord.Color.green()
        )
        embed.set_image(url="attachment://cohost.png")
        await release_message.reply(content=f"{ctx.author.mention} is now cohosting this session!", embed=embed, file=file)
    except FileNotFoundError:
        await release_message.reply(f"{ctx.author.mention} is now cohosting this session!")
    
    log_channel = bot.get_channel(RELEASE_LOG_CHANNEL)
    if log_channel:
        log_embed = discord.Embed(
            title="🎉 New Co-host",
            description=f"{ctx.author.mention} ({ctx.author.name}) is now cohosting the session!",
            color=discord.Color.green(),
            timestamp=ctx.message.created_at if hasattr(ctx, 'message') else discord.utils.utcnow()
        )
        await log_channel.send(embed=log_embed)
    
    try:
        if hasattr(ctx, 'message'):
            await ctx.message.delete()
    except:
        pass

@bot.command()
async def setting_up(ctx):
    """Responds to the latest startup message indicating host is setting up"""
    global latest_startup_message_id, latest_startup_host_id
    
    if not latest_startup_message_id or not latest_startup_host_id:
        await ctx.send("❌ No recent startup found!", delete_after=5)
        try:
            await ctx.message.delete()
        except:
            pass
        return
    
    session_channel = bot.get_channel(SESSION_CHANNEL_ID)
    if not session_channel:
        await ctx.send("❌ Session channel not found!", delete_after=5)
        try:
            await ctx.message.delete()
        except:
            pass
        return
    
    try:
        startup_message = await session_channel.fetch_message(latest_startup_message_id)
        host_user = await ctx.guild.fetch_member(latest_startup_host_id)
        
        await startup_message.reply(f"{host_user.mention} is now setting up the session! Please be patient and allow them to set up to 10 minutes!")
        
        try:
            await ctx.message.delete()
        except:
            pass
            
    except discord.NotFound:
        await ctx.send("❌ Startup message not found!", delete_after=5)
        try:
            await ctx.message.delete()
        except:
            pass
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}", delete_after=5)
        try:
            await ctx.message.delete()
        except:
            pass

@bot.command()
async def apply(ctx):
    if ctx.author.id in active_applications:
        await ctx.send("❌ You already have an active application!", delete_after=5)
        return
    
    await ctx.send("✅ Check your DMs to complete your application!", delete_after=5)
    
    questions = [
        "What is your Discord username?",
        "What is your Roblox username?",
        "What is your age?",
        "What country/timezone are you in?",
        "Have you ever been staff in another Roblox/Discord server before? (if yes, tell more about it)",
        "How many hours per week can you dedicate to moderating the server?",
        "Do you have experience using moderation tools (Discord commands, Greenville commands, etc.)?",
        "If a player is FailRP'ing (e.g., reckless driving, unrealistic behavior), how would you handle the situation?",
        "If two members are arguing and it escalates, what steps would you take to calm things down?",
        "If a fellow staff member is abusing their powers, what would you do?",
        "Why do you want to join the Greenville Roleplay Prism staff team?",
        "What skills, qualities, or strengths make you a good fit for staff?",
        "What will you bring to the Greenville Roleplay Prism?",
        "Do you understand that being staff requires professionalism, responsibility, and fairness at all times?",
        "Do you agree to follow all server rules and staff guidelines if accepted?"
    ]
    
    answers = []
    
    try:
        dm_channel = await ctx.author.create_dm()
        await dm_channel.send("📋 **Staff Application Started!**\nPlease answer the following questions. Type your answer and press Enter after each question.")
        
        for i, question in enumerate(questions, 1):
            embed = discord.Embed(
                title=f"Question {i}/15",
                description=question,
                color=discord.Color.blue()
            )
            await dm_channel.send(embed=embed)
            
            def check(m):
                return m.author == ctx.author and isinstance(m.channel, discord.DMChannel)
            
            try:
                answer = await bot.wait_for('message', check=check, timeout=300.0)
                answers.append(answer.content)
            except asyncio.TimeoutError:
                await dm_channel.send("❌ Application timed out. Please use ?apply to start again.")
                return
        
        await dm_channel.send("✅ Application submitted! Staff will review it soon.")
        
        active_applications[ctx.author.id] = answers
        
        review_channel = ctx.guild.get_channel(APPLICATION_CHANNEL_ID)
        
        embed = discord.Embed(
            title="📋 New Staff Application",
            description=f"**Applicant:** {ctx.author.mention}",
            color=discord.Color.blue()
        )
        
        for i, (question, answer) in enumerate(zip(questions, answers), 1):
            if len(answer) > 1024:
                answer = answer[:1021] + "..."
            embed.add_field(name=f"Q{i}: {question[:100]}", value=answer, inline=False)
        
        class ApplicationButtons(View):
            def __init__(self, applicant_id, guild_obj):
                super().__init__(timeout=None)
                self.applicant_id = applicant_id
                self.guild_obj = guild_obj
            
            @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
            async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                reviewer_role = interaction.guild.get_role(APPLICATION_REVIEWER_ROLE_ID)
                if reviewer_role not in interaction.user.roles:
                    await interaction.response.send_message("❌ You don't have permission to review applications.", ephemeral=True)
                    return
                
                modal = Modal(title="Accept Application")
                reason_input = TextInput(label="Reason for Acceptance", style=discord.TextStyle.paragraph, placeholder="Enter reason...")
                modal.add_item(reason_input)
                
                async def modal_callback(modal_interaction):
                    applicant = await self.guild_obj.fetch_member(self.applicant_id)
                    await modal_interaction.response.send_message(f"✅ Application from {applicant.mention} has been accepted by {interaction.user.mention}!\n**Reason:** {reason_input.value}")
                    
                    try:
                        await applicant.send(f"🎉 Congratulations! Your staff application for **{self.guild_obj.name}** has been accepted!\n**Reason:** {reason_input.value}")
                    except:
                        pass
                    
                    if self.applicant_id in active_applications:
                        del active_applications[self.applicant_id]
                    
                    for item in self.children:
                        item.disabled = True
                    await interaction.message.edit(view=self)
                
                modal.on_submit = modal_callback
                await interaction.response.send_modal(modal)
            
            @discord.ui.button(label="Deny", style=discord.ButtonStyle.red)
            async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                reviewer_role = interaction.guild.get_role(APPLICATION_REVIEWER_ROLE_ID)
                if reviewer_role not in interaction.user.roles:
                    await interaction.response.send_message("❌ You don't have permission to review applications.", ephemeral=True)
                    return
                
                modal = Modal(title="Deny Application")
                reason_input = TextInput(label="Reason for Denial", style=discord.TextStyle.paragraph, placeholder="Enter reason...")
                modal.add_item(reason_input)
                
                async def modal_callback(modal_interaction):
                    applicant = await self.guild_obj.fetch_member(self.applicant_id)
                    await modal_interaction.response.send_message(f"❌ Application from {applicant.mention} has been denied by {interaction.user.mention}.\n**Reason:** {reason_input.value}")
                    
                    try:
                        await applicant.send(f"❌ Unfortunately, your staff application for **{self.guild_obj.name}** has been denied.\n**Reason:** {reason_input.value}\n\nYou can reapply in the future.")
                    except:
                        pass
                    
                    if self.applicant_id in active_applications:
                        del active_applications[self.applicant_id]
                    
                    for item in self.children:
                        item.disabled = True
                    await interaction.message.edit(view=self)
                
                modal.on_submit = modal_callback
                await interaction.response.send_modal(modal)
        
        view = ApplicationButtons(ctx.author.id, ctx.guild)
        await review_channel.send(embed=embed, view=view)
        
    except discord.Forbidden:
        await ctx.send("❌ I couldn't DM you! Please enable DMs from server members and try again.", delete_after=10)

@bot.hybrid_command()
async def giveaway(ctx):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message("❌ You don't have permission to start giveaways.", ephemeral=True)
        else:
            await ctx.send("❌ You don't have permission to start giveaways.", ephemeral=True)
        return

    modal = Modal(title="Create Giveaway")
    prize_input = TextInput(label="Prize", placeholder="Enter the prize")
    duration_input = TextInput(label="Duration (minutes)", placeholder="Enter duration in minutes")
    modal.add_item(prize_input)
    modal.add_item(duration_input)

    async def modal_callback(modal_interaction):
        try:
            duration = int(duration_input.value)
        except:
            await modal_interaction.response.send_message("❌ Invalid duration!", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🎉 GIVEAWAY 🎉",
            description=f"**Prize:** {prize_input.value}\n**Duration:** {duration} minutes\n**Hosted by:** {ctx.author.mention}\n\nReact with 🎉 to enter!",
            color=discord.Color.gold()
        )
        
        try:
            file = discord.File("giveaway.png", filename="giveaway.png")
            embed.set_image(url="attachment://giveaway.png")
            message = await ctx.channel.send(content="@everyone", embed=embed, file=file)
        except FileNotFoundError:
            message = await ctx.channel.send(content="@everyone", embed=embed)
        
        await message.add_reaction("🎉")
        
        active_giveaways[message.id] = {
            'prize': prize_input.value,
            'duration': duration,
            'host': ctx.author.id,
            'end_time': modal_interaction.created_at.timestamp() + (duration * 60),
            'channel_id': ctx.channel.id
        }
        
        await modal_interaction.response.send_message(f"✓ Giveaway started! It will end in {duration} minutes.", ephemeral=True)

    modal.on_submit = modal_callback
    
    class GiveawayView(View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="Create Giveaway", style=discord.ButtonStyle.blurple)
        async def giveaway_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(modal)
    
    view = GiveawayView()
    
    if isinstance(ctx, discord.Interaction):
        await ctx.response.send_message("Click to create a giveaway:", view=view, ephemeral=True)
    else:
        await ctx.message.delete()
        await ctx.send("Click to create a giveaway:", view=view, ephemeral=True)

@bot.command()
async def reroll(ctx, message_id: int):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to reroll giveaways.")
        return
    
    try:
        message = await ctx.channel.fetch_message(message_id)
    except:
        await ctx.send("❌ Message not found!")
        return
    
    reaction = discord.utils.get(message.reactions, emoji="🎉")
    if not reaction:
        await ctx.send("❌ No giveaway found on that message!")
        return
    
    users = [user async for user in reaction.users() if not user.bot]
    if not users:
        await ctx.send("❌ No valid entries!")
        return
    
    winner = random.choice(users)
    await ctx.send(f"🎉 New winner: {winner.mention}!")

@bot.command()
async def endgiveaway(ctx, message_id: int):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to end giveaways.")
        return
    
    try:
        message = await ctx.channel.fetch_message(message_id)
    except:
        await ctx.send("❌ Message not found!")
        return
    
    reaction = discord.utils.get(message.reactions, emoji="🎉")
    if not reaction:
        await ctx.send("❌ No giveaway found on that message!")
        return
    
    users = [user async for user in reaction.users() if not user.bot]
    if not users:
        await ctx.send("❌ No valid entries!")
        return
    
    winner = random.choice(users)
    
    if message_id in active_giveaways:
        prize = active_giveaways[message_id]['prize']
        del active_giveaways[message_id]
    else:
        prize = "Prize"
    
    await ctx.send(f"🎉 Giveaway ended! Winner: {winner.mention} won **{prize}**!")

@bot.command()
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to warn users.")
        return
    
    role1 = ctx.guild.get_role(WARNING_ROLE_1)
    role2 = ctx.guild.get_role(WARNING_ROLE_2)
    role3 = ctx.guild.get_role(WARNING_ROLE_3)
    
    current_warning_count = 0
    if role3 in member.roles:
        current_warning_count = 3
    elif role2 in member.roles:
        current_warning_count = 2
    elif role1 in member.roles:
        current_warning_count = 1
    
    warning_count = current_warning_count + 1
    user_warnings[member.id] = warning_count
    
    if warning_count == 1:
        await member.add_roles(role1)
        await ctx.send(f"⚠️ {member.mention} has been warned! (Warning 1/3)\nReason: {reason}")
    elif warning_count == 2:
        await member.remove_roles(role1)
        await member.add_roles(role2)
        await ctx.send(f"⚠️ {member.mention} has been warned! (Warning 2/3)\nReason: {reason}")
    elif warning_count >= 3:
        await member.remove_roles(role1, role2)
        await member.add_roles(role3)
        await ctx.send(f"⚠️ {member.mention} has been warned! (Warning 3/3 - FINAL WARNING)\nReason: {reason}")
        
        alarm_channel = ctx.guild.get_channel(WARNING_STAFF_CHANNEL)
        if alarm_channel:
            alarm_embed = discord.Embed(
                title="🚨 FINAL WARNING ISSUED",
                description=f"**User:** {member.mention}\n**Warning Count:** 3/3 (FINAL)\n**Reason:** {reason}\n**Warned by:** {ctx.author.mention}",
                color=discord.Color.red(),
                timestamp=ctx.message.created_at
            )
            await alarm_channel.send(f"@everyone", embed=alarm_embed)
    
    warning_channel = ctx.guild.get_channel(WARNING_STAFF_CHANNEL)
    if warning_channel:
        embed = discord.Embed(
            title="⚠️ User Warned",
            description=f"**User:** {member.mention}\n**Warning Count:** {warning_count}/3\n**Reason:** {reason}\n**Warned by:** {ctx.author.mention}",
            color=discord.Color.orange(),
            timestamp=ctx.message.created_at
        )
        await warning_channel.send(embed=embed)

@bot.command()
async def rank(ctx, member: discord.Member = None):
    if not member:
        member = ctx.author
    
    if member.id not in user_levels:
        user_levels[member.id] = {'xp': 0, 'level': 1}
    
    level = user_levels[member.id]['level']
    xp = user_levels[member.id]['xp']
    xp_needed = level * 100
    
    embed = discord.Embed(title=f"{member.display_name}'s Rank", color=discord.Color.blue())
    embed.add_field(name="Level", value=level, inline=True)
    embed.add_field(name="XP", value=f"{xp}/{xp_needed}", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    await ctx.send(embed=embed)

@bot.command()
async def balance(ctx, member: discord.Member = None):
    if not member:
        member = ctx.author
    
    if member.id not in user_economy:
        user_economy[member.id] = {'wallet': 0, 'bank': 0, 'last_daily': None, 'last_work': None}
    
    wallet = user_economy[member.id]['wallet']
    bank = user_economy[member.id]['bank']
    
    embed = discord.Embed(title=f"💰 {member.display_name}'s Balance", color=discord.Color.green())
    embed.add_field(name="Wallet", value=f"${wallet}", inline=True)
    embed.add_field(name="Bank", value=f"${bank}", inline=True)
    embed.add_field(name="Total", value=f"${wallet + bank}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def daily(ctx):
    if ctx.author.id not in user_economy:
        user_economy[ctx.author.id] = {'wallet': 0, 'bank': 0, 'last_daily': None, 'last_work': None}
    
    last_daily = user_economy[ctx.author.id]['last_daily']
    now = datetime.now()
    
    if last_daily:
        time_diff = (now - last_daily).total_seconds()
        if time_diff < 86400:
            hours_left = int((86400 - time_diff) / 3600)
            await ctx.send(f"❌ You already claimed your daily reward! Come back in {hours_left} hours.")
            return
    
    reward = random.randint(100, 500)
    user_economy[ctx.author.id]['wallet'] += reward
    user_economy[ctx.author.id]['last_daily'] = now
    
    await ctx.send(f"💰 You claimed your daily reward of ${reward}!")

@bot.command()
async def work(ctx):
    if ctx.author.id not in user_economy:
        user_economy[ctx.author.id] = {'wallet': 0, 'bank': 0, 'last_daily': None, 'last_work': None}
    
    last_work = user_economy[ctx.author.id]['last_work']
    now = datetime.now()
    
    if last_work:
        time_diff = (now - last_work).total_seconds()
        if time_diff < 3600:
            minutes_left = int((3600 - time_diff) / 60)
            await ctx.send(f"❌ You're tired! Rest for {minutes_left} more minutes.")
            return
    
    reward = random.randint(50, 200)
    user_economy[ctx.author.id]['wallet'] += reward
    user_economy[ctx.author.id]['last_work'] = now
    
    jobs = ["delivery driver", "cashier", "waiter", "mechanic", "taxi driver"]
    job = random.choice(jobs)
    
    await ctx.send(f"💼 You worked as a {job} and earned ${reward}!")

@bot.command()
async def deposit(ctx, amount: str):
    if ctx.author.id not in user_economy:
        user_economy[ctx.author.id] = {'wallet': 0, 'bank': 0, 'last_daily': None, 'last_work': None}
    
    if amount.lower() == "all":
        amount = user_economy[ctx.author.id]['wallet']
    else:
        try:
            amount = int(amount)
        except:
            await ctx.send("❌ Invalid amount!")
            return
    
    if amount > user_economy[ctx.author.id]['wallet']:
        await ctx.send("❌ You don't have that much money in your wallet!")
        return
    
    user_economy[ctx.author.id]['wallet'] -= amount
    user_economy[ctx.author.id]['bank'] += amount
    
    await ctx.send(f"✓ Deposited ${amount} to your bank!")

@bot.command()
async def withdraw(ctx, amount: str):
    if ctx.author.id not in user_economy:
        user_economy[ctx.author.id] = {'wallet': 0, 'bank': 0, 'last_daily': None, 'last_work': None}
    
    if amount.lower() == "all":
        amount = user_economy[ctx.author.id]['bank']
    else:
        try:
            amount = int(amount)
        except:
            await ctx.send("❌ Invalid amount!")
            return
    
    if amount > user_economy[ctx.author.id]['bank']:
        await ctx.send("❌ You don't have that much money in your bank!")
        return
    
    user_economy[ctx.author.id]['bank'] -= amount
    user_economy[ctx.author.id]['wallet'] += amount
    
    await ctx.send(f"✓ Withdrew ${amount} from your bank!")

@bot.command()
async def give(ctx, member: discord.Member, amount: int):
    if ctx.author.id not in user_economy:
        user_economy[ctx.author.id] = {'wallet': 0, 'bank': 0, 'last_daily': None, 'last_work': None}
    
    if member.id not in user_economy:
        user_economy[member.id] = {'wallet': 0, 'bank': 0, 'last_daily': None, 'last_work': None}
    
    if amount > user_economy[ctx.author.id]['wallet']:
        await ctx.send("❌ You don't have that much money!")
        return
    
    user_economy[ctx.author.id]['wallet'] -= amount
    user_economy[member.id]['wallet'] += amount
    
    await ctx.send(f"✓ You gave ${amount} to {member.mention}!")

@bot.command()
async def leaderboard(ctx, category: str = "levels"):
    if category.lower() == "levels":
        sorted_users = sorted(user_levels.items(), key=lambda x: (x[1]['level'], x[1]['xp']), reverse=True)
        embed = discord.Embed(title="📊 Level Leaderboard", color=discord.Color.blue())
        
        for i, (user_id, data) in enumerate(sorted_users[:10], 1):
            user = await bot.fetch_user(user_id)
            embed.add_field(
                name=f"{i}. {user.name}",
                value=f"Level {data['level']} ({data['xp']} XP)",
                inline=False
            )
    
    elif category.lower() == "economy":
        sorted_users = sorted(user_economy.items(), key=lambda x: (x[1]['wallet'] + x[1]['bank']), reverse=True)
        embed = discord.Embed(title="💰 Economy Leaderboard", color=discord.Color.green())
        
        for i, (user_id, data) in enumerate(sorted_users[:10], 1):
            user = await bot.fetch_user(user_id)
            total = data['wallet'] + data['bank']
            embed.add_field(
                name=f"{i}. {user.name}",
                value=f"${total}",
                inline=False
            )
    
    await ctx.send(embed=embed)

@bot.command(name="8ball")
async def eightball(ctx, *, question: str):
    responses = [
        "Yes, definitely!",
        "It is certain.",
        "Without a doubt.",
        "Most likely.",
        "Ask again later.",
        "Cannot predict now.",
        "Don't count on it.",
        "My sources say no.",
        "Very doubtful.",
        "Outlook not so good."
    ]
    
    response = random.choice(responses)
    embed = discord.Embed(title="🎱 Magic 8-Ball", color=discord.Color.purple())
    embed.add_field(name="Question", value=question, inline=False)
    embed.add_field(name="Answer", value=response, inline=False)
    
    await ctx.send(embed=embed)

@bot.command()
async def coinflip(ctx):
    result = random.choice(["Heads", "Tails"])
    await ctx.send(f"🪙 The coin landed on: **{result}**!")

@bot.command()
async def dice(ctx, sides: int = 6):
    result = random.randint(1, sides)
    await ctx.send(f"🎲 You rolled a **{result}** (d{sides})!")

@bot.command()
async def rate(ctx, *, thing: str):
    rating = random.randint(0, 100)
    await ctx.send(f"I'd rate **{thing}** a **{rating}/100**!")

@bot.command()
async def meme(ctx):
    memes = [
        "This is fine. 🔥🐶🔥",
        "It is what it is.",
        "Anyways...",
        "So true bestie.",
        "Not me...",
        "💀💀💀"
    ]
    
    await ctx.send(random.choice(memes))

@bot.command()
async def poll(ctx, question: str, *options):
    if len(options) < 2:
        await ctx.send("❌ Please provide at least 2 options!")
        return
    
    if len(options) > 10:
        await ctx.send("❌ Maximum 10 options allowed!")
        return
    
    embed = discord.Embed(
        title="📊 Poll",
        description=question,
        color=discord.Color.blue()
    )
    
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    for i, option in enumerate(options):
        embed.add_field(name=f"{emojis[i]} {option}", value="\u200b", inline=False)
    
    message = await ctx.send(embed=embed)
    
    for i in range(len(options)):
        await message.add_reaction(emojis[i])

@bot.command()
async def afk(ctx, *, reason: str = "AFK"):
    user_afk[ctx.author.id] = reason
    await ctx.send(f"✓ {ctx.author.mention}, I set your AFK: {reason}", delete_after=5)

@bot.command()
async def suggest(ctx, *, suggestion: str):
    global suggestion_counter
    suggestion_counter += 1
    
    if SUGGESTION_CHANNEL_ID:
        channel = bot.get_channel(SUGGESTION_CHANNEL_ID)
        embed = discord.Embed(
            title=f"💡 Suggestion #{suggestion_counter}",
            description=suggestion,
            color=discord.Color.gold()
        )
        embed.set_footer(text=f"Suggested by {ctx.author.name}")
        
        message = await channel.send(embed=embed)
        await message.add_reaction("👍")
        await message.add_reaction("👎")
        
        await ctx.send("✓ Suggestion submitted!", delete_after=5)
    else:
        await ctx.send("❌ Suggestion channel not configured!")

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    
    embed = discord.Embed(title=f"{guild.name} Server Info", color=discord.Color.blue())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="Owner", value=guild.owner.mention, inline=True)
    embed.add_field(name="Members", value=guild.member_count, inline=True)
    embed.add_field(name="Created", value=guild.created_at.strftime("%B %d, %Y"), inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Channels", value=len(guild.channels), inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    if not member:
        member = ctx.author
    
    embed = discord.Embed(title=f"{member.name}'s Info", color=member.color)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="Nickname", value=member.display_name, inline=True)
    embed.add_field(name="Joined", value=member.joined_at.strftime("%B %d, %Y"), inline=True)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%B %d, %Y"), inline=True)
    embed.add_field(name="Roles", value=len(member.roles), inline=True)
    
    await ctx.send(embed=embed)

@bot.command()
async def embed(ctx):
    modal = Modal(title="Create Custom Embed")
    title_input = TextInput(label="Title", placeholder="Enter embed title")
    description_input = TextInput(label="Description", placeholder="Enter embed description", style=discord.TextStyle.paragraph)
    color_input = TextInput(label="Color (hex)", placeholder="#FF5733 (optional)", required=False)
    
    modal.add_item(title_input)
    modal.add_item(description_input)
    modal.add_item(color_input)

    async def modal_callback(modal_interaction):
        try:
            if color_input.value:
                color = int(color_input.value.replace("#", ""), 16)
            else:
                color = discord.Color.blue().value
        except:
            color = discord.Color.blue().value
        
        embed = discord.Embed(
            title=title_input.value,
            description=description_input.value,
            color=color
        )
        
        await modal_interaction.response.send_message(embed=embed)

    modal.on_submit = modal_callback
    
    class EmbedView(View):
        def __init__(self):
            super().__init__(timeout=60)
        
        @discord.ui.button(label="Create Embed", style=discord.ButtonStyle.blurple)
        async def embed_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(modal)
    
    view = EmbedView()
    await ctx.send("Click to create a custom embed:", view=view, delete_after=60)

@bot.command()
async def reactionrole(ctx, message_id: int, emoji: str, role: discord.Role):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to setup reaction roles.")
        return
    
    try:
        message = await ctx.channel.fetch_message(message_id)
    except:
        await ctx.send("❌ Message not found!")
        return
    
    await message.add_reaction(emoji)
    reaction_roles[(message_id, emoji)] = role.id
    
    await ctx.send(f"✓ Reaction role setup! React with {emoji} to get {role.mention}", delete_after=5)

@bot.command()
async def help(ctx, category: str = None):
    if not category:
        embed = discord.Embed(
            title="🤖 Greenville Roleplay Prism Bot - Command Center",
            description="Use `?help <category>` for detailed commands\n\nCategories: `leveling`, `economy`, `moderation`, `fun`, `utility`, `server`",
            color=discord.Color.orange()
        )
        embed.add_field(name="📊 Leveling", value="`?help leveling`", inline=True)
        embed.add_field(name="💰 Economy", value="`?help economy`", inline=True)
        embed.add_field(name="🛡️ Moderation", value="`?help moderation`", inline=True)
        embed.add_field(name="🎮 Fun", value="`?help fun`", inline=True)
        embed.add_field(name="🔧 Utility", value="`?help utility`", inline=True)
        embed.add_field(name="🎫 Sessions & Tickets", value="`?help server`", inline=True)
        embed.set_footer(text=f"Requested by {ctx.author.name}")
        await ctx.send(embed=embed)
    
    elif category.lower() == "leveling":
        embed = discord.Embed(title="📊 Leveling Commands", color=discord.Color.blue())
        embed.add_field(name="?rank [@user]", value="View your or someone's rank card", inline=False)
        embed.add_field(name="?leaderboard [levels/economy]", value="Show server leaderboard", inline=False)
        embed.set_footer(text="Earn XP by chatting!")
        await ctx.send(embed=embed)
    
    elif category.lower() == "economy":
        embed = discord.Embed(title="💰 Economy Commands", color=discord.Color.green())
        embed.add_field(name="?balance [@user]", value="Check wallet and bank balance", inline=False)
        embed.add_field(name="?daily", value="Claim daily reward ($100-$500)", inline=False)
        embed.add_field(name="?work", value="Work for money ($50-$200)", inline=False)
        embed.add_field(name="?deposit <amount/all>", value="Deposit money to bank", inline=False)
        embed.add_field(name="?withdraw <amount/all>", value="Withdraw from bank", inline=False)
        embed.add_field(name="?give @user <amount>", value="Give money to someone", inline=False)
        embed.set_footer(text="Earn coins by chatting!")
        await ctx.send(embed=embed)
    
    elif category.lower() == "moderation":
        embed = discord.Embed(title="🛡️ Moderation Commands", color=discord.Color.red())
        embed.add_field(name="?warn @user <reason>", value="Warn a user (progressive roles)", inline=False)
        embed.add_field(name="?timeout @user <minutes> <reason>", value="Timeout a user", inline=False)
        embed.add_field(name="?untimeout @user", value="Remove timeout", inline=False)
        embed.add_field(name="?kick @user <reason>", value="Kick a member", inline=False)
        embed.add_field(name="?ban @user <reason>", value="Ban a member", inline=False)
        embed.add_field(name="?clear [amount]", value="Delete messages", inline=False)
        embed.add_field(name="?reactionrole <msg_id> <emoji> @role", value="Setup reaction roles", inline=False)
        embed.set_footer(text="Staff only commands")
        await ctx.send(embed=embed)
    
    elif category.lower() == "fun":
        embed = discord.Embed(title="🎮 Fun Commands", color=discord.Color.purple())
        embed.add_field(name="?8ball <question>", value="Ask the magic 8-ball", inline=False)
        embed.add_field(name="?coinflip", value="Flip a coin", inline=False)
        embed.add_field(name="?dice [sides]", value="Roll a dice (default d6)", inline=False)
        embed.add_field(name="?rate <thing>", value="Rate something out of 100", inline=False)
        embed.add_field(name="?meme", value="Get a random meme phrase", inline=False)
        embed.add_field(name="?poll <question> <opt1> <opt2> ...", value="Create a poll", inline=False)
        await ctx.send(embed=embed)
    
    elif category.lower() == "utility":
        embed = discord.Embed(title="🔧 Utility Commands", color=discord.Color.blue())
        embed.add_field(name="?afk [reason]", value="Set AFK status", inline=False)
        embed.add_field(name="?suggest <suggestion>", value="Submit a suggestion", inline=False)
        embed.add_field(name="?serverinfo", value="Show server statistics", inline=False)
        embed.add_field(name="?userinfo [@user]", value="Show user information", inline=False)
        embed.add_field(name="?embed", value="Create a custom embed", inline=False)
        embed.add_field(name="?announce <message>", value="Send announcement (staff)", inline=False)
        await ctx.send(embed=embed)
    
    elif category.lower() == "server":
        embed = discord.Embed(title="🎫 Sessions & Server Commands", color=discord.Color.orange())
        embed.add_field(name="?startup", value="Start a session (host role)", inline=False)
        embed.add_field(name="?release_early", value="Release early access (host)", inline=False)
        embed.add_field(name="?release", value="Release full session (host)", inline=False)
        embed.add_field(name="?cohost", value="Join as cohost for latest release", inline=False)
        embed.add_field(name="?addcohost @user", value="Add co-host (host)", inline=False)
        embed.add_field(name="?removecohost @user", value="Remove co-host (host)", inline=False)
        embed.add_field(name="?apply", value="Apply for staff", inline=False)
        embed.add_field(name="?giveaway <mins> <prize>", value="Start giveaway (staff)", inline=False)
        embed.add_field(name="?close", value="Close ticket (in ticket channel)", inline=False)
        await ctx.send(embed=embed)
    
    else:
        await ctx.send("❌ Invalid category! Use: `leveling`, `economy`, `moderation`, `fun`, `utility`, `server`")

if not TOKEN:
    print("Error: No bot token found. Please add DISCORD_BOT_TOKEN to Secrets.")
else:
    bot.run(TOKEN)




