"""
CashPulse Cloud Edition - Airflow DAG.

Orchestrates the same pipeline as cloud/pipeline/run_pipeline.py, but as a
scheduled, monitored, retryable DAG instead of a script you run by hand.
All the real logic lives in cloud/pipeline/tasks.py -- this file is just
wiring (see that module's docstring for why the split exists).

Schedule: daily at 3am. In a real company this would more likely be
triggered after the source system's nightly batch closes (a sensor or an
event) rather than a fixed clock time -- worth mentioning if asked in an
interview about how you'd productionize this further.

anomalies and forecast run in parallel because they're independent reads
of the same dbt marts -- no reason to serialize them.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import dag, task

# tasks.py (and the ml_*.py / load_raw.py modules it imports) live in
# cloud/pipeline/, not on Airflow's default path -- add it explicitly.
PIPELINE_DIR = Path(__file__).resolve().parent.parent.parent / "pipeline"
sys.path.insert(0, str(PIPELINE_DIR))

default_args = {
    "owner": "cashpulse",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    # "email_on_failure": True, "email": ["you@example.com"],  # stretch goal: wire up alerting
}


@dag(
    dag_id="cashpulse_pipeline",
    description="Generate -> load raw -> dbt transform -> dbt test -> ML forecast + anomaly detection",
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["cashpulse", "finance", "elt"],
)
def cashpulse_pipeline():

    @task
    def generate_data():
        import tasks
        tasks.generate_data()

    @task
    def load_raw():
        import tasks
        tasks.load_raw()

    @task
    def dbt_run():
        import tasks
        tasks.dbt_run()

    @task
    def dbt_test():
        # If a dbt test fails, this task fails, and by default Airflow will
        # NOT run its downstream tasks -- bad data never reaches the ML
        # models or the BI layer. This is the pipeline's real quality gate.
        import tasks
        tasks.dbt_test()

    @task
    def ml_anomaly_detection():
        import tasks
        return tasks.run_ml_anomaly_detection()

    @task
    def ml_forecast():
        import tasks
        return tasks.run_ml_forecast()

    generated = generate_data()
    loaded = load_raw()
    transformed = dbt_run()
    tested = dbt_test()
    anomalies = ml_anomaly_detection()
    forecast = ml_forecast()

    generated >> loaded >> transformed >> tested >> [anomalies, forecast]


cashpulse_pipeline()
