#!/usr/bin/env python3
import argparse, os, json, csv, re
from datetime import datetime, timedelta

STOP = set(x.lower() for x in """
the a an and or for to of with without adult youth kids men men's womens women's shirt t-shirt tshirt tee tank long sleeve short sleeve
fit slim classic heavyweight lightweight novelty funny cool new official vintage retro graphic apparel clothing brand color colors size sizes
""".split())

def parse_dt(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z",""))
    except Exception:
        return None

def rank_int(s):
    try:
        return int(re.sub(r"[^\d]", "", s or ""))
    except Exception:
        return None

def keywords_from_title(title):
    words = re.findall(r"[A-Za-z0-9']+", (title or ""))
    kws = [w.lower() for w in words if w and w.lower() not in STOP and len(w) > 2]
    seen, out = set(), []
    for w in kws:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:12]

def load_snaps(data_dir, days):
    files = sorted([f for f in os.listdir(data_dir) if f.endswith(".json")])
    cutoff = datetime.utcnow() - timedelta(days=days)
    snaps = []
    for fn in files:
        path = os.path.join(data_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            t = parse_dt(s.get("scraped_at")) or datetime.utcfromtimestamp(os.path.getmtime(path))
            if t >= cutoff:
                snaps.append({"when": t, "data": s})
        except Exception:
            continue
    snaps.sort(key=lambda x: x["when"])
    return snaps

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--max-rank", type=int, default=50, help="keep items ranked <= this")
    ap.add_argument("--new-only", action="store_true", help="only items that are new today vs previous days")
    ap.add_argument("--output-json", required=True)
    ap.add_argument("--output-csv", required=True)
    args = ap.parse_args()

    snaps = load_snaps(args.data_dir, args.days)
    if not snaps:
        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.utcnow().isoformat()+"Z", "items": []}, f, indent=2)
        os.makedirs(os.path.dirname(args.output_csv) or ".", exist_ok=True)
        with open(args.output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f); writer.writerow(["asin","title","link","current_rank","category_url","days_seen","first_seen","keywords","idea_prompt"])
        print("No snapshots found; wrote empty reports.")
        return

    latest_time = snaps[-1]["when"]
    prev_snaps = [s for s in snaps if s["when"] < latest_time]
    latest_snaps = [s for s in snaps if s["when"] == latest_time]

    def key(cat_url, asin, title):
        return (cat_url or "") + "||" + (asin or title or "")

    history = {}
    for s in snaps:
        when = s["when"]
        cat = s["data"].get("category_url")
        for it in s["data"].get("items", []):
            k = key(cat, it.get("asin"), it.get("title"))
            e = history.setdefault(k, {"title": it.get("title"), "asin": it.get("asin"), "link": it.get("link"), "cat": cat, "ranks": [], "dates": []})
            r = rank_int(it.get("rank"))
            if r is not None:
                e["ranks"].append(r)
            e["dates"].append(when)

    prev_set = set()
    for s in prev_snaps:
        cat = s["data"].get("category_url")
        for it in s["data"].get("items", []):
            r = rank_int(it.get("rank"))
            if r is not None and r <= args.max_rank:
                prev_set.add(key(cat, it.get("asin"), it.get("title")))

    today = []
    for s in latest_snaps:
        cat = s["data"].get("category_url")
        for it in s["data"].get("items", []):
            r = rank_int(it.get("rank"))
            if r is not None and r <= args.max_rank:
                k = key(cat, it.get("asin"), it.get("title"))
                if not args.new_only or (args.new_only and k not in prev_set):
                    today.append((k, it, cat, r))

    rows, seen = [], set()
    for k, it, cat, r in sorted(today, key=lambda x: x[3]):
        if k in seen: continue
        seen.add(k)
        h = history.get(k, {})
        days_seen = len(set(d.date() for d in h.get("dates", [])))
        first_seen = min(h.get("dates", [])) if h.get("dates") else latest_time
        kws = keywords_from_title(it.get("title"))
        idea = f"Create an original, text-forward T-shirt design around: {', '.join(kws)}. Use clear fonts and simple iconography. Avoid trademarks."
        rows.append({
            "asin": it.get("asin"),
            "title": it.get("title"),
            "link": it.get("link"),
            "current_rank": r,
            "category_url": cat,
            "days_seen": days_seen,
            "first_seen": first_seen.isoformat()+"Z",
            "keywords": kws,
            "idea_prompt": idea
        })

    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.utcnow().isoformat()+"Z",
            "window_days": args.days,
            "max_rank": args.max_rank,
            "new_only": args.new_only,
            "items": rows
        }, f, indent=2, ensure_ascii=False)

    os.makedirs(os.path.dirname(args.output_csv) or ".", exist_ok=True)
    with open(args.output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["asin","title","link","current_rank","category_url","days_seen","first_seen","keywords","idea_prompt"])
        for row in rows:
            writer.writerow([
                row["asin"] or "",
                row["title"] or "",
                row["link"] or "",
                row["current_rank"] or "",
                row["category_url"] or "",
                row["days_seen"] or "",
                row["first_seen"] or "",
                ", ".join(row["keywords"]),
                row["idea_prompt"]
            ])
    print(f"Wrote {args.output_json} and {args.output_csv} with {len(rows)} items")

if __name__ == "__main__":
    main()
