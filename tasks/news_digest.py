"""
Nhiệm vụ 2 - ĐIỂM TIN TỔNG HỢP
Chạy 1 lần/ngày lúc 8h00 (giờ VN).

Luồng xử lý:
1. Lấy tin thô từ RSS (quốc tế + trong nước).
2. Lấy tin doanh nghiệp qua vnstock cho các mã trong watchlist giao dịch.
3. Gửi cả 3 nhóm tin thô cho Claude API tóm tắt lại thành các gạch đầu dòng
   ngắn gọn, giữ đúng ý, không thêm bình luận.
4. Ghép thành 1 tin nhắn theo mẫu và gửi qua Zalo.

LƯU Ý:
- RSS là nguồn public, link hay thay đổi/redirect theo thời gian — nếu một nguồn
  trả về rỗng, bot sẽ bỏ qua nguồn đó thay vì lỗi toàn bộ tác vụ.
- Cần thêm ANTHROPIC_API_KEY vào GitHub Secrets để bước tóm tắt hoạt động.
"""
import time

import requests

import config
from utils.zalo_client import ZaloBotClient

try:
    import feedparser
except ImportError:
    feedparser = None

try:
    from vnstock.explorer.vci import Company
except ImportError:
    Company = None


def fetch_rss_entries(feed_urls: list[str], limit_per_feed: int) -> list[dict]:
    if feedparser is None:
        raise RuntimeError("Chưa cài feedparser: pip install feedparser")
    entries = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries[:limit_per_feed]:
                entries.append({
                    "title": e.get("title", ""),
                    "summary": e.get("summary", "")[:300],
                    "link": e.get("link", ""),
                })
        except Exception as ex:
            print(f"[news_digest] Bỏ qua nguồn lỗi {url}: {ex}")
    return entries


def fetch_company_news(symbols: list[str], limit_per_symbol: int = 3) -> list[dict]:
    if Company is None:
        raise RuntimeError("Chưa cài vnstock")
    entries = []
    for sym in symbols:
        try:
            df_news = Company(symbol=sym).news()
            for _, row in df_news.head(limit_per_symbol).iterrows():
                entries.append({
                    "title": f"[{sym}] {row.get('title', '')}",
                    "summary": str(row.get('summary', row.get('description', '')))[:300],
                    "link": row.get('link', row.get('url', '')),
                })
        except Exception as ex:
            print(f"[news_digest] Lỗi lấy tin doanh nghiệp {sym}: {ex}")
        time.sleep(0.2)  # danh mục có thể tới 147 mã, tránh gọi dồn dập
    return entries


def summarize_section(entries: list[dict], section_name: str) -> str:
    """Gọi Claude API tóm tắt danh sách tin thành các gạch đầu dòng ngắn gọn."""
    if not entries:
        return "(Không có tin đáng chú ý)"
    if not config.ANTHROPIC_API_KEY:
        # Fallback: không có API key thì chỉ liệt kê tiêu đề thô
        return "\n".join(f"- {e['title']}" for e in entries)

    raw_text = "\n".join(f"- {e['title']}: {e['summary']}" for e in entries)
    prompt = (
        f"Dưới đây là các tin thô thuộc mục '{section_name}' cho bản tin chứng khoán buổi sáng.\n"
        f"Tóm tắt lại thành tối đa 5 gạch đầu dòng ngắn gọn, mỗi dòng 1 câu, "
        f"giữ đúng thông tin, không bịa thêm, không nhận xét cá nhân, viết bằng tiếng Việt:\n\n"
        f"{raw_text}"
    )
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": config.SUMMARIZER_MODEL,
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(block.get("text", "") for block in data.get("content", []))


def build_digest_message() -> str:
    intl_raw = fetch_rss_entries(config.RSS_FEEDS_INTERNATIONAL, config.NEWS_ITEMS_PER_SECTION)
    domestic_raw = fetch_rss_entries(config.RSS_FEEDS_DOMESTIC, config.NEWS_ITEMS_PER_SECTION)

    # Danh mục có tới 147 mã — lấy tin từng mã (1 tin/mã) rồi chỉ giữ lại
    # NEWS_ITEMS_PER_SECTION tin đầu để tránh dồn quá nhiều nội dung vào 1 lần
    # gọi AI tóm tắt (vừa tốn token vừa dễ vượt giới hạn).
    company_raw_all = fetch_company_news(config.WATCHLIST_TRADING, limit_per_symbol=1)
    company_raw = company_raw_all[: config.NEWS_ITEMS_PER_SECTION]

    intl_summary = summarize_section(intl_raw, "Tin quốc tế")
    domestic_summary = summarize_section(domestic_raw, "Tin trong nước")
    company_summary = summarize_section(company_raw, "Tin doanh nghiệp")

    return (
        "ĐIỂM TIN TỔNG HỢP\n\n"
        "Tin quốc tế\n"
        f"{intl_summary}\n\n"
        "Tin trong nước\n"
        f"{domestic_summary}\n\n"
        "Tin doanh nghiệp\n"
        f"{company_summary}"
    )


def run():
    client = ZaloBotClient(config.ZALO_BOT_TOKEN, config.ZALO_CHAT_ID)
    message = build_digest_message()
    client.send_message(message)


if __name__ == "__main__":
    run()
