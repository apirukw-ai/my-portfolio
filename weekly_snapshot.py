import os
from datetime import datetime, timedelta, timezone
import yfinance as yf
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

def get_usd_thb_rate():
    try:
        ticker = yf.Ticker("THB=X")
        hist = ticker.history(period="1d")
        if not hist.empty:
            rate = float(hist['Close'].iloc[-1])
            print(f"💱 อัตราแลกเปลี่ยน USD/THB ปัจจุบัน: ฿{rate:.4f}")
            return rate
    except Exception as e:
        print(f"⚠️ ไม่สามารถดึงเรทอัตราแลกเปลี่ยนได้ ใช้ค่าสำรอง 34.5 THB: {e}")
    return 34.5

def take_weekly_snapshot():
    print("🚀 เริ่มต้นกระบวนการ บันทึก Portfolio Snapshot ประจำสัปดาห์...")

    thai_tz = timezone(timedelta(hours=7))
    today_str = datetime.now(thai_tz).strftime("%Y-%m-%d")
    usd_thb_rate = get_usd_thb_rate()

    # ==========================================
    # 2. ดึงข้อมูลพอร์ตปัจจุบันจาก user_portfolios
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

    # คำนวณยอดรวม THB แยกตามแอป
    app_totals = {}
    for item in items:
        app = (item.get("app_source") or "OTHER").strip().upper()
        val = float(item.get("current_value") or 0)
        
        # 🟢 ถ้าเป็น DIME ให้แปลงจาก USD เป็น THB ก่อนรวมยอด
        if app == "DIME":
            val = val * usd_thb_rate

        app_totals[app] = app_totals.get(app, 0.0) + val

    # ==========================================
    # 3. ดึง Snapshot ล่าสุดก่อนหน้า เพื่อนำมาคำนวณ WoW และ YTD
    # ==========================================
    prev_snapshots = {}
    try:
        prev_res = (
            supabase.table("portfolio_snapshots")
            .select("*")
            .order("snapshot_date", desc=True)
            .limit(10)
            .execute()
        )
        for prev in (prev_res.data or []):
            p_app = prev.get("app_source")
            if p_app and p_app not in prev_snapshots and prev.get("snapshot_date") != today_str:
                prev_snapshots[p_app] = prev
    except Exception as e:
        print(f"⚠️ ดึง snapshot ก่อนหน้าไม่สำเร็จ: {e}")

    # ==========================================
    # 4. บันทึกลงตาราง portfolio_snapshots
    # ==========================================
    print(f"📊 สรุปยอดรวมแยกตามแอป ณ วันที่ {today_str}:")
    snapshot_rows = []
    
    for app, total_thb in app_totals.items():
        prev_item = prev_snapshots.get(app, {})
        prev_val = float(prev_item.get("total_value_thb") or 0)
        
        # คำนวณ WoW Change
        wow_change = round(total_thb - prev_val, 2) if prev_val > 0 else 0.0
        wow_return = round((wow_change / prev_val) * 100, 2) if prev_val > 0 else 0.0
        
        # ดึงค่า % YTD ล่าสุดเดิมมาประคองไว้
        reported_ytd = prev_item.get("reported_ytd_pct")
        if reported_ytd is not None:
            reported_ytd = round(float(reported_ytd) + wow_return, 2)

        print(f"   • {app}: ฿{total_thb:,.2f} (WoW: {wow_return:+.2f}%)")

        row_payload = {
            "snapshot_date": today_str,
            "app_source": app,
            "total_value_thb": round(total_thb, 2),
            "wow_change_thb": wow_change,
            "wow_return_pct": wow_return,
            "reported_ytd_pct": reported_ytd
        }
        
        # คัดลอกค่าประวัติอื่นจากของเดิม (ถ้ามี)
        if prev_item.get("reported_5y_pct") is not None:
            row_payload["reported_5y_pct"] = prev_item.get("reported_5y_pct")
        if prev_item.get("reported_since_inception_pct") is not None:
            row_payload["reported_since_inception_pct"] = prev_item.get("reported_since_inception_pct")

        snapshot_rows.append(row_payload)

    try:
        supabase.table("portfolio_snapshots").insert(snapshot_rows).execute()
        print(f"💾 บันทึก Snapshot ลงตาราง portfolio_snapshots สำเร็จ {len(snapshot_rows)} รายการ")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการบันทึก snapshot: {e}")

if __name__ == "__main__":
    take_weekly_snapshot()
    print("✨ ทำงานเสร็จสิ้น!")