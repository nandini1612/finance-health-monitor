# CashPulse — Personal & SME Finance Health Monitor

An end-to-end data pipeline that predicts cash-flow trouble and flags
suspicious transactions before they become a crisis, for individuals and
small businesses managing multiple accounts.

## Why this project

Cash flow problems are the single most commonly cited reason small
businesses fail — one widely cited figure, from a U.S. Bank study
popularized by the SBA-affiliated nonprofit SCORE, puts it at **82%**
([SCORE](https://www.score.org/articles/1-reason-small-businesses-fail-and-how-avoid-it/)).
Most owners find out they're in trouble only after it's already happened,
because nobody is forecasting forward or watching for the small anomalies
(a duplicate charge, a subscription that crept up, an unusually large
withdrawal) that erode a cash position over time. CashPulse simulates
that early-warning system: it ingests transactions into a proper
relational database, forecasts 30 days of cash flow with a machine
learning model (beating a naive baseline), flags anomalous transactions
with an unsupervised model, and surfaces all of it in a BI-style
dashboard.

**This project intentionally exercises the whole pipeline a data role
actually touches**: schema design (DBMS), ingestion/validation (ETL),
predictive + unsupervised modeling (ML), and stakeholder-facing reporting
(BI) — rather than stopping at a Jupyter notebook.

## Two tiers — start here, then go to `cloud/`

This repo has two versions of the same idea, meant to be built in order:

1. **Local quickstart (this file, repo root)** — SQLite, no signups, no
   cost, nothing to tear down. Proves the pipeline logic works and is the
   right place to learn SQL and the ML models without cloud complexity
   getting in the way.
2. **[Cloud edition](cloud/README.md)** — the same pipeline rebuilt on AWS
   RDS Postgres, dbt (ELT transformation), Apache Airflow (orchestration),
   Terraform (infrastructure as code), and GitHub Actions (CI). This is
   the tier that answers "have you used the tools real companies use" —
   go there once the local tier makes sense to you. It includes an
   explicit cost-safety checklist since real cloud accounts are involved.

"I built it local-first to prove the logic, then migrated it to a
cloud-native stack" is a genuinely strong thing to say in an interview —
better than either tier alone.

## Architecture (local quickstart)

```
generate_data.py          load_to_db.py            detect_anomalies.py
(synthetic CSVs)   --->    (validate + load)  --->   forecast_cashflow.py
                                   |                          |
                                   v                          v
                            data/finance.db  <----------------+
                            (SQLite: tables + BI-ready views)
                                   |
                    -------------------------------
                    |                              |
              dashboard/app.py              Power BI / Tableau
              (Streamlit)                   (see dashboard/POWER_BI_TABLEAU_GUIDE.md)
```

Data flows one direction: raw CSVs → validated relational tables → model
outputs written back into their own tables → BI layer queries clean views,
never raw tables. That separation (dumb storage, smart pipeline, thin BI
layer) is deliberate and worth explaining in an interview.

## Folder structure

```
finance-health-monitor/
├── data/
│   ├── generate_data.py        # synthetic data generator (Faker)
│   └── finance.db              # created by etl/load_to_db.py (gitignored)
├── sql/
│   ├── schema.sql               # DBMS: tables, keys, indexes, views
│   └── practice_queries.sql     # SQL practice set (joins -> window fns -> CTEs)
├── etl/
│   └── load_to_db.py            # CSV -> validated -> SQLite
├── ml/
│   ├── detect_anomalies.py      # Isolation Forest -> ml_anomaly_flags
│   └── forecast_cashflow.py     # Gradient boosted regressor -> ml_cashflow_forecast
├── dashboard/
│   ├── app.py                   # Streamlit BI-style dashboard
│   └── POWER_BI_TABLEAU_GUIDE.md
├── requirements.txt
└── README.md
```

## Setup & run order

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

python data/generate_data.py      # 1. generate ~18 months of synthetic transactions
python etl/load_to_db.py          # 2. validate + load into SQLite
python ml/detect_anomalies.py     # 3. flag suspicious transactions
python ml/forecast_cashflow.py    # 4. forecast next 30 days of cash flow
streamlit run dashboard/app.py    # 5. view the dashboard at localhost:8501
```

Then follow `dashboard/POWER_BI_TABLEAU_GUIDE.md` to connect the same
database to Power BI or Tableau for real BI-tool practice.

## About the data

All data is synthetically generated (`data/generate_data.py`, seeded for
reproducibility) — it is not real financial data. This is a standard,
legitimate approach for a portfolio project since real bank data isn't
something you can legally source or share. The generator injects realistic
patterns on purpose: recurring bills, payroll cycles, seasonal retail
bumps, and six intentional anomalies (large withdrawals, duplicate
charges, card-testing-style rapid small charges) so the ML step has real
signal to find — and so you can verify its output against ground truth
you control.

## What each layer demonstrates

- **DBMS**: a normalized schema (accounts, categories, merchants,
  transactions, budgets) plus purpose-built views that pre-aggregate for
  reporting — the schema doc in `sql/schema.sql` explains the design
  choices inline.
- **ETL**: `etl/load_to_db.py` resolves foreign keys, rejects invalid rows
  (bad amounts, bad types, missing dates) instead of silently loading
  garbage, and logs what it rejected.
- **ML**: an Isolation Forest for unsupervised anomaly detection (no
  labels needed — appropriate since nobody has labeled fraud data for
  their own transactions) and a gradient-boosted regressor for cash-flow
  forecasting, backtested against a naive seasonal baseline so the model's
  value is quantified rather than assumed.
- **BI**: a working Streamlit dashboard plus a guided path to build the
  same reporting in Power BI or Tableau against the same database.

## Extending it further

The obvious next steps here — Postgres instead of SQLite, Airflow instead
of running scripts by hand, Terraform-provisioned cloud infrastructure, a
dbt transformation layer, CI — aren't just ideas to mention in an
interview anymore. They're built and verified in **[`cloud/`](cloud/README.md)**.
Go there next.

If you want ideas beyond even that: swap the generator for a real
(permissioned) data source like the Plaid sandbox API, add a Slack/email
alert when a dbt test fails, or add a second BI tool (Looker Studio is
free and pairs well with a cloud SQL database) to compare against Power
BI/Tableau.

## Integrations & Proof

AWS and Power BI/Tableau are the two pieces of this project that need
your own account/install to actually complete — no one can click
"Publish" for you. **[`INTEGRATION_PROOF_GUIDE.md`](INTEGRATION_PROOF_GUIDE.md)**
is the short, specific path to doing both and capturing real proof
(a Terraform output, an AWS Console screenshot, a published Power BI
link) that shows up automatically in the dashboard's **Integrations**
section and slots straight into this README. Once you've done it, add a
section here following that guide's template.

## Resume / interview bullet points

Use whichever best fits the role you're applying for — these are written
to be true to what this project actually does, so adapt the numbers if
you change the data scale. **If you've also built the [cloud edition](cloud/README.md),
use its resume bullets instead/in addition — they cover Terraform, dbt,
Airflow, and CI, which is a stronger signal for most data engineering and
analytics roles than the local tier alone.**

- "Built an end-to-end personal/SME finance analytics pipeline (Python,
  SQL, scikit-learn, Streamlit) that ingests transaction data into a
  normalized relational database, forecasts 30-day cash flow with a
  gradient-boosted model that outperforms a naive baseline, and flags
  anomalous transactions via unsupervised learning."
- "Designed a normalized database schema and BI-ready SQL views to
  decouple data storage from reporting, enabling both a custom dashboard
  and Power BI/Tableau to consume the same clean data layer."
- "Implemented an ETL process with data validation and referential
  integrity checks, rejecting and logging malformed records rather than
  silently loading bad data."
- "Applied Isolation Forest for unsupervised fraud/anomaly detection on
  transaction data with no labeled ground truth, and validated model
  quality with engineered features like category-relative z-scores."

## A note on honesty

If you present this project (resume, interview, GitHub), be upfront that
the data is synthetic/simulated — that's completely normal for a learning
project and nobody will hold it against you. What matters is that the
pipeline, schema design, modeling choices, and evaluation methodology are
real and defensible, and they are.
