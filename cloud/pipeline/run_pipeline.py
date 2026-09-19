"""
Manual, no-orchestrator pipeline run -- useful for local development and
for verifying everything works before wiring up Airflow. This calls the
exact same functions the Airflow DAG calls (see cloud/pipeline/tasks.py).

Requires DATABASE_URL (and DB_HOST/DB_USER/DB_PASSWORD/DB_NAME/DB_PORT for
dbt) to already be set -- see cloud/.env.example.

Run:
    python cloud/pipeline/run_pipeline.py
"""

import sys
import time

import tasks


def main():
    steps = [
        ("Generate synthetic source data", tasks.generate_data),
        ("Load raw zone", tasks.load_raw),
        ("dbt run (staging + marts)", tasks.dbt_run),
        ("dbt test (data quality gate)", tasks.dbt_test),
        ("ML: anomaly detection", tasks.run_ml_anomaly_detection),
        ("ML: cash-flow forecast", tasks.run_ml_forecast),
    ]
    for label, fn in steps:
        print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
        start = time.time()
        try:
            fn()
        except Exception as e:
            print(f"\nFAILED at step '{label}': {e}", file=sys.stderr)
            sys.exit(1)
        print(f"({time.time() - start:.1f}s)")

    print("\nPipeline complete. Point the dashboard or your BI tool at the same DATABASE_URL.")


if __name__ == "__main__":
    main()
