"""
Cấu hình trung tâm cho Zalo Invest Bot.
Token/chat_id thật sự lấy từ biến môi trường (GitHub Secrets khi deploy),
KHÔNG hardcode ở đây.
"""
import os

# ---- Zalo Bot Platform ----
ZALO_BOT_TOKEN = os.environ.get("ZALO_BOT_TOKEN", "")
ZALO_CHAT_ID = os.environ.get("ZALO_CHAT_ID", "")  # group chat_id để đẩy tin

# ---- Danh mục theo dõi chung (từ file DANH_MUC_THEO_DOI của bạn) ----
# Dùng chung cho Nhiệm vụ 1 (tín hiệu kỹ thuật) và Nhiệm vụ 3 (lịch sự kiện).
# Cập nhật file watchlist.py khi danh mục thay đổi, không cần sửa các file khác.
from watchlist import WATCHLIST

WATCHLIST_TRADING = WATCHLIST
WATCHLIST_EVENTS = WATCHLIST

WMA_PERIODS = [20, 40, 200]
WMA_CHART_PERIODS = [20, 40, 60, 200]  # WMA60 chỉ để hiển thị trên biểu đồ, KHÔNG dùng để phát tín hiệu chạm hỗ trợ
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9

# Sai số cho phép để coi là "giá chạm" đường WMA (tính theo %)
TOUCH_TOLERANCE_PCT = 0.5  # giá nằm trong +-0.5% quanh đường WMA thì coi là "chạm"

# File lưu trạng thái "đang theo dõi" giữa 2 phiên (chạm hôm nay, xác nhận hôm sau)
STATE_FILE_TRADING = "data/trading_watch_state.json"

# ---- Nhiệm vụ 2: Điểm tin tổng hợp ----
# RSS mặc định — các nguồn hay đổi link, kiểm tra lại định kỳ nếu bot báo lỗi fetch rỗng.
RSS_FEEDS_INTERNATIONAL = [
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",  # CNBC World Markets
    "https://finance.yahoo.com/news/rssindex",  # Yahoo Finance
]
RSS_FEEDS_DOMESTIC = [
    "https://cafef.vn/thi-truong-chung-khoan.rss",
    "https://vneconomy.vn/chung-khoan.rss",
]
# Tin doanh nghiệp: lấy qua vnstock Reference.company(symbol).news() cho từng mã trong watchlist giao dịch
NEWS_ITEMS_PER_SECTION = 8  # số tin lấy thô trước khi đưa AI tóm tắt

# AI tóm tắt tin (dùng Anthropic API) — cần biến môi trường ANTHROPIC_API_KEY
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SUMMARIZER_MODEL = "claude-sonnet-4-6"

# ---- Nhiệm vụ 3: Thông tin sự kiện ----
# Quét theo WATCHLIST_EVENTS (danh mục theo dõi của bạn, 147 mã) thay vì toàn sàn.
STATE_FILE_EVENTS = "data/events_seen_state.json"  # lưu event đã đẩy để tránh gửi trùng

# Mệnh giá mặc định dùng để quy đổi tỷ lệ cổ tức tiền mặt (đa số 10,000đ)
FACE_VALUE = 10000
