"""Add PEG valuation columns to fundamental_ranking and populate from JSON."""
import json
from sqlalchemy import text
from app.db import SessionLocal, engine
from app import models as m

NEW_COLS = {
    "trailing_pe": "FLOAT",
    "valuation_growth_pct": "FLOAT",
    "valuation_growth_source": "VARCHAR(4)",
    "peg_ratio": "FLOAT",
    "valuation_verdict": "VARCHAR(32)",
}

with engine.begin() as conn:
    existing = {r[1] for r in conn.execute(text("PRAGMA table_info(fundamental_ranking)"))}
    for col, typ in NEW_COLS.items():
        if col not in existing:
            conn.execute(text(f"ALTER TABLE fundamental_ranking ADD COLUMN {col} {typ}"))
            print("added column", col)

val = json.load(open("data/valuation_peg.json", encoding="utf-8"))
s = SessionLocal()
tick2id = {c.ticker: c.id for c in s.query(m.Company).all()}
n = 0
for tick, d in val.items():
    cid = tick2id.get(tick)
    if cid is None:
        continue
    row = s.query(m.FundamentalRanking).filter_by(company_id=cid).first()
    if row is None:
        continue
    row.trailing_pe = d.get("trailing_pe")
    row.valuation_growth_pct = d.get("growth_pct")
    row.valuation_growth_source = d.get("growth_source")
    row.peg_ratio = d.get("peg")
    row.valuation_verdict = d.get("verdict")
    n += 1
s.commit()
print(f"updated {n} rows with PEG valuation")
