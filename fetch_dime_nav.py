import os
from supabase import create_client, Client
import yfinance as yf

# 1. เชื่อมต่อ Supabase
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("❌ Error: กรุณาตั้งค่า SUPABASE_URL และ SUPABASE_KEY")
    exit(1)

supabase: Client = create_client(url, key)

def update_dime_stocks():
    print("🚀 เริ่มต้นอัปเดตราคาหุ้น US (DIME)...")
    
    # 🟢 แก้ไขจุดที่ 1: ดึงเฉพาะรายการที่เป็นแอป DIME และเลือก units มาด้วย
    try:
        response = (
            supabase.table("user_portfolios")
            .select("id, asset_name, asset_code, units")
            .ilike("app_source", "DIME")
            .execute()
        )
        portfolios = response.data or []
    except Exception as e:
        print(f"❌ ไม่สามารถดึงข้อมูลจาก Supabase ได้: {e}")
        return

    print(f"📦 พบรายการหุ้น DIME ในระบบทั้งหมด {len(portfolios)} รายการ")

    for item in portfolios:
        # ใช้ asset_code หรือ asset_name เป็น Ticker Symbol (เช่น NVDA, GOOGL, JPM)
        ticker_symbol = (item.get("asset_code") or item.get("asset_name") or "").strip()
        units = float(item.get("units") or 0)
        
        if not ticker_symbol:
            continue

        try:
            # ดึงราคาประวัติย้อนหลัง 5 วันทำการจาก yfinance
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="5d")

            if len(hist) >= 2:
                current_price = float(hist['Close'].iloc[-1]) # ราคาปิดวันล่าสุด
                prev_price = float(hist['Close'].iloc[-2])    # ราคาปิดวันก่อนหน้า
                
                # 🟢 แก้ไขจุดที่ 2: คำนวณ current_value (units * current_price) เพิ่มเข้าไปด้วย
                update_payload = {
                    "current_nav": round(current_price, 4),
                    "prev_nav": round(prev_price, 4),
                    "current_value": round(units * current_price, 4)
                }

                supabase.table("user_portfolios").update(update_payload).eq("id", item['id']).execute()

                print(f"✅ {ticker_symbol}: Price=${current_price:.4f} | Value=${units * current_price:,.2f}")
            else:
                print(f"⚠️ {ticker_symbol}: ไม่พบข้อมูลราคาประวัติย้อนหลังพอสำหรับการอัปเดต")

        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการอัปเดต {ticker_symbol}: {e}")

if __name__ == "__main__":
    update_dime_stocks()
    print("✨ ทำงานเสร็จสิ้น!")