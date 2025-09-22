#!/usr/bin/env python3
import argparse, json, re, random, time, os
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
DEFAULT_UA = UA_LIST[0]

MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "6"))
BASE_BACKOFF = float(os.getenv("BASE_BACKOFF", "10"))   # seconds
MAX_BACKOFF = float(os.getenv("MAX_BACKOFF", "120"))    # seconds

def random_ua():
    return random.choice(UA_LIST)

def is_captcha(html: str) -> bool:
    t = html.lower()
    return ("captcha" in t or
            "robot check" in t or
            "/errors/validatecaptcha" in t or
            "type the characters you see" in t)

def fetch_html(url, ua=DEFAULT_UA):
    backoff = BASE_BACKOFF
    last_err = None
    sess = requests.Session()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        use_ua = ua if ua else random_ua()
        headers = {
            "User-Agent": use_ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.amazon.com/",
        }
        try:
            time.sleep(random.uniform(1.2, 2.8))
            r = sess.get(url, headers=headers, timeout=(15, 45), allow_redirects=True)
            status = r.status_code

            if status in (429, 403, 503) or is_captcha(r.text):
                retry_after = r.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = float(retry_after)
                else:
                    wait = min(backoff + random.uniform(0, 5), MAX_BACKOFF)
                print(f"Got {status} (or captcha). Attempt {attempt}/{MAX_ATTEMPTS}. Sleeping {wait:.1f}s...")
                time.sleep(wait)
                backoff = min(backoff * 1.8, MAX_BACKOFF)
                last_err = requests.HTTPError(f"Status {status}")
                continue

            r.raise_for_status()
            return r.text

        except requests.RequestException as e:
            last_err = e
            wait = min(backoff + random.uniform(0, 5), MAX_BACKOFF)
            print(f"Request error on attempt {attempt}/{MAX_ATTEMPTS}: {e}. Sleeping {wait:.1f}s...")
            time.sleep(wait)
            backoff = min(backoff * 1.8, MAX_BACKOFF)

    raise last_err or RuntimeError("Failed to fetch after retries")

def extract_items(html, base="https://www.amazon.com"):
    soup = BeautifulSoup(html, "lxml")
    items, seen = [], set()

    ol = soup.find("ol")
    li_candidates = ol.find_all("li", recursive=True) if ol else []

    if not li_candidates:
        anchors = soup.select("a[href*='/dp/']")
        for a in anchors:
            href = a.get("href") or ""
            m = re.search(r"/dp/([A-Z0-9]{10})", href)
            if not m: continue
            asin = m.group(1)
            if asin in seen: continue
            seen.add(asin)
            link = urljoin(base, href.split("?")[0])

            container = a
            for _ in range(4):
                if container and container.find(class_=re.compile(r"a-price|a-icon-alt|a-link-normal")):
                    break
                container = container.parent

            title = None
            img = container.find("img") if container else None
            if img and img.get("alt"): title = img["alt"].strip()
            if not title:
                t = a.get_text(strip=True)
                title = t if t else None

            price_tag = container.select_one(".a-price .a-offscreen") if container else None
            price = price_tag.get_text(strip=True) if price_tag else None
            rating_tag = container.select_one(".a-icon-alt") if container else None
            rating = rating_tag.get_text(strip=True) if rating_tag else None

            items.append({"rank": None, "title": title, "link": link, "asin": asin, "price": price, "rating": rating})
    else:
        for li in li_candidates:
            a = li.select_one("a[href*='/dp/']")
            if not a: continue
            href = a.get("href") or ""
            m = re.search(r"/dp/([A-Z0-9]{10})", href)
            if not m: continue
            asin = m.group(1)
            if asin in seen: continue
            seen.add(asin)
            link = urljoin(base, href.split("?")[0])

            rank = None
            rank_tag = li.select_one(".zg-badge-text, .a-badge-text, .zg-rank-number")
            if rank_tag: rank = rank_tag.get_text(strip=True)

            title = None
            img = li.find("img")
            if img and img.get("alt"): title = img["alt"].strip()
            if not title:
                t = li.select_one("a.a-link-normal")
                if t: title = t.get_text(strip=True) or None

            price_tag = li.select_one(".a-price .a-offscreen, .p13n-sc-price")
            price = price_tag.get_text(strip=True) if price_tag else None

            rating_tag = li.select_one(".a-icon-alt")
            rating = rating_tag.get_text(strip=True) if rating_tag else None

            items.append({"rank": rank, "title": title, "link": link, "asin": asin, "price": price, "rating": rating})

    for i, it in enumerate(items, start=1):
        if not it.get("rank"):
            it["rank"] = f"#{i}"
    return items

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category-url", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--ua", default=DEFAULT_UA)
    args = ap.parse_args()

    html = fetch_html(args.category_url, args.ua)
    items = extract_items(html)
    snapshot = {
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "category_url": args.category_url,
        "items": items,
    }
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    print("Wrote", args.output)

if __name__ == "__main__":
    main()
