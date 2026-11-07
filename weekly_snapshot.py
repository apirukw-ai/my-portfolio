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
    # 2. ดึงข้อมูล current_value และ total_cost จาก user_portfolios
    # ==========================================
    try:
        res = supabase.table("user_portfolios").select("app_source, current_value, total_cost").execute()
        items = res.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก user_portfolios ได้: {e}")
        return

    if not items:
        print("⚠️ ไม่พบข้อมูลในตาราง user_portfolios")
        return

    # รวมยอด current_value และ total_cost แยกตาม app_source
    app_data = {}
    for item in items:
        app = (item.get("app_source") or "OTHER").strip().upper()
        c_val = float(item.get("current_value") or 0)
        c_cost = float(item.get("total_cost") or 0)

        if app not in app_data:
            app_data[app] = {"val": 0.0, "cost": 0.0}

        app_data[app]["val"] += c_val
        app_data[app]["cost"] += c_cost

    # ==========================================
    # 3. ดึง Snapshot ล่าสุดก่อนหน้า เพื่อนำมาคำนวณ WoW และดึงค่าเดิม
    # ==========================================
    prev_snapshots = {}
    try:
        prev_res = (
            supabase.table("portfolio_snapshots")
            .select("*")
            .order("snapshot_date", desc=True)
            .limit(20)
            .execute()
        )
        for prev in (prev_res.data or []):
            p_app = prev.get("app_source")
            if p_app and p_app not in prev_snapshots and prev.get("snapshot_date") != today_str:
                prev_snapshots[p_app] = prev
    except Exception as e:
        print(f"⚠️ ดึง snapshot ก่อนหน้าไม่สำเร็จ: {e}")

    # ==========================================
    # 4. จัดเตรียมข้อมูลแยกตามเงื่อนไขแอป และ บันทึกลง portfolio_snapshots
    # ==========================================
    print(f"📊 สรุปยอดรวมและผลตอบแทนแยกตามแอป ณ วันที่ {today_str}:")
    snapshot_rows = []

    for app, data in app_data.items():
        raw_val = data["val"]
        total_cost = data["cost"]

        # แปลงเฉพาะ DIME เป็น THB สำหรับบันทึกยอดเงินรวม
        total_thb = raw_val * usd_thb_rate if app == "DIME" else raw_val

        # คำนวณ WoW (มูลค่าเปลี่ยนแปลงเทียบสัปดาห์ก่อน)
        prev_item = prev_snapshots.get(app, {})
        prev_val = float(prev_item.get("total_value_thb") or 0)
        wow_change = round(total_thb - prev_val, 2) if prev_val > 0 else 0.0
        wow_return = round((wow_change / prev_val) * 100, 2) if prev_val > 0 else 0.0

        row_payload = {
            "snapshot_date": today_str,
            "app_source": app,
            "total_value_thb": round(total_thb, 2),
            "wow_change_thb": wow_change,
            "wow_return_pct": wow_return,
        }

        # 🟢 1. เคส GPF: เว้น reported_ytd_pct เป็น None เพื่อแสดง 5 ปีย้อนหลัง / ตั้งแต่เริ่มส่ง
        if app == "GPF":
            row_payload["reported_ytd_pct"] = None
            row_payload["reported_5y_pct"] = prev_item.get("reported_5y_pct")
            row_payload["reported_since_inception_pct"] = prev_item.get("reported_since_inception_pct")
            print(f"   • GPF: มูลค่า ฿{total_thb:,.2f} | (5ปี: {row_payload['reported_5y_pct']}%, เริ่มส่ง: {row_payload['reported_since_inception_pct']}%)")

        # 🟢 2. เคส MFC: ดึงค่า YTD เดิมมาใส่ล่วงหน้า รอพิมพ์อัปเดต YTD ใหม่เองใน Supabase
        elif app == "MFC":
            row_payload["reported_ytd_pct"] = prev_item.get("reported_ytd_pct")
            row_payload["reported_5y_pct"] = prev_item.get("reported_5y_pct")
            row_payload["reported_since_inception_pct"] = prev_item.get("reported_since_inception_pct")
            print(f"   • MFC: มูลค่า ฿{total_thb:,.2f} | YTD สแตนด์บาย: {row_payload['reported_ytd_pct']}% (รอพิมพ์อัปเดตใน Supabase) | WoW: {wow_return:+.2f}%")

        # 🟢 3. เคส SCB & DIME: คำนวณ % กำไร/ขาดทุนสะสมจริง อัตโนมัติ
        else:
            cum_pnl_pct = round(((raw_val - total_cost) / total_cost) * 100, 2) if total_cost > 0 else 0.0
            row_payload["reported_ytd_pct"] = cum_pnl_pct
            row_payload["reported_5y_pct"] = None
            row_payload["reported_since_inception_pct"] = None

            prev_ytd = prev_item.get("reported_ytd_pct")
            ytd_diff_str = f" ({cum_pnl_pct - float(prev_ytd):+.2f}%)" if prev_ytd is not None else ""
            print(f"   • {app}: มูลค่า ฿{total_thb:,.2f} | กำไรสะสม {cum_pnl_pct:+.2f}%{ytd_diff_str} | WoW: {wow_return:+.2f}%")

        snapshot_rows.append(row_payload)

    try:
        supabase.table("portfolio_snapshots").insert(snapshot_rows).execute()
        print(f"💾 บันทึก Snapshot ลงตาราง portfolio_snapshots สำเร็จ {len(snapshot_rows)} รายการ")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการบันทึก snapshot: {e}")

if __name__ == "__main__":
    take_weekly_snapshot()
    print("✨ ทำงานเสร็จสิ้น!")