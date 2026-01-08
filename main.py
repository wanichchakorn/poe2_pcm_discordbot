import discord
import os
import requests
import datetime
import json
from urllib.parse import quote
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from thefuzz import process, fuzz

# POE2_PCM_Bot v0.3 by Shork_Shark & Gemini
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

class POE2PCMBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.item_cache = []
        self.item_id_map = {}

    async def setup_hook(self):
        self.update_item_cache.start()
        await self.tree.sync()
        print(f"✅ บอทออนไลน์และ Sync Commands เรียบร้อย!")

    @tasks.loop(minutes=60)
    async def update_item_cache(self):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            url = "https://poe2scout.com/api/items"
            # ดึงข้อมูลจากลีกหลักเพื่อทำ Cache ชื่อไอเทม
            response = requests.get(url, params={'league': 'Fate of the Vaal'}, headers=headers, timeout=15)
            items_list = response.json() if isinstance(response.json(), list) else response.json().get('items', [])
            
            temp_cache = []
            temp_id_map = {}
            for i in items_list:
                name = i.get('text') or i.get('name')
                item_id = i.get('itemId')
                if name and item_id:
                    temp_cache.append(name)
                    temp_id_map[name] = item_id

            self.item_cache = sorted(list(set(temp_cache)))
            self.item_id_map = temp_id_map
            print(f"🔄 อัปเดต Cache สำเร็จ: {len(self.item_cache)} รายการ")
        except Exception as e:
            print(f"⚠️ Cache Error: {e}")

bot = POE2PCMBot()

# --- ฟังก์ชันวาดกราฟเส้น ---
def generate_chart_url(item_name, history_list):
    history_list.reverse() # เรียงจากอดีตไปปัจจุบัน
    labels = []
    prices = []
    for entry in history_list:
        dt = datetime.datetime.fromtimestamp(entry.get('Epoch'))
        labels.append(dt.strftime('%H:%M'))
        price = entry.get('Data', {}).get('CurrencyOneData', {}).get('RelativePrice', 0)
        prices.append(float(price))

    chart_config = {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [{
                "label": "Price (Ex)",
                "data": prices,
                "borderColor": "#5de2e7", 
                "backgroundColor": "rgba(93, 226, 231, 0.1)",
                "fill": True,
                "pointRadius": 0,
                "lineTension": 0.3
            }]
        },
        "options": {
            "title": {"display": True, "text": f"24h Trend: {item_name}", "fontColor": "#fff"},
            "legend": {"display": False},
            "scales": {
                "yAxes": [{"ticks": {"fontColor": "#ccc"}}],
                "xAxes": [{"ticks": {"fontColor": "#ccc", "maxRotation": 45}}]
            }
        }
    }
    return f"https://quickchart.io/chart?c={quote(json.dumps(chart_config))}"

# --- คำสั่งหลัก /price ---
@bot.tree.command(name="price", description="เช็คราคาไอเทม POE2")
@app_commands.describe(league="เลือกลีก", item_name="พิมพ์ชื่อไอเทม")
async def price(interaction: discord.Interaction, league: str, item_name: str):
    await interaction.response.defer()
    
    try:
        # 1. ค้นหาชื่อไอเทมและดึงข้อมูลพื้นฐานจาก Cache
        best_match, score = process.extractOne(item_name, bot.item_id_map.keys(), scorer=fuzz.token_set_ratio)
        if score < 60:
            await interaction.followup.send(f"❌ ไม่พบไอเทม '{item_name}'")
            return

        item_id = bot.item_id_map[best_match]
        headers = {'User-Agent': 'Mozilla/5.0'}

        # 2. ดึงข้อมูลเรทเงิน Divine ใน League ปัจจุบัน
        leagues_res = requests.get("https://poe2scout.com/api/leagues", timeout=10).json()
        ex_per_divine = 100 # ค่า Default
        for l in leagues_res:
            if l['value'] == league:
                ex_per_divine = l.get('divinePrice', 100)
                break

        # 3. ดึงประวัติราคาและข้อมูลไอเทม
        history_url = "https://poe2scout.com/api/currencyExchange/PairHistory"
        ex_id = bot.item_id_map.get("Exalted Orb", 450)
        h_res = requests.get(history_url, params={
            'league': league, 'currencyOneItemId': item_id, 
            'currencyTwoItemId': ex_id, 'limit': 24
        }, headers=headers).json()
        
        history_list = h_res.get("History", [])
        
        # ค้นหารูป Icon จากรายชื่อไอเทมทั้งหมด
        items_res = requests.get("https://poe2scout.com/api/items", params={'league': league}, headers=headers).json()
        items_list = items_res if isinstance(items_res, list) else items_res.get('items', [])
        found_item_data = next((i for i in items_list if i.get('itemId') == item_id), {})
        icon_url = found_item_data.get('iconUrl')

        # 4. สร้าง Embed
        embed = discord.Embed(title=f"💎 Market Info: {best_match}", color=0x5de2e7)
        
        if history_list:
            current_price_ex = float(history_list[0].get('Data', {}).get('CurrencyOneData', {}).get('RelativePrice', 0))
            
            # บรรทัดที่ 1: ราคาปัจจุบันในหน่วย Ex
            # บรรทัดที่ 2: เรทเปรียบเทียบหน่วย Divine
            price_in_div = current_price_ex / ex_per_divine
            desc_text = f"ราคาปัจจุบัน: **{current_price_ex:,.2f} Ex**\n"
            desc_text += f"เทียบเท่า: `{price_in_div:,.3f} Divine Orb` (Rate: 1 Div = {ex_per_divine} Ex)"
            embed.description = desc_text

            chart_url = generate_chart_url(best_match, history_list)
            embed.set_image(url=chart_url)
        else:
            embed.description = "⚠️ ไม่พบข้อมูลราคาล่าสุด"

        # ใส่รูปไอเทมที่มุมขวาบน
        if icon_url:
            embed.set_thumbnail(url=icon_url)

        embed.set_footer(text=f"League: {league} | Data: poe2scout.com")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Error in /price final: {e}")
        await interaction.followup.send("⚠️ เกิดข้อผิดพลาดในการประมวลผลข้อมูล")

# Autocomplete ส่วนไอเทม
@price.autocomplete('item_name')
async def item_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=n, value=n) for n in bot.item_cache if current.lower() in n.lower()][:25]

# Autocomplete ส่วนลีก
@price.autocomplete('league')
async def league_autocomplete(interaction: discord.Interaction, current: str):
    leagues = ["Fate of the Vaal", "Standard", "Hardcore Fate of the Vaal"]
    return [app_commands.Choice(name=l, value=l) for l in leagues if current.lower() in l.lower()]

bot.run(TOKEN)