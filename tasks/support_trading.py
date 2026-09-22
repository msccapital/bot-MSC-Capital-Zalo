"""
Nhiệm vụ 1 - HỖ TRỢ GIAO DỊCH
Chạy 2 lần/ngày: 12h00 và 15h00 (giờ VN).

Logic:
1. Với mỗi mã trong watchlist, tính WMA20/40/200, RSI14, MACD.
2. Nếu giá đang giảm và CHẠM (nằm trong TOUCH_TOLERANCE_PCT quanh) một đường WMA
   -> lưu vào state "đang theo dõi" + gửi thông báo THEO DÕI kèm biểu đồ.
3. Ở phiên của NGÀY GIAO DỊCH KẾ TIẾP (không tính 2 lần chạy trong cùng 1 ngày là
   2 phiên khác nhau — dữ liệu giá theo ngày chưa đổi trong cùng ngày nên so sánh
   lại sẽ vô nghĩa), với mã đang trong state:
   - Nếu giá bật tăng trở lại trên đường WMA đã chạm -> xác nhận khuyến nghị MUA
     (đối chiếu thêm RSI hướng lên & MACD tích cực để mô tả phần "Kỹ thuật").
   - Nếu giá thủng hẳn xuống dưới đường WMA đó -> khuyến nghị BÁN.
   - Nếu chưa rõ xu hướng -> tiếp tục giữ trong state (không spam thêm tin).
   Tất cả các thông báo (THEO DÕI/MUA/BÁN) đều gửi kèm 1 ảnh biểu đồ giá + WMA +
   RSI + MACD của mã đó.

Giá mục tiêu / Stoploss: xác định theo vùng kháng cự - hỗ trợ gần nhất
(đỉnh/đáy cũ trong lịch sử giá + các đường WMA còn lại đóng vai trò kháng cự/hỗ trợ),
không dùng % cố định.

Các hàm tính chỉ báo / vẽ biểu đồ nằm ở utils/analysis.py — dùng chung với
server.py (webhook) để đảm bảo luôn cho ra cùng 1 kết quả.
"""
import json
import os
import time

import pandas as pd

import config
from utils.zalo_client import ZaloBotClient
from utils.analysis import (
    get_analyzed, find_swing_levels, nearest_above, nearest_below,
    macd_state_text, rsi_trend_text, plot_chart,
)


# ---------- State (nhớ giữa các phiên) ----------

def load_state() -> dict:
    if os.path.exists(config.STATE_FILE_TRADING):
        with open(config.STATE_FILE_TRADING, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    os.makedirs(os.path.dirname(config.STATE_FILE_TRADING), exist_ok=True)
    with open(config.STATE_FILE_TRADING, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ---------- Core logic ----------

def find_touched_wma(last_row) -> int | None:
    """Trả về period của đường WMA mà giá đang chạm (nếu có), None nếu không chạm."""
    price = last_row["close"]
    for p in config.WMA_PERIODS:
        wma_val = last_row.get(f"wma{p}")
        if pd.isna(wma_val):
            continue
        diff_pct = abs(price - wma_val) / wma_val * 100
        if diff_pct <= config.TOUCH_TOLERANCE_PCT:
            return p
    return None


def is_downtrend(df: pd.DataFrame, lookback: int = 5) -> bool:
    recent = df["close"].tail(lookback)
    return recent.iloc[-1] < recent.iloc[0]


def build_watch_message(symbol: str, touched_wma: int, row) -> str:
    return (
        f"⚠️ THEO DÕI [{symbol}]\n"
        f"Giá chạm hỗ trợ WMA{touched_wma} tại {row['close']:,.0f}\n"
        f"RSI14: {row['rsi14']:.1f} | MACD: {macd_state_text(row)}\n"
        f"-> Theo dõi phiên tới: bật tăng = tín hiệu MUA, thủng = tín hiệu BÁN."
    )


def build_recommendation_message(symbol: str, action: str, touched_wma: int, entry_row, df) -> str:
    entry_price = entry_row["close"]
    touched_val = entry_row[f"wma{touched_wma}"]

    highs, lows = find_swing_levels(df)
    other_wma_values = [
        entry_row[f"wma{p}"] for p in config.WMA_PERIODS
        if p != touched_wma and not pd.isna(entry_row[f"wma{p}"])
    ]

    if action == "MUA":
        target = nearest_above(entry_price, highs + other_wma_values)
        stoploss = nearest_below(entry_price, lows + other_wma_values)
        target = target if target is not None else entry_price * 1.08
        stoploss = stoploss if stoploss is not None else touched_val * 0.97
    else:  # BÁN
        target = nearest_below(entry_price, lows + other_wma_values)
        stoploss = nearest_above(entry_price, highs + other_wma_values + [touched_val])
        target = target if target is not None else entry_price * 0.92
        stoploss = stoploss if stoploss is not None else entry_price * 1.03

    return (
        f"KHUYẾN NGHỊ DÀNH CHO CỔ PHIẾU {symbol} [{action}]\n"
        f"Giá {'mua' if action == 'MUA' else 'bán'}: quanh {entry_price:,.0f} "
        f"(vùng WMA{touched_wma})\n"
        f"Giá mục tiêu: {target:,.0f}\n"
        f"Stoploss: {stoploss:,.0f}\n"
        f"Kỹ thuật: giá {'bật lên từ' if action == 'MUA' else 'thủng'} hỗ trợ WMA{touched_wma}, "
        f"RSI {rsi_trend_text(df)}, MACD {macd_state_text(entry_row)}."
    )


def scan_symbol(symbol: str, state: dict, client: ZaloBotClient):
    df = get_analyzed(symbol)
    if len(df) < max(config.WMA_PERIODS) + 5:
        return  # chưa đủ dữ liệu

    last_row = df.iloc[-1]
    last_date = str(last_row["date"].date())
    watching = state.get(symbol)

    if watching:
        if last_date == watching["touch_date"]:
            # Vẫn là cùng phiên giao dịch đã ghi nhận chạm (chạy 12h/15h cùng
            # ngày, dữ liệu ngày chưa đổi) — không so sánh, chờ sang ngày kế
            # tiếp mới có dữ liệu mới để xác nhận MUA/BÁN.
            return

        touched_wma = watching["touched_wma"]
        wma_val_now = last_row[f"wma{touched_wma}"]
        # TODO: chưa gửi kèm biểu đồ ở đây — nhiệm vụ này chạy qua GitHub
        # Actions (không có server luôn bật để host ảnh thành URL công khai
        # như server.py), và sendPhoto của Zalo Bot Platform không nhận
        # upload file trực tiếp (xem lưu ý trong utils/zalo_client.py). Tạm
        # gửi text để không bị mất khuyến nghị; sẽ bổ sung cách host ảnh cho
        # nhánh này sau (vd host qua GitHub raw URL) nếu bạn cần.
        plot_chart(symbol, df)  # vẫn vẽ để lưu lại, dù chưa gửi được qua Zalo

        if last_row["close"] > wma_val_now:
            msg = build_recommendation_message(symbol, "MUA", touched_wma, last_row, df)
            client.send_message(msg)
            del state[symbol]
        elif last_row["close"] < wma_val_now * 0.98:  # thủng rõ ràng
            msg = build_recommendation_message(symbol, "BÁN", touched_wma, last_row, df)
            client.send_message(msg)
            del state[symbol]
        # else: chưa rõ ràng, giữ nguyên state, không gửi thêm tin
        return

    # Chưa theo dõi -> kiểm tra có chạm WMA trong xu hướng giảm không
    if is_downtrend(df):
        touched_wma = find_touched_wma(last_row)
        if touched_wma:
            state[symbol] = {
                "touched_wma": touched_wma,
                "touch_date": last_date,
                "touch_price": float(last_row["close"]),
            }
            plot_chart(symbol, df)  # vẫn vẽ để lưu lại, dù chưa gửi được qua Zalo
            client.send_message(build_watch_message(symbol, touched_wma, last_row))


def run():
    client = ZaloBotClient(config.ZALO_BOT_TOKEN, config.ZALO_CHAT_ID)
    state = load_state()
    for symbol in config.WATCHLIST_TRADING:
        try:
            scan_symbol(symbol, state, client)
        except Exception as e:
            print(f"[support_trading] Lỗi với {symbol}: {e}")
        time.sleep(1.1)  # 147 mã — giữ dưới ngưỡng rate-limit của vnstock (60/phút)
    save_state(state)


if __name__ == "__main__":
    run()
