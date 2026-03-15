import discord
from discord.ext import commands
import requests

import os
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print("Bot is online!")


@bot.command()
async def steamid(ctx, *, game):
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={game}&l=english&cc=US"
        response = requests.get(url, timeout=10)
        data = response.json()

        if data["total"] == 0:
            await ctx.send("Game not found")
            return

        game_data = data["items"][0]

        name = game_data["name"]
        appid = game_data["id"]

        await ctx.send(f"{name} : {appid}")

    except Exception as e:
        await ctx.send("Error fetching Steam data")
        print(e)


bot.run(TOKEN)