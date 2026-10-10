#!/usr/bin/env python3
"""把 data/*.csv 合成页面数据，写进 index.html 的 <script id="fut-data">（页面是纯静态的，数据内嵌）。
"""
import csv
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HTML = ROOT / "index.html"


def rd(name):
    p = DATA / name
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    out = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    totals = defaultdict(list)
    for r in rd("futures_total.csv"):
        totals[r["metal"]].append([r["date"], int(r["vol"]), int(r["oi"]), int(r["oi_chg"])])
    for metal, pf in (("gold", "price_gold.csv"), ("silver", "price_silver.csv")):
        out[metal] = {
            "price": [[r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])] for r in rd(pf)],
            "total": sorted(totals[metal]),
        }
    js = "window.FUT_DATA=" + json.dumps(out, separators=(",", ":"), ensure_ascii=False) + ";"
    html = HTML.read_text(encoding="utf-8")
    new, n = re.subn(r'(<script id="fut-data">).*?(</script>)', lambda m: m.group(1) + js + m.group(2), html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("index.html 里没找到 <script id=\"fut-data\">")
    HTML.write_text(new, encoding="utf-8")
    print(f"【成功】已写入 index.html：黄金 {len(out['gold']['total'])} 天，白银 {len(out['silver']['total'])} 天")


if __name__ == "__main__":
    main()
