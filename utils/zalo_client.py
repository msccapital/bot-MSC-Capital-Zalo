"""
Client gọi API Zalo Bot Platform (bot.zaloplatforms.com).
API có dạng tương tự Telegram Bot API: sendMessage, sendPhoto, getUpdates.
"""
import os

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
        # Gửi chat_id/caption qua query string (không phải multipart form field) —
        # API sendPhoto của Zalo Bot Platform không đọc đúng các trường này khi
        # trộn chung với multipart file, đã xác nhận qua lỗi thật "chat_id must
        # not be empty" / "photo must not be empty" khi gửi theo cách cũ.
        params = {"chat_id": chat_id or self.default_chat_id, "caption": caption}
        with open(photo_path, "rb") as f:
            files = {"photo": (os.path.basename(photo_path), f, "image/png")}
            resp = requests.post(self._url("sendPhoto"), params=params, files=files, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_updates(self, offset: int = None) -> dict:
        params = {"offset": offset} if offset else {}
        resp = requests.get(self._url("getUpdates"), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
