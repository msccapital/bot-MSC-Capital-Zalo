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
"""
import json
import os
import time
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # không cần màn hình hiển thị, chỉ xuất file ảnh
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

import config
from utils.zalo_client import ZaloBotClient

try:
    # Dùng thẳng module vnstock.explorer.vci — cách Vnstock().stock(...) cũ
    # đã bị chính vnstock thông báo deprecated (ngừng hỗ trợ) từ 31/08/2025.
    from vnstock.explorer.vci import Quote
except ImportError:
    Quote = None

CHART_DIR = "data/charts"


# ---------- Indicator helpers ----------

def wma(series: pd.Series, period: int) -> pd.Series:
    weights = list(range(1, period + 1))
    return series.rolling(period).apply(
        lambda x: (x * weights).sum() / sum(weights), raw=True
    )


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Hợp cả 2 danh sách: WMA_PERIODS dùng để phát tín hiệu, WMA_CHART_PERIODS
    # (có thêm WMA60) chỉ để hiển thị trên biểu đồ cho dễ đối chiếu.
    all_periods = sorted(set(config.WMA_PERIODS) | set(config.WMA_CHART_PERIODS))
    for p in all_periods:
        df[f"wma{p}"] = wma(df["close"], p)
    df["rsi14"] = rsi(df["close"], config.RSI_PERIOD)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(
        df["close"], config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    )
    return df


# ---------- Data fetch ----------

def fetch_price_history(symbol: str, days: int = 300) -> pd.DataFrame:
    if Quote is None:
        raise RuntimeError("Chưa cài vnstock: pip install vnstock")
    df = Quote(symbol=symbol).history(
        start=(datetime.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d"),
        end=datetime.now().strftime("%Y-%m-%d"),
    )
    df = df.rename(columns={"time": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


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


# ---------- Vùng kháng cự / hỗ trợ (đỉnh - đáy cũ) ----------

def find_swing_levels(df: pd.DataFrame, lookback: int = 120, window: int = 5):
    """Tìm các đỉnh/đáy cục bộ (swing high/low) trong `lookback` phiên gần nhất.
    Một điểm là đỉnh/đáy nếu nó là max/min trong cửa sổ +-`window` phiên quanh nó."""
    sub = df.tail(lookback).reset_index(drop=True)
    highs, lows = [], []
    for i in range(window, len(sub) - window):
        seg_h = sub["high"].iloc[i - window: i + window + 1]
        if sub["high"].iloc[i] == seg_h.max():
            highs.append(float(sub["high"].iloc[i]))
        seg_l = sub["low"].iloc[i - window: i + window + 1]
        if sub["low"].iloc[i] == seg_l.min():
            lows.append(float(sub["low"].iloc[i]))
    return sorted(set(highs)), sorted(set(lows))


def nearest_above(entry: float, candidates: list[float]):
    above = [c for c in candidates if c > entry * 1.005]
    return min(above) if above else None


def nearest_below(entry: float, candidates: list[float]):
    below = [c for c in candidates if c < entry * 0.995]
    return max(below) if below else None


def macd_state_text(row) -> str:
    return "tích cực (MACD trên Signal)" if row["macd"] > row["macd_signal"] else "tiêu cực (MACD dưới Signal)"


def rsi_trend_text(df: pd.DataFrame) -> str:
    rsi_now, rsi_prev = df["rsi14"].iloc[-1], df["rsi14"].iloc[-2]
    return "hướng lên" if rsi_now > rsi_prev else "hướng xuống"


# ---------- Biểu đồ ----------

def plot_chart(symbol: str, df: pd.DataFrame, lookback: int = 90) -> str:
    """Vẽ biểu đồ NẾN + khối lượng + WMA20/40/60/200 + RSI14 + MACD,
    trả về đường dẫn file ảnh."""
    sub = df.tail(lookback).copy()
    sub = sub.set_index(pd.DatetimeIndex(sub["date"]))
    sub = sub.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })
    os.makedirs(CHART_DIR, exist_ok=True)

    wma_colors = {20: "#1f77b4", 40: "#ff7f0e", 60: "#2ca02c", 200: "#d62728"}
    add_plots = []
    for p in config.WMA_CHART_PERIODS:
        add_plots.append(mpf.make_addplot(
            sub[f"wma{p}"], panel=0, color=wma_colors.get(p, "gray"), width=1.0,
        ))
    add_plots.append(mpf.make_addplot(
        sub["rsi14"], panel=2, color="purple", width=1.0, ylabel="RSI14",
    ))
    add_plots.append(mpf.make_addplot(
        sub["macd"], panel=3, color="blue", width=1.0, ylabel="MACD",
    ))
    add_plots.append(mpf.make_addplot(
        sub["macd_signal"], panel=3, color="orange", width=1.0,
    ))
    add_plots.append(mpf.make_addplot(
        sub["macd_hist"], panel=3, type="bar", color="gray", alpha=0.5,
    ))

    style = mpf.make_mpf_style(base_mpf_style="yahoo", gridstyle=":", gridcolor="#dddddd")

    path = os.path.join(CHART_DIR, f"{symbol}.png")
    mpf.plot(
        sub,
        type="candle",
        style=style,
        addplot=add_plots,
        volume=True,
        panel_ratios=(3, 1, 1, 1),  # giá, volume, RSI, MACD
        figsize=(10, 9),
        title=f"\n{symbol} — Giá (nến) & WMA20/40/60/200",
        savefig=dict(fname=path, dpi=120),
    )
    return path


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
    df = fetch_price_history(symbol)
    df = compute_indicators(df)
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
        chart_path = plot_chart(symbol, df)

        if last_row["close"] > wma_val_now:
            msg = build_recommendation_message(symbol, "MUA", touched_wma, last_row, df)
            client.send_photo(chart_path, caption=msg)
            del state[symbol]
        elif last_row["close"] < wma_val_now * 0.98:  # thủng rõ ràng
            msg = build_recommendation_message(symbol, "BÁN", touched_wma, last_row, df)
            client.send_photo(chart_path, caption=msg)
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
            chart_path = plot_chart(symbol, df)
            client.send_photo(chart_path, caption=build_watch_message(symbol, touched_wma, last_row))


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
