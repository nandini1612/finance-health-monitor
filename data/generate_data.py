"""
CashPulse - synthetic data generator.

Generates realistic-looking (but entirely fake) 18-month transaction
histories for a handful of personal and small-business accounts, and
writes them out as CSVs that the ETL step will load into SQLite.

Why synthetic data at all: real bank data is sensitive and hard to source
legally for a portfolio project. Generating it yourself is a legitimate,
common approach -- just be upfront in your README that the data is
simulated. The generator deliberately injects seasonality, recurring
bills, and a handful of anomalies so the ML step has something real to find.

Run:
    python data/generate_data.py
Outputs (in this folder):
    accounts.csv, categories.csv, merchants.csv, transactions.csv, budgets.csv
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

OUT_DIR = Path(__file__).parent
MONTHS_OF_HISTORY = 18
END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=MONTHS_OF_HISTORY * 30)

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

CATEGORIES = [
    # (name, group)
    ("Salary/Revenue", "income"),
    ("Client Payment", "income"),
    ("Rent/Lease", "fixed_expense"),
    ("Utilities", "fixed_expense"),
    ("Insurance", "fixed_expense"),
    ("Loan Payment", "fixed_expense"),
    ("Payroll", "fixed_expense"),
    ("Software Subscriptions", "fixed_expense"),
    ("Groceries", "variable_expense"),
    ("Supplies/Inventory", "variable_expense"),
    ("Transportation", "variable_expense"),
    ("Marketing", "variable_expense"),
    ("Dining Out", "discretionary"),
    ("Entertainment", "discretionary"),
    ("Shopping", "discretionary"),
    ("Transfer", "transfer"),
]

MERCHANTS_BY_CATEGORY = {
    "Rent/Lease": ["Skyline Properties", "Downtown Leasing Co"],
    "Utilities": ["CityPower & Light", "AquaFlow Water", "MetroGas"],
    "Insurance": ["SafeGuard Insurance", "ShieldCo"],
    "Loan Payment": ["First National Bank Loan Svc", "SBA Loan Servicing"],
    "Payroll": ["Gusto Payroll", "ADP Payroll"],
    "Software Subscriptions": ["Slack", "Notion", "AWS", "Adobe", "QuickBooks", "Zoom"],
    "Groceries": ["Fresh Market", "GreenGrocer", "Costco"],
    "Supplies/Inventory": ["Uline", "Staples", "Alibaba Wholesale"],
    "Transportation": ["Uber", "Shell Gas", "MetroTransit"],
    "Marketing": ["Meta Ads", "Google Ads", "Mailchimp"],
    "Dining Out": ["The Coffee House", "Pasta Palace", "Sushi Go"],
    "Entertainment": ["Netflix", "Spotify", "AMC Theatres"],
    "Shopping": ["Amazon", "Target", "Best Buy"],
    "Transfer": ["Internal Transfer"],
    "Salary/Revenue": ["Employer Direct Deposit"],
    "Client Payment": ["Client Invoice Payment"],
}

ACCOUNTS = [
    {"name": "Nina's Personal Checking", "type": "personal", "owner": "Nina Alvarez", "opening_balance": 4200},
    {"name": "Rahul's Personal Checking", "type": "personal", "owner": "Rahul Mehta", "opening_balance": 2600},
    {"name": "Brew & Bean Cafe", "type": "small_business", "owner": "Brew & Bean LLC", "opening_balance": 18000},
    {"name": "Pixel Studio Freelance", "type": "small_business", "owner": "Pixel Studio LLC", "opening_balance": 9500},
    {"name": "Urban Fit Gym", "type": "small_business", "owner": "Urban Fit LLC", "opening_balance": 27000},
]


def daterange(start, end):
    for n in range((end - start).days + 1):
        yield start + timedelta(days=n)


def write_csv(filename, rows, fieldnames):
    with open(OUT_DIR / filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows):>6} rows -> {filename}")


def build_reference_tables():
    categories = [{"category_name": name, "category_group": grp} for name, grp in CATEGORIES]
    merchants = []
    for cat_name, names in MERCHANTS_BY_CATEGORY.items():
        for m in names:
            merchants.append({"merchant_name": m, "default_category": cat_name})
    accounts = [
        {
            "account_name": a["name"],
            "account_type": a["type"],
            "owner_name": a["owner"],
            "currency": "USD",
            "opening_balance": a["opening_balance"],
        }
        for a in ACCOUNTS
    ]
    return accounts, categories, merchants


def is_business(account):
    return account["type"] == "small_business"


def generate_transactions_for_account(account_idx, account):
    """Generate one account's transaction history with seasonality + anomalies."""
    txns = []
    business = is_business(account)
    monthly_income_base = random.uniform(15000, 30000) if business else random.uniform(4500, 8500)

    # --- Sticky recurring setup, drawn ONCE per account -----------------------
    # Real recurring bills stay with the same merchant and roughly the same
    # amount every month -- you don't get a new landlord or insurer picked at
    # random each cycle. Before this fix, every recurring line item re-rolled
    # both its merchant (via random.choice in _txn) and its full amount range
    # from scratch each month, which made a "did this subscription's price
    # change" detector useless: everything looked changed, all the time.
    # Fixed costs below get ONE merchant + ONE base amount for the account's
    # whole history, with a small monthly jitter for realism (rent/insurance/
    # subscriptions barely move month to month; loan payments don't move at
    # all). Utilities is the deliberate exception -- usage-based bills really
    # do swing with the season, so it keeps a wide range, but now bills all
    # three providers every month instead of picking one at random.
    rent_merchant = random.choice(MERCHANTS_BY_CATEGORY["Rent/Lease"])
    rent_base = random.uniform(1800, 4200) if business else random.uniform(900, 1900)

    payroll_merchant = random.choice(MERCHANTS_BY_CATEGORY["Payroll"]) if business else None
    payroll_base = random.uniform(4000, 12000) if business else None

    insurance_merchant = random.choice(MERCHANTS_BY_CATEGORY["Insurance"]) if business else None
    insurance_base = random.uniform(150, 600) if business else None

    loan_merchant = random.choice(MERCHANTS_BY_CATEGORY["Loan Payment"])
    loan_base = random.uniform(300, 1500)

    utility_bases = {m: random.uniform(60, 260) for m in MERCHANTS_BY_CATEGORY["Utilities"]}

    # A fixed pair of subscriptions for this account (not a fresh random pair
    # every month), each with its own stable base price.
    sub_merchants = random.sample(MERCHANTS_BY_CATEGORY["Software Subscriptions"], k=2)
    sub_bases = {m: random.uniform(10, 120) for m in sub_merchants}
    # Give one subscription a real, one-time price hike partway through the
    # history (about half of accounts), so the dashboard's "amount changed"
    # flag has a genuine, provable case to catch instead of firing on noise.
    price_hike_merchant = random.choice(sub_merchants) if random.random() < 0.5 else None
    price_hike_day_offset = random.randint(60, MONTHS_OF_HISTORY * 30 - 30)
    price_hike_multiplier = random.uniform(1.15, 1.4)

    for d in daterange(START_DATE, END_DATE):
        month_progress = d.month  # crude seasonality hook (e.g. higher retail spend in Nov/Dec)
        seasonal_boost = 1.25 if month_progress in (11, 12) and business else 1.0

        # --- Recurring fixed costs, posted on fixed days of month ---
        if d.day == 1:
            txns.append(_txn(account_idx, d, "Rent/Lease", rent_base * random.uniform(0.98, 1.02),
                              "debit", recurring=True, merchant_override=rent_merchant))
        if d.day == 3 and business:
            txns.append(_txn(account_idx, d, "Payroll", payroll_base * random.uniform(0.92, 1.08),
                              "debit", recurring=True, merchant_override=payroll_merchant))
        if d.day == 5:
            for merchant, base in utility_bases.items():
                txns.append(_txn(account_idx, d, "Utilities", random.uniform(0.6, 1.5) * base,
                                  "debit", recurring=True, merchant_override=merchant))
        if d.day == 10 and business:
            txns.append(_txn(account_idx, d, "Insurance", insurance_base * random.uniform(0.99, 1.01),
                              "debit", recurring=True, merchant_override=insurance_merchant))
        if d.day == 15:
            txns.append(_txn(account_idx, d, "Loan Payment", loan_base,
                              "debit", recurring=True, merchant_override=loan_merchant))
        if d.day == 20:
            for sub in sub_merchants:
                base = sub_bases[sub]
                if sub == price_hike_merchant and (d - START_DATE).days >= price_hike_day_offset:
                    base *= price_hike_multiplier
                txns.append(_txn(account_idx, d, "Software Subscriptions", base * random.uniform(0.98, 1.02),
                                  "debit", recurring=True, merchant_override=sub))

        # --- Income ---
        if business:
            if d.weekday() < 6 and random.random() < 0.85:  # daily-ish revenue, closed Sundays-ish ~15%
                txns.append(_txn(account_idx, d, "Client Payment",
                                  (monthly_income_base / 26) * seasonal_boost * random.uniform(0.6, 1.4),
                                  "credit"))
        else:
            if d.day in (1, 15):
                txns.append(_txn(account_idx, d, "Salary/Revenue", monthly_income_base / 2, "credit", recurring=True))

        # --- Variable / discretionary spend, random daily draws ---
        n_random_txns = random.choices([0, 1, 2, 3], weights=[0.35, 0.35, 0.2, 0.1])[0]
        for _ in range(n_random_txns):
            if business:
                cat = random.choice(["Supplies/Inventory", "Marketing", "Transportation"])
                amt = random.uniform(20, 350)
            else:
                cat = random.choice(["Groceries", "Dining Out", "Entertainment", "Shopping", "Transportation"])
                amt = random.uniform(8, 250)
            txns.append(_txn(account_idx, d, cat, amt, "debit"))

    # --- Inject a handful of anomalies so the ML step has real signal ---
    anomaly_dates = random.sample(list(daterange(START_DATE, END_DATE)), k=6)
    for d in anomaly_dates:
        kind = random.choice(["large_withdrawal", "duplicate_charge", "odd_hour_spike"])
        if kind == "large_withdrawal":
            txns.append(_txn(account_idx, d, "Shopping" if not business else "Supplies/Inventory",
                              random.uniform(2500, 6000), "debit"))
        elif kind == "duplicate_charge":
            dup_cat = "Software Subscriptions"
            dup_merchant = random.choice(MERCHANTS_BY_CATEGORY[dup_cat])
            amt = round(random.uniform(20, 90), 2)
            txns.append(_txn(account_idx, d, dup_cat, amt, "debit", merchant_override=dup_merchant))
            txns.append(_txn(account_idx, d, dup_cat, amt, "debit", merchant_override=dup_merchant))
        else:  # odd_hour_spike -- several rapid small charges same day (card-testing-fraud pattern)
            for _ in range(5):
                txns.append(_txn(account_idx, d, "Shopping", random.uniform(1, 15), "debit"))

    return txns


_txn_counter = [0]


def _txn(account_idx, d, category, amount, txn_type, recurring=False, merchant_override=None):
    _txn_counter[0] += 1
    merchant = merchant_override or random.choice(MERCHANTS_BY_CATEGORY.get(category, ["Misc Merchant"]))
    return {
        "source_txn_id": _txn_counter[0],  # stable id from the "source system" -- see note in cloud/dbt
        "account_ref": account_idx,
        "txn_date": d.isoformat(),
        "merchant_name": merchant,
        "category_name": category,
        "amount": round(amount, 2),
        "txn_type": txn_type,
        "description": f"{merchant} - {category}",
        "is_recurring": int(recurring),
    }


def build_budgets(accounts, all_txns):
    """Monthly budgets per account/category for the last 6 months, sized off
    that account's own real spending history instead of a flat random draw.

    The original version set a budget of random.uniform(200, 1500) for the
    same 7 categories on every account, regardless of account type or actual
    spend. Two problems with that: personal-only categories (Groceries,
    Dining Out, ...) got budgets on business accounts that never spend a
    cent there (and vice versa for Marketing/Supplies on personal accounts),
    and a category that naturally runs $1,500-2,000/month from the
    transaction-volume math below would always look "blown" against an
    unrelated $200-1,500 random number -- not a real signal, just noise from
    a budget that had nothing to do with reality.

    Fix: only budget categories the account actually has debit spend in
    (variable/discretionary categories only -- fixed costs like Rent aren't
    really "budgeted" the same way), and set the budget to that account's
    own average monthly spend in the category, +/- 30%. That keeps the mix
    realistic -- some months land over, some under -- without hardcoding it.
    """
    BUDGETABLE_GROUPS = {"variable_expense", "discretionary"}
    category_group = {name: grp for name, grp in CATEGORIES}

    # Total debit spend per (account_ref, category, month), from the real
    # generated transaction history -- this is what a real budgeting tool
    # would look at before suggesting a number.
    monthly_spend = {}
    for t in all_txns:
        if t["txn_type"] != "debit":
            continue
        cat = t["category_name"]
        if category_group.get(cat) not in BUDGETABLE_GROUPS:
            continue
        key = (t["account_ref"], cat, t["txn_date"][:7])
        monthly_spend[key] = monthly_spend.get(key, 0.0) + t["amount"]

    # Average monthly spend per (account_ref, category), across whichever
    # months that category actually had activity in.
    totals, counts = {}, {}
    for (acct, cat, _month), amt in monthly_spend.items():
        totals[(acct, cat)] = totals.get((acct, cat), 0.0) + amt
        counts[(acct, cat)] = counts.get((acct, cat), 0) + 1
    typical_spend = {k: totals[k] / counts[k] for k in totals}

    months = sorted({(END_DATE - timedelta(days=30 * i)).strftime("%Y-%m") for i in range(6)})
    budget_rows = []
    for idx, account in enumerate(accounts):
        account_categories = [cat for (acct, cat) in typical_spend if acct == idx]
        for cat in account_categories:
            avg_spend = typical_spend[(idx, cat)]
            for month in months:
                budgeted = avg_spend * random.uniform(0.7, 1.3)
                budget_rows.append({
                    "account_ref": idx,
                    "category_name": cat,
                    "month": month,
                    "budgeted_amount": round(budgeted, 2),
                })
    return budget_rows


def main():
    accounts, categories, merchants = build_reference_tables()

    write_csv("accounts.csv", accounts,
              ["account_name", "account_type", "owner_name", "currency", "opening_balance"])
    write_csv("categories.csv", categories, ["category_name", "category_group"])
    write_csv("merchants.csv", merchants, ["merchant_name", "default_category"])

    all_txns = []
    for idx, account in enumerate(ACCOUNTS):
        all_txns.extend(generate_transactions_for_account(idx, account))
    write_csv("transactions.csv", all_txns,
              ["source_txn_id", "account_ref", "txn_date", "merchant_name", "category_name", "amount",
               "txn_type", "description", "is_recurring"])

    budgets = build_budgets(ACCOUNTS, all_txns)
    write_csv("budgets.csv", budgets, ["account_ref", "category_name", "month", "budgeted_amount"])

    print("\nDone. 'account_ref' in transactions.csv/budgets.csv is the 0-based index into accounts.csv")
    print("(the ETL script resolves this to the real account_id after inserting accounts).")


if __name__ == "__main__":
    main()
