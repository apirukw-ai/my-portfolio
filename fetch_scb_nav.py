import os
import re
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from supabase import create_client, Client

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ Supabase
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# 2. จับคู่ asset_name -> คำค้นหาสัญลักษณ์กองทุน
# ==========================================
FUND_MAP = {
    'SCBAXJ(E)':    ['SCBAXJ(E)', 'SCBAXJ-E', 'SCBAXJ'],
    'SCBNDQ(E)':    ['SCBNDQ(E)', 'SCBNDQ-E', 'SCBNDQ'],
    'SCBS&P500E':   ['SCBS&P500E', 'SCBS&P500(E)', 'SCBS&P500-E', 'SCBS&P500'],
    'SCBSEMI(E)':   ['SCBSEMI(E)', 'SCBSEMI-E', 'SCBSEMI'],
    'SCBGVALUE(E)': ['SCBGVALUE(E)', 'SCBGVALUE-E', 'SCBGVALUE'],
    'SCBWORLD(E)':  ['SCBWORLD(E)', 'SCBWORLD-E', 'SCBWORLD']
}

def fetch_scb_nav():
    url = "https://www.scbam.com/funds"
    nav_results = {}

    print(f"📡 กำลังเปิด Headless Browser เพื่อดึงข้อมูลจาก SCBAM: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                
                # รอให้ Element ของกองทุนแสดงผลบนหน้าเว็บ
                page.wait_for_timeout(5000)
                html_content = page.content()
            finally:
                browser.close()

        soup = BeautifulSoup(html_content, 'html.parser')
        
        # ค้นหาข้อความการ์ด หรือองค์ประกอบในหน้าเว็บ
        text_blocks = soup.find_all(['div', 'tr', 'li', 'article'])
        
        for block in text_blocks:
            raw_text = block.get_text()
            clean_text = re.sub(r'[\s\-]+', '', raw_text).upper()

            for asset_name, aliases in FUND_MAP.items():
                if asset_name in nav_results:
                    continue

                for alias in aliases:
                    clean_alias = re.sub(r'[\s\-]+', '', alias).upper()
                    if clean_alias in clean_text:
                        # ดึงตัวเลขทศนิยม 4 ตำแหน่งที่อยู่ตามหลังคำว่า NAV หรือในข้อความ
                        matches = re.findall(r'\d[\d\,]*\.\d{4}', raw_text)
                        if matches:
                            try:
                                nav_val = float(matches[0].replace(',', ''))
                                if 1.0 <= nav_val <= 1000.0:
                                    nav_results[asset_name] = nav_val
                                    print(f"✅ เจอ {asset_name} -> NAV: {nav_val}")
                                    break
                            except ValueError:
                                continue

        return nav_results

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดขณะดึง NAV: {e}")
        return nav_results

def update_supabase_batch(nav_data):
    if not nav_data:
        print("⚠️ ไม่มีข้อมูล NAV ที่จะอัปเดต")
        return

    thai_tz = timezone(timedelta(hours=7))
    now_thai = datetime.now(thai_tz)
    today_str = now_thai.strftime("%Y-%m-%d")

    try:
        db_res = supabase.table("user_portfolios").select("*").ilike("app_source", "SCB").execute()
        scb_items = db_res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก Supabase ได้: {e}")
        return

    batch_payload = []
    for item in scb_items:
        asset_name = item.get("asset_name", "").strip()
        asset_code = item.get("asset_code", "").strip()
        
        nav_val = nav_data.get(asset_name) or nav_data.get(asset_code)

        if nav_val:
            units = float(item.get("units") or 0)
            old_current_nav = item.get("current_nav")
            old_prev_nav = item.get("prev_nav")

            # Logic ป้องกัน prev_nav ซ้ำกับ current_nav
            if old_current_nav and float(old_current_nav) != float(nav_val):
                prev_nav = float(old_current_nav)
            elif old_prev_nav:
                prev_nav = float(old_prev_nav)
            else:
                prev_nav = float(nav_val)
            
            updated_item = item.copy()
            updated_item.update({
                "prev_nav": round(prev_nav, 4),
                "current_nav": round(nav_val, 4),
                "current_value": round(units * nav_val, 4),
                "nav_date": today_str,
                "updated_at": now_thai.isoformat()
            })
            batch_payload.append(updated_item)

    if batch_payload:
        try:
            supabase.table("user_portfolios").upsert(batch_payload).execute()
            print(f"💾 อัปเดต Supabase (SCB) แบบ Batch สำเร็จทั้งหมด {len(batch_payload)} รายการ")
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการอัปเดตแบบ Batch: {e}")
    else:
        print("⚠️ ไม่พบข้อมูล asset_name / asset_code ใน Supabase ที่จับคู่ตรงกัน")

if __name__ == "__main__":
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (SCB via Playwright)...")
    nav_data = fetch_scb_nav()
    print("-" * 40)
    print(f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)}/{len(FUND_MAP)} กองทุน): {nav_data}")
    print("-" * 40)
    update_supabase_batch(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")