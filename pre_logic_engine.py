"""Pre-logic engine for BIM-first Field2BIM processor.


Stages covered here:
- import model metadata
- import sensor evidence
- import binding ledger
- write readiness and staging outputs
"""


from __future__ import annotations


import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


# Ensure local modules in the same directory are importable when script
# is executed from a different working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))


import pandas as pd


from import_bim_model_metadata import import_model_metadata
from import_binding_ledger import import_binding_ledger
from import_sensor_evidence import import_sensor_evidence
from arm1_db import connect



def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()



def run_pre_logic(
    output_dir: Path,
    model_register_csv: Path | None,
    input_ifc: Path | None,
    supplemental_csv: Path | None,
    sensor_evidence_csv: Path,
    binding_ledger_csv: Path | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # These functions call connect() internally; no db argument needed
    import_model_metadata(
        model_register_csv=model_register_csv,
        input_ifc=input_ifc,
        supplemental_csv=supplemental_csv,
        replace=True,
    )
    import_sensor_evidence(
        sensor_evidence_csv=sensor_evidence_csv,
        replace=True,
    )
    if binding_ledger_csv:
        import_binding_ledger(
            binding_ledger_csv=binding_ledger_csv,
            replace=True,
        )

    # Read from the default DB for readiness checks
    with connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        model = pd.read_sql_query("SELECT * FROM model_elements", conn)
        sensor = pd.read_sql_query("SELECT * FROM sensor_observations", conn)
        binding = pd.read_sql_query("SELECT * FROM binding_ledger", conn)

    model.to_csv(output_dir / "bim_model_register_STAGED.csv", index=False)
    sensor.to_csv(output_dir / "bim_sensor_evidence_STAGED.csv", index=False)
    binding.to_csv(output_dir / "bim_binding_ledger_STAGED.csv", index=False)

    readiness_rows = []
    observation_ids = sensor["ObservationID"].astype(str) if not sensor.empty else pd.Series(dtype=str)
    readiness_rows.append(
        {
            "CheckID": "RC-01",
            "CheckName": "Unique observation",
            "PassCondition": "ObservationID unique",
            "Status": "PASS" if observation_ids.nunique(dropna=False) == len(sensor) else "FAIL",
            "BlocksArm2": "YES",
            "Owner": "BIM/data manager",
            "Evidence": f"{len(sensor)} sensor rows",
            "CheckedAt": now(),
        }
    )
    required_model = {"ElementGUID", "IFCClass", "Discipline"}
    readiness_rows.append(
        {
            "CheckID": "RC-02",
            "CheckName": "Model metadata present",
            "PassCondition": "model register contains required identity fields",
            "Status": "PASS" if required_model.issubset(set(model.columns)) and not model.empty else "FAIL",
            "BlocksArm2": "YES",
            "Owner": "BIM manager",
            "Evidence": f"{len(model)} model rows",
            "CheckedAt": now(),
        }
    )
    readiness_rows.append(
        {
            "CheckID": "RC-03",
            "CheckName": "Calibration disclosed",
            "PassCondition": "CalibrationPerformed populated",
            "Status": (
                "PASS"
                if "CalibrationPerformed" in sensor.columns
                and sensor["CalibrationPerformed"].astype(str).str.strip().ne("").all()
                else "FAIL"
            ),
            "BlocksArm2": "YES",
            "Owner": "Sensor team",
            "Evidence": "CalibrationPerformed field check",
            "CheckedAt": now(),
        }
    )
    readiness_rows.append(
        {
            "CheckID": "RC-04",
            "CheckName": "Binding source available",
            "PassCondition": "ElementGUID in evidence or binding ledger supplied",
            "Status": (
                "PASS"
                if (
                    "ElementGUID" in sensor.columns
                    and sensor["ElementGUID"].astype(str).str.strip().ne("").any()
                )
                or not binding.empty
                else "FAIL"
            ),
            "BlocksArm2": "YES",
            "Owner": "BIM/data manager",
            "Evidence": "Evidence/binding source check",
            "CheckedAt": now(),
        }
    )
    readiness_rows.append(
        {
            "CheckID": "RC-05",
            "CheckName": "Governance timestamps present",
            "PassCondition": "ObservationDate and SourceTimestamp available",
            "Status": (
                "PASS"
                if {"ObservationDate", "SourceTimestamp"}.issubset(sensor.columns)
                else "FAIL"
            ),
            "BlocksArm2": "YES",
            "Owner": "Governance owner",
            "Evidence": "Timestamp field check",
            "CheckedAt": now(),
        }
    )
    pd.DataFrame(readiness_rows).to_csv(
        output_dir / "bim_pre_logic_readiness_checks.csv", index=False
    )



def main() -> None:
    parser = argparse.ArgumentParser(description="Run BIM-first pre-logic engine.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model-register-csv", type=Path, default=None)
    parser.add_argument("--input-ifc", type=Path, default=None)
    parser.add_argument("--supplemental-csv", type=Path, default=None)
    parser.add_argument("--sensor-evidence-csv", required=True, type=Path)
    parser.add_argument("--binding-ledger-csv", type=Path, default=None)
    args = parser.parse_args()

    # No --db argument: imports use connect() -> DEFAULT_DB_PATH (Inputs\field2bim_run.db)
    run_pre_logic(
        output_dir=args.output_dir,
        model_register_csv=args.model_register_csv,
        input_ifc=args.input_ifc,
        supplemental_csv=args.supplemental_csv,
        sensor_evidence_csv=args.sensor_evidence_csv,
        binding_ledger_csv=args.binding_ledger_csv,
    )
    print(args.output_dir)



if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
