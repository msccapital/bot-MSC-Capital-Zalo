"""
Client gọi API Zalo Bot Platform (bot.zaloplatforms.com).
API có dạng tương tự Telegram Bot API: sendMessage, sendPhoto, getUpdates.
"""
import requests

BASE_URL_TEMPLATE = "https://bot-api.zapps.me/bot{token}/{method}"


class ZaloBotClient:
    def __init__(self, token: str, default_chat_id: str = ""):
        if not token:
            raise ValueError("Thiếu ZALO_BOT_TOKEN")
        self.token = token
        self.default_chat_id = default_chat_id

    def _url(self, method: str) -> str:
        return BASE_URL_TEMPLATE.format(token=self.token, method=method)

    def send_message(self, text: str, chat_id: str = None) -> dict:
        payload = {
            "chat_id": chat_id or self.default_chat_id,
            "text": text,
        }
        resp = requests.post(self._url("sendMessage"), json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def send_photo(self, photo_path: str, caption: str = "", chat_id: str = None) -> dict:
        data = {"chat_id": chat_id or self.default_chat_id, "caption": caption}
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            resp = requests.post(self._url("sendPhoto"), data=data, files=files, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_updates(self, offset: int = None) -> dict:
        params = {"offset": offset} if offset else {}
        resp = requests.get(self._url("getUpdates"), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
