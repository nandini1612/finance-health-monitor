# CashPulse — Personal & SME Finance Health Monitor

[![CashPulse CI](https://github.com/nandini1612/finance-health-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/nandini1612/finance-health-monitor/actions/workflows/ci.yml)

An end-to-end data pipeline that predicts cash-flow trouble and flags
suspicious transactions before they become a crisis, for individuals and
small businesses managing multiple accounts. Built to exercise the full
path a real data role touches — schema design, ingestion, machine
learning, orchestration, infrastructure, and BI — rather than stopping at
a single notebook.

**[Live demo →](https://finance-health-monitor.streamlit.app/)** — log in with
`demo` / `CashPulseDemo!26` (all 5 accounts), or `nina` / `NinaDemo!26` (just
Nina's personal account, to see the per-login access restriction in action).
These credentials are meant to be public — see **Authentication** below.

## At a glance

| | |
|---|---|
| **Two tiers** | SQLite "local quickstart" (deployed at the live demo) and a Postgres/dbt/Airflow/Terraform "cloud edition" — the same pipeline logic, built twice on purpose |
| **Data** | ~18 months of synthetic transactions, seeded for full reproducibility (`Faker.seed(42)`, `random.seed(42)`) across 5 accounts (2 personal, 3 small-business) |
| **ML** | Isolation Forest (anomaly detection) + gradient-boosted regressor (30-day cash-flow forecast), both backtested against a naive baseline, both seeded (`random_state=42`) |
| **Data quality** | 18 dbt tests gating the cloud pipeline (uniqueness, not-null, referential integrity, accepted values) |
| **Test coverage** | 36 pytest tests across both tiers (ETL validation logic, ML edge cases, and full dashboard regression tests via `AppTest`), plus the 18 dbt tests above |
| **CI** | 2 independent GitHub Actions jobs, one per tier, on every push |
| **Auth** | Real per-login authentication (bcrypt + signed session cookie) with per-account access control, not a single shared password |

## Architecture

Both tiers keep the same shape — dumb storage, a pipeline that does the
validation/transformation work, and a thin BI layer that only ever reads
clean, already-tested data:

**Local quickstart** (what's deployed at the live demo):

```mermaid
flowchart LR
    A["generate_data.py<br/>synthetic CSVs, seeded"] --> B["etl/load_to_db.py<br/>validate + load"]
    B --> C[("data/finance.db<br/>SQLite")]
    C --> D["ml/detect_anomalies.py<br/>Isolation Forest"]
    C --> E["ml/forecast_cashflow.py<br/>Gradient Boosted Regressor"]
    D --> C
    E --> C
    C --> F["dashboard/app.py<br/>Streamlit"]
    C --> G["Power BI / Tableau<br/>native ODBC connector"]
```

**Cloud edition** (`cloud/`):

```mermaid
flowchart LR
    A["generate_data.py"] --> B["load_raw.py"]
    B --> C[("Postgres<br/>raw.* — unvalidated")]
    C --> D["dbt: staging.stg_*<br/>typed, cleaned"]
    D --> E["dbt: analytics.*<br/>fact/dim + marts<br/>18 tests"]
    E --> F["ml_anomaly.py"]
    E --> G["ml_forecast.py"]
    F --> H[("Postgres<br/>ml.*")]
    G --> H
    E --> I["dashboard/app.py"]
    E --> J["Power BI / Tableau"]
    H --> I
```

Orchestrated end-to-end by the Airflow DAG in `cloud/airflow/`, which gates
the ML tasks behind a passing `dbt test`. Infrastructure — a Postgres
instance and an S3 landing bucket — is provisioned by `cloud/terraform/`
(real AWS) or `cloud/terraform-localstack/` (a free, no-AWS-account
alternative; see **Connecting real AWS & BI tools** below).

### Database schema

The same normalized schema (SQLite locally, Postgres in the cloud tier)
backs both tiers:

```mermaid
erDiagram
    ACCOUNTS ||--o{ TRANSACTIONS : has
    ACCOUNTS ||--o{ BUDGETS : sets
    CATEGORIES ||--o{ TRANSACTIONS : categorizes
    CATEGORIES ||--o{ BUDGETS : "budgeted for"
    CATEGORIES ||--o{ MERCHANTS : "default category"
    MERCHANTS |o--o{ TRANSACTIONS : "made at (nullable)"
    TRANSACTIONS ||--o{ ML_ANOMALY_FLAGS : "may be flagged"
    ACCOUNTS ||--o{ ML_CASHFLOW_FORECAST : "forecasted for"

    ACCOUNTS {
        int account_id PK
        string account_name
        string account_type "personal | small_business"
        string owner_name
        numeric opening_balance
    }
    CATEGORIES {
        int category_id PK
        string category_name
        string category_group "income | fixed_expense | variable_expense | discretionary | transfer"
    }
    MERCHANTS {
        int merchant_id PK
        string merchant_name
        int default_category_id FK
    }
    TRANSACTIONS {
        int transaction_id PK
        int account_id FK
        int merchant_id FK "nullable"
        int category_id FK
        date txn_date
        numeric amount
        string txn_type "credit | debit"
        bool is_recurring
    }
    BUDGETS {
        int budget_id PK
        int account_id FK
        int category_id FK
        string month
        numeric budgeted_amount
    }
    ML_ANOMALY_FLAGS {
        int flag_id PK
        int transaction_id FK
        numeric anomaly_score
        string reason
    }
    ML_CASHFLOW_FORECAST {
        int forecast_id PK
        int account_id FK
        date forecast_date
        numeric predicted_balance
    }
```

`ml_anomaly_flags` and `ml_cashflow_forecast` are *output* tables, written
by the ML layer rather than the application — predictions live in the
database itself, so the dashboard and any BI tool query them the same way
they'd query any other table, instead of the ML step being a notebook
that dead-ends.

## Design decisions

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
  (uniqueness, not-null, referential integrity, accepted values) run as
  part of `dbt test`, and CI fails the build if any of them fail — the
  same gate a real data team would put in front of anything downstream
  trusting this data.
- **ML is backtested against a naive baseline, not just fit and shipped.**
  See **Methodology** below for the exact evaluation setup — "the model
  beats a naive guess" is a claim this project can actually back up with a
  number on every run, not an assumption.
- **Honest about what was verified vs. what needs a human.** The cloud
  tier's dbt project, ML pipeline, and Airflow DAG were all run and
  verified end to end against a real local Postgres instance. Terraform
  against real AWS and the Airflow Docker stack need a human's own AWS
  account and Docker daemon to actually execute — flagged as such rather
  than claimed. The same honesty carries into the dashboard itself: its
  "Integrations & Proof" panel reads the real environment live and only
  ever shows a connection that's actually there.
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

## Methodology

### Data generation

`data/generate_data.py` builds ~18 months of trailing synthetic
transaction history using Faker and numpy, with `Faker.seed(42)` and
`random.seed(42)` fixed — the same code reproduces the same qualitative
dataset on any machine. It's not just random noise: recurring bills keep
a stable per-merchant price, payroll lands on a consistent cycle, retail
categories carry seasonal variation, and budgets are sized off each
account's own historical spend rather than arbitrary numbers. Six
anomaly events are also injected into each account's history, each
randomly one of three patterns — a large one-off withdrawal, a duplicate
charge, or a burst of rapid small charges mimicking card-testing fraud —
so the anomaly detector has real, verifiable signal to find, and its
output can be checked against ground truth that's actually known.

### Anomaly detection

An **Isolation Forest** (`n_estimators=200`, `contamination=0.02`,
`random_state=42`) trained fresh on every run over five engineered
features per debit transaction: the raw amount; the amount's z-score
*within its own category* (how unusual the size is for that specific
category, not globally — a $400 grocery run and a $400 electronics
purchase mean very different things); same-day transaction count for
that account (catches duplicate-charge and card-testing patterns, which
show up as a spike in same-day volume); day-of-week; day-of-month.
Unsupervised on purpose — nobody has labeled "this transaction was
fraudulent" ground truth for their own spending, so treating this as a
supervised classification problem would mean training on fabricated
labels. On a representative run this flags roughly 2% of debit
transactions (matching the model's `contamination` setting by
construction), each with a plain-language reason string built from
which feature(s) drove the score.

### Cash-flow forecasting

A **gradient-boosted regressor** (`random_state=42`, `n_estimators=150`,
`max_depth=3`, `learning_rate=0.05`) trained independently per account on
daily net cash flow, using seven lag features (net flow on each of the
previous seven days), day-of-week, day-of-month, and a trailing 7-day
rolling mean. Evaluated with a **chronological** 85/15 train/test split —
never a random shuffle, since shuffling time-series data leaks future
information into training — and scored with mean absolute error (MAE)
against a naive baseline (predict the same value as seven days ago).
Both numbers are logged on every run, so "beats the naive baseline" is a
claim this project can actually back up rather than assert. Exact MAE
values shift slightly run to run, since the training window is a rolling
~18 months ending today rather than a frozen dataset, but the
gradient-boosted model has out-performed the naive baseline on every one
of the five demo accounts on every run so far — for example, one run
measured a model MAE of $130 against a $524 naive baseline on a single
account, a pattern consistent with every other account and run observed.

### Testing methodology

Three layers, deliberately different in what each one checks:

1. **18 dbt tests** (`uniqueness`, `not_null`, `relationships`,
   `accepted_values`) gate `dbt test` in the cloud tier — nothing
   downstream of `analytics.*` is trusted until these pass.
2. **31 pytest tests on the local tier**: 14 in `etl/test_load_to_db.py`
   unit-test the ETL loader's validation branches (non-positive amounts,
   bad transaction types, missing dates, unknown categories, out-of-range
   account references) against an in-memory SQLite connection; 7 in
   `ml/test_ml_scripts.py` cover the feature-engineering and backtest
   logic in both ML scripts, including edge cases like a category with
   only one transaction (an undefined standard deviation the code has to
   fall back from cleanly); 10 in `dashboard/test_app.py` drive the real
   Streamlit app end to end with `streamlit.testing.v1.AppTest` — the
   login gate, per-login account restriction, the recommendations panel
   across every demo account, and a dedicated regression test for a
   runway-calculation edge case found during development (see
   **Prescriptive Recommendations** below).
3. **5 pytest tests on the cloud tier** (`cloud/pipeline/test_pipeline.py`)
   cover the same ML feature-engineering logic against the cloud
   pipeline's own task functions.

All of it runs in CI on every push, split into two independent GitHub
Actions jobs (`cloud-pipeline`, `local-tier`) so a change to either tier's
code is verified against that tier specifically, rather than one green
badge standing in for both.

## Features

| Feature | Why |
|---|---|
| **KPI row** (balance, avg. daily burn, runway, last month's net flow) | A single glanceable "how am I doing right now" snapshot, deliberately independent of any date filter below it |
| **30-day cash-flow forecast** | Turns a reactive tool ("here's what happened") into a forward-looking one — the actual point of an early-warning system |
| **Historical net flow chart** | Context for the forecast: is this month's trend continuing or reversing |
| **Spend by category, with click-to-drill-down** | A category chart alone answers "how much" — clicking a bar to see the underlying transactions turns it into an actual investigation tool |
| **Date-range filter** | Category spend and budget comparisons shouldn't be locked to whatever "latest month" happens to mean |
| **Budget vs. actual** | Budgets sized off each account's own real spending (see Methodology), not arbitrary targets, with an explicit over-budget warning |
| **Recurring/subscription detection** | Surfaces a "changed" flag when a recurring charge's amount drifts — the kind of thing that's easy to miss scrolling a bank statement |
| **Anomaly flags + CSV export** | The Isolation Forest's output, made actionable: a downloadable list of exactly what to double-check |
| **Manual transaction entry, editing, auto-categorization** (local tier) | A synthetic-data demo still needs a real data-entry path to be usable with anyone's own numbers eventually; picking a known merchant auto-suggests its category, and a new merchant's chosen category is learned inline |
| **Prescriptive Recommendations** | Goes one step past "here's an anomaly" or "here's a forecast" to an actual next action, quantified in the same units as the rest of the page — see below |
| **Authentication & per-account access control** | Real login, not a locked door — see **Authentication** |
| **Integrations & Proof panel** | Reads the live environment and reports connection status truthfully — never a hardcoded "Connected" |

### Prescriptive Recommendations, in more detail

This panel is deliberately a transparent rules engine, not a model: it
ranks (1) any category already over its budget this month, where the
recommendation is simply "get back to budget" and the savings figure is
the real overage, then (2) the largest discretionary/variable-expense
categories not already over budget, where the savings is a hypothetical
cut at a user-adjustable slider (5–30%, default 15%). Each recommendation
is translated into the same two units already used elsewhere on the
page — runway days and the 30-day forecasted ending balance — rather than
introducing a new metric to trust.

One real edge case surfaced during development and is now covered by a
regression test: for an account with a negative current balance, the
runway ratio (`balance ÷ burn`) gets *more* negative after a spending
cut, since dividing a negative number by a smaller positive one moves it
further from zero — which would read as "saving money makes your runway
worse." The fix suppresses the runway metric specifically when the
balance isn't positive, while the dollar-savings and forecast-impact
numbers (which stay directionally correct regardless of balance sign)
are shown either way.

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

## Folder structure

```
finance-health-monitor/
├── .streamlit/
│   ├── config.toml              # theme
│   └── secrets.toml              # auth credentials + per-login account access (see Authentication)
├── data/
│   ├── generate_data.py        # synthetic data generator (Faker, seeded)
│   └── finance.db              # created by etl/load_to_db.py (gitignored)
├── sql/
│   ├── schema.sql               # DBMS: tables, keys, indexes, views
│   └── practice_queries.sql     # SQL practice set (joins -> window fns -> CTEs)
├── etl/
│   ├── load_to_db.py            # CSV -> validated -> SQLite
│   └── test_load_to_db.py       # 14 unit tests on the validation logic
├── ml/
│   ├── detect_anomalies.py      # Isolation Forest -> ml_anomaly_flags
│   ├── forecast_cashflow.py     # Gradient boosted regressor -> ml_cashflow_forecast
│   └── test_ml_scripts.py       # 7 unit tests on feature engineering + backtesting
├── dashboard/
│   ├── app.py                   # Streamlit BI-style dashboard (both tiers)
│   └── test_app.py              # 10 AppTest regression tests (login, auth, recommendations)
├── cloud/                       # Postgres + dbt + Airflow + Terraform edition
│   ├── pipeline/                # load_raw, ML jobs, orchestration tasks, 5 pytest tests
│   ├── dbt/cashpulse_dbt/       # staging -> marts, 18 dbt tests
│   ├── airflow/                 # DAG + docker-compose
│   ├── terraform/               # real AWS: RDS + S3
│   └── terraform-localstack/    # free, no-account alternative: S3 only
├── .github/workflows/ci.yml     # 2 jobs: cloud-pipeline, local-tier
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

To run this tier's own test suite locally (same three files the
`local-tier` CI job runs):

```bash
pip install pytest
pytest etl/test_load_to_db.py ml/test_ml_scripts.py -v   # pure unit tests, no data needed
pytest dashboard/test_app.py -v                          # needs steps 1-4 above run first
```

**Cloud edition**, once you have a Postgres instance reachable (real RDS
via `cloud/terraform/`, or local/Docker Postgres paired with the free
LocalStack S3 path in `cloud/terraform-localstack/` — see **Connecting
real AWS & BI tools** below):

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
something you can legally source or share. See **Methodology** above for
exactly what patterns the generator injects and why.

## Connecting real AWS & BI tools

Everything described above is built and verified. Real AWS and a real
Power BI/Tableau report are the two pieces that genuinely need a human's
own accounts to go further — a real portfolio project should be upfront
that a person, not the pipeline, has to click "Publish."

**Real AWS** (`cloud/terraform/`): provisions exactly two things — an RDS
Postgres instance and an S3 landing bucket:

```bash
cd cloud/terraform
cp terraform.tfvars.example terraform.tfvars   # set db_password and my_ip_cidr
terraform init && terraform plan && terraform apply
```

AWS requires a card on file to create *any* account, even one that only
ever touches free-tier services — that's a standard identity-verification
step for the whole account, not a paid feature. Set up an AWS Budget
alert before running `apply` (a cost-safety habit worth having
regardless), and run `terraform destroy` once you're done — RDS isn't
free to leave running. Point the dashboard at it with
`DATABASE_URL=postgresql://...@<rds_endpoint>:5432/cashpulse`, and the
"Integrations & Proof" panel flips from "Not connected yet" to
"Connected" automatically, driven entirely by that environment variable.

**No AWS account needed** (`cloud/terraform-localstack/`):
[LocalStack](https://www.localstack.io/) runs a local simulator of AWS's
own APIs — Terraform talks to `http://localhost:4566` instead of
`amazonaws.com`, with no account, no card, and no cost:

```bash
pip install localstack awscli-local
localstack start -d
cd cloud/terraform-localstack
terraform init && terraform apply
```

This provisions a genuinely real S3 bucket. LocalStack's free Community
edition mocks the RDS *API* but doesn't run a database engine behind it,
so pair it with a real Postgres container as the RDS stand-in
(`docker run -d --name cashpulse-pg -e POSTGRES_PASSWORD=devpassword -e POSTGRES_DB=cashpulse -p 5432:5432 postgres:16`),
then run with `AWS_INTEGRATION_MODE=localstack` set alongside
`DATABASE_URL` — the Integrations panel shows this honestly as
"🧪 Simulated," in amber, deliberately never the same green "Connected"
state real AWS gets.

**Power BI or Tableau**: connect either tool's native Postgres connector
to the cloud tier's `analytics.*` views (or SQLite's views on the local
tier, via ODBC), model the relationships, and build on the same tested
data layer the dashboard reads. To surface a published report inside the
dashboard's Integrations panel automatically, publish it (Power BI's
*Publish to web*, if the report is safe to make public — this project's
data is synthetic, so it is) and save the URL as the only line in
`dashboard/assets/powerbi_report_url.txt`; the panel reads that file live
and shows a "View live report" link the moment it exists.

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
- "Set up CI (GitHub Actions, 2 independent jobs) that runs the full
  ELT pipeline and a 36-test pytest suite against an ephemeral database
  on every push, catching pipeline and UI regressions before merge."
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
- "Closed a test-coverage gap by adding 31 pytest tests (ETL validation
  logic, ML edge cases, and Streamlit UI regression tests via AppTest) and
  a second CI job covering the tier actually running in production, which
  previously had none."

## A note on honesty

The data is synthetic/simulated — that's completely normal for a learning
project and nobody will hold it against you, as long as you say so
upfront. What matters is that the pipeline, schema design, modeling
choices, and evaluation methodology are real and defensible, and they
are: every piece described above was actually run and verified, not just
written and assumed to work. Every random component — data generation,
both ML models — is seeded specifically so that claim is checkable:
clone the repo, run the setup steps above, and the same qualitative
results reproduce.
