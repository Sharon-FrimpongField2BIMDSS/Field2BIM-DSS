from __future__ import annotations

"""
ids_checker.py
==============
ARM 3 Utility 2 — IDS Compliance Checker


Validates annotated IFC against IDS (Information Delivery Specification) schema files.
IDS is the buildingSMART standard for declaring and checking information requirements.
Confirms mandatory Psets and properties are present on the correct IFC classes.


Vendor-neutral: IDS is an open buildingSMART standard (XML format).
Standards basis: IDS (buildingSMART International); ISO 19650-2 §5.3 info quality.
Two modes:
 1. ifctester library (pip install ifctester) — full IDS XML validation
 2. Built-in fallback — retained only for direct library use when no IDS file is supplied
"""
import sys
import argparse, csv, json, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# Minimum required properties per Pset — static, same for every project
# These match the 5 custom Psets in apply_exchange_to_ifc_v2.py
MINIMUM_IDS = {
    "Pset_Field2BIM_DCS": ["DataConfidenceScore"],
    "Pset_Field2BIM_Triangulation": ["TriangulationConfidence","ReviewFlag"],
    "Pset_CircularityMetadata": ["CircularityScore"],
    "Pset_DSS_ScenarioOutput": ["DSSAction","BestScenario"],
    "Pset_GWP_LCA": ["GlobalWarmingPotential"],
}

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def check_ids(ifc_path: Path, ids_path: Path | None, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = now(); t = ts.replace(":","").replace("-","")
    results = {"ifc_file":str(ifc_path),"ids_file":str(ids_path) if ids_path else "built-in",
               "timestamp":ts,"checks":[],"passed":0,"failed":0}

    # Mode 1: ifctester
    if ids_path and ids_path.exists():
        try:
            from ifctester import ids, reporter  # type: ignore
            import ifcopenshell
            my_ids = ids.open(str(ids_path))
            my_ifc = ifcopenshell.open(str(ifc_path))
            my_ids.validate(my_ifc)
            report = reporter.Json(my_ids)
            report.to_file(str(output_dir/f"ids_report_{t}.json"))
            passed = sum(1 for s in my_ids.specifications if s.status)
            failed = sum(1 for s in my_ids.specifications if not s.status)
            results.update({"mode":"ifctester","passed":passed,"failed":failed,
                "overall":"PASS" if failed==0 else "FAIL"})
            print(f"[ids_checker] ifctester: {passed} passed {failed} failed")
            return results
        except ImportError as error:
            results["checks"].append({"check":"ifctester_available","status":"FAIL",
                "detail":f"Install the required ifctester dependency: {error}"})
            results["failed"] += 1
            results["overall"] = "FAIL"
            (output_dir/f"ids_report_{t}.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8")
            print("[ids_checker] FAIL: ifctester is required when an IDS file is supplied")
            return results
        except Exception as e:
            results["checks"].append({"check":"ifctester_execution","status":"FAIL",
                "detail":f"IDS validation failed inside ifctester: {e}"})
            results["failed"] += 1
            results["overall"] = "FAIL"
            (output_dir/f"ids_report_{t}.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8")
            print(f"[ids_checker] FAIL: ifctester error: {e}")
            return results

    # Mode 2: built-in fallback
    try:
        import ifcopenshell
        model = ifcopenshell.open(str(ifc_path))
        psets_in_model = {}
        for ps in model.by_type("IfcPropertySet"):
            if ps.Name and ps.Name in MINIMUM_IDS:
                props = {p.Name for p in (ps.HasProperties or [])}
                psets_in_model.setdefault(ps.Name, set()).update(props)

        for pset_name, required_props in MINIMUM_IDS.items():
            found_props = psets_in_model.get(pset_name, set())
            for prop in required_props:
                if prop in found_props:
                    results["checks"].append({"check":f"{pset_name}.{prop}",
                        "status":"PASS","detail":"Property present"})
                    results["passed"] += 1
                else:
                    results["checks"].append({"check":f"{pset_name}.{prop}",
                        "status":"FAIL","detail":"Property missing from IFC"})
                    results["failed"] += 1

        results.update({"mode":"built-in","overall":"PASS" if results["failed"]==0 else "FAIL"})
    except ImportError:
        results["checks"].append({"check":"ifcopenshell","status":"FAIL",
            "detail":"pip install ifcopenshell"})
        results["failed"] += 1
        results["overall"] = "FAIL"

    (output_dir/f"ids_report_{t}.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    with (output_dir/f"ids_report_{t}.csv").open("w",newline="",encoding="utf-8") as f:
        w = csv.DictWriter(f,fieldnames=["check","status","detail"])
        w.writeheader(); w.writerows(results.get("checks",[]))
    print(f"[ids_checker] {results.get('overall')}: {results['passed']} passed {results['failed']} failed")
    return results

def main():
    p = argparse.ArgumentParser(description="IDS compliance checker — ARM 3 utility")
    p.add_argument("--input-ifc", type=Path, required=True)
    p.add_argument("--ids-file", type=Path, default=None, help="IDS XML schema file (optional)")
    p.add_argument("--output-dir", type=Path, default=Path("outputs/validation"))
    a = p.parse_args()
    results = check_ids(a.input_ifc, a.ids_file, a.output_dir)
    if results.get("overall") == "FAIL":
        raise SystemExit(1)

if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    main()
