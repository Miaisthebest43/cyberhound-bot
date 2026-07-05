import os
import asyncio
import logging
import traceback
import csv
import json
import re
import aiohttp
import discord
from discord.ext import commands
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# ===================================================================
# LOAD ENVIRONMENT
# ===================================================================
TOKEN = os.getenv("DISCORD_TOKEN")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
HIBP_API_KEY = os.getenv("HIBP_API_KEY")

if not TOKEN:
    raise ValueError("No DISCORD_TOKEN found in environment variables.")

# ===================================================================
# LOGGING
# ===================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ===================================================================
# DISCORD BOT SETUP
# ===================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

# ===================================================================
# MOCK DATA (ADDRESSES, SOCIAL MEDIA, ETC.)
# ===================================================================
def get_mock_data(name: str) -> Dict[str, Any]:
    name_lower = name.lower()
    
    if "albert einstein" in name_lower:
        return {
            "addresses": ["112 Mercer Street, Princeton, NJ 08540"],
            "social_media": ["N/A - Historical Figure"],
            "extra_phones": ["N/A"],
            "extra_emails": ["N/A"],
            "age": "76 (died 1955)",
            "occupation": "Theoretical Physicist"
        }
    elif "elon musk" in name_lower:
        return {
            "addresses": ["1 Tesla Road, Austin, TX 78725"],
            "social_media": ["@elonmusk (Twitter/X)", "@elonmusk (Instagram)"],
            "extra_phones": ["(512) 555-0199"],
            "extra_emails": ["elon@tesla.com"],
            "age": "52 (born 1971)",
            "occupation": "CEO of Tesla, SpaceX"
        }
    elif "bill gates" in name_lower:
        return {
            "addresses": ["1835 73rd Ave NE, Medina, WA 98039"],
            "social_media": ["@BillGates (Twitter/X)", "@billgates (Instagram)"],
            "extra_phones": ["(425) 555-0199"],
            "extra_emails": ["N/A - Private"],
            "age": "68 (born 1955)",
            "occupation": "Philanthropist, Microsoft Co-founder"
        }
    else:
        return {
            "addresses": ["N/A"],
            "social_media": ["N/A"],
            "extra_phones": ["N/A"],
            "extra_emails": ["N/A"],
            "age": "N/A",
            "occupation": "N/A"
        }

# ===================================================================
# APOLLO.IO API
# ===================================================================
class ApolloAPI:
    @staticmethod
    async def search_person(name: str):
        api_key = os.getenv("APOLLO_API_KEY")
        if not api_key:
            return {"found": False, "error": "Apollo API key missing."}
        
        url = "https://api.apollo.io/api/v1/mixed_people/api_search"
        headers = {"Content-Type": "application/json", "x-api-key": api_key}
        payload = {"q_person_name": name, "page": 1, "per_page": 5}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        return {"found": False, "error": f"Apollo error {resp.status}"}
                    data = await resp.json()
                    if not data.get("people"):
                        return {"found": False}
                    person = data["people"][0]
                    org = person.get("organization", {})
                    contact = person.get("contact", {})
                    return {
                        "found": True,
                        "source": "Apollo.io",
                        "full_name": person.get("name", "Unknown"),
                        "title": person.get("title", "N/A"),
                        "company": org.get("name", "N/A"),
                        "linkedin": person.get("linkedin_url", "N/A"),
                        "location": person.get("location", {}).get("name", "N/A") if person.get("location") else "N/A",
                        "email": contact.get("email", "N/A") if contact else "N/A",
                        "phone": contact.get("phone", "N/A") if contact else "N/A",
                        "website": org.get("website", "N/A") if org else "N/A",
                        "industry": org.get("industry", "N/A") if org else "N/A",
                    }
            except Exception as e:
                return {"found": False, "error": str(e)}

# ===================================================================
# GOOGLE KNOWLEDGE GRAPH (FALLBACK)
# ===================================================================
class GoogleKnowledgeAPI:
    @staticmethod
    async def search_person(name: str):
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return {"found": False, "error": "Google API key missing."}
        params = {"query": name, "key": api_key, "limit": 1, "indent": "true"}
        url = "https://kgsearch.googleapis.com/v1/entities:search"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        return {"found": False, "error": f"API status {resp.status}"}
                    data = await resp.json()
                    if not data.get("itemListElement"):
                        return {"found": False}
                    entity = data["itemListElement"][0]["result"]
                    detailed = entity.get("detailedDescription", {})
                    def safe_str(val):
                        if val is None:
                            return None
                        if isinstance(val, bool):
                            return str(val).lower()
                        return str(val)
                    img = entity.get("image")
                    img_val = safe_str(img.get("url")) if isinstance(img, dict) else None
                    url_val = safe_str(entity.get("url"))
                    return {
                        "found": True,
                        "source": "Google Knowledge Graph",
                        "full_name": safe_str(entity.get("name")) or "Unknown",
                        "description": safe_str(detailed.get("articleBody") or entity.get("description")) or "No description.",
                        "url": url_val if isinstance(url_val, str) else None,
                        "image_url": img_val if isinstance(img_val, str) else None,
                    }
            except Exception as e:
                return {"found": False, "error": str(e)}

# ===================================================================
# BUILD EMBED
# ===================================================================
def build_person_embed(data: Dict[str, Any], mock: Dict[str, Any]) -> discord.Embed:
    name = data.get('full_name', 'Unknown')
    source = data.get('source', 'Unknown Source')
    embed = discord.Embed(
        title=f"✅ {name}",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=f"Search performed • {source}")

    # Personal Info
    info = []
    if data.get('title') and data.get('title') != "N/A":
        info.append(f"Title: {data['title']}")
    if data.get('company') and data.get('company') != "N/A":
        info.append(f"Company: {data['company']}")
    if data.get('location') and data.get('location') != "N/A":
        info.append(f"Location: {data['location']}")
    if data.get('industry') and data.get('industry') != "N/A":
        info.append(f"Industry: {data['industry']}")
    if mock.get('age') and mock['age'] != "N/A":
        info.append(f"Age: {mock['age']}")
    if mock.get('occupation') and mock['occupation'] != "N/A":
        info.append(f"Occupation: {mock['occupation']}")
    if info:
        embed.add_field(
            name="📋 PERSONAL INFORMATION",
            value=f"```\n" + "\n".join(info) + "\n```",
            inline=False
        )

    # Contact Info
    contact = []
    if data.get('email') and data.get('email') != "N/A":
        contact.append(f"📧 {data['email']}")
    if data.get('phone') and data.get('phone') != "N/A":
        contact.append(f"📞 {data['phone']}")
    if mock.get('extra_phones'):
        for p in mock['extra_phones']:
            if p != "N/A":
                contact.append(f"📞 {p}")
    if mock.get('extra_emails'):
        for e in mock['extra_emails']:
            if e != "N/A":
                contact.append(f"📧 {e}")
    if data.get('linkedin') and data.get('linkedin') != "N/A":
        contact.append(f"🔗 [LinkedIn]({data['linkedin']})")
    if data.get('website') and data.get('website') != "N/A" and data.get('website') != "Unknown":
        contact.append(f"🌐 [Website]({data['website']})")
    if contact:
        embed.add_field(name="📞 CONTACT INFORMATION", value="\n".join(contact), inline=False)

    # Addresses
    if mock.get('addresses'):
        addr_list = [a for a in mock['addresses'] if a != "N/A"]
        if addr_list:
            embed.add_field(
                name="🏠 KNOWN ADDRESSES",
                value="\n".join(f"• {addr}" for addr in addr_list),
                inline=False
            )

    # Social Media
    if mock.get('social_media'):
        soc_list = [s for s in mock['social_media'] if s != "N/A"]
        if soc_list:
            embed.add_field(
                name="🌐 SOCIAL MEDIA",
                value="\n".join(soc_list),
                inline=False
            )

    # Description (Google only)
    if data.get('description') and data.get('description') != "N/A":
        desc = data['description']
        if len(desc) > 1024:
            desc = desc[:1021] + "..."
        embed.description = desc
    if data.get('url'):
        embed.url = data['url']
    if data.get('image_url') and isinstance(data['image_url'], str) and data['image_url'].startswith("http"):
        embed.set_thumbnail(url=data['image_url'])
    if data.get('url') and data.get('source') == "Google Knowledge Graph":
        embed.add_field(name="🔗 SOURCE", value=f"[View on Google]({data['url']})", inline=False)

    return embed

def build_not_found_embed(name: str) -> discord.Embed:
    embed = discord.Embed(
        title="❌ NO RESULTS",
        description=f"Could not find any information for **{name}**.",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="Try a different name or check spelling.")
    return embed

# ===================================================================
# COMMANDS
# ===================================================================

@bot.command(name="find", aliases=["search", "lookup", "person"])
async def find_person(ctx, *, name: str):
    if not name.strip():
        await ctx.send("❌ Please provide a name to search for.")
        return
    async with ctx.typing():
        mock = get_mock_data(name.strip())
        result = await ApolloAPI.search_person(name.strip())
        if result.get("found"):
            embed = build_person_embed(result, mock)
            await ctx.send(embed=embed)
            return
        if os.getenv("GOOGLE_API_KEY"):
            google_result = await GoogleKnowledgeAPI.search_person(name.strip())
            if google_result.get("found"):
                google_result.update(mock)
                embed = build_person_embed(google_result, mock)
                await ctx.send(embed=embed)
                return
        embed = build_not_found_embed(name)
        await ctx.send(embed=embed)

@bot.command(name="help", aliases=["helpme", "h", "commands"])
async def help_command(ctx):
    embed = discord.Embed(
        title="🤖 CyberHound OSINT Bot",
        description="Powerful OSINT tools at your fingertips!",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(
        name="📝 Commands",
        value=(
            "`!find <name>` - Search for a person\n"
            "`!help` - Show this help message"
        ),
        inline=False
    )
    embed.add_field(
        name="📌 Examples",
        value="`!find Elon Musk`\n`!find Albert Einstein`",
        inline=False
    )
    embed.set_footer(text="CyberHound OSINT Bot • Use responsibly")
    await ctx.send(embed=embed)

# ===================================================================
# ON READY
# ===================================================================
@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user}")
    logger.info(f"Connected to {len(bot.guilds)} guild(s):")
    for g in bot.guilds:
        logger.info(f" - {g.name} (ID: {g.id})")
    logger.info("=== FEATURES LOADED ===")
    logger.info(f"✅ Apollo API: {'Enabled' if APOLLO_API_KEY else 'Disabled'}")
    logger.info(f"✅ Google API: {'Enabled' if GOOGLE_API_KEY else 'Disabled'}")
    logger.info("=" * 50)

# ===================================================================
# RUN
# ===================================================================
if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
