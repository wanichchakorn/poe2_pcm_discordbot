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
@bot.tree.command(name="price", description="เช็คราคาไอเทมและดูประวัติกราฟ")
@app_commands.describe(league="เลือกลีก", item_name="พิมพ์ชื่อไอเทม")
async def price(interaction: discord.Interaction, league: str, item_name: str):
    await interaction.response.defer() # ป้องกัน Timeout
    
    try:
        # 1. ค้นหาชื่อไอเทมที่ใกล้เคียงที่สุดจาก Cache
        best_match, score = process.extractOne(item_name, bot.item_id_map.keys(), scorer=fuzz.token_set_ratio)
        if score < 60:
            await interaction.followup.send(f"❌ ไม่พบไอเทม '{item_name}'")
            return

        item_id = bot.item_id_map[best_match]
        ex_id = bot.item_id_map.get("Exalted Orb", 450)
        headers = {'User-Agent': 'Mozilla/5.0'}

        # 2. ดึงประวัติราคา (PairHistory)
        history_url = "https://poe2scout.com/api/currencyExchange/PairHistory"
        h_res = requests.get(history_url, params={
            'league': league, 'currencyOneItemId': item_id, 
            'currencyTwoItemId': ex_id, 'limit': 24
        }, headers=headers).json()
        
        history_list = h_res.get("History", [])
        
        # 3. สร้าง Embed และแนบกราฟ
        embed = discord.Embed(title=f"💎 Market Info: {best_match}", color=0x5de2e7)
        
        if history_list:
            current_price = history_list[0].get('Data', {}).get('CurrencyOneData', {}).get('RelativePrice', 0)
            embed.description = f"ราคาปัจจุบัน: **{float(current_price):,.2f} Ex**"
            chart_url = generate_chart_url(best_match, history_list)
            embed.set_image(url=chart_url)
        else:
            embed.description = "⚠️ พบไอเทมแต่ไม่พบประวัติราคาล่าสุด"

        embed.set_footer(text=f"League: {league} | Data from poe2scout.com")
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"Error in /price: {e}")
        await interaction.followup.send("⚠️ เกิดข้อผิดพลาดในการดึงข้อมูล")

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