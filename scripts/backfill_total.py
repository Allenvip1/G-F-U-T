#!/usr/bin/env python3
"""一次性补历史：PG62 的 Wayback 存档有缺日，缺的日子用早先下载的 PG02B 公报（只含期货合计，无分月）补上
黄金/白银期货的总成交量、总持仓量，写入 data/futures_total.csv（已有的日期不覆盖）。
用法： python scripts/backfill_total.py <存放 PG02B pdf 的目录>
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fut

LINE = re.compile(r"^(GC|SI) COMEX (?:GOLD|SILVER) FUTURES .*?(\d+) (\d+) (?:([+-]) (\d+)|UNCH) .*$")


def main() -> None:
    folder = Path(sys.argv[1])
    have = fut.read_totals()
    sums = {}                                              # 先用 PG62 逐合约数据合计（优先）
    for (d, metal, _m), r in fut.read_rows().items():
        s = sums.setdefault((d, metal), [0, 0, 0])
        s[0] += int(r["vol"]); s[1] += int(r["oi"]); s[2] += int(r["oi_chg"])
    for k, s in sums.items():
        have[k] = {"date": k[0], "metal": k[1], "vol": s[0], "oi": s[1], "oi_chg": s[2]}
    added = 0
    for p in sorted(folder.glob("*.pdf")):
        try:
            text = fut.pdf_text(p.read_bytes())
            day = fut.bulletin_date(text).isoformat()
        except Exception as e:
            print(p.name, "跳过：", e)
            continue
        for ln in text.splitlines():
            ln = ln.strip()
            if not (ln.startswith("GC COMEX GOLD FUTURES") or ln.startswith("SI COMEX SILVER FUTURES")):
                continue
            metal = "gold" if ln.startswith("GC") else "silver"
            toks = re.sub(r"([+-])(?=\d)", r" \1 ", ln).split()
            s = next((i for i, t in enumerate(toks) if t in ("+", "-")), None)
            if s is None:
                continue
            nums = [int(t) for t in toks[4:s] if t.isdigit()]       # 前面: 成交量...(Globex/场内/合计)；s-1 = 总持仓量
            vol, oi, chg = nums[0], nums[-1],int(toks[s + 1]) * (1 if toks[s] == "+" else -1)
            if (day, metal) not in have:
                have[(day, metal)] = {"date": day, "metal": metal, "vol": vol, "oi": oi, "oi_chg": chg}
                added += 1
    fut.write_totals(have)
    print(f"新增 {added} 条，合计 {len(have)} 条")


if __name__ == "__main__":
    main()
