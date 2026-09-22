"""
Server webhook cho Zalo Bot — CHẠY RIÊNG, LUÔN BẬT (khác với tasks/ chạy theo
lịch qua GitHub Actions). Cần deploy lên 1 nơi có server thật (vd Render.com),
xem hướng dẫn trong README.md phần "Server webhook (chức năng gõ lệnh xem
biểu đồ)".

Cách dùng: người dùng nhắn trực tiếp cho bot 1 mã cổ phiếu (vd "VCI" hoặc
"/vci"), server nhận webhook, vẽ biểu đồ NGAY LÚC ĐÓ (không dùng dữ liệu cache
từ Nhiệm vụ 1), gửi ảnh trả lời ngay trong cuộc chat đó.

LƯU Ý QUAN TRỌNG — CẦN XÁC NHẬN KHI CHẠY THẬT:
- Cấu trúc JSON thật mà Zalo gửi tới webhook (tên field message/chat/text...)
  mình suy luận từ kết quả getUpdates đã thấy trước đó, CHƯA có tài liệu chính
  thức xác nhận 100% khớp với payload webhook thực tế. Code bên dưới in toàn bộ
  payload thô ra log (xem trong Render > Logs) — nếu bot không phản hồi, gửi
  đoạn log đó lại để chỉnh cho khớp.
- Cơ chế xác thực Secret Token (chống giả mạo request) cũng suy luận tương tự,
  đang tạm bỏ qua bước xác thực (ai gọi đúng URL cũng được xử lý) — có thể bổ
  sung sau khi xác nhận đúng tên header Zalo dùng để gửi secret token.
"""
import os
import re
import traceback

from flask import Flask, request, jsonify, Response

import config
from utils.zalo_client import ZaloBotClient
from utils.analysis import get_analyzed, plot_chart, build_snapshot_caption, CHART_DIR

app = Flask(__name__)
client = ZaloBotClient(config.ZALO_BOT_TOKEN, config.ZALO_CHAT_ID)

# Mã cổ phiếu VN chuẩn: 3 chữ cái (đa số), một số ít 3-4 ký tự có số.
SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,4}$")

HELP_TEXT = (
    "Gõ 1 mã cổ phiếu (vd: VCI, FPT, VNM) để xem biểu đồ giá + WMA20/40/60/200 "
    "+ RSI + MACD hiện tại."
)


def extract_message(payload: dict):
    """Trả về (chat_id, text) từ payload webhook, hoặc (None, None) nếu
    không nhận diện được cấu trúc — xem lưu ý ở đầu file."""
    msg = payload.get("message") or {}
    text = msg.get("text") or payload.get("text")
    chat = msg.get("chat") or payload.get("chat") or {}
    chat_id = chat.get("id") or payload.get("chat_id")
    return chat_id, text


@app.route("/webhook", methods=["POST"])
@app.route("/", methods=["POST"])  # phòng trường hợp Zalo chỉ gọi được domain gốc
def webhook():
    payload = request.get_json(silent=True) or {}
    print("[webhook] payload nhận được:", payload)  # xem trong Render > Logs

    chat_id, text = extract_message(payload)
    if not chat_id or not text:
        # Không nhận diện được — vẫn trả 200 để Zalo không gửi lại liên tục,
        # nhưng log lại để mình chỉnh extract_message() cho khớp payload thật.
        return jsonify({"ok": True, "note": "unrecognized payload, see logs"}), 200

    symbol = text.strip().upper().lstrip("/")

    try:
        if not SYMBOL_RE.match(symbol):
            result = client.send_message(HELP_TEXT, chat_id=chat_id)
            print("[webhook] kết quả send_message (help):", result)
        else:
            df = get_analyzed(symbol)
            if len(df) < 30:
                result = client.send_message(f"Không đủ dữ liệu cho mã {symbol}.", chat_id=chat_id)
                print("[webhook] kết quả send_message (thiếu dữ liệu):", result)
            else:
                chart_path = plot_chart(symbol, df)
                # sendPhoto của Zalo Bot Platform cần 1 URL công khai, không
                # nhận upload file trực tiếp -- server này tự host file ảnh
                # vừa vẽ tại route /charts/<file>, rồi gửi đúng URL đó đi.
                chart_url = request.host_url.rstrip("/") + "/charts/" + os.path.basename(chart_path)
                caption = build_snapshot_caption(symbol, df)
                result = client.send_photo_url(chart_url, caption=caption, chat_id=chat_id)
                print("[webhook] kết quả send_photo_url:", result)
    except Exception:
        traceback.print_exc()
        try:
            client.send_message(f"Có lỗi khi lấy dữ liệu mã {symbol}, thử lại sau.", chat_id=chat_id)
        except Exception:
            pass

    return jsonify({"ok": True}), 200


@app.route("/charts/<path:filename>", methods=["GET"])
def serve_chart(filename):
    # Đọc file vào bộ nhớ và tự set Content-Length/Content-Type rõ ràng,
    # KHÔNG dùng send_from_directory mặc định -- đã xác nhận qua log thật
    # trên Render: file phục vụ theo cách mặc định bị log content-length = 0,
    # khiến Zalo tải về báo "The photo URL is invalid".
    safe_name = os.path.basename(filename)  # chặn path traversal
    file_path = os.path.join(CHART_DIR, safe_name)
    if not os.path.isfile(file_path):
        return "not found", 404
    with open(file_path, "rb") as f:
        data = f.read()
    return Response(
        data,
        mimetype="image/png",
        headers={"Content-Length": str(len(data)), "Cache-Control": "no-store"},
    )


@app.route("/", methods=["GET"])
def health():
    # Endpoint kiểm tra server còn sống — dùng để ping giữ server không "ngủ"
    # trên các gói free hay tự tắt khi không có traffic (xem README).
    return "zalo-invest-bot webhook server is running", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
