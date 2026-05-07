"""
Forex Scalp Alert Server - Text Only
"""

import os
import logging
from datetime import datetime
from flask import Flask, request, jsonify
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "422331755")
PORT               = int(os.environ.get("PORT", 5000))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)


def send_telegram_text(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    log.info(f"Sending to chat_id={TELEGRAM_CHAT_ID}")
    try:
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
        log.info(f"Telegram response: {resp.status_code} — {resp.text}")
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Telegram sendMessage failed: {e}")
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    # No secret check — TradingView does not support custom headers
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    pair   = data.get("pair", "UNKNOWN").upper().replace("FX:", "").replace("OANDA:", "").replace(":", "")
    signal = data.get("signal", "?").upper()
    price  = data.get("price", "?")
    time_  = data.get("time", datetime.utcnow().isoformat())

    log.info(f"Signal received: {signal} on {pair} @ {price}")

    emoji   = "🟢" if signal == "BUY" else "🔴"
    tv_link = f"https://www.tradingview.com/chart/?symbol=FX:{pair}&interval=1"
    message = (
        f"{emoji} <b>{signal} — {pair}</b>\n"
        f"💰 Price: <code>{price}</code>\n"
        f"🕐 Time: <code>{time_}</code>\n"
        f"📊 TF: 1M | HA Scalp | EMA100\n"
        f'🔗 <a href="{tv_link}">Open Chart</a>'
    )

    ok = send_telegram_text(message)

    if ok:
        return jsonify({"status": "alert sent", "pair": pair, "signal": signal}), 200
    else:
        return jsonify({"status": "alert failed"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
