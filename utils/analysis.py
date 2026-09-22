"""
Các hàm phân tích kỹ thuật + vẽ biểu đồ DÙNG CHUNG cho:
- tasks/support_trading.py (chạy theo lịch qua GitHub Actions)
- server.py (webhook, phản hồi tức thời khi người dùng gõ lệnh trong Zalo)

Tách riêng ra đây để 2 nơi luôn cho ra cùng 1 kết quả tính toán, không lệch nhau.
"""
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # không cần màn hình hiển thị, chỉ xuất file ảnh
import mplfinance as mpf
import pandas as pd

import config

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


def get_analyzed(symbol: str, days: int = 300) -> pd.DataFrame:
    """Lấy giá + tính sẵn chỉ báo, dùng chung 1 chỗ cho mọi nơi cần dữ liệu mã này."""
    df = fetch_price_history(symbol, days=days)
    return compute_indicators(df)


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


def build_snapshot_caption(symbol: str, df: pd.DataFrame) -> str:
    """Chú thích ngắn kèm ảnh khi người dùng chủ động gõ lệnh xem biểu đồ
    (khác với tin cảnh báo THEO DÕI/MUA/BÁN tự động của Nhiệm vụ 1)."""
    row = df.iloc[-1]
    return (
        f"📊 {symbol} — phiên {row['date'].date()}\n"
        f"Giá đóng cửa: {row['close']:,.0f}\n"
        f"WMA20: {row['wma20']:,.0f} | WMA40: {row['wma40']:,.0f} | "
        f"WMA60: {row['wma60']:,.0f} | WMA200: {row['wma200']:,.0f}\n"
        f"RSI14: {row['rsi14']:.1f} | MACD: {macd_state_text(row)}"
    )
