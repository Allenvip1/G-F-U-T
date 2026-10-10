#!/usr/bin/env python3
"""
抓 CME Daily Bulletin 的 PG62（金属期货），读取 COMEX 黄金(GC)、白银(SI)各合约月份的成交量和持仓量，
追加写入 data/futures_oi.csv（长表：date,metal,month,expiry,vol,oi,oi_chg）。
当天 PDF 没发布或不是 PDF 时安全退出，保留历史数据。

  python scripts/fut.py                 抓取当前这一份
  python scripts/fut.py --pdf a.pdf     解析本地 PDF（补历史用，见 backfill.py）
"""
import csv
import datetime as dt
import io
import re
import sys
from pathlib import Path

URL = "https://www.cmegroup.com/daily_bulletin/current/Section62_Metals_Futures_Products.pdf"
REFERER = "https://www.cmegroup.com/"
CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "futures_oi.csv"
HEADER = ["date", "metal", "month", "expiry", "vol", "oi", "oi_chg"]
MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
SECTIONS = {"GC FUT": "gold", "SI FUT": "silver"}     # 标题行前缀 -> 品种
ROW = re.compile(r"^([A-Z]{3})(\d{2}) .*?(\S+) (\S+) (\d+) (?:([+-]) (\d+)|UNCH)$")


def fetch_pdf() -> bytes:
    from curl_cffi import requests
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": REFERER}
    try:
        r = requests.get(URL, headers=headers, impersonate="chrome120", timeout=60)
        if r.status_code == 404:
            print("【提示】CME 当天的 PDF 尚未发布（404）。安全退出，保留历史数据。")
            sys.exit(0)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            print("【提示】CME 返回的不是 PDF。安全退出，保留历史数据。")
            sys.exit(0)
        return r.content
    except SystemExit:
        raise
    except Exception as e:
        raise RuntimeError(f"CME 官网连接或文件校验异常: {e}")


def pdf_text(data: bytes) -> str:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def bulletin_date(text: str) -> dt.date:
    m = re.search(r"BULLETIN # \d+@?[^\n]*?\b\w{3},\s+(\w{3} \d{2}, \d{4})", text)
    if not m:
        raise ValueError("找不到公报日期（页眉格式可能变了）")
    return dt.datetime.strptime(m.group(1), "%b %d, %Y").date()


def expiry_date(year: int, month: int) -> dt.date:
    """COMEX 黄金/白银期货最后交易日 = 交割月倒数第 3 个营业日（只排除周末，不考虑美国假日，误差最多 1 天）。"""
    d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    n = 0
    while True:
        if d.weekday() < 5:
            n += 1
            if n == 3:
                return d
        d -= dt.timedelta(days=1)


def parse(text: str):
    """返回 [(metal, month_label, expiry, vol, oi, oi_chg)]；vol 缺失(----)记 0。"""
    out, metal = [], None
    for ln in text.splitlines():
        ln = ln.strip()
        head = next((v for k, v in SECTIONS.items() if ln.startswith(k + " ")), None)
        if head:
            metal = head
            continue
        if re.match(r"^[A-Z0-9]{1,5} FUT ", ln):      # 其他期货品种的标题行
            metal = None
            continue
        if metal is None:
            continue
        m = ROW.match(ln)
        if not m or m.group(1) not in MONTHS:
            continue
        mon, yy, a, _b, oi, sign, chg = m.groups()
        if oi is None:
            continue
        vol = int(a) if a.isdigit() else 0
        year = 2000 + int(yy)
        oi_chg = 0 if sign is None else (int(chg) if sign == "+" else -int(chg))
        out.append((metal, f"{mon}{yy}", expiry_date(year, MONTHS[mon]), vol, int(oi), oi_chg))
    return out


def read_rows(path: Path = CSV_PATH):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {(r["date"], r["metal"], r["month"]): r for r in csv.DictReader(f)}


def upsert(day: dt.date, rows, path: Path = CSV_PATH) -> None:
    have = read_rows(path)
    for metal, month, exp, vol, oi, chg in rows:
        have[(day.isoformat(), metal, month)] = {
            "date": day.isoformat(), "metal": metal, "month": month, "expiry": exp.isoformat(),
            "vol": vol, "oi": oi, "oi_chg": chg}
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for k in sorted(have, key=lambda k: (k[0], k[1], have[k]["expiry"])):
            w.writerow(have[k])


TOTAL_PATH = Path(__file__).resolve().parent.parent / "data" / "futures_total.csv"
TOTAL_HEADER = ["date", "metal", "vol", "oi", "oi_chg"]


def read_totals(path: Path = TOTAL_PATH):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {(r["date"], r["metal"]): r for r in csv.DictReader(f)}


def write_totals(have, path: Path = TOTAL_PATH) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TOTAL_HEADER)
        w.writeheader()
        for k in sorted(have):
            w.writerow(have[k])


def process(data: bytes) -> dt.date:
    text = pdf_text(data)
    day = bulletin_date(text)
    rows = parse(text)
    for metal in ("gold", "silver"):
        n = sum(1 for r in rows if r[0] == metal)
        if n < 5:
            raise ValueError(f"{metal} 只解析出 {n} 个合约，格式可能变了")
    upsert(day, rows)
    tot = read_totals()
    for metal in ("gold", "silver"):
        sel = [r for r in rows if r[0] == metal]
        tot[(day.isoformat(), metal)] = {"date": day.isoformat(), "metal": metal, "vol": sum(r[3] for r in sel),
                                         "oi": sum(r[4] for r in sel), "oi_chg": sum(r[5] for r in sel)}
    write_totals(tot)
    return day


def main() -> None:
    if "--pdf" in sys.argv:
        data = Path(sys.argv[sys.argv.index("--pdf") + 1]).read_bytes()
    else:
        data = fetch_pdf()
    day = process(data)
    print(f"【成功】{day} 已写入 {CSV_PATH.name}")


if __name__ == "__main__":
    main()
