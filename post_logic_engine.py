#!/usr/bin/env python3
"""Post-logic engine for BIM-first Field2BIM processor.


Stages covered here:
- finalize Arm 2 handoff files
- emit explicit post-logic contracts
"""
from __future__ import annotations

import sys
import argparse
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError


def safe_read_csv(path: Path, fallback_columns: list[str] | None = None) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(columns=fallback_columns or [])


def run_post_logic(integrated_output_dir: Path, post_output_dir: Path) -> None:
    post_output_dir.mkdir(parents=True, exist_ok=True)
    ready = safe_read_csv(integrated_output_dir / "integrated_dss_ready_or_review.csv")
    review = safe_read_csv(integrated_output_dir / "integrated_review_required.csv", fallback_columns=list(ready.columns))
    seed1 = safe_read_csv(integrated_output_dir / "dss_seed_1_element_library.csv")
    seed7 = safe_read_csv(integrated_output_dir / "dss_seed_7_governance.csv")

    ready.to_csv(post_output_dir / "bim_post_logic_READY_FOR_DSS.csv", index=False)
    review.to_csv(post_output_dir / "bim_post_logic_REVIEW_REQUIRED.csv", index=False)
    seed1.to_csv(post_output_dir / "bim_post_logic_seed_1_element_library.csv", index=False)
    seed7.to_csv(post_output_dir / "bim_post_logic_seed_7_governance.csv", index=False)

    contract = pd.DataFrame(
        [
            {"OutputFile": "bim_post_logic_READY_FOR_DSS.csv", "Purpose": "Integrated element-level evidence and gate outcomes"},
            {"OutputFile": "bim_post_logic_REVIEW_REQUIRED.csv", "Purpose": "Manual review queue for low-confidence or incomplete records"},
            {"OutputFile": "bim_post_logic_seed_1_element_library.csv", "Purpose": "DSS seed data for workbook sheet 1_Element_Library"},
            {"OutputFile": "bim_post_logic_seed_7_governance.csv", "Purpose": "DSS seed data for workbook sheet 7_Governance"},
        ]
    )
    contract.to_csv(post_output_dir / "bim_post_logic_output_contract.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run BIM-first post-logic engine.")
    parser.add_argument("--integrated-output-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    run_post_logic(args.integrated_output_dir, args.output_dir)
    print(args.output_dir)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
