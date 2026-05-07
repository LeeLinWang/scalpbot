"""
Forex Scalp Alert Server
Receives TradingView webhooks → grabs chart screenshot → sends Telegram message
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from flask import Flask, request, jsonify
import requests
from playwright.sync_api import sync_playwright

# ─── CONFIG (set these as Railway environment variables) ─────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "")       # optional auth
PORT               = int(os.environ.get("PORT", 5000))

# TradingView chart URLs per pair (1M, Heikin Ashi, 100 EMA)
# Replace these with your actual saved chart URLs from TradingView
TV_CHART_URLS = {
    "EURUSD":  "https://www.tradingview.com/chart/?symbol=EURUSD&interval=1",
    "GBPUSD":  "https://www.tradingview.com/chart/?symbol=GBPUSD&interval=1",
    "USDJPY":  "https://www.tradingview.com/chart/?symbol=USDJPY&interval=1",
    "AUDUSD":  "https://www.tradingview.com/chart/?symbol=AUDUSD&interval=1",
    # FX broker prefixes TradingView may use:
    "FX:EURUSD": "https://www.tradingview.com/chart/?symbol=FX:EURUSD&interval=1",
    "FX:GBPUSD": "https://www.tradingview.com/chart/?symbol=FX:GBPUSD&interval=1",
    "FX:USDJPY": "https://www.tradingview.com/chart/?symbol=FX:USDJPY&interval=1",
    "FX:AUDUSD": "https://www.tradingview.com/chart/?symbol=FX:AUDUSD&interval=1",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)


# ─── SCREENSHOT ───────────────────────────────────────────────────────────────

def take_screenshot(pair: str) -> bytes | None:
    """
    Uses Playwright to open the TradingView chart and take a screenshot.
    Returns PNG bytes or None on failure.
    """
    # Normalize pair key
    url = TV_CHART_URLS.get(pair) or TV_CHART_URLS.get(pair.replace("FX:", "").replace(":", ""))
    if not url:
        log.warning(f"No chart URL configured for pair: {pair}")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            page = browser.new_page(viewport={"width": 1400, "height": 800})
            page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait for chart to render
            page.wait_for_timeout(4000)
            # Hide UI chrome if possible
            page.evaluate("""
                () => {
                    // Hide top bar and sidebars for clean chart
                    const els = document.querySelectorAll(
                        '.tv-header, .tv-side-toolbar, .layout__area--left'
                    );
                    els.forEach(el => el.style.display = 'none');
                }
            """)
            screenshot = page.screenshot(type="png")
            browser.close()
            return screenshot
    except Exception as e:
        log.error(f"Screenshot failed for {pair}: {e}")
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
            return jsonify({"error": "unauthorized"}), 401

    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    pair   = data.get("pair", "UNKNOWN").upper().replace("FX:", "").replace(":", "")
    signal = data.get("signal", "?").upper()
    price  = data.get("price", "?")
    time_  = data.get("time", datetime.utcnow().isoformat())

    log.info(f"Signal received: {signal} on {pair} @ {price}")

    # Build caption
    emoji  = "🟢" if signal == "BUY" else "🔴"
    caption = (
        f"{emoji} <b>{signal} SIGNAL — {pair}</b>\n"
        f"Price: <code>{price}</code>\n"
        f"Time: <code>{time_}</code>\n"
        f"TF: 1M | Setup: HA Scalp | EMA100"
    )

    # Take screenshot
    screenshot = take_screenshot(pair)

    if screenshot:
        ok = send_telegram_photo(screenshot, caption)
    else:
        # Fallback: text-only alert
        log.warning("No screenshot — sending text alert only")
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
