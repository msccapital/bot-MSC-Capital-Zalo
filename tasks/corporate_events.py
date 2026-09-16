"""
Nhiệm vụ 3 - THÔNG TIN SỰ KIỆN
Chạy 1 lần/ngày lúc 14h00 (giờ VN).

Luồng xử lý:
1. Duyệt qua danh mục theo dõi của bạn (config.WATCHLIST_EVENTS — 147 mã từ file
   DANH_MUC_THEO_DOI, xem watchlist.py).
2. Với mỗi mã, lấy lịch sự kiện (events()) và lọc các sự kiện có ngày công bố = hôm nay,
   thuộc loại cổ tức / phát hành thêm.
3. Với sự kiện mới (chưa gửi trước đó, theo state dedupe), tính giá tham chiếu sau chia
   và gửi thông báo qua Zalo.

LƯU Ý VỀ SCHEMA:
- Tên cột trả về từ ref.company(symbol).events() cần được xác nhận thực tế khi chạy
  thử (title/type/ratio/record_date... có thể khác tên). Code dưới dùng .get() với
  nhiều khả năng tên cột để không vỡ nếu thiếu field, nhưng bạn nên in thử df_events
  1 lần để đối chiếu và chỉnh lại cho khớp.
"""
import json
import os
import time
from datetime import date

import config
from utils.ex_dividend import calc_ex_dividend_price
from utils.zalo_client import ZaloBotClient

try:
    from vnstock_data import Reference
except ImportError:
    Reference = None

try:
    from vnstock import Vnstock
except ImportError:
    Vnstock = None


def load_seen_state() -> set:
    if os.path.exists(config.STATE_FILE_EVENTS):
        with open(config.STATE_FILE_EVENTS, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_state(seen: set):
    os.makedirs(os.path.dirname(config.STATE_FILE_EVENTS), exist_ok=True)
    with open(config.STATE_FILE_EVENTS, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def get_last_close(symbol: str) -> float | None:
    if Vnstock is None:
        return None
    try:
        stock = Vnstock().stock(symbol=symbol, source="VCI")
        df = stock.quote.history(
            start=str(date.today().replace(day=1)), end=str(date.today())
        )
        if len(df):
            return float(df.iloc[-1]["close"])
    except Exception:
        return None
    return None


def format_event_message(symbol: str, exchange: str, event: dict, close_price: float) -> str:
    event_type = (event.get("event_type") or event.get("type") or "").lower()
    ratio = float(event.get("ratio", 0) or 0)  # kỳ vọng dạng thập phân, vd 0.10 = 10%
    issue_price = float(event.get("issue_price", 0) or 0)
    exright_date = event.get("exright_date") or event.get("gdkhq_date") or "?"
    record_date = event.get("record_date") or "?"

    lines = [f"{event.get('company_name', symbol)} [{exchange}: {symbol}] - "]

    if "tiền mặt" in event_type or "cash" in event_type:
        lines[0] += "Chia cổ tức tiền mặt"
        adjusted = calc_ex_dividend_price(close_price, rate_cash_div=ratio)
        lines += [
            "Hình thức: tiền mặt",
            f"Tỷ lệ chia: {ratio * 100:.0f}%",
            f"Ngày GDKHQ: {exright_date}",
            f"Ngày đăng ký cuối cùng: {record_date}",
            f"Giá sau chia: {adjusted:,.0f}",
        ]
    elif "cổ phiếu" in event_type or "stock" in event_type:
        lines[0] += "Chia cổ phiếu thưởng"
        adjusted = calc_ex_dividend_price(close_price, rate_stock_div=ratio)
        lines += [
            "Hình thức: cổ phiếu",
            f"Tỷ lệ chia: {ratio * 100:.0f}%",
            f"Ngày GDKHQ: {exright_date}",
            f"Ngày đăng ký cuối cùng: {record_date}",
            f"Giá sau chia: {adjusted:,.0f}",
        ]
    else:  # phát hành thêm
        lines[0] += "Phát hành thêm cổ phiếu"
        adjusted = calc_ex_dividend_price(close_price, rate_issue=ratio, price_issue=issue_price)
        lines += [
            f"Tỷ lệ phát hành: {ratio * 100:.0f}%",
            f"Giá phát hành: {issue_price:,.0f}",
            f"Ngày GDKHQ: {exright_date}",
            f"Ngày đăng ký cuối cùng: {record_date}",
            f"Giá sau phát hành: {adjusted:,.0f}",
        ]
    return "\n".join(lines)


def run():
    if Reference is None:
        raise RuntimeError("Chưa cài vnstock_data")

    client = ZaloBotClient(config.ZALO_BOT_TOKEN, config.ZALO_CHAT_ID)
    seen = load_seen_state()
    today_str = str(date.today())

    symbols = config.WATCHLIST_EVENTS
    ref = Reference()

    for symbol in symbols:
        try:
            df_events = ref.company(symbol).events()
        except Exception:
            continue  # mã lỗi/không có dữ liệu sự kiện, bỏ qua

        if df_events is None or len(df_events) == 0:
            continue

        for _, row in df_events.iterrows():
            event = row.to_dict()
            announce_date = str(event.get("announce_date") or event.get("public_date") or "")
            if not announce_date.startswith(today_str):
                continue

            event_key = f"{symbol}:{event.get('event_type', '')}:{event.get('exright_date', '')}"
            if event_key in seen:
                continue

            close_price = get_last_close(symbol)
            if close_price is None:
                continue

            msg = format_event_message(symbol, event.get("exchange", "HOSE"), event, close_price)
            client.send_message(msg)
            seen.add(event_key)

        time.sleep(0.3)  # tránh dồn dập request khi quét toàn sàn

    save_seen_state(seen)


if __name__ == "__main__":
    run()
