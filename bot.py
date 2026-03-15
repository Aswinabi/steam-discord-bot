import discord
from discord.ext import commands
import requests
import os
import re

TOKEN = os.getenv("TOKEN")

# Allowed channel
ALLOWED_CHANNEL = 1482722919028363347

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print("Bot is online!")


# -----------------------
# Steam AppID command
# -----------------------
@bot.command()
async def steamid(ctx, *, game):

    if ctx.channel.id != ALLOWED_CHANNEL:
        return

    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={game}&l=english&cc=US"
        r = requests.get(url)
        data = r.json()

        if data["total"] == 0:
            await ctx.send("Game not found")
            return

        game_data = data["items"][0]

        name = game_data["name"]
        appid = game_data["id"]

        await ctx.send(f"🎮 **{name}**\nAppID: `{appid}`")

    except:
        await ctx.send("Error fetching Steam data")


# -----------------------
# SteamDB Depot command
# -----------------------
@bot.command()
async def depots(ctx, appid: int):

    if ctx.channel.id != ALLOWED_CHANNEL:
        return

    try:
        url = f"https://steamdb.info/app/{appid}/depots/"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})

        depots = re.findall(r'/depot/(\d+)/', r.text)
        depots = list(set(depots))

        if not depots:
            await ctx.send("No depots found.")
            return

        depots = depots[:10]

        msg = "\n".join(depots)

        await ctx.send(f"📦 **Depots for AppID {appid}**\n```{msg}```")

    except:
        await ctx.send("Error fetching depots")


bot.run(TOKEN)
