import discord
import os
import requests
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from thefuzz import process, fuzz

# โหลดค่าจากไฟล์ .env
load_dotenv()

# ดึง Token มาจาก Environment Variable
TOKEN = os.getenv('DISCORD_TOKEN')

# ตรวจสอบว่าโหลด Token สำเร็จไหม (กัน Error)
if TOKEN is None:
    print("❌ ไม่พบ DISCORD_TOKEN ในไฟล์ .env หรือ Environment Variable")
    exit()

# --- ตั้งค่าเริ่มต้น ---
#TOKEN = '' # Token 

class POE2Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # ลงทะเบียน Slash Command
        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")

bot = POE2Bot()

# --- ส่วนของ Modal (หน้าต่างกรอกชื่อไอเทม) ---
class ItemSearchModal(discord.ui.Modal, title='ค้นหาไอเทม PoE 2'):
    item_name = discord.ui.TextInput(label='ชื่อไอเทมหรือค่าเงิน', placeholder='เช่น Divine Orb, Exalted...')

    def __init__(self, selected_league):
        super().__init__()
        self.selected_league = selected_league

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🔍 กำลังค้นหาข้อมูล...", ephemeral=True)
        
        try:
            # 1. ดึงข้อมูลจาก API
            params = {'league': self.selected_league}
            res_items = requests.get("https://poe2scout.com/api/items", params=params, timeout=10).json()
            res_leagues = requests.get("https://poe2scout.com/api/leagues", timeout=10).json()

            # 2. เตรียมข้อมูลเรทเงิน
            ex_per_divine = 100 
            ex_per_chaos = 5     
            for l in res_leagues:
                if l['value'] == self.selected_league:
                    ex_per_divine = l.get('divinePrice', 100)
                    chaos_per_divine = l.get('chaosDivinePrice', 20)
                    ex_per_chaos = ex_per_divine / chaos_per_divine
                    break

            # 3. เตรียมข้อมูลไอเทมสำหรับการค้นหาคำใกล้เคียง
            items_list = res_items if isinstance(res_items, list) else res_items.get("items", [])
            item_map = {}
            for item in items_list:
                name = item.get('text') or item.get('name')
                if name:
                    item_map[name] = item

            # 4. ใช้ Fuzzy Search หาคำที่ใกล้เคียงที่สุด
            user_input = self.item_name.value
            best_match_name, score = process.extractOne(
                user_input, 
                item_map.keys(), 
                scorer=fuzz.token_set_ratio
            )

            # 5. ตรวจสอบความแม่นยำ (ถ้า score > 60 ถือว่าใช้ได้)
            if score > 60:
                found = item_map[best_match_name]
                price_in_ex = found.get('currentPrice', 0)
                
                # --- Logic การแปลงหน่วยเงิน ---
                if price_in_ex >= ex_per_divine:
                    final_price = price_in_ex / ex_per_divine
                    display_text = f"**{final_price:,.2f} Divine Orb**"
                    color = 0x00ffff 
                elif price_in_ex >= ex_per_chaos:
                    final_price = price_in_ex / ex_per_chaos
                    display_text = f"**{final_price:,.2f} Chaos Orb**"
                    color = 0x964B00 
                else:
                    display_text = f"**{price_in_ex:,.0f} Exalted Orb**"
                    color = 0xe91e63 

                embed = discord.Embed(title=f"💰 ราคาตลาด: {self.selected_league}", color=color)
                embed.add_field(name="ไอเทมที่พบ", value=best_match_name, inline=False)
                #embed.add_field(name="ไอเทมที่พบ", value=f"**{best_match_name}** (แม่นยำ {score}%)", inline=False)
                embed.add_field(name="ราคาปัจจุบัน", value=display_text, inline=True)
                
                # ใส่รูปไอเทมถ้ามี
                if found.get('iconUrl'):
                    embed.set_thumbnail(url=found.get('iconUrl'))
                    
                embed.set_footer(text=f"เรท: 1 Chaos = {ex_per_chaos:.1f} Ex | 1 Div = {ex_per_divine} Ex")
                await interaction.followup.send(embed=embed)
            else:
                await interaction.followup.send(f"❌ ไม่พบไอเทมที่ใกล้เคียงกับ '{user_input}'")

        except Exception as e:
            print(f"Error: {e}")
            await interaction.followup.send("⚠️ เกิดข้อผิดพลาดขณะดึงข้อมูลหรือค้นหา")

# --- ส่วนของ Select Menu (แถบเลือกลีก) ---
class LeagueSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="เลือกลีกที่ต้องการค้นหา...", options=options)

    async def callback(self, interaction: discord.Interaction):
        # เมื่อเลือกลีกเสร็จ ให้เปิด Modal กรอกชื่อไอเทมทันที
        await interaction.response.send_modal(ItemSearchModal(self.values[0]))

class LeagueView(discord.ui.View):
    def __init__(self, options):
        super().__init__()
        self.add_item(LeagueSelect(options))


@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)  # 1 ครั้ง ต่อ 5 วิ ต่อ user
async def check_rate(ctx):
    try:
        res_leagues = requests.get("https://poe2scout.com/api/leagues").json()
        target_league = "Fate of the Vaal"
        
        for l in res_leagues:
            if l['value'] == target_league:
                # พิมพ์ค่าทั้งหมดออกมาดูเพื่อความชัวร์
                await ctx.send(f"📊 **League: {target_league}**\n"
                               f"- divinePrice (Ex per Div?): `{l.get('divinePrice')}`\n"
                               f"- chaosDivinePrice (Chaos per Div?): `{l.get('chaosDivinePrice')}`")
                return
    except Exception as e:
        await ctx.send(f"Error: {e}")

# --- Slash Command /poe2 ---
@bot.tree.command(name="poe2", description="เช็คราคาไอเทมโดยเลือกลีกก่อน")
async def poe2(interaction: discord.Interaction):
    try:
        # ดึงรายชื่อลีกจาก API
        res = requests.get("https://poe2scout.com/api/leagues").json()
        
        # สร้างตัวเลือกจาก JSON (ใช้ค่า 'value')
        options = [
            discord.SelectOption(label=l['value'], value=l['value']) 
            for l in res[:25] # Discord จำกัด Select Menu ได้ไม่เกิน 25 รายการ
        ]
        
        await interaction.response.send_message("กรุณาเลือกลีกที่ต้องการ:", view=LeagueView(options), ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"⚠️ ไม่สามารถดึงรายชื่อลีกได้: {e}", ephemeral=True)

@check_rate.error
async def check_rate_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ รออีก {error.retry_after:.1f} วินาที")
        
bot.run(TOKEN)
