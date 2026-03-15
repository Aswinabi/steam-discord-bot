import discord
from discord.ext import commands
import requests
import os
import re
import json
import zipfile
import hashlib
from datetime import datetime
import asyncio
import logging

# Set up logging for Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get token from Railway environment variables
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    logger.error("❌ TOKEN environment variable not set!")
    exit(1)

# Railway specific - use volumes for persistent storage
# Railway provides /data for persistent storage
DATA_DIR = "/data" if os.path.exists("/data") else "."
DOWNLOADS_FOLDER = os.path.join(DATA_DIR, "generated_games")
GAMES_FILE = os.path.join(DATA_DIR, "games_database.json")

# Create directories
os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)

# Configuration
ALLOWED_CHANNEL = int(os.getenv("ALLOWED_CHANNEL", "0"))  # Set this in Railway
GAMES_CHANNEL = int(os.getenv("GAMES_CHANNEL", "0"))      # Set this in Railway

# Game database
GAMES_DB = {}

# Load existing games from Railway volume
if os.path.exists(GAMES_FILE):
    try:
        with open(GAMES_FILE, 'r') as f:
            GAMES_DB = json.load(f)
        logger.info(f"✅ Loaded {len(GAMES_DB)} games from database")
    except Exception as e:
        logger.error(f"❌ Error loading games database: {e}")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logger.info(f"🟢 {bot.user} is online on Railway!")
    logger.info(f"📁 Games available: {len(GAMES_DB)}")
    logger.info(f"💾 Data directory: {DATA_DIR}")
    await bot.change_presence(activity=discord.Game(name="!gen-games-here | !help"))


# -----------------------
# Permission Check
# -----------------------
def is_allowed_channel():
    async def predicate(ctx):
        if ctx.channel.id != ALLOWED_CHANNEL:
            await ctx.send("❌ This command can only be used in the designated channel!")
            return False
        return True
    return commands.check(predicate)


# -----------------------
# Main Command - Generate Game
# -----------------------
@bot.command(name="gen-games-here", aliases=["gen", "generate"])
@is_allowed_channel()
async def generate_game(ctx, game_name=None, appid=None):
    """
    Generate a game package (like in LuaTools)
    Usage: !gen-games-here <game_name> [appid]
    """
    if not game_name:
        await ctx.send("❌ Please specify a game name!\nExample: `!gen-games-here Atomfall 801800`")
        return
    
    # Create embed for generation status
    embed = discord.Embed(
        title="🔄 Generating Game Package",
        description=f"**{game_name}**" + (f" (AppID: {appid})" if appid else ""),
        color=discord.Color.blue()
    )
    embed.set_footer(text="LuaTools Generator • Railway Hosted")
    
    status_msg = await ctx.send(embed=embed)
    
    try:
        # Step 1: Get game info
        embed.color = discord.Color.gold()
        embed.description = "🔍 **Step 1/4:** Fetching game information..."
        await status_msg.edit(embed=embed)
        
        if not appid:
            # Try to find appid from Steam
            appid = await fetch_appid(game_name)
            if not appid:
                embed.color = discord.Color.red()
                embed.description = "❌ Could not find AppID. Please provide it manually."
                await status_msg.edit(embed=embed)
                return
        
        # Step 2: Fetch depots
        embed.description = f"📦 **Step 2/4:** Fetching depots for AppID {appid}..."
        await status_msg.edit(embed=embed)
        
        depots = await fetch_depots(appid)
        if not depots:
            embed.color = discord.Color.red()
            embed.description = f"❌ No depots found for AppID {appid}"
            await status_msg.edit(embed=embed)
            return
        
        # Step 3: Generate files
        embed.description = f"🗜️ **Step 3/4:** Generating package with {len(depots)} depots..."
        await status_msg.edit(embed=embed)
        
        # Create game folder in Railway volume
        game_folder = f"{DOWNLOADS_FOLDER}/{appid}"
        os.makedirs(game_folder, exist_ok=True)
        
        # Create manifest file
        manifest = {
            "appid": appid,
            "name": game_name,
            "generated": datetime.now().isoformat(),
            "depots": depots[:10],  # Limit to 10 depots
            "generated_by": str(ctx.author),
            "generated_by_id": ctx.author.id
        }
        
        manifest_path = f"{game_folder}/{appid}_manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        # Create depot list file
        depots_path = f"{game_folder}/{appid}_depots.txt"
        with open(depots_path, 'w') as f:
            for depot in depots[:10]:
                f.write(f"{depot}\n")
        
        # Create zip file
        zip_filename = f"{appid}_{game_name.replace(' ', '_')}.zip"
        zip_path = os.path.join(DOWNLOADS_FOLDER, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            zipf.write(manifest_path, arcname=f"{appid}_manifest.json")
            zipf.write(depots_path, arcname=f"{appid}_depots.txt")
            
            # Add placeholder files for depots
            for i, depot in enumerate(depots[:10]):
                depot_info = f"Depot ID: {depot}\nGame: {game_name}\nAppID: {appid}\nGenerated on Railway: {datetime.now()}"
                depot_file = f"{game_folder}/depot_{depot}.info"
                with open(depot_file, 'w') as f:
                    f.write(depot_info)
                zipf.write(depot_file, arcname=f"depots/depot_{depot}.info")
        
        # Get file size
        file_size = os.path.getsize(zip_path)
        size_mb = file_size / (1024 * 1024)
        
        # Step 4: Complete
        embed.color = discord.Color.green()
        embed.description = f"✅ **Step 4/4:** Package created successfully!"
        await status_msg.edit(embed=embed)
        
        # Store in database
        GAMES_DB[appid] = {
            "name": game_name,
            "depots": depots[:10],
            "generated": datetime.now().isoformat(),
            "generated_by": str(ctx.author),
            "generated_by_id": ctx.author.id,
            "file": zip_filename,
            "size": f"{size_mb:.2f} MB",
            "downloads": 0
        }
        
        # Save to Railway volume
        with open(GAMES_FILE, 'w') as f:
            json.dump(GAMES_DB, f, indent=2)
        
        # Send the generated file
        file = discord.File(zip_path, filename=zip_filename)
        
        result_embed = discord.Embed(
            title=f"✅ Completed! {game_name} - {appid}",
            description=f"**Package Details:**\n"
                       f"📦 **Depots:** {len(depots[:10])}\n"
                       f"💾 **Size:** {size_mb:.2f} MB\n"
                       f"👤 **Generated by:** {ctx.author.mention}\n"
                       f"🆔 **AppID:** `{appid}`\n"
                       f"🚂 **Hosted on:** Railway",
            color=discord.Color.green()
        )
        result_embed.set_footer(text="LuaTools Generator • Railway Hosted")
        
        await ctx.send(embed=result_embed, file=file)
        
        # Clean up temp folder but keep the zip
        import shutil
        shutil.rmtree(game_folder)
        
        logger.info(f"✅ Generated {game_name} ({appid}) - {size_mb:.2f} MB")
        
    except Exception as e:
        logger.error(f"❌ Error generating game: {e}")
        embed.color = discord.Color.red()
        embed.description = f"❌ Error: {str(e)}"
        await status_msg.edit(embed=embed)


# -----------------------
# Download Counter
# -----------------------
@bot.command(name="download")
@is_allowed_channel()
async def download_game(ctx, appid: str):
    """Get download link for a game"""
    
    if appid not in GAMES_DB:
        await ctx.send(f"❌ Game with AppID `{appid}` not found!")
        return
    
    game = GAMES_DB[appid]
    zip_path = os.path.join(DOWNLOADS_FOLDER, game['file'])
    
    if not os.path.exists(zip_path):
        await ctx.send(f"❌ File not found! Please regenerate the game.")
        return
    
    # Increment download counter
    game['downloads'] = game.get('downloads', 0) + 1
    with open(GAMES_FILE, 'w') as f:
        json.dump(GAMES_DB, f, indent=2)
    
    file = discord.File(zip_path, filename=game['file'])
    
    embed = discord.Embed(
        title=f"📥 Downloading {game['name']}",
        description=f"**AppID:** `{appid}`\n"
                   f"**Size:** {game['size']}\n"
                   f"**Downloads:** {game['downloads']}",
        color=discord.Color.green()
    )
    
    await ctx.send(embed=embed, file=file)


# -----------------------
# List All Generated Games
# -----------------------
@bot.command(name="games", aliases=["game-list", "available"])
@is_allowed_channel()
async def list_games(ctx):
    """List all generated games"""
    
    if not GAMES_DB:
        await ctx.send("📭 No games have been generated yet. Use `!gen-games-here` to create one!")
        return
    
    embed = discord.Embed(
        title="🎮 Available Games",
        description=f"Total: **{len(GAMES_DB)}** games generated",
        color=discord.Color.blue()
    )
    
    # Group by generator
    by_generator = {}
    for appid, info in GAMES_DB.items():
        generator = info.get('generated_by', 'Unknown')
        if generator not in by_generator:
            by_generator[generator] = []
        by_generator[generator].append(f"**{info['name']}** - `{appid}` ({info['size']})")
    
    for generator, games in list(by_generator.items())[:5]:
        embed.add_field(
            name=f"👤 {generator}",
            value="\n".join(games[:3]) + ("\n..." if len(games) > 3 else ""),
            inline=False
        )
    
    await ctx.send(embed=embed)


# -----------------------
# Game Info Command
# -----------------------
@bot.command(name="game-info", aliases=["ginfo"])
@is_allowed_channel()
async def game_info(ctx, appid: str):
    """Get detailed info about a generated game"""
    
    if appid not in GAMES_DB:
        await ctx.send(f"❌ Game with AppID `{appid}` not found in database")
        return
    
    info = GAMES_DB[appid]
    
    embed = discord.Embed(
        title=f"📋 {info['name']}",
        description=f"AppID: `{appid}`",
        color=discord.Color.purple()
    )
    
    embed.add_field(name="Generated", value=info['generated'][:10], inline=True)
    embed.add_field(name="Size", value=info['size'], inline=True)
    embed.add_field(name="Downloads", value=info.get('downloads', 0), inline=True)
    embed.add_field(name="Generated By", value=info['generated_by'], inline=True)
    embed.add_field(name="Depots", value=f"```{', '.join(map(str, info['depots'][:5]))}```", inline=False)
    
    await ctx.send(embed=embed)


# -----------------------
# User Stats Command
# -----------------------
@bot.command(name="user-stats", aliases=["ustats"])
@is_allowed_channel()
async def user_stats(ctx, member: discord.Member = None):
    """Show generation stats for a user"""
    
    if not member:
        member = ctx.author
    
    user_games = []
    total_size = 0
    total_downloads = 0
    
    for appid, info in GAMES_DB.items():
        if info.get('generated_by_id') == member.id:
            user_games.append(info)
            # Parse size
            size_str = info['size'].replace(' MB', '')
            try:
                total_size += float(size_str)
            except:
                pass
            total_downloads += info.get('downloads', 0)
    
    embed = discord.Embed(
        title=f"📊 Stats for {member.display_name}",
        color=discord.Color.gold()
    )
    
    embed.add_field(name="Games Generated", value=str(len(user_games)), inline=True)
    embed.add_field(name="Total Size", value=f"{total_size:.2f} MB", inline=True)
    embed.add_field(name="Total Downloads", value=str(total_downloads), inline=True)
    
    if user_games:
        recent = sorted(user_games, key=lambda x: x['generated'], reverse=True)[:3]
        recent_list = "\n".join([f"• {g['name']} ({g['size']})" for g in recent])
        embed.add_field(name="Recent Games", value=recent_list, inline=False)
    
    await ctx.send(embed=embed)


# -----------------------
# Helper Functions
# -----------------------
async def fetch_appid(game_name):
    """Fetch AppID from Steam"""
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={game_name}&l=english&cc=US"
        r = requests.get(url, timeout=10)
        data = r.json()
        
        if data["total"] > 0:
            return str(data["items"][0]["id"])
    except Exception as e:
        logger.error(f"Error fetching AppID: {e}")
    return None


async def fetch_depots(appid):
    """Fetch depots from SteamDB"""
    try:
        url = f"https://steamdb.info/app/{appid}/depots/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        r = requests.get(url, headers=headers, timeout=10)
        
        depots = re.findall(r'/depot/(\d+)/', r.text)
        return list(set(depots))  # Remove duplicates
    except Exception as e:
        logger.error(f"Error fetching depots: {e}")
        return []


# -----------------------
# Health Check for Railway
# -----------------------
@bot.command(name="health")
async def health_check(ctx):
    """Check bot health status"""
    embed = discord.Embed(
        title="🟢 Bot Health",
        color=discord.Color.green()
    )
    
    embed.add_field(name="Status", value="Online", inline=True)
    embed.add_field(name="Games in DB", value=str(len(GAMES_DB)), inline=True)
    embed.add_field(name="Data Directory", value=DATA_DIR, inline=True)
    embed.add_field(name="Storage Used", value=f"{get_folder_size(DOWNLOADS_FOLDER):.2f} MB", inline=True)
    
    await ctx.send(embed=embed)


def get_folder_size(folder):
    """Get folder size in MB"""
    total = 0
    for path, dirs, files in os.walk(folder):
        for f in files:
            fp = os.path.join(path, f)
            total += os.path.getsize(fp)
    return total / (1024 * 1024)


# -----------------------
# Error Handler
# -----------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        # Already handled in check
        pass
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: {error.param.name}")
    else:
        logger.error(f"Command error: {error}")
        await ctx.send(f"❌ Error: {str(error)}")


# -----------------------
# Admin Commands
# -----------------------
@bot.command(name="add-game")
@commands.has_permissions(administrator=True)
async def add_game_manual(ctx, appid, name, *depots):
    """Manually add a game to database (Admin only)"""
    
    GAMES_DB[appid] = {
        "name": name,
        "depots": list(depots),
        "generated": datetime.now().isoformat(),
        "generated_by": str(ctx.author),
        "generated_by_id": ctx.author.id,
        "file": f"{appid}_{name.replace(' ', '_')}.zip",
        "size": "0 MB",
        "downloads": 0
    }
    
    with open(GAMES_FILE, 'w') as f:
        json.dump(GAMES_DB, f, indent=2)
    
    await ctx.send(f"✅ Added {name} ({appid}) to database!")
    logger.info(f"Admin {ctx.author} added game {name} ({appid})")


@bot.command(name="remove-game")
@commands.has_permissions(administrator=True)
async def remove_game(ctx, appid):
    """Remove a game from database (Admin only)"""
    
    if appid in GAMES_DB:
        name = GAMES_DB[appid]['name']
        del GAMES_DB[appid]
        
        with open(GAMES_FILE, 'w') as f:
            json.dump(GAMES_DB, f, indent=2)
        
        await ctx.send(f"✅ Removed {name} ({appid}) from database!")
        logger.info(f"Admin {ctx.author} removed game {name} ({appid})")
    else:
        await ctx.send(f"❌ AppID {appid} not found!")


if __name__ == "__main__":
    logger.info("🚀 Starting bot on Railway...")
    bot.run(TOKEN)
