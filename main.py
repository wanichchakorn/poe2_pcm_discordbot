import discord
import os
import requests
import time

from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ==================================================
# โหลด Environment Variable (.env ใช้ตอนรัน local)
# Railway จะใช้ Environment Variable ของระบบแทน
# ==================================================
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# กันกรณีลืมตั้งค่า Token
if not TOKEN:
    print("❌ ไม่พบ DISCORD_TOKEN")
    exit()

# ==================================================
# CONFIG / CONSTANTS
# ==================================================

API_TIMEOUT = 10        # timeout (วินาที) ป้องกัน API ค้าง
ITEM_CACHE_TTL = 60     # cache รายชื่อไอเทมต่อลีก (วินาที)
USER_COOLDOWN = 5       # cooldown ต่อ user (วินาที)

# cache รายชื่อไอเทม แยกตาม league
# โครงสร้าง:
# {
#   "League Name": {
#       "time": timestamp,
#       "items": [ชื่อไอเทม, ...]
#   }
# }
item_cache = {}

# เก็บเวลาล่าสุดที่ user ใช้คำสั่ง
# { user_id: timestamp }
user_cooldowns = {}

# ==================================================
# BOT CLASS
# ==================================================
class POE2Bot(commands.Bot):
    """
    คลาสหลักของ Discord Bot
    ใช้ commands.Bot เพื่อรองรับทั้ง prefix และ slash command
    """

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(
            command_prefix="!",
            intents=intents
        )

    async def setup_hook(self):
        """
        ถูกเรียกตอนบอทเริ่มทำงาน
        ใช้ sync slash command กับ Discord
        """
        await self.tree.sync()
        print("✅ Slash commands synced")

bot = POE2Bot()

# ==================================================
# HELPER FUNCTIONS
# ==================================================

def check_user_cooldown(user_id: int):
    """
    ตรวจ cooldown ต่อ user
    ถ้ายังติด cooldown → return เวลาที่ต้องรอ
    ถ้าไม่ติด → บันทึกเวลาใหม่ และ return 0
    """
    now = time.time()
    last_used = user_cooldowns.get(user_id, 0)

    if now - last_used < USER_COOLDOWN:
        return USER_COOLDOWN - (now - last_used)

    user_cooldowns[user_id] = now
    return 0


def get_exchange_rate(league: str):
    """
    ดึงเรทค่าเงินจาก poe2scout
    - Exalted ต่อ Divine
    - Exalted ต่อ Chaos
    """
    res = requests.get(
        "https://poe2scout.com/api/leagues",
        timeout=API_TIMEOUT
    ).json()

    # ค่า default เผื่อ API เปลี่ยน
    ex_per_div = 100
    ex_per_chaos = 5

    for l in res:
        if l["value"] == league:
            ex_per_div = l.get("divinePrice", 100)
            chaos_per_div = l.get("chaosDivinePrice", 20)

            # แปลง Chaos → Exalted
            ex_per_chaos = ex_per_div / chaos_per_div
            break

    return ex_per_div, ex_per_chaos


def get_items_for_league(league: str):
    """
    ดึงรายชื่อไอเทมของลีก
    ใช้ cache เพื่อลดการเรียก API ซ้ำ
    """
    now = time.time()
    cached = item_cache.get(league)

    # ใช้ cache ถ้ายังไม่หมดอายุ
    if cached and now - cached["time"] < ITEM_CACHE_TTL:
        return cached["items"]

    # ดึงข้อมูลใหม่จาก API
    res = requests.get(
        "https://poe2scout.com/api/items",
        params={"league": league},
        timeout=API_TIMEOUT
    ).json()

    # ดึงเฉพาะชื่อไอเทม
    items = [
        i.get("text") or i.get("name")
        for i in res
        if i.get("text") or i.get("name")
    ]

    # เก็บลง cache
    item_cache[league] = {
        "time": now,
        "items": items
    }

    return items

# ==================================================
# AUTOCOMPLETE FUNCTION
# ==================================================
async def item_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    """
    ฟังก์ชัน autocomplete
    จะถูกเรียก "ทุกครั้งที่ user พิมพ์"
    ดังนั้น:
    - ห้ามเรียก API ตรง ๆ
    - ต้องใช้ cache เท่านั้น
    """

    league = interaction.namespace.league
    if not league:
        return []

    try:
        items = get_items_for_league(league)
    except:
        return []

    # filter ตามตัวอักษรที่ user พิมพ์
    matches = [
        app_commands.Choice(name=name, value=name)
        for name in items
        if current.lower() in name.lower()
    ]

    # Discord จำกัด autocomplete ไม่เกิน 25 ตัว
    return matches[:25]

# ==================================================
# SLASH COMMAND: /poe2
# ==================================================
@bot.tree.command(
    name="poe2",
    description="เช็คราคาไอเทม PoE2"
)
@app_commands.describe(
    league="เลือกลีก",
    item="ชื่อไอเทม"
)
@app_commands.autocomplete(item=item_autocomplete)
async def poe2(
    interaction: discord.Interaction,
    league: str,
    item: str
):
    """
    Slash command หลักของบอท
    flow:
    1) เช็ค cooldown
    2) ดึงเรทค่าเงิน
    3) ดึงข้อมูลไอเทม
    4) แปลงราคา
    5) ส่ง embed
    """

    # -------- cooldown --------
    wait = check_user_cooldown(interaction.user.id)
    if wait > 0:
        await interaction.response.send_message(
            f"⏳ กรุณารออีก {wait:.1f} วินาที",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"🔍 กำลังค้นหา **{item}** ในลีก **{league}**...",
        ephemeral=True
    )

    try:
        # ดึงเรทค่าเงิน
        ex_per_div, ex_per_chaos = get_exchange_rate(league)

        # ดึงข้อมูลไอเทมทั้งหมด
        res = requests.get(
            "https://poe2scout.com/api/items",
            params={"league": league},
            timeout=API_TIMEOUT
        ).json()

        # หาไอเทมที่ตรงกับชื่อที่เลือก
        data = next(
            (
                i for i in res
                if (i.get("text") or i.get("name", "")).lower()
                == item.lower()
            ),
            None
        )

        if not data:
            await interaction.followup.send("❌ ไม่พบไอเทม")
            return

        price_ex = data.get("currentPrice", 0)

        # -------- แปลงราคา --------
        if price_ex >= ex_per_div:
            price = price_ex / ex_per_div
            text = f"{price:,.2f} Divine Orb"
            color = 0x00ffff
        elif price_ex >= ex_per_chaos:
            price = price_ex / ex_per_chaos
            text = f"{price:,.2f} Chaos Orb"
            color = 0x964B00
        else:
            text = f"{price_ex:,.0f} Exalted Orb"
            color = 0xe91e63

        # -------- Embed --------
        embed = discord.Embed(
            title=f"💰 ราคาในลีก {league}",
            color=color
        )
        embed.add_field(name="ไอเทม", value=item, inline=False)
        embed.add_field(name="ราคาตลาด", value=f"**{text}**", inline=True)
        embed.set_footer(
            text=f"เรท: 1 Chaos = {ex_per_chaos:.1f} Ex | 1 Div = {ex_per_div} Ex"
        )

        await interaction.followup.send(embed=embed)

    except requests.exceptions.Timeout:
        await interaction.followup.send(
            "⏳ API ตอบช้าเกินไป กรุณาลองใหม่"
        )
    except Exception as e:
        print("ERROR:", e)
        await interaction.followup.send("⚠️ เกิดข้อผิดพลาด")

# ==================================================
# RUN BOT
# ==================================================
bot.run(TOKEN)
