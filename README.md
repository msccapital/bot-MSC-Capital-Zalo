# Zalo Invest Bot

Bot Zalo cho 3 nhiệm vụ độc lập:

| Nhiệm vụ | Giờ chạy (VN) | File |
|---|---|---|
| Điểm tin tổng hợp | 08:00 | `tasks/news_digest.py` |
| Hỗ trợ giao dịch | 12:00 & 15:00 | `tasks/support_trading.py` |
| Thông tin sự kiện | 14:00 | `tasks/corporate_events.py` |

## Cài đặt

```bash
pip install -r requirements.txt
```

## Biến môi trường / GitHub Secrets cần có

- `ZALO_BOT_TOKEN` — token bot lấy từ bot.zaloplatforms.com
- `ZALO_CHAT_ID` — chat_id của group Zalo đã mời bot vào
- `ANTHROPIC_API_KEY` — dùng để tóm tắt tin ở Nhiệm vụ 2 (tuỳ chọn — nếu bỏ trống bot sẽ gửi tiêu đề thô thay vì bản tóm tắt)

## Chạy thử từng nhiệm vụ

```bash
python -m tasks.news_digest
python -m tasks.support_trading
python -m tasks.corporate_events
```

## Việc cần làm trước khi chạy thật (đã đánh dấu TODO trong code)

1. **`tasks/corporate_events.py`** — schema cột trả về từ `Reference().company(symbol).events()` mình chưa có tài liệu cột chính xác (`event_type`, `ratio`, `exright_date`...). Chạy thử `print(ref.company("VCI").events())` một lần rồi đối chiếu, chỉnh lại tên cột trong `format_event_message()` cho khớp thực tế.
2. **Timing giá đóng cửa Nhiệm vụ 3** — bot chạy 14h00 (thị trường VN chưa đóng cửa, thường 15h00 mới đóng). Hiện đang lấy giá đóng cửa của phiên gần nhất có sẵn — cần xác nhận đây có phải cách bạn muốn tính hay nên đợi sau giờ đóng cửa.
3. **Nguồn RSS** (`config.RSS_FEEDS_INTERNATIONAL` / `RSS_FEEDS_DOMESTIC`) — link RSS công khai hay đổi/redirect theo thời gian, nên kiểm tra định kỳ.
4. **`utils/zalo_client.py`** — base URL API (`bot-api.zapps.me`) dựa trên tài liệu cộng đồng, nên xác nhận lại đúng domain/method khi có token thật để test.

## Danh mục theo dõi

`watchlist.py` chứa 147 mã lấy từ file `DANH_MUC_THEO_DOI` của bạn (kèm nhóm ngành để tham khảo), dùng chung cho Nhiệm vụ 1 và Nhiệm vụ 3. Khi danh mục đổi, chỉ cần cập nhật file này.
