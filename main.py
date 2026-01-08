import discord
import os
import requests
import asyncio
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from thefuzz import process, fuzz

# --- 1. Token ---
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if TOKEN is None:
    print("❌ ไม่พบ DISCORD_TOKEN")
    exit()

class POE2PCMBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        # สร้างตัวแปรเก็บรายชื่อไอเทมสำหรับ Autocomplete
        self.item_cache = []

    async def setup_hook(self):
        # เริ่มต้นดึงข้อมูลไอเทมเข้า Cache ทันทีที่บอทเปิด
        self.update_item_cache.start()
        await self.tree.sync()
        print(f"✅ Synced slash commands for {self.user}")

    # ดึงรายชื่อไอเทมมาเก็บไว้ทุกๆ 60 นาที เพื่อความรวดเร็วในการแสดงผล Autocomplete
    @tasks.loop(minutes=60)
    async def update_item_cache(self):
        try:
            # ดึงจากลีกหลักเพื่อนำชื่อมาแสดงเป็นตัวเลือก
            res = requests.get("https://poe2scout.com/api/items?league=Fate%20of%20the%20Vaal", timeout=10).json()
            items = res if isinstance(res, list) else res.get("items", [])
            names = {i.get('text') or i.get('name') for i in items if i.get('text') or i.get('name')}
            self.item_cache = sorted(list(names))
            print(f"🔄 อัปเดตรายชื่อไอเทม {len(self.item_cache)} รายการสำเร็จ")
        except Exception as e:
            print(f"⚠️ ไม่สามารถอัปเดต Cache ได้: {e}")

bot = POE2PCMBot()

# --- 2. คำสั่งหลัก /price (พร้อม Autocomplete) ---
@bot.tree.command(name="price", description="บอทเช็คราคาไอเทม POE2SCOUT by Shork_Shark")
@app_commands.describe(
    league="เลือกลีกที่ต้องการ",
    item_name="พิมพ์ชื่อไอเทม"
)
async def price(interaction: discord.Interaction, league: str, item_name: str):
    # ใช้ defer เพื่อบอก Discord ว่าบอทกำลังประมวลผล (ป้องกัน Error 3 วินาที)
    await interaction.response.defer(ephemeral=True)
    
    try:
        # 1. ดึงข้อมูลราคาและเรทเงิน
        params = {'league': league}
        res_items = requests.get("https://poe2scout.com/api/items", params=params, timeout=10).json()
        res_leagues = requests.get("https://poe2scout.com/api/leagues", timeout=10).json()

        # 2. คำนวณเรทเงิน
        ex_per_divine, ex_per_chaos = 100, 5
        for l in res_leagues:
            if l['value'] == league:
                ex_per_divine = l.get('divinePrice', 100)
                chaos_div_price = l.get('chaosDivinePrice', 20)
                ex_per_chaos = ex_per_divine / chaos_div_price
                break

        # 3. ค้นหาไอเทม (ใช้ Fuzzy Search เพื่อความชัวร์หากผู้ใช้ไม่เลือกจาก List)
        items_list = res_items if isinstance(res_items, list) else res_items.get("items", [])
        item_map = { (i.get('text') or i.get('name')): i for i in items_list if i.get('text') or i.get('name') }
        
        best_match, score = process.extractOne(item_name, item_map.keys(), scorer=fuzz.token_set_ratio)

        if score > 60:
            found = item_map[best_match]
            price_in_ex = found.get('currentPrice', 0)
            
            # Logic การแปลงหน่วย (ทศนิยม 2 ตำแหน่ง)
            if price_in_ex >= ex_per_divine:
                val, unit, color = price_in_ex / ex_per_divine, "Divine Orb", 0x00ffff
            elif price_in_ex >= ex_per_chaos:
                val, unit, color = price_in_ex / ex_per_chaos, "Chaos Orb", 0x964B00
            else:
                val, unit, color = price_in_ex, "Exalted Orb", 0xe91e63

            embed = discord.Embed(title=f"💰 ราคาตลาด: {league}", color=color)
            embed.add_field(name="ชื่อไอเทม", value=f"**{best_match}**", inline=False)
            embed.add_field(name="ราคาปัจจุบัน", value=f"**{val:,.2f} {unit}**", inline=True)
            
            if found.get('iconUrl'):
                embed.set_thumbnail(url=found.get('iconUrl'))
            
            embed.set_footer(text=f"เรท: 1 Chaos = {ex_per_chaos:.1f} Ex | 1 Div = {ex_per_divine} Ex")
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(f"❌ ไม่พบข้อมูลไอเทม '{item_name}'")

    except Exception as e:
        print(f"Error: {e}")
        await interaction.followup.send("⚠️ เกิดข้อผิดพลาดขณะดึงข้อมูล")

# --- 3. ฟังก์ชันสำหรับทำ Autocomplete ---

# แนะนำชื่อไอเทมขณะพิมพ์
@price.autocomplete('item_name')
async def item_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=name, value=name)
        for name in bot.item_cache if current.lower() in name.lower()
    ][:25] # Discord จำกัดที่ 25 รายการ

# แนะนำชื่อลีกขณะพิมพ์
@price.autocomplete('league')
async def league_autocomplete(interaction: discord.Interaction, current: str):
    leagues = ["Fate of the Vaal", "Standard", "Hardcore Fate of the Vaal"]
    return [
        app_commands.Choice(name=l, value=l)
        for l in leagues if current.lower() in l.lower()
    ]

bot.run(TOKEN)