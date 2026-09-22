#!/usr/bin/env python3
"""Integrated logic engine for BIM-first Field2BIM processor.


Stages covered here:
- resolve element bindings
- compute integrated evidence outputs
- materialize reconciliation and lineage outputs
"""
from __future__ import annotations

import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError

from arm1_db import connect
from bind_model_and_sensor_data import resolve_bindings
from build_arm1_dss_seeds import build_outputs


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()



def safe_csv_row_count(path: Path) -> int:
    try:
        return len(pd.read_csv(path))
    except EmptyDataError:
        return 0



def run_integrated_logic(output_dir: Path) -> None:
    """Run ARM 1b integrated logic using the default staging DB."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # ARM 1b: resolve bindings and build DSS seeds
    resolve_bindings()
    build_outputs(output_dir)

    # Read results from the default DB for materialized outputs
    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        bindings = pd.read_sql_query("SELECT * FROM binding_results", conn)
        integrated = pd.read_sql_query("SELECT * FROM arm1_integrated_results", conn)
        audit = pd.read_sql_query("SELECT * FROM arm1_audit_log", conn)

    # Write CSV outputs
    bindings.to_csv(output_dir / "bim_evidence_reconciliation_RESULTS.csv", index=False)
    integrated.to_csv(output_dir / "bim_integrated_logic_RESULTS.csv", index=False)
    audit.to_csv(output_dir / "bim_lineage_audit_log.csv", index=False)

    # Coverage audit
    coverage_rows = [
        {
            "Metric": "model_elements",
            "Value": safe_csv_row_count(output_dir / "dss_seed_1_element_library.csv"),
            "CheckedAt": now(),
        },
        {
            "Metric": "review_rows",
            "Value": safe_csv_row_count(output_dir / "integrated_review_required.csv"),
            "CheckedAt": now(),
        },
        {
            "Metric": "binding_results",
            "Value": len(bindings),
            "CheckedAt": now(),
        },
    ]
    pd.DataFrame(coverage_rows).to_csv(output_dir / "bim_data_coverage_audit.csv", index=False)



def main() -> None:
    parser = argparse.ArgumentParser(description="Run BIM-first integrated logic engine.")
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    run_integrated_logic(args.output_dir)
    print(args.output_dir)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
