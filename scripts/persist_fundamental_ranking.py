"""Persist data/fundamental_ranking.json into the fundamental_ranking table."""
import json
from app.db import SessionLocal, init_db
from app import models as m

init_db()  # create fundamental_ranking table if missing

data = json.load(open("data/fundamental_ranking.json", encoding="utf-8"))
s = SessionLocal()
tick2id = {c.ticker: c.id for c in s.query(m.Company).all()}

n = 0
for tick, d in data.items():
    cid = tick2id.get(tick)
    if cid is None:
        print("skip (no company):", tick); continue
    row = s.query(m.FundamentalRanking).filter_by(company_id=cid).first()
    if row is None:
        row = m.FundamentalRanking(company_id=cid)
        s.add(row)
    row.rank = d["rank"]
    row.composite_score = d["composite_score"]
    row.completeness = d["completeness"]
    row.business_quality = d["business_quality"]
    row.decision_band = d["band"]
    row.stock_cagr_pct = d["stock_cagr"]
    row.stock_cagr_years = d["stock_years"]
    row.sales_cagr_pct = d["sales_cagr"]
    row.sales_cagr_flag = d["sales_flag"]
    row.sales_cagr_note = d["sales_note"]
    row.profit_cagr_pct = d["profit_cagr"]
    row.profit_cagr_flag = d["profit_flag"]
    row.profit_cagr_note = d["profit_note"]
    row.roe_pct = d["roe"]
    row.roe_flag = d["roe_flag"]
    row.roe_note = d["roe_note"]
    n += 1

s.commit()
print(f"persisted {n} ranking rows")
