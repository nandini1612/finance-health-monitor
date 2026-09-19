"""
CashPulse Cloud Edition - pipeline task functions.

Every real unit of work in the pipeline lives here as a plain Python
function with no Airflow import anywhere in this file. Two things call
into it:
    - cloud/pipeline/run_pipeline.py   (manual, no orchestrator needed)
    - cloud/airflow/dags/cashpulse_pipeline.py  (the real DAG)

Why split it this way: Airflow DAG files get imported and re-parsed by the
scheduler every few seconds, so anything slow or fragile in a DAG file (a
missing dependency, a slow import) affects the whole scheduler, not just
one run. Keeping business logic in a plain module -- and unit-testable
without spinning up Airflow at all -- is the standard mitigation, and it's
also just better software design: these functions have exactly one job
and no framework tangled into them.
"""

import runpy
import subprocess
import sys
from pathlib import Path

CLOUD_DIR = Path(__file__).parent.parent
DBT_PROJECT_DIR = CLOUD_DIR / "dbt" / "cashpulse_dbt"
DATA_GENERATOR = CLOUD_DIR.parent / "data" / "generate_data.py"


def generate_data():
    """Simulate an extract from a source system. In a real company this
    function would instead call an API or query an operational database --
    everything downstream only cares that CSVs land in data/."""
    runpy.run_path(str(DATA_GENERATOR), run_name="__main__")


def load_raw():
    from load_raw import main as load_raw_main
    load_raw_main()


def dbt_run():
    result = subprocess.run(
        ["dbt", "run"], cwd=DBT_PROJECT_DIR, capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"dbt run failed with exit code {result.returncode}")
    return result.stdout


def dbt_test():
    result = subprocess.run(
        ["dbt", "test"], cwd=DBT_PROJECT_DIR, capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(
            "dbt test failed -- a data quality check did not pass. "
            "Treat this like a failed CI build: fix the data or the model before "
            "letting downstream ML/BI consume it."
        )
    return result.stdout


def run_ml_anomaly_detection():
    import ml_anomaly
    return ml_anomaly.run()


def run_ml_forecast():
    import ml_forecast
    return ml_forecast.run()
