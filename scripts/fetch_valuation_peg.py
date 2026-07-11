"""Fetch current PE + YoY earnings growth from Yahoo and compute PEG valuation.

PEG = trailing PE / growth%   (growth% in whole numbers, e.g. 25 for 25%)
  PEG < 1  -> Undervalued
  PEG >= 1 -> Overvalued
Growth source priority (flagged):
  C  = our computed Profit CAGR (from filings)
  Y  = Yahoo trailing YoY earnings growth
  Sp = Sales CAGR used as growth proxy
Valuation is N/A when PE is missing/negative (loss-making) or no growth available.
"""
import httpx, json, io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

stock = json.load(open("data/stock_cagr.json", encoding="utf-8"))
rank  = json.load(open("data/fundamental_ranking.json", encoding="utf-8"))

h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
c = httpx.Client(headers=h, timeout=30, follow_redirects=True)
c.get("https://fc.yahoo.com")
crumb = c.get("https://query1.finance.yahoo.com/v1/test/getcrumb").text

out = {}
for tick, sd in stock.items():
    sym = (sd or {}).get("symbol")
    pe = None; egrowth = None
    if sym:
        url = (f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
               f"?modules=summaryDetail,financialData&crumb={crumb}")
        try:
            r = c.get(url)
            if r.status_code == 200:
                d = r.json()["quoteSummary"]["result"][0]
                pe = d.get("summaryDetail", {}).get("trailingPE", {}).get("raw")
                egrowth = d.get("financialData", {}).get("earningsGrowth", {}).get("raw")
        except Exception:
            pass
        time.sleep(0.2)
    out[tick] = {"symbol": sym, "trailing_pe": round(pe, 2) if pe else None,
                 "yoy_earnings_growth_pct": round(egrowth*100, 1) if egrowth is not None else None}

# compute PEG
for tick, d in out.items():
    pe = d["trailing_pe"]
    r = rank.get(tick, {})
    profit_cagr = r.get("profit_cagr")
    sales_cagr = r.get("sales_cagr")
    yoy = d["yoy_earnings_growth_pct"]
    growth = None; gsrc = "NA"
    if profit_cagr and profit_cagr > 0:
        growth, gsrc = profit_cagr, "C"          # computed multi-year Profit CAGR (best)
    elif sales_cagr and sales_cagr > 0:
        growth, gsrc = sales_cagr, "S"            # sustainable Sales CAGR (mgmt/computed/guidance)
    elif yoy and yoy > 0:
        growth, gsrc = yoy, "Y"                   # Yahoo 1-yr YoY earnings growth (volatile fallback)
    peg = None; verdict = "N/A"
    if pe and pe > 0 and growth:
        peg = round(pe/growth, 2)
        verdict = "Undervalued" if peg < 1 else "Overvalued"
    elif pe is not None and pe <= 0:
        verdict = "Loss-making (PE n/a)"
    d.update({"growth_pct": growth, "growth_source": gsrc, "peg": peg, "verdict": verdict})

json.dump(out, open("data/valuation_peg.json", "w"), indent=2)

print(f"{'Ticker':12} {'PE':>7} {'Growth%':>8}{'':2} {'PEG':>6}  Verdict")
print("-"*52)
for t in sorted(out, key=lambda k: (out[k]['peg'] is None, out[k]['peg'] or 0)):
    d = out[t]
    pe = f"{d['trailing_pe']}" if d['trailing_pe'] else "n/a"
    g = f"{d['growth_pct']}" if d['growth_pct'] else "n/a"
    peg = f"{d['peg']}" if d['peg'] is not None else "n/a"
    print(f"{t:12} {pe:>7} {g:>8}{d['growth_source']:<2} {peg:>6}  {d['verdict']}")
