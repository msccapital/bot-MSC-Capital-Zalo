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
- Cột thực tế trả về từ Company(symbol).events() (theo tài liệu vnstock công khai):
  event_title, en__event_title, public_date (ngày công bố), record_date
  (ngày đăng ký cuối cùng), exright_date (ngày GDKHQ), event_list_name (nhóm sự
  kiện, vd "Phát hành cổ phiếu"). KHÔNG có cột tỷ lệ/giá phát hành riêng — tỷ lệ
  và giá phát hành (nếu có) nằm trong câu chữ của event_title (vd "...tỷ lệ 10%"),
  nên code bên dưới tự dò bằng regex từ event_title. Nếu vnstock đổi format câu
  chữ, phần dò tỷ lệ có thể cần chỉnh lại — chạy thử 1 lần và đối chiếu.
- event_list_name "Phát hành cổ phiếu" (Share Issue) dùng chung cho CẢ cổ phiếu
  thưởng lẫn phát hành thêm/quyền mua — code phân loại lại dựa vào từ khoá trong
  event_title (ví dụ "trả cổ tức" = thưởng cổ phiếu, "chào bán"/"quyền mua" =
  phát hành thêm) vì vnstock không tách 2 loại này thành field riêng.
"""
import json
import os
import re
import time
from datetime import date

import config
from utils.ex_dividend import calc_ex_dividend_price
from utils.zalo_client import ZaloBotClient

try:
    from vnstock.explorer.vci import Company, Quote
except ImportError:
    Company = None
    Quote = None


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
    if Quote is None:
        return None
    try:
        df = Quote(symbol=symbol).history(
            start=str(date.today().replace(day=1)), end=str(date.today())
        )
        if len(df):
            return float(df.iloc[-1]["close"])
    except Exception:
        return None
    return None


_RATIO_RE = re.compile(r"tỷ lệ\s*([\d]+[.,]?[\d]*)\s*%", re.IGNORECASE)
_ISSUE_PRICE_RE = re.compile(r"giá\s*(?:phát hành|chào bán)\D{0,10}([\d.,]+)\s*(?:đ|vnd)?", re.IGNORECASE)


def parse_ratio_from_title(title: str) -> float:
    m = _RATIO_RE.search(title or "")
    if not m:
        return 0.0
    return float(m.group(1).replace(",", ".")) / 100


def parse_issue_price_from_title(title: str) -> float:
    m = _ISSUE_PRICE_RE.search(title or "")
    if not m:
        return 0.0
    return float(m.group(1).replace(".", "").replace(",", ""))


def classify_event(title: str) -> str:
    t = (title or "").lower()
    if "cổ tức" in t and ("tiền" in t or "tiền mặt" in t):
        return "cash"
    if "trả cổ tức" in t and "cổ phiếu" in t:
        return "stock_div"  # cổ phiếu thưởng (trả cổ tức bằng cổ phiếu)
    if "chào bán" in t or "quyền mua" in t or "phát hành thêm" in t:
        return "rights_issue"
    if "cổ phiếu" in t:
        return "stock_div"
    return "cash"  # mặc định, ít gặp nhất trong 3 loại nên đặt cuối


def format_event_message(symbol: str, event: dict, close_price: float) -> str:
    title = event.get("event_title") or ""
    exright_date = event.get("exright_date") or "?"
    record_date = event.get("record_date") or "?"
    ratio = parse_ratio_from_title(title)

    kind = classify_event(title)
    lines = [f"{symbol} - {title}"]

    if kind == "cash":
        adjusted = calc_ex_dividend_price(close_price, rate_cash_div=ratio)
        lines += [
            "Hình thức: tiền mặt",
            f"Tỷ lệ chia: {ratio * 100:.2f}%" if ratio else "Tỷ lệ chia: (xem chi tiết trong tiêu đề)",
            f"Ngày GDKHQ: {exright_date}",
            f"Ngày đăng ký cuối cùng: {record_date}",
            f"Giá sau chia: {adjusted:,.0f}" if ratio else "Giá sau chia: (chưa dò được tỷ lệ từ tiêu đề)",
        ]
    elif kind == "stock_div":
        adjusted = calc_ex_dividend_price(close_price, rate_stock_div=ratio)
        lines += [
            "Hình thức: cổ phiếu",
            f"Tỷ lệ chia: {ratio * 100:.2f}%" if ratio else "Tỷ lệ chia: (xem chi tiết trong tiêu đề)",
            f"Ngày GDKHQ: {exright_date}",
            f"Ngày đăng ký cuối cùng: {record_date}",
            f"Giá sau chia: {adjusted:,.0f}" if ratio else "Giá sau chia: (chưa dò được tỷ lệ từ tiêu đề)",
        ]
    else:  # rights_issue
        issue_price = parse_issue_price_from_title(title)
        adjusted = calc_ex_dividend_price(close_price, rate_issue=ratio, price_issue=issue_price)
        lines += [
            f"Tỷ lệ phát hành: {ratio * 100:.2f}%" if ratio else "Tỷ lệ phát hành: (xem chi tiết trong tiêu đề)",
            f"Giá phát hành: {issue_price:,.0f}" if issue_price else "Giá phát hành: (xem chi tiết trong tiêu đề)",
            f"Ngày GDKHQ: {exright_date}",
            f"Ngày đăng ký cuối cùng: {record_date}",
            f"Giá sau phát hành: {adjusted:,.0f}" if (ratio or issue_price) else "Giá sau phát hành: (chưa dò được từ tiêu đề)",
        ]
    return "\n".join(lines)


def run():
    if Company is None:
        raise RuntimeError("Chưa cài vnstock")

    client = ZaloBotClient(config.ZALO_BOT_TOKEN, config.ZALO_CHAT_ID)
    seen = load_seen_state()
    today_str = str(date.today())

    symbols = config.WATCHLIST_EVENTS

    for symbol in symbols:
        try:
            df_events = Company(symbol=symbol).events()
        except Exception as ex:
            print(f"[corporate_events] Lỗi lấy events {symbol}: {ex}")
            continue  # mã lỗi/không có dữ liệu sự kiện, bỏ qua

        if df_events is None or len(df_events) == 0:
            continue

        for _, row in df_events.iterrows():
            event = row.to_dict()
            public_date = str(event.get("public_date") or "")
            if not public_date.startswith(today_str):
                continue

            event_key = f"{symbol}:{event.get('exright_date', '')}:{event.get('event_title', '')}"
            if event_key in seen:
                continue

            close_price = get_last_close(symbol)
            if close_price is None:
                continue

            msg = format_event_message(symbol, event, close_price)
            client.send_message(msg)
            seen.add(event_key)

        time.sleep(1.1)  # 147 mã — giữ dưới ngưỡng rate-limit của vnstock (60/phút)

    save_seen_state(seen)


if __name__ == "__main__":
    run()
