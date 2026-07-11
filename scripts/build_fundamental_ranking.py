"""
Build a fundamentals-based ranking of the 23 analyzed companies.

Factors (each flagged for source/quality; gaps allowed):
  - business_quality : concall composite total_0_100 (ALL 23)  -> "overall business metrics"
  - stock_cagr_pct   : Yahoo Finance, 5y or since-listing (22/23)
  - sales_cagr_pct   : management-disclosed historical CAGR or computed from FY figures
  - profit_cagr_pct  : computed from multi-year PAT where available (sparse)
  - roe_pct          : disclosed ROE, else ROCE proxy (flagged)

Flags: M=management-disclosed historical, C=computed from our FY data,
       G=forward guidance only, P=ROCE used as ROE proxy, D=dated, NA=missing
"""
import json, io, sys, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

stock = json.load(open("data/stock_cagr.json", encoding="utf-8"))
bq    = json.load(open("data/bq_scores.json", encoding="utf-8"))
fy    = json.load(open("data/bq_and_fy.json", encoding="utf-8"))

def cagr(v0, v1, yrs):
    if v0 and v1 and v0 > 0 and yrs > 0:
        return round(((v1/v0)**(1/yrs) - 1)*100, 1)
    return None

# ---- hand-encoded management-disclosed fundamentals (value, flag, note) ----
# sales CAGR (historical unless flagged G)
SALES = {
 "AARTIPHARM": (19.0, "M", "~18-20% long-run CAGR (150cr FY12->1500cr)"),
 "ACUTAAS":    (25.0, "M", "25% CAGR over last 10-11 yrs"),
 "ASTRAMICRO": (20.0, "M", "20% CAGR over last 5 yrs"),
 "CENTUM":     (18.0, "G", "targeting 18-20% (forward only)"),
 "GOKEX":      (None, "NA", "no historical CAGR disclosed"),
 "HFCL":       (None, "NA", "overall revenue ~flat; only export/product segment CAGR high"),
 "HLEGLAS":    (23.0, "M", "23-24% CAGR last 5 yrs"),
 "IDEAFORGE":  (None, "NA", "not disclosed"),
 "INOXINDIA":  (24.0, "M", "24% CAGR FY21-FY24"),
 "KRN":        (None, "NA", "not disclosed (recent listing)"),
 "NEOGEN":     (30.0, "G", "targets >30% (forward)"),
 "PRIVISCL":   (19.5, "M", "~19-20% CAGR over 20 yrs"),
 "QPOWER":     (None, "NA", "recent listing; 1yr +154% not annualizable"),
 "RAIN":       (None, "NA", "not disclosed"),
 "SAILIFE":    (15.7, "C", "FY24 1465->FY25 1695 (1yr only)"),
 "SAMBHV":     (None, "NA", "not disclosed"),
 "SANSERA":    (None, "NA", "only aero-segment 25-30%; overall not disclosed"),
 "SBCL":       (24.5, "M", "24.48% CAGR FY20-FY24"),
 "SHADOWFAX":  (32.0, "M", "32% CAGR FY23-FY25"),
 "SJS":        (25.0, "G", "~25% medium-term plan (part acq-led)"),
 "STLTECH":    (None, "NA", "revenue declined; 23-25% is forward target"),
 "SYRMA":      (24.1, "C", "FY24 3154->FY26 4857 (2yr)"),
 "TDPOWERSYS": (35.8, "C", "FY24 1017->FY26 1878 (2yr)"),
}
# ROE (disclosed) else ROCE proxy
ROE = {
 "AARTIPHARM": (18.0, "P", "ROCE 18% FY24 (ROE n/d)"),
 "ACUTAAS":    (None, "NA", "not disclosed in hits"),
 "ASTRAMICRO": (14.0, "M", "ROE ~14% FY25"),
 "CENTUM":     (22.0, "P", "ROCE 20-25% (EMS) proxy"),
 "GOKEX":      (25.0, "P", "ROCE ~25% (ROE n/d)"),
 "HFCL":       (None, "NA", "not disclosed"),
 "HLEGLAS":    (30.0, "MD", "ROE/ROCE >30% but dated FY21; recent profit fell"),
 "IDEAFORGE":  (None, "NA", "loss-making (PAT negative)"),
 "INOXINDIA":  (28.0, "M", "ROE 28% FY23"),
 "KRN":        (None, "NA", "not disclosed"),
 "NEOGEN":     (None, "NA", "20% is a target, not current"),
 "PRIVISCL":   (20.0, "M", "ROE ~20% FY26"),
 "QPOWER":     (None, "NA", "not disclosed"),
 "RAIN":       (None, "NA", "not disclosed"),
 "SAILIFE":    (9.5,  "M", "ROE 9-10% (ROCE 12%)"),
 "SAMBHV":     (16.0, "P", "ROCE 16% (ROE n/d)"),
 "SANSERA":    (19.0, "P", "ROCE ~18-20% proxy"),
 "SBCL":       (33.0, "M", "ROE ~33%, ROCE 36% FY23"),
 "SHADOWFAX":  (None, "NA", "not disclosed (recently profitable)"),
 "SJS":        (16.5, "M", "ROE 16.5%, ROCE 27%"),
 "STLTECH":    (None, "NA", "ROCE target 20%; actual low/negative"),
 "SYRMA":      (22.0, "P", "ROCE ~22% proxy (ROE lower)"),
 "TDPOWERSYS": (None, "NA", "not disclosed in transcript"),
}

TICKERS = [t for t in bq]
rows = {}
for t in TICKERS:
    st = stock.get(t) or {}
    revd = {int(k): v for k, v in fy.get(t, {}).get("revenue_by_fy", {}).items()}
    patd = {int(k): v for k, v in fy.get(t, {}).get("pat_by_fy", {}).items()}
    # profit CAGR from our multi-year PAT
    pcagr = None; pflag = "NA"; pnote = "insufficient multi-year PAT"
    yrs_pat = sorted(patd)
    if len(yrs_pat) >= 2:
        y0, y1 = yrs_pat[0], yrs_pat[-1]
        pcagr = cagr(patd[y0], patd[y1], y1 - y0)
        if pcagr is not None:
            pflag = "C"; pnote = f"PAT FY{y0} {patd[y0]}->FY{y1} {patd[y1]}"
    s_val, s_flag, s_note = SALES[t]
    r_val, r_flag, r_note = ROE[t]
    rows[t] = {
        "business_quality": bq[t]["total"],
        "band": bq[t]["band"],
        "stock_cagr": st.get("stock_cagr_pct"),
        "stock_years": st.get("years"),
        "sales_cagr": s_val, "sales_flag": s_flag, "sales_note": s_note,
        "profit_cagr": pcagr, "profit_flag": pflag, "profit_note": pnote,
        "roe": r_val, "roe_flag": r_flag, "roe_note": r_note,
    }

# ---- normalize each factor to 0-100 among companies that HAVE it ----
def norm_factor(key):
    vals = [(t, rows[t][key]) for t in rows if rows[t][key] is not None]
    if not vals: return {}
    lo = min(v for _, v in vals); hi = max(v for _, v in vals)
    span = (hi - lo) or 1
    return {t: (v - lo)/span*100 for t, v in vals}

# winsorize stock CAGR to reduce short-window IPO distortion (cap at 100%)
for t in rows:
    sc = rows[t]["stock_cagr"]
    if sc is not None:
        rows[t]["stock_cagr_adj"] = min(sc, 100.0)
    else:
        rows[t]["stock_cagr_adj"] = None

N_bq   = norm_factor("business_quality")
N_st   = norm_factor("stock_cagr_adj")
N_sa   = norm_factor("sales_cagr")
N_roe  = norm_factor("roe")

# ---- valuation factor: reward LOW PEG (undervalued) ----
# load PEG from valuation_peg.json if present; cap PEG at 4 so extreme
# overvaluation doesn't dominate the min-max spread. Lower PEG => higher score.
import os
peg_map = {}
if os.path.exists("data/valuation_peg.json"):
    vdata = json.load(open("data/valuation_peg.json", encoding="utf-8"))
    for t in rows:
        peg = (vdata.get(t) or {}).get("peg")
        rows[t]["peg"] = peg
        if peg is not None and peg > 0:
            peg_map[t] = min(peg, 4.0)
        else:
            rows[t]["peg"] = peg
else:
    for t in rows:
        rows[t]["peg"] = None

N_val = {}
if peg_map:
    lo = min(peg_map.values()); hi = max(peg_map.values()); span = (hi - lo) or 1
    # invert: lowest PEG -> 100, highest -> 0
    N_val = {t: (hi - v)/span*100 for t, v in peg_map.items()}

W = {"bq": 0.30, "st": 0.25, "sa": 0.15, "roe": 0.10, "val": 0.20}
for t in rows:
    parts = []
    if t in N_bq:  parts.append((W["bq"],  N_bq[t]))
    if t in N_st:  parts.append((W["st"],  N_st[t]))
    if t in N_sa:  parts.append((W["sa"],  N_sa[t]))
    if t in N_roe: parts.append((W["roe"], N_roe[t]))
    if t in N_val: parts.append((W["val"], N_val[t]))
    wsum = sum(w for w, _ in parts)
    score = sum(w*v for w, v in parts)/wsum if wsum else 0
    n_have = sum(1 for k in ("stock_cagr","sales_cagr","roe","business_quality","peg")
                 if rows[t].get(k) is not None)
    rows[t]["composite_score"] = round(score, 1)
    rows[t]["completeness"] = f"{n_have}/5"

ranked = sorted(rows.items(), key=lambda kv: kv[1]["composite_score"], reverse=True)
for i, (t, d) in enumerate(ranked, 1):
    rows[t]["rank"] = i

json.dump(rows, open("data/fundamental_ranking.json", "w"), indent=2)

def fmt(v, suf="%"):
    return f"{v}{suf}" if v is not None else "  n/a"

print(f"{'#':>2} {'Ticker':12} {'Score':>5} {'BizQ':>5} {'StkCAGR':>8} {'SalesCAGR':>9} {'ProfCAGR':>8} {'ROE':>6} {'PEG':>6} {'Compl':>5}")
print("-"*90)
for i, (t, d) in enumerate(ranked, 1):
    sc = d["stock_cagr"]
    scs = (f"{sc}%" + ("*" if (d['stock_years'] or 9) < 3 else "")) if sc is not None else "n/a"
    peg = d.get("peg")
    pegs = (f"{peg}" + ("U" if peg < 1 else "O")) if peg is not None else "n/a"
    print(f"{i:>2} {t:12} {d['composite_score']:>5} {d['business_quality']:>5} "
          f"{scs:>8} {fmt(d['sales_cagr']):>9}{d['sales_flag']:<2} "
          f"{fmt(d['profit_cagr']):>7}{d['profit_flag']:<2} {fmt(d['roe']):>5}{d['roe_flag']:<3} {pegs:>6} {d['completeness']:>5}")
print("\n* = stock CAGR window <3y (since-listing, annualized; treat as inflated)")
print("PEG: U=undervalued(<1) O=overvalued(>=1)")
print("flags: M=mgmt-disclosed  C=computed  G=forward-guidance-only  P=ROCE-proxy  MD=dated  NA=missing")
