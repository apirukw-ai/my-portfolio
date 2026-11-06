import os
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

# ==========================================
# 1. ตั้งค่าการเชื่อมต่อ Supabase
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY ใน Environment Variables")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def take_weekly_snapshot():
    print("🚀 เริ่มต้นกระบวนการ บันทึก Portfolio Snapshot ประจำสัปดาห์...")

    thai_tz = timezone(timedelta(hours=7))
    today_str = datetime.now(thai_tz).strftime("%Y-%m-%d")

    # ==========================================
    # 2. ดึงข้อมูลพอร์ตทั้งหมดจาก user_portfolios
    # ==========================================
    try:
        res = supabase.table("user_portfolios").select("app_source, current_value").execute()
        items = res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก user_portfolios ได้: {e}")
        return

    if not items:
        print("⚠️ ไม่พบข้อมูลในตาราง user_portfolios")
        return

    # ==========================================
    # 3. รวมมูลค่าพอร์ตแยกตาม app_source (GPF, DIME, SCB, MFC)
    # ==========================================
    app_totals = {}
    for item in items:
        app = (item.get("app_source") or "OTHER").strip().upper()
        val = float(item.get("current_value") or 0)
        app_totals[app] = app_totals.get(app, 0.0) + val

    print(f"📊 สรุปยอดรวมแยกตามแอป ณ วันที่ {today_str}:")
    snapshot_rows = []
    for app, total in app_totals.items():
        print(f"   • {app}: ฿{total:,.2f}")
        snapshot_rows.append({
            "snapshot_date": today_str,
            "app_source": app,
            "total_value_thb": round(total, 2)
        })

    # ==========================================
    # 4. บันทึกลงตาราง portfolio_snapshots
    # ==========================================
    try:
        supabase.table("portfolio_snapshots").insert(snapshot_rows).execute()
        print(f"💾 บันทึก Snapshot ลงตาราง portfolio_snapshots สำเร็จทั้งหมด {len(snapshot_rows)} รายการ")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการบันทึก snapshot: {e}")

if __name__ == "__main__":
    take_weekly_snapshot()
    print("✨ ทำงานเสร็จสิ้น!")