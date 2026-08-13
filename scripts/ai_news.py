#!/usr/bin/env python3
import sys
# Avoid UnicodeEncodeError on Windows consoles (GBK) when logging emoji/text.
if sys.stdout.encoding and "utf-8" not in sys.stdout.encoding.lower():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
"""
AI news daily push: fetch RSS -> keep today's items -> dedupe -> send to Telegram.

Designed to run from a GitHub Actions scheduled workflow. Dedupe state is
stored in the Actions cache so already-pushed items are skipped on later
runs within the same day.

Setup (once):
  - Put your Telegram bot token in the workflow secrets (TELEGRAM_BOT_TOKEN).
  - Put your chat id in the workflow variables (TELEGRAM_CHAT_ID).

Environment used:
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / TELEGRAM_API_BASE (optional override)
  RSS_FEED_URL (optional; defaults to https://daily.juya.uk/rss.xml)
  SEND_SILENT (optional; set "true" to disable preview in Telegram)
  ACTIONS_CACHE_URL / ACTIONS_RUNTIME_TOKEN (set automatically in Actions)
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
RSS_URL = os.environ.get("RSS_FEED_URL", "https://daily.juya.uk/rss.xml")
BEIJING = timezone(timedelta(hours=8))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_BASE = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org")

SEND_SILENT = os.environ.get("SEND_SILENT", "").lower() in ("1", "true", "yes")

CACHE_FILE = "rss_cache.json"
CACHE_KEY = "ai-news-pushed-ids"
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "")

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def log(msg):
    print(f"[{datetime.now(BEIJING):%H:%M:%S}] {msg}", flush=True)


def parse_pub_date(value):
    """Parse RSS pubDate/published. Returns Beijing datetime or None."""
    if not value:
        return None
    text = value.strip()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(BEIJING)
    return None


def fetch_rss_entries(url):
    """Fetch RSS/Atom XML with retries. Returns list of dicts."""
    import httpx

    resp = None
    last_err = None
    for attempt in range(1, 4):
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            break
        except Exception as exc:
            last_err = exc
            log(f"RSS fetch attempt {attempt}/3 failed: {exc}")
            time.sleep(2 * attempt)
    if resp is None:
        raise last_err
    root = ET.fromstring(resp.content)

    entries = []
    if root.tag == "feed":  # Atom
        for item in root.findall("{http://www.w3.org/2005/Atom}entry"):
            title = (item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href") if link_el is not None else ""
            summary = (
                item.findtext("{http://www.w3.org/2005/Atom}summary")
                or item.findtext("{http://www.w3.org/2005/Atom}content")
                or ""
            ).strip()
            published = item.findtext("{http://www.w3.org/2005/Atom}updated") or item.findtext(
                "{http://www.w3.org/2005/Atom}published"
            )
            entries.append(
                {
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published_dt": parse_pub_date(published),
                }
            )
    else:  # RSS 2.0
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            summary = (item.findtext("description") or "").strip()
            pub = item.findtext("pubDate") or item.findtext("dc:date", None)
            entries.append(
                {
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published_dt": parse_pub_date(pub),
                }
            )
    return entries


def strip_html(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def item_key(item):
    return item.get("link") or item.get("title") or item.get("published_dt")


def send_telegram(text):
    """Send message to Telegram. Returns True on success."""
    import httpx

    url = f"{TELEGRAM_API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": not SEND_SILENT,
    }
    resp = httpx.post(url, json=payload, timeout=30)
    data = resp.json()
    if not resp.is_success or not data.get("ok"):
        log(f"Telegram send failed: {resp.status_code} {data}")
        return False
    return True


def run_cache_setup():
    """Restore previous cache (if any) so dedupe works across runs in one day."""
    if not GITHUB_REPO or not os.environ.get("ACTIONS_CACHE_URL"):
        return
    try:
        import httpx

        url = os.environ["ACTIONS_CACHE_URL"].rstrip("/") + "/_apis/actioncache/caches"
        params = {"keys": CACHE_KEY, "repositoryId": GITHUB_REPO}
        headers = {"Authorization": f"Bearer {os.environ['ACTIONS_RUNTIME_TOKEN']}"}
        resp = httpx.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("archiveLocation"):
            archive = httpx.get(data["archiveLocation"], timeout=60)
            archive.raise_for_status()
            import io
            import zipfile

            with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
                zf.extractall(".")
                log(f"Cache restored: {CACHE_FILE}")
    except Exception as exc:
        log(f"Cache restore skipped: {exc}")


def run_cache_save():
    """Upload current cache back to Actions so the next run sees it."""
    if not GITHUB_REPO or not os.path.exists(CACHE_FILE):
        return
    try:
        import io
        import zipfile

        import httpx

        url = os.environ["ACTIONS_CACHE_URL"].rstrip("/") + "/_apis/actioncache/caches"
        headers = {"Authorization": f"Bearer {os.environ['ACTIONS_RUNTIME_TOKEN']}"}

        resp = httpx.get(url, params={"repositoryId": GITHUB_REPO, "keys": CACHE_KEY}, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("cacheKey"):
            cache_id = data["cacheId"]
            url_put = f"{os.environ['ACTIONS_CACHE_URL'].rstrip('/')}/_apis/actioncache/caches/{cache_id}"
            httpx.delete(url_put, headers=headers, timeout=30)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.write(CACHE_FILE, CACHE_FILE)
        data_bytes = buf.getvalue()

        import hashlib

        resp = httpx.post(
            os.environ["ACTIONS_CACHE_URL"].rstrip("/") + "/_apis/actioncache/caches",
            json={"key": CACHE_KEY, "version": "1", "repositoryId": GITHUB_REPO},
            headers={**headers, "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code in (200, 201):
            resp = httpx.put(resp.json()["archiveLocation"], content=data_bytes, timeout=120)
            resp.raise_for_status()
            log("Cache saved")
    except Exception as exc:
        log(f"Cache save skipped: {exc}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured. Nothing to do.")
        return 0

    # Window check (Beijing time). PUSH_START_HOUR/PUSH_END_HOUR control the
    # push window (default 07:00-11:00). Wide window tolerates GitHub Actions
    # schedule delays, while dedupe still guarantees only one push per day.
    now_bj = datetime.now(BEIJING)
    if os.environ.get("FORCE_WINDOW", "").lower() in ("1", "true", "yes"):
        log("FORCE_WINDOW set, skipping window check.")
        now_bj = now_bj.replace(hour=8, minute=30)
    try:
        start_h = int(os.environ.get("PUSH_START_HOUR", "7"))
        end_h = int(os.environ.get("PUSH_END_HOUR", "11"))
    except ValueError:
        start_h, end_h = 7, 11
    hour, minute = now_bj.hour, now_bj.minute
    if not (start_h, 0) <= (hour, minute) <= (end_h, 0):
        log(f"Outside push window ({start_h:02d}:00-{end_h:02d}:00 Beijing), current {now_bj:%H:%M}, exiting.")
        return 0

    try:
        run_cache_setup()

        pushed = set()
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as fh:
                    pushed = set(json.load(fh).get("pushed_ids", []))
            except Exception:
                pushed = set()

        today = now_bj.date()
        log(f"Fetching RSS: {RSS_URL}")
        entries = fetch_rss_entries(RSS_URL)
        log(f"Fetched {len(entries)} entries")
    except Exception as exc:
        log(f"Fetch failed: {exc}")
        return 1

    fresh = []
    for e in entries:
        if not e.get("published_dt"):
            log(f"Skipping item without parseable date: {e['title']}")
            continue
        if e["published_dt"].date() != today:
            log(f"Skipping not-today item: {e['title']} ({e['published_dt'].date()})")
            continue
        key = item_key(e)
        if key in pushed:
            log(f"Skipping already-pushed: {e['title']}")
            continue
        fresh.append(e)

    if not fresh:
        log("No new items for today.")
        return 0

    lines = [f"\U0001F525 每日 AI 新闻 · {datetime.now(BEIJING):%Y-%m-%d}"]
    for e in fresh:
        lines.append(f"- {e['title']}\n  {e['link']}")
    text = "\n".join(lines)

    if not send_telegram(text):
        log("Push failed, keeping items unmarked so they can retry.")
        return 1

    for e in fresh:
        pushed.add(item_key(e))
    with open(CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump({"pushed_ids": sorted(pushed)}, fh, ensure_ascii=False)
    log(f"Pushed {len(fresh)} items, marked as read.")

    run_cache_save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
