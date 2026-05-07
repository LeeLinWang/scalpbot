"""
Forex Scalp Alert Server
Receives TradingView webhooks → sends Telegram message with chart image
Uses TradingView's snapshot API (no Playwright needed)
"""

import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify
import requests

# ─── CONFIG ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "")
PORT               = int(os.environ.get("PORT", 5000))

# TradingView chart symbol map for snapshot API
# Format: exchange:symbol
TV_SYMBOLS = {
    "EURUSD":  "FX:EURUSD",
    "GBPUSD":  "FX:GBPUSD",
    "USDJPY":  "FX:USDJPY",
    "AUDUSD":  "FX:AUDUSD",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)


# ─── CHART IMAGE ─────────────────────────────────────────────────────────────

def get_chart_image(pair: str) -> bytes | None:
    """
    Fetches a chart snapshot from TradingView's public snapshot API.
    Returns PNG bytes or None on failure.
    """
    symbol = TV_SYMBOLS.get(pair, f"FX:{pair}")

    # TradingView mini chart snapshot — no auth needed
    url = (
        f"https://charts.tradingview.com/mini-symbol-overview"
        f"?symbol={symbol}"
        f"&interval=1m"
        f"&theme=dark"
        f"&width=800"
        f"&height=400"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image"):
            return resp.content
        else:
            log.warning(f"TV snapshot returned {resp.status_code} for {pair}")
            return None
    except Exception as e:
        log.error(f"Chart image fetch failed: {e}")
        return None


def get_chart_image_v2(pair: str) -> bytes | None:
    """
    Alternative: use TradingView's widget screenshot endpoint
    """
    symbol = TV_SYMBOLS.get(pair, f"FX:{pair}")

    url = f"https://s3.tradingview.com/snapshots/s/{symbol.replace(':', '_')}.png"

    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception as e:
        log.error(f"Chart image v2 failed: {e}")
        return None


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────

def send_telegram_photo(image_bytes: bytes, caption: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        resp = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("chart.png", image_bytes, "image/png")},
            timeout=15
        )
        resp.raise_for_status()
        log.info("Telegram photo sent successfully")
        return True
    except Exception as e:
        log.error(f"Telegram sendPhoto failed: {e}")
        return False


def send_telegram_text(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
        resp.raise_for_status()
        log.info("Telegram text sent successfully")
        return True
    except Exception as e:
        log.error(f"Telegram sendMessage failed: {e}")
        return False


# ─── WEBHOOK ENDPOINT ─────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    # Optional secret check
    if WEBHOOK_SECRET:
        incoming = request.headers.get("X-Webhook-Secret", "")
        if incoming != WEBHOOK_SECRET:
            log.warning("Unauthorized webhook attempt")
            return jsonify({"error": "unauthorized"}), 401

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    # Normalize pair — strip FX: prefix and colons
    raw_pair = data.get("pair", "UNKNOWN").upper()
    pair     = raw_pair.replace("FX:", "").replace(":", "").replace("_", "")
    signal   = data.get("signal", "?").upper()
    price    = data.get("price", "?")
    time_    = data.get("time", datetime.utcnow().isoformat())

    log.info(f"Signal received: {signal} on {pair} @ {price}")

    # Build caption
    emoji   = "🟢" if signal == "BUY" else "🔴"
    tv_link = f"https://www.tradingview.com/chart/?symbol=FX:{pair}&interval=1"
    caption = (
        f"{emoji} <b>{signal} — {pair}</b>\n"
        f"💰 Price: <code>{price}</code>\n"
        f"🕐 Time: <code>{time_}</code>\n"
        f"📊 TF: 1M | HA Scalp | EMA100\n"
        f"🔗 <a href='{tv_link}'>Open Chart</a>"
    )

    # Try to get chart image
    image = get_chart_image(pair) or get_chart_image_v2(pair)

    if image:
        ok = send_telegram_photo(image, caption)
    else:
        log.warning(f"No chart image available for {pair} — sending text alert")
        ok = send_telegram_text(caption + "\n\n⚠️ <i>Chart screenshot unavailable</i>")

    if ok:
        return jsonify({"status": "alert sent", "pair": pair, "signal": signal}), 200
    else:
        return jsonify({"status": "alert failed"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
