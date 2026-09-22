#!/usr/bin/env python3
"""
run_field2bim_pipeline_api.py
=============================

Field2BIM API-Based Circular DSS pipeline orchestrator.

Usage:
    python run_field2bim_pipeline_api.py \
        --input-ifc models/Gymnasium.ifc
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("F2BIM-API")

HERE = Path(__file__).resolve().parent
_LOG_DIR: Path | None = None


def validate_runtime() -> None:
    """Stop before creating outputs when the selected interpreter is unsupported."""
    for module_name, package_name in [
        ("ifcopenshell", "ifcopenshell"),
        ("IfcLCA", "ifclca"),
        ("requests", "requests"),
    ]:
        try:
            __import__(module_name)
        except ImportError as error:
            raise SystemExit(
                f"Missing runtime dependency '{package_name}' for "
                f"interpreter {sys.executable}. "
                f"Run: {sys.executable} install_dependencies.py"
            ) from error


DEFAULTS: dict[str, Any] = {
    "dss_workbook": "Field2BIM_DSS_Structural_Scope_v1.xlsx",
    "sensor_evidence_csv": "inputs/sensor_evidence.csv",
    "binding_ledger_csv": "inputs/binding_ledger.csv",
    "delphi_evidence_csv": "inputs/delphi_weights.csv",
    "output_root": "outputs",
    "economic_inputs_file": "economic_inputs.yaml",
    "unified_economic_mcda": True,
    "dss_calculation_mode": "api_first",
    "workbook_fallback_enabled": True,
    "pre_1985": False,
    "gfa_m2": 1250.0,
    "rsp_years": 30,

    "w_LCA": 0.20,
    "w_CIRC": 0.20,
    "w_SI": 0.20,
    "w_PERF": 0.10,
    "w_CDW": 0.05,
    "w_SV": 0.05,
    "w_ECON": 0.20,

    "alpha_REN": 0.40,
    "alpha_DIS": 0.90,
    "alpha_DEM": 1.00,

    "dis_disassembly_gate": 6,
    "dis_circ_penalty": 0.40,

    "lambda_penalty": 2.0,
    "tau_conflict": 0.15,
    "gamma_review": 0.60,

    "discount_rate": 0.035,
    "carbon_price_base": 65.0,

    "bau_maintenance_escalation": 0.03,
    "rebound_steel_scrap": 0.20,
    "rebound_rca": 0.35,

    "lca_data_tier": 2,
    "lca_preferred_api": "oekobaudat",
    "lca_db_standard": "EN15804_A2",

    "si_review_threshold": 0.60,

    "sv_heritage_weight": 0.40,
    "sv_accessibility_weight": 0.35,
    "sv_employment_weight": 0.25,

    "writeback_guard": True,
    "ifc_output_suffix": "_Field2BIM_DSS_Annotated",
}


def load_config(config_path: Path) -> dict[str, Any]:
    """Load project configuration over the built-in defaults."""
    if not config_path.exists():
        log.warning(
            "Configuration file not found: %s. "
            "Using built-in defaults.",
            config_path,
        )
        return dict(DEFAULTS)

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ValueError(
            f"Configuration must contain a YAML mapping: {config_path}"
        )

    return {**DEFAULTS, **data}


def safe_step_name(step: str) -> str:
    """Return a filesystem-safe pipeline step name."""
    return "".join(
        character if character.isalnum() else "_"
        for character in step
    )


def run(
    cmd: list[Any],
    step: str,
    *,
    non_fatal: bool = False,
) -> bool:
    """
    Run one subprocess pipeline step.

    All subprocess output is written to the run log directory.
    Fatal steps terminate the pipeline on failure.
    Non-fatal steps return False on failure.
    """
    log.info("[%s] running", step)

    command = [str(value) for value in cmd]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        message = f"[{step}] could not start subprocess: {error}"

        if non_fatal:
            log.error(message)
            return False

        log.error(message)
        sys.exit(f"Pipeline aborted at: {step}")

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if _LOG_DIR is not None:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)

        log_file = _LOG_DIR / f"{safe_step_name(step)}.log"
        log_file.write_text(
            "\n".join(
                [
                    f"COMMAND: {' '.join(command)}",
                    f"RETURN_CODE: {result.returncode}",
                    "",
                    "STDOUT:",
                    stdout,
                    "",
                    "STDERR:",
                    stderr,
                ]
            ),
            encoding="utf-8",
        )

    if stdout.strip():
        log.info(
            "[%s] %s",
            step,
            stdout.strip()[:200],
        )

    if stderr.strip():
        log.warning(
            "[%s] stderr: %s",
            step,
            stderr.strip()[:400],
        )

    if step == "ARM0 validation":
        arm0_failed = (
            "[run_arm0_setup] STATUS: FAIL" in stdout
            or result.returncode != 0
        )

        if arm0_failed:
            log.error(
                "[%s] ARM0 reported failure "
                "(return code %s)",
                step,
                result.returncode,
            )
            sys.exit(f"Pipeline aborted at: {step}")

        log.info("[%s] OK", step)
        return True

    if result.returncode != 0:
        log.error(
            "[%s] failed with return code %s",
            step,
            result.returncode,
        )

        if non_fatal:
            log.warning(
                "[%s] non-fatal failure; continuing pipeline",
                step,
            )
            return False

        sys.exit(f"Pipeline aborted at: {step}")

    log.info("[%s] OK", step)
    return True


def apply_fix_a(
    seed_csv: Path,
    cfg: dict[str, Any],
    out_csv: Path,
) -> None:
    """Apply the in-process scenario differentiation fields."""
    if not seed_csv.exists():
        log.warning(
            "Scenario differentiation input not found: %s",
            seed_csv,
        )
        return

    df = pd.read_csv(seed_csv)

    gate = cfg["dis_disassembly_gate"]
    penalty = cfg["dis_circ_penalty"]

    service_multiplier = cfg.get(
        "ren_svc_life_factors",
        {
            "excellent": 1.20,
            "good": 1.10,
            "fair": 1.00,
            "poor": 0.90,
            "critical": 0.75,
        },
    )
    circ_column = next(
        (
            column
            for column in df.columns
            if "circ" in column.lower()
            and "elem" in column.lower()
        ),
        None,
    )

    si_column = next(
        (
            column
            for column in df.columns
            if column.lower() in {"si_elem_0_1", "si_e"}
        ),
        None,
    )

    disassembly_column = next(
        (
            column
            for column in df.columns
            if "disassembly" in column.lower()
            and "score" in column.lower()
        ),
        None,
    )

    condition_column = next(
        (
            column
            for column in df.columns
            if "condition" in column.lower()
            and "0_10" in column.lower()
        ),
        None,
    )

    if circ_column:
        df["CIRC_e_REN"] = df[circ_column]

        def dis_circularity(row: pd.Series) -> float:
            circularity = float(
                row.get(circ_column, 0) or 0
            )

            disassembly_score = float(
                row.get(disassembly_column, 0) or 0
            ) if disassembly_column else 0.0

            if disassembly_score >= gate:
                return circularity

            return circularity * penalty

        df["CIRC_e_DIS"] = df.apply(
            dis_circularity,
            axis=1,
        )

        df["CIRC_e_DEM"] = df[circ_column] * 0.74

    if si_column and condition_column:

        def get_condition_multiplier(value: Any) -> float:
            condition = float(value or 5)

            if condition >= 8:
                return service_multiplier["excellent"]
            if condition >= 6:
                return service_multiplier["good"]
            if condition >= 4:
                return service_multiplier["fair"]
            if condition >= 2:
                return service_multiplier["poor"]

            return service_multiplier["critical"]

        def renewable_si(row: pd.Series) -> float:
            si_value = float(
                row.get(si_column, 0) or 0
            )

            multiplier = get_condition_multiplier(
                row.get(condition_column, 5)
            )

            return round(
                min(1.0, si_value * multiplier),
                4,
            )

        df["SI_e_REN"] = df.apply(
            renewable_si,
            axis=1,
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    log.info(
        "Scenario differentiation written to: %s",
        out_csv,
    )


def build_arm2_handover_ready(
    seed_csv: Path,
    canonical_csv: Path,
    out_csv: Path,
) -> None:
    """
    Merge ARM 1 seed fields with ARM 2 canonical DSS outputs.

    ReviewFlag is taken from the ARM 1 seed so that the ARM 1 review
    decision is not overwritten by default values from the canonical file.
    """
    seed_df = pd.read_csv(seed_csv)
    canonical_df = pd.read_csv(canonical_csv)

    if "ElementGUID" not in seed_df.columns:
        raise ValueError(
            "ARM 1 seed output is missing ElementGUID"
        )

    if "ElementGUID" not in canonical_df.columns:
        raise ValueError(
            "ARM 2 canonical output is missing ElementGUID"
        )

    canonical_fields = [
        "ElementGUID",
        "ScenarioID",
        "CircularityScore_0_1",
        "LCA_GWP_kgCO2e",
        "ReusePotential_0_1",
        "RecyclePotential_0_1",
        "RecommendedRStrategy",
        "SourceRunID",
        "DecisionTimestamp",
    ]

    available_fields = [
        field
        for field in canonical_fields
        if field in canonical_df.columns
    ]

    handover_df = seed_df.merge(
        canonical_df[available_fields].drop_duplicates(
            subset=["ElementGUID"]
        ),
        on="ElementGUID",
        how="left",
    )

    if "ReviewFlag" in handover_df.columns:
        handover_df["ManualReviewFlag"] = (
            handover_df["ReviewFlag"]
            .astype(str)
            .str.upper()
            .map(
                {
                    "YES": "YES",
                    "TRUE": "YES",
                    "1": "YES",
                    "NO": "NO",
                    "FALSE": "NO",
                    "0": "NO",
                }
            )
            .fillna("NO")
        )
    else:
        log.warning(
            "[ARM2] ReviewFlag is missing from ARM 1 seed. "
            "ManualReviewFlag will default to NO."
        )
        handover_df["ManualReviewFlag"] = "NO"

    if "ReviewReason" not in handover_df.columns:
        handover_df["ReviewReason"] = ""

    handover_df["DSS_Action"] = (
        handover_df["ManualReviewFlag"]
        .map(
            {
                "YES": "HELD_FOR_REVIEW",
                "NO": "READY_FOR_DSS_MASTER",
            }
        )
        .fillna("READY_FOR_DSS_MASTER")
    )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    handover_df.to_csv(out_csv, index=False)

    log.info(
        "[ARM2] Handover file written: %s",
        out_csv,
    )


def main() -> None:
    validate_runtime()

    parser = argparse.ArgumentParser(
        description=(
            "Field2BIM API-Based Circular DSS pipeline. "
            "Input: original IFC file."
        )
    )

    parser.add_argument(
        "--input-ifc",
        required=True,
        type=Path,
        help="Path to the original IFC file",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=HERE / "project_config.yaml",
        help="Path to project_config.yaml",
    )

    args = parser.parse_args()
    cfg = load_config(args.config)

    ifc = args.input_ifc.resolve()

    if not ifc.exists():
        sys.exit(f"IFC not found: {ifc}")

    if cfg.get("writeback_guard", True):
        output_suffix = cfg.get(
            "ifc_output_suffix",
            "_Field2BIM_DSS_Annotated",
        )

        if output_suffix in ifc.stem:
            sys.exit(
                "WRITEBACK GUARD: the input IFC appears to be "
                "an annotated output. Use the original IFC."
            )

    run_id = uuid.uuid4().hex[:8].upper()
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S"
    )

    root = (
        Path(cfg["output_root"])
        / f"{ifc.stem}_{timestamp}_{run_id}"
    )

    global _LOG_DIR
    _LOG_DIR = root / "logs"

    db = root / "pre" / "field2bim_run.db"

    exchange_db = (
        root
        / "db"
        / "F2BIM_DSS_VENDOR_NEUTRAL_EXCHANGE.db"
    )

    output_suffix = cfg.get(
        "ifc_output_suffix",
        "_Field2BIM_DSS_Annotated",
    )

    output_ifc = (
        root
        / "ifc"
        / f"{ifc.stem}{output_suffix}.ifc"
    )

    dss_dir = root / "dss"
    exchange_dir = root / "exchange"

    sensor_csv = Path(
        cfg["sensor_evidence_csv"]
    ).resolve()

    binding_csv = Path(
        cfg.get(
            "binding_ledger_csv",
            "inputs/binding_ledger.csv",
        )
    ).resolve()

    delphi_csv = Path(
        cfg.get(
            "delphi_evidence_csv",
            "inputs/delphi_weights.csv",
        )
    ).resolve()

    log.info("=" * 60)
    log.info("Field2BIM API-Based Circular DSS — START")
    log.info("IFC: %s", ifc.name)
    log.info("Run: %s", run_id)
    log.info("LCA API: %s", cfg.get("lca_preferred_api"))
    log.info("LCA tier: %s", cfg.get("lca_data_tier"))
    log.info("LCA standard: %s", cfg.get("lca_db_standard"))
    log.info("=" * 60)

    # ARM 0
    arm0_dir = root / "arm0"

    run(
        [
            sys.executable,
            HERE / "run_arm0_setup.py",
            "--config",
            args.config,
            "--output-dir",
            arm0_dir,
            "--run-mode",
            cfg.get("run_mode", "deployment"),
        ],
        "ARM0 validation",
    )

    # ARM 1a
    pre_dir = root / "pre"

    if "model_register_csv" not in cfg:
        raise KeyError(
            "project_config.yaml must define "
            "'model_register_csv'."
        )

    model_register_csv = Path(
        cfg["model_register_csv"]
    ).resolve()

    pre_command = [
        sys.executable,
        HERE / "pre_logic_engine.py",
        "--output-dir",
        pre_dir,
        "--model-register-csv",
        model_register_csv,
        "--sensor-evidence-csv",
        sensor_csv,
    ]

    if binding_csv.exists():
        pre_command.extend(
            [
                "--binding-ledger-csv",
                binding_csv,
            ]
        )

    run(pre_command, "ARM1a pre_logic_engine")

    # ARM 1b
    integrated_dir = root / "integrated"

    run(
        [
            sys.executable,
            HERE / "integrated_logic_engine.py",
            "--output-dir",
            integrated_dir,
        ],
        "ARM1b integrated_logic_engine",
    )

    # ARM 1c
    post_dir = root / "post"

    run(
        [
            sys.executable,
            HERE / "post_logic_engine.py",
            "--integrated-output-dir",
            integrated_dir,
            "--output-dir",
            post_dir,
        ],
        "ARM1c post_logic_engine",
    )

    # Scenario differentiation
    seed_input = (
        post_dir
        / "bim_post_logic_seed_1_element_library.csv"
    )

    seed_output = (
        post_dir
        / "bim_post_logic_seed_1_FIX_A_applied.csv"
    )

    handover_output = (
        post_dir
        / "bim_post_logic_arm2_handover_ready.csv"
    )

    apply_fix_a(
        seed_input,
        cfg,
        seed_output,
    )

    # ARM 2 API DSS
    log.info("[ARM2] Running API-based DSS computation")

    arm2_ready_csv = seed_output
    canonical_csv = (
        dss_dir
        / "canonical_dss_element_state.csv"
    )

    try:
        sys.path.insert(0, str(HERE))

        from dss_equations_api import compute_all_api

        dss_input = (
            seed_output
            if seed_output.exists()
            else seed_input
        )

        dss_dir.mkdir(parents=True, exist_ok=True)

        result = compute_all_api(
            seed_csv=dss_input,
            cfg=cfg,
            db=db if db.exists() else None,
            output_dir=dss_dir,
            delphi_csv=(
                delphi_csv
                if delphi_csv.exists()
                else None
            ),
            exchange_db=exchange_db,
        )

        npv_value = result["bau_result"]["NPV_BAU_total"]
        log.info(
            "[ARM2] API DSS complete. BAU NPV: EUR %s",
            f"{npv_value:,.0f}",
        )

        scenario_results = result.get("scenario_results")
        if scenario_results:
            import csv as _csv
            summary_csv = post_dir / "scenario_decision_summary.csv"
            summary_json = post_dir / "scenario_decision_summary.json"
            fieldnames = sorted({k for row in scenario_results for k in row.keys()})
            with summary_csv.open("w", newline="", encoding="utf-8") as handle:
                writer = _csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(scenario_results)
            import json as _json
            summary_json.write_text(
                _json.dumps(scenario_results, indent=2, default=str),
                encoding="utf-8",
            )
            log.info(
                "[ARM2] Scenario-level comparison (BAU/REN/DIS/DEM) written to: %s",
                summary_csv,
            )
        else:
            log.warning(
                "[ARM2] compute_all_api() returned no 'scenario_results' — "
                "scenario-level comparison file not written"
            )

        by_scenario_csv = dss_dir / "canonical_dss_element_state_by_scenario.csv"
        by_scenario_json = dss_dir / "canonical_dss_element_state_by_scenario.json"
        if by_scenario_csv.exists():
            (post_dir / by_scenario_csv.name).write_text(
                by_scenario_csv.read_text(encoding="utf-8"), encoding="utf-8"
            )
        if by_scenario_json.exists():
            (post_dir / by_scenario_json.name).write_text(
                by_scenario_json.read_text(encoding="utf-8"), encoding="utf-8"
            )

        si_issues = result.get("si_issues") or []

        if si_issues:
            log.warning(
                "[ARM2] SI feedback issues: %d",
                len(si_issues),
            )

            for issue in si_issues:
                log.warning(
                    "[ARM2] Scenario %s: SUST_s=%s, "
                    "confidence=%s, reason=%s",
                    issue.get("ScenarioID"),
                    issue.get("SUST_s"),
                    issue.get("SUST_conf"),
                    issue.get("reason"),
                )

        if canonical_csv.exists():
            build_arm2_handover_ready(
                seed_output,
                canonical_csv,
                handover_output,
            )
            arm2_ready_csv = handover_output
        else:
            log.warning(
                "[ARM2] Canonical DSS CSV was not found. "
                "Using ARM 1 seed for exchange export."
            )

    except Exception as error:
        if canonical_csv.exists():
            log.warning(
                "[ARM2] API DSS failed after writing canonical "
                "output: %s",
                error,
            )

            build_arm2_handover_ready(
                seed_output,
                canonical_csv,
                handover_output,
            )

            arm2_ready_csv = handover_output

        else:
            log.warning(
                "[ARM2] API DSS failed: %s",
                error,
            )

            workbook = Path(
                cfg.get("dss_workbook", "")
            ).resolve()

            if workbook.exists():
                run(
                    [
                        sys.executable,
                        HERE / "export_dss_answer_sheet.py",
                        "--workbook",
                        workbook,
                        "--output-dir",
                        dss_dir,
                        "--source-run-id",
                        run_id,
                    ],
                    "ARM2 export_dss_answer_sheet fallback",
                )

                if canonical_csv.exists():
                    arm2_ready_csv = canonical_csv
            else:
                log.error(
                    "[ARM2] No DSS workbook was found. "
                    "DSS fallback was skipped."
                )

    # ARM 2 exchange export
    review_csv = (
        post_dir
        / "bim_post_logic_REVIEW_REQUIRED.csv"
    )

    run(
        [
            sys.executable,
            HERE / "export_vendor_neutral_exchange.py",
            "--ready-file",
            arm2_ready_csv,
            "--review-file",
            review_csv if review_csv.exists() else "",
            "--output-dir",
            exchange_dir,
            "--source-run-id",
            run_id,
        ],
        "ARM2 export_vendor_neutral_exchange",
    )

    run(
        [
            sys.executable,
            HERE / "build_unified_exchange_db.py",
            "--exchange-dir",
            exchange_dir,
            "--answer-dir",
            dss_dir,
            "--output-db",
            exchange_db,
        ],
        "ARM2 build_unified_exchange_db",
    )

    log.info("[ARM2 IfcLCA] Running scenario validation")

    ifclca_failures: list[str] = []
    mapping_file = HERE / "ifclca_material_mapping.csv"


    for scenario, alpha_key in [
        ("REN", "alpha_REN"),
        ("DIS", "alpha_DIS"),
        ("DEM", "alpha_DEM"),
    ]:
        ifclca_command = [
            sys.executable,
            HERE / "ifclca_scenario.py",
            "--input-ifc",
            ifc,
            "--scenario",
            scenario,
            "--alpha-factor",
            cfg[alpha_key],
            "--output-dir",
            root / "ifclca",
            "--lca-source",
            "api",
            "--okobaudat-cache",
            HERE / "okobaudat_cache.json",
        ]

        if mapping_file.exists():
            ifclca_command.extend(
                [
                    "--mapping-file",
                    mapping_file,
                ]
            )
        else:
            log.warning(
                "[ARM2 IfcLCA] Manual mapping file not found: %s. "
                "Automatic mapping only.",
                mapping_file,
            )

        success = run(
            ifclca_command,
            f"ARM2 IfcLCA {scenario}",
            non_fatal=True,
        )

        if not success:
            ifclca_failures.append(scenario)

    if ifclca_failures:
        log.warning(
            "[ARM2 IfcLCA] Failed scenarios: %s",
            ", ".join(ifclca_failures),
        )

    import json as _json
    ifclca_dir = root / "ifclca"
    combined = {}
    individual_paths = []
    for scenario in ("REN", "DIS", "DEM"):
        result_path = ifclca_dir / f"ifclca_{scenario.lower()}_result.json"
        if result_path.exists():
            with result_path.open(encoding="utf-8") as handle:
                combined[scenario] = _json.load(handle)
            individual_paths.append(result_path)
    if combined:
        combined_path = ifclca_dir / "ifclca_whole_building_comparison.json"
        combined_path.write_text(
            _json.dumps(combined, indent=2, default=str), encoding="utf-8"
        )
        log.info(
            "[ARM2 IfcLCA] Combined REN/DIS/DEM comparison written to: %s",
            combined_path,
        )
        for p in individual_paths:
            p.unlink()
    else:
        log.info(
            "[ARM2 IfcLCA] All scenarios completed"
        )

    # ARM 3a: IFC Pset stamping
    run(
        [
            sys.executable,
            HERE / "apply_exchange_to_ifc.py",
            "--exchange-db",
            exchange_db,
            "--input-ifc",
            ifc,
            "--output-ifc",
            output_ifc,
            "--report",
            root / "ifc" / "ifc_import_report.csv",
        ],
        "ARM3a apply_exchange_to_ifc",
    )

    # ARM 3b: CDE notification
    run(
        [
            sys.executable,
            HERE / "cde_issue_notifier.py",
            "--exchange-db",
            exchange_db,
            "--output-dir",
            root / "cde",
        ],
        "ARM3b cde_issue_notifier",
    )

    # ARM 3c: digital-twin synchronisation
    dt_sync_script = HERE / "dt_sync.py"

    if dt_sync_script.exists():
        run(
            [
                sys.executable,
                dt_sync_script,
                "--current-ifc",
                output_ifc,
                "--exchange-db",
                exchange_db,
                "--output-dir",
                root / "sync",
            ],
            "ARM3c dt_sync",
        )

    # ARM 3: IFC validation
    validator_script = HERE / "ifc_validator.py"

    if validator_script.exists() and output_ifc.exists():
        run(
            [
                sys.executable,
                validator_script,
                "--input-ifc",
                output_ifc,
                "--output-dir",
                root / "validation",
            ],
            "ARM3 ifc_validator",
        )

    # ARM 3: IDS checking
    ids_script = HERE / "ids_checker.py"
    ids_file = (
        HERE
        / "schemas"
        / "field2bim_structural.ids"
    )

    if (
        ids_script.exists()
        and output_ifc.exists()
        and ids_file.exists()
    ):
        run(
            [
                sys.executable,
                ids_script,
                "--input-ifc",
                output_ifc,
                "--ids-file",
                ids_file,
                "--output-dir",
                root / "validation",
            ],
            "ARM3 ids_checker",
        )

    # ARM 3: audit report
    audit_script = HERE / "audit_reporter.py"

    if audit_script.exists():
        run(
            [
                sys.executable,
                audit_script,
                "--run-root",
                root,
                "--output-dir",
                root / "audit",
            ],
            "ARM3 audit_reporter",
        )

    log.info("=" * 60)

    if ifclca_failures:
        log.warning(
            "Field2BIM pipeline COMPLETE WITH IFC LCA WARNINGS"
        )
    else:
        log.info(
            "Field2BIM API-Based Circular DSS — COMPLETE"
        )

    log.info("Run ID: %s", run_id)
    log.info("IFC input: %s", ifc)
    log.info("Annotated IFC: %s", output_ifc)
    log.info("Output root: %s", root)


if __name__ == "__main__":
    main()