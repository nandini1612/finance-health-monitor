# CashPulse — Personal & SME Finance Health Monitor

An end-to-end data pipeline that predicts cash-flow trouble and flags
suspicious transactions before they become a crisis, for individuals and
small businesses managing multiple accounts.

**[Live demo →](https://finance-health-monitor.streamlit.app/)** — log in with
`demo` / `CashPulseDemo!26` (all 5 accounts), or `nina` / `NinaDemo!26` (just
Nina's personal account, to see the per-login access restriction in action).
These credentials are meant to be public — see **Authentication** below.

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
with an unsupervised model, tracks budget vs. actual spend and recurring
subscriptions, and surfaces all of it in a BI-style dashboard.

**This project intentionally exercises the whole pipeline a data role
actually touches**: schema design (DBMS), ingestion/validation (ETL vs.
ELT), predictive + unsupervised modeling (ML), orchestration and infra
(Airflow, Terraform), and stakeholder-facing reporting (BI) — rather than
stopping at a Jupyter notebook.

## Two tiers, built in order

This repo has two versions of the same idea:

1. **Local quickstart** (what you're reading) — SQLite, no signups, no
   cost, nothing to tear down. Proves the pipeline logic works and is the
   right place to learn SQL and the ML models without cloud complexity
   getting in the way. This is what's deployed at the live demo link above.
2. **Cloud edition** (`cloud/`) — the same pipeline rebuilt on Postgres
   (standing in for AWS RDS), **dbt** for ELT transformation, **Apache
   Airflow** for orchestration, **Terraform** for infrastructure as code,
   and **GitHub Actions** for CI. This is the tier that answers "have you
   used the tools real companies use."

"I built it local-first to prove the logic, then migrated it to a
cloud-native stack" is a genuinely strong thing to say in an interview —
better than either tier alone.

## Key design decisions

The reasoning behind a few choices here is worth more than the code
itself in an interview — pulled up front rather than left buried in
inline comments:

- **ETL locally, ELT in the cloud, on purpose.** The local tier validates
  and transforms data *before* loading it (`etl/load_to_db.py` rejects bad
  rows up front). The cloud tier flips this: `cloud/pipeline/load_raw.py`
  lands raw, unvalidated CSVs straight into a `raw` schema, and dbt does
  all validation and transformation downstream (`staging` → `analytics`).
  That's not an inconsistency — it's the two dominant real-world patterns,
  built once each, so both can be spoken to directly instead of one being
  a guess.
- **Postgres instead of a dedicated warehouse (Redshift/Snowflake/BigQuery).**
  This project committed to strictly free-tier-safe AWS services.
  Redshift Serverless's "free" tier is a time-boxed trial, not a real free
  tier, so it was excluded to avoid billing risk. Running dbt directly
  against Postgres — as both the operational and analytical store — is a
  completely normal pattern at this data scale, and plenty of real
  companies do exactly this instead of paying for a warehouse they don't
  need yet.
- **One-way data flow, both tiers.** Raw → validated → modeled →
  BI-ready, always in that order — the BI layer never touches a raw table
  directly in either tier.
- **dbt tests gate the pipeline, not just document it.** 18 dbt tests
  (uniqueness, not-null, referential integrity) run as part of `dbt test`,
  and CI fails the build if any of them fail — the same gate a real data
  team would put in front of anything downstream trusting this data.
- **ML is backtested against a naive baseline, not just fit and shipped.**
  The cash-flow forecaster's MAE is compared against a naive seasonal
  baseline every run (`cloud/pipeline/ml_forecast.py` /
  `ml/forecast_cashflow.py`) — "the model beats a naive guess" is a
  claim this project can actually back up with a number, not an assumption.
- **Honest about what was verified vs. what needs a human.** The cloud
  tier's dbt project, ML pipeline, and Airflow DAG were all run and
  verified end to end against a real local Postgres instance. Terraform
  against real AWS and the Airflow Docker stack need a human's own AWS
  account and Docker daemon to actually execute — flagged as such rather
  than claimed. The same honesty carries into the dashboard itself: its
  "Integrations" panel reads the real environment live and only ever
  shows a connection that's actually there.
- **A LocalStack path exists for the AWS-without-a-credit-card case.**
  AWS requires a card on file to create any account, even a free-tier-only
  one. `cloud/terraform-localstack/` provisions a genuinely real S3
  bucket against LocalStack (a local AWS API simulator) with zero AWS
  account needed — paired with a real Postgres run locally, since
  LocalStack's free tier mocks RDS's API but doesn't run a database behind
  it. That limitation is stated directly rather than glossed over.
- **Real authentication, not a hand-rolled password check.** The
  dashboard sits behind [streamlit-authenticator](https://github.com/mkhorasani/Streamlit-Authenticator)
  (bcrypt-hashed credentials, a signed session cookie, a logout button) —
  "don't roll your own auth" applies to a portfolio project too. Logins
  are also scoped per-account (`nina` only ever sees Nina's account; `demo`
  sees all five), which is what makes this real access control rather
  than just a locked door. The credentials themselves are intentionally
  public and checked into `.streamlit/secrets.toml`: every login sees the
  same synthetic dataset, never real financial data, so there's nothing to
  protect — and a private, gitignored secrets file would break the
  "clone it, or open the live link, and it just works" promise this whole
  project is built around. See **Authentication** below.
- **Recommendations are rules, not a model.** The "Prescriptive
  Recommendations" panel deliberately does not use ML: it's plain
  arithmetic (this month's overage, or a hypothetical cut %) applied to
  the same numbers already shown in the KPI row and the forecast chart. A
  black-box model producing "spend less on X" would be strictly harder to
  trust and easier to fake than a rule a reader can verify by hand in ten
  seconds — the honest choice here was to *not* reach for ML just because
  the rest of the project has some.

## Authentication

The live demo (and a local run) requires logging in:

| Username | Password | Sees |
|---|---|---|
| `demo` | `CashPulseDemo!26` | All 5 demo accounts |
| `nina` | `NinaDemo!26` | Only Nina's Personal Checking |

Both are also shown directly on the app's own login screen. Credentials
and per-login account access live in `.streamlit/secrets.toml`
(`[auth.credentials]` and `[auth.account_access]`) — edit that file to
add logins, change passwords (re-hash with
`streamlit_authenticator.Hasher().hash("new-password")`), or change who
sees which account. This is SQLite-and-Postgres-tier agnostic: it gates
the app itself, not either database, so it works the same way regardless
of `DATABASE_URL`.

## Architecture

**Local quickstart:**

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
              (Streamlit)                   (native ODBC/Postgres connector)
```

**Cloud edition:**

```
data/generate_data.py  (simulated source system)
        |
        v
cloud/pipeline/load_raw.py  ---------->  Postgres: raw.*  (unvalidated landing tables)
                                                |
                                                v
                                    dbt: staging.stg_*  (typed, cleaned views)
                                                |
                                                v
                                    dbt: analytics.*  (fact/dim tables + marts, tested)
                                          |                    |
                                          v                    v
                          cloud/pipeline/ml_anomaly.py   ml_forecast.py
                                          |                    |
                                          v                    v
                                    Postgres: ml.anomaly_flags / ml.cashflow_forecast
                                                |
                                    ------------+------------
                                    |                        |
                              dashboard/app.py        Power BI / Tableau
                              (DATABASE_URL set)      (native Postgres connector)
```

Orchestrated end-to-end by the Airflow DAG in `cloud/airflow/`.
Infrastructure (a Postgres instance + an S3 landing bucket) is provisioned
by `cloud/terraform/` (real AWS) or `cloud/terraform-localstack/` (free,
no-account alternative). Both tiers keep the same separation — dumb
storage, smart pipeline, thin BI layer — so the BI layer only ever reads
clean, tested views, never raw tables.

## Folder structure

```
finance-health-monitor/
├── .streamlit/
│   ├── config.toml              # theme
│   └── secrets.toml              # auth credentials + per-login account access (see Authentication)
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
│   └── app.py                   # Streamlit BI-style dashboard (both tiers)
├── cloud/                       # Postgres + dbt + Airflow + Terraform edition
│   ├── pipeline/                # load_raw, ML jobs, orchestration tasks
│   ├── dbt/cashpulse_dbt/       # staging -> marts, 18 dbt tests
│   ├── airflow/                 # DAG + docker-compose
│   ├── terraform/               # real AWS: RDS + S3
│   └── terraform-localstack/    # free, no-account alternative: S3 only
├── .github/workflows/ci.yml     # lint + dbt test + pytest on every push
├── requirements.txt
└── README.md
```

## Setup & run order

**Local quickstart:**

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

(The dashboard also generates this data automatically on first run if it's
missing — e.g. right after cloning — so steps 1-4 are optional convenience,
not a hard requirement.)

**Cloud edition**, once you have a Postgres instance reachable (real RDS
via `cloud/terraform/`, or local/Docker Postgres paired with the free
LocalStack S3 path in `cloud/terraform-localstack/`):

```bash
pip install -r cloud/requirements.txt
export DATABASE_URL=postgresql://user:pass@host:5432/cashpulse
python cloud/pipeline/run_pipeline.py     # generate -> load raw -> dbt run/test -> ML
streamlit run dashboard/app.py            # same dashboard, same DATABASE_URL
```

`cloud/pipeline/run_pipeline.py` runs the whole chain in one shot; see the
files under `cloud/` for how each stage works individually, and
`cloud/airflow/` to run the same chain as an orchestrated DAG instead of a
script.

## About the data

All data is synthetically generated (`data/generate_data.py`, seeded for
reproducibility) — it is not real financial data. This is a standard,
legitimate approach for a portfolio project since real bank data isn't
something you can legally source or share. The generator injects realistic
patterns on purpose: recurring bills with stable per-merchant pricing,
payroll cycles, seasonal retail bumps, budgets sized off each account's
own real spending (not arbitrary numbers), and six intentional anomalies
(large withdrawals, duplicate charges, card-testing-style rapid small
charges) so the ML step has real signal to find — and so you can verify
its output against ground truth you control.

## What each layer demonstrates

- **DBMS**: a normalized schema (accounts, categories, merchants,
  transactions, budgets) plus purpose-built views/marts that pre-aggregate
  for reporting — `sql/schema.sql` and the dbt models under `cloud/dbt/`
  explain the design choices inline.
- **ETL / ELT**: `etl/load_to_db.py` resolves foreign keys and rejects
  invalid rows before loading (ETL); `cloud/pipeline/load_raw.py` +
  dbt validate and transform after loading (ELT) — both built, not just
  one assumed.
- **ML**: an Isolation Forest for unsupervised anomaly detection (no
  labels needed — appropriate since nobody has labeled fraud data for
  their own transactions) and a gradient-boosted regressor for cash-flow
  forecasting, backtested against a naive seasonal baseline so the model's
  value is quantified rather than assumed.
- **Orchestration & IaC**: an Airflow DAG that gates ML tasks behind a dbt
  test pass, and Terraform-provisioned infrastructure (real AWS, or a
  free LocalStack alternative).
- **CI**: GitHub Actions runs lint, the full dbt build/test cycle against
  an ephemeral Postgres container, and the pytest suite on every push.
- **BI**: a working Streamlit dashboard (budget vs. actual, recurring
  subscriptions, anomaly flags, cash-flow forecast) that reads either
  backend through the same code, plus a native path to point Power BI or
  Tableau at the same database.
- **Auth & access control**: bcrypt-hashed, cookie-persisted login via
  streamlit-authenticator, with per-login account restriction rather than
  an all-or-nothing gate.
- **Product thinking**: a "Prescriptive Recommendations" panel that goes
  beyond descriptive ML output ("here's an anomaly," "here's a forecast")
  to an actual next action, quantified in the same units as the rest of
  the page (dollars/month, runway days, forecasted balance) — and does it
  with a transparent rule instead of a model, on purpose.

## Resume / interview bullet points

- "Built an end-to-end personal/SME finance analytics pipeline (Python,
  SQL, scikit-learn, Streamlit) that ingests transaction data into a
  normalized relational database, forecasts 30-day cash flow with a
  gradient-boosted model that outperforms a naive baseline, and flags
  anomalous transactions via unsupervised learning."
- "Provisioned cloud infrastructure (Postgres, S3) with Terraform, and
  built an ELT pipeline (Python extract/load, dbt for transformation)
  with 18 automated data-quality tests gating a downstream ML layer."
- "Orchestrated a multi-stage pipeline (data load, dbt transform/test, ML
  forecasting and anomaly detection) with Apache Airflow, including a
  quality gate that halts the DAG before bad data reaches ML or BI."
- "Set up CI (GitHub Actions) that runs the full ELT pipeline and test
  suite against an ephemeral database on every push, catching pipeline
  regressions before merge."
- "Designed a normalized database schema and BI-ready SQL views/marts to
  decouple data storage from reporting, enabling both a custom dashboard
  and Power BI/Tableau to consume the same clean data layer."
- "Implemented authentication (bcrypt-hashed credentials, signed session
  cookies) with per-login access control, restricting each login to its
  own account(s) rather than gating the app as a single all-or-nothing
  door."
- "Designed a prescriptive-recommendations feature that translates
  descriptive analytics (budget variance, category spend) into ranked,
  quantified actions — dollars saved, runway impact, forecast impact —
  using a transparent rules engine instead of a model, prioritizing
  interpretability over unwarranted ML complexity."

## A note on honesty

The data is synthetic/simulated — that's completely normal for a learning
project and nobody will hold it against you, as long as you say so
upfront. What matters is that the pipeline, schema design, modeling
choices, and evaluation methodology are real and defensible, and they are:
every piece described above was actually run and verified, not just
written and assumed to work.
