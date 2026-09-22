\"""
Client gọi API Zalo Bot Platform (bot.zaloplatforms.com).
API có dạng tương tự Telegram Bot API: sendMessage, sendPhoto, getUpdates.

LƯU Ý QUAN TRỌNG:
- sendPhoto qua multipart upload (gửi thẳng file) liên tục báo lỗi thật từ
  Zalo "The photo must not be empty" dù đã thử nhiều cách khác nhau -- nhiều
  khả năng API này CHỈ nhận link ảnh công khai (URL), không nhận upload file
  trực tiếp như Telegram. Nên đã đổi sang send_photo_url() — cần 1 URL công
  khai trỏ tới ảnh, không dùng file cục bộ nữa. Xem server.py để biết cách
  server tự host ảnh và tạo URL.
- Mọi hàm gọi API giờ đều tự kiểm tra field "ok" trong JSON trả về và raise
  lỗi nếu "ok" là false — trước đây bỏ sót bước này khiến các lần gọi lỗi
  (nhưng HTTP status vẫn là 200) bị coi là thành công, làm mất tin nhắn âm
  thầm không ai biết.
"""
import requests

BASE_URL_TEMPLATE = "https://bot-api.zapps.me/bot{token}/{method}"


class ZaloAPIError(Exception):
    pass


class ZaloBotClient:
    def __init__(self, token: str, default_chat_id: str = ""):
        if not token:
            raise ValueError("Thiếu ZALO_BOT_TOKEN")
        self.token = token
        self.default_chat_id = default_chat_id

    def _url(self, method: str) -> str:
        return BASE_URL_TEMPLATE.format(token=self.token, method=method)

    @staticmethod
    def _check(resp) -> dict:
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok", False):
            raise ZaloAPIError(f"Zalo API trả lỗi: {data}")
        return data

    def send_message(self, text: str, chat_id: str = None) -> dict:
        payload = {
            "chat_id": chat_id or self.default_chat_id,
            "text": text,
        }
        resp = requests.post(self._url("sendMessage"), json=payload, timeout=15)
        return self._check(resp)

    def send_photo_url(self, photo_url: str, caption: str = "", chat_id: str = None) -> dict:
        """Gửi ảnh bằng LINK công khai (không phải upload file trực tiếp —
        xem lưu ý ở đầu file)."""
        payload = {
            "chat_id": chat_id or self.default_chat_id,
            "photo": photo_url,
            "caption": caption,
        }
        resp = requests.post(self._url("sendPhoto"), json=payload, timeout=15)
        return self._check(resp)

    def get_updates(self, offset: int = None) -> dict:
        params = {"offset": offset} if offset else {}
        resp = requests.get(self._url("getUpdates"), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
