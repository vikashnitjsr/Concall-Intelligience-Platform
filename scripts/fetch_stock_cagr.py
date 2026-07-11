import httpx, datetime as dt, math, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TICKERS = ["AARTIPHARM","ACUTAAS","ASTRAMICRO","CENTUM","GOKEX","HFCL","HLEGLAS",
           "IDEAFORGE","INOXINDIA","KRN","NEOGEN","PRIVISCL","QPOWER","RAIN",
           "SAILIFE","SAMBHV","SANSERA","SBCL","SHADOWFAX","SJS","STLTECH",
           "SYRMA","TDPOWERSYS"]
# manual overrides where NSE symbol != our ticker
OVERRIDE = {}

H = {"User-Agent": "Mozilla/5.0"}
out = {}
for t in TICKERS:
    sym = OVERRIDE.get(t, t)
    got = None
    for suffix in (".NS", ".BO"):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}{suffix}?range=5y&interval=1mo"
        try:
            r = httpx.get(url, headers=H, timeout=30)
            if r.status_code != 200:
                continue
            res = r.json()["chart"]["result"][0]
            ts = res["timestamp"]; cl = res["indicators"]["quote"][0]["close"]
            pairs = [(ts[i], cl[i]) for i in range(len(ts)) if cl[i] is not None]
            if len(pairs) < 6:
                continue
            t0, p0 = pairs[0]; t1, p1 = pairs[-1]
            yrs = (t1 - t0) / (365.25*24*3600)
            cagr = (p1/p0)**(1/yrs) - 1 if yrs > 0.5 and p0 > 0 else None
            got = {"symbol": f"{sym}{suffix}", "first_date": str(dt.date.fromtimestamp(t0)),
                   "first_px": round(p0,2), "last_date": str(dt.date.fromtimestamp(t1)),
                   "last_px": round(p1,2), "years": round(yrs,2),
                   "stock_cagr_pct": round(cagr*100,1) if cagr is not None else None}
            break
        except Exception as e:
            continue
    out[t] = got
    if got:
        print(f"{t:12} {got['symbol']:16} {got['first_date']}->{got['last_date']} "
              f"({got['years']}y) {got['first_px']:>8}->{got['last_px']:>8}  CAGR={got['stock_cagr_pct']}%")
    else:
        print(f"{t:12} -- NO DATA --")

with open("data/stock_cagr.json","w",encoding="utf-8") as f:
    json.dump(out, f, indent=2)
print("\nsaved data/stock_cagr.json")
