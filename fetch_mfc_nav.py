import os
import re
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from supabase import Client, create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get(
    "SUPABASE_KEY"
)

if not SUPABASE_URL or not SUPABASE_KEY:
    print(
        "❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน Environment"
        " Variables"
    )
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

FUND_MAP = {
    "IGOLD-G": ["IGOLD-G", "IGOLD"],
    "MGTECH": ["MGTECH", "MTECH", "M-TECH"],
    "M-EM": ["M-EM"],
    "MEURO-G": ["MEURO-G", "MEURO"],
    "MGFPVD": ["MGFPVD"],
    "M-ASIA": ["M-ASIA", "MASIA"],
}


def fetch_mfc_nav():
    url = "https://mfcfund.com/funds/filtersets/prices/"
    nav_results = {}

    print(f"📡 กำลังเปิด Headless Browser เพื่อดึงข้อมูลจาก: {url}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)

                # 🛠️ รอให้ตารางแสดงผล
                page.wait_for_selector("tr", timeout=15000)
                page.wait_for_timeout(5000)  # หน่วงเวลาเพิ่มเติมสำหรับ JS render

                html_content = page.content()

            finally:
                browser.close()

        soup = BeautifulSoup(html_content, "html.parser")
        rows = soup.find_all("tr")
        print(f"ℹ️ พบแถวตารางทั้งหมด: {len(rows)} แถว")

        for row in rows:
            cells = row.find_all("td")

            if len(cells) < 8:
                continue

            fund_text = cells[1].get_text(" ", strip=True).upper()

            for asset_name, aliases in FUND_MAP.items():
                if asset_name in nav_results:
                    continue

                aliases_upper = [a.upper() for a in aliases]

                for alias in aliases_upper:
                    if alias in fund_text:
                        try:
                            nav_val = float(
                                cells[4].get_text(strip=True).replace(",", "")
                            )
                            nav_results[asset_name] = nav_val
                            print(
                                f"✅ {asset_name} <- {alias} -> NAV {nav_val}"
                            )
                        except Exception as e:
                            print(f"⚠️ {alias}: {e}")

                        break

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
        db_res = (
            supabase.table("user_portfolios")
            .select("*")
            .ilike("app_source", "MFC")
            .execute()
        )
        mfc_items = db_res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก Supabase ได้: {e}")
        return

    batch_payload = []
    for item in mfc_items:
        asset_name = item.get("asset_name", "").strip()
        asset_code = item.get("asset_code", "").strip()

        # ตรวจสอบทั้ง asset_name และ asset_code
        nav_val = nav_data.get(asset_name) or nav_data.get(asset_code)

        if nav_val:
            units = float(item.get("units") or 0)

            updated_item = item.copy()
            updated_item.update({
                "current_nav": round(nav_val, 4),
                "current_value": round(units * nav_val, 4),
                "nav_date": today_str,
                "updated_at": now_thai.isoformat(),
            })
            batch_payload.append(updated_item)

    if batch_payload:
        try:
            supabase.table("user_portfolios").upsert(batch_payload).execute()
            print(
                "💾 อัปเดต Supabase แบบ Batch สำเร็จทั้งหมด"
                f" {len(batch_payload)} รายการ"
            )
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการอัปเดตแบบ Batch: {e}")
    else:
        print("⚠️ ไม่พบข้อมูล asset_name / asset_code ใน Supabase ที่จับคู่ตรงกัน")


if __name__ == "__main__":
    print("🚀 เริ่มต้นกระบวนการ Auto Update NAV (Playwright - MFC)...")
    nav_data = fetch_mfc_nav()
    print("-" * 40)
    print(
        f"📊 สรุปข้อมูลที่ดึงได้ ({len(nav_data)}/{len(FUND_MAP)} กองทุน):"
        f" {nav_data}"
    )
    print("-" * 40)
    update_supabase_batch(nav_data)
    print("✨ ทำงานเสร็จสิ้น!")