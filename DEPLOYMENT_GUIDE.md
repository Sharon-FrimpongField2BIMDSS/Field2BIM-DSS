# Field2BIM Pilot Deployment Guide

## 1. Purpose

This guide defines the repeatable pilot process for running the Field2BIM API pipeline on a user's Windows machine. It is written for BIM, survey, data, and review teams. A normal operator should only need to provide an IFC file and confirm the input data.

The package has two parts:

- `bootstrap_deployment.ps1`: prepares and verifies the selected Python environment, then starts the pipeline.
- This guide: defines responsibilities, inputs, outputs, gates, warnings, and recovery.

The bootstrap does not install Python itself. Python must already be available on the machine. It can use any Python command that successfully installs and imports all required packages.

## 2. Proven pilot baseline

Run `5460D846` completed with Python 3.14.5 through the bootstrap. The run logs show that ARM0, ARM1a, ARM1b, ARM1c, API DSS, all three IfcLCA scenarios, IFC stamping, IFC validation, IDS validation, sync, and audit returned code 0.

Observed outputs from that run:

- ARM0: `16 PASS, 0 FAIL, 1 WARN`
- IfcLCA: REN, DIS, and DEM completed
- IFC validator: `8 passed, 0 failed, 1 warning`
- IDS validator: `5 passed, 0 failed`
- Audit: `3471` elements, `0` HALT
- Sync: baseline registered, `0` deltas

This proves that the current pilot package executes on the tested machine. It does not prove that every new project has complete evidence or that every output is substantively ready for approval.

The active API economic model does not use a Weibull reliability factor. Earlier configuration/documentation mentioned Weibull parameters, but the executed API calculation never consumed them; those inactive parameters have been removed from the active deployment contract. Maintenance is currently a declared real-price escalation input only.

## 3. Machine prerequisites

The operator needs:

- Windows PowerShell
- Python available as `python`, `py -3.11`, `py -3.12`, `py -3.14`, or a full `python.exe` path
- Internet access for first-time package installation
- Microsoft Visual C++ runtime available to the selected Python environment when required by native IFC packages
- An input IFC file

The required Python distributions are installed by `install_dependencies.py`:

```text
pandas
pyyaml
openpyxl
ifcopenshell
ifclca
requests
ifctester
```

Python environments are isolated. Installing a package into Python 3.11 does not make it available to Python 3.14. The bootstrap always installs and runs with the same `$PythonCommand`.

## 4. Pilot package contents

Give the team these source files and folders:

### Entry point and setup

- `bootstrap_deployment.ps1`
- `install_dependencies.py`
- `run_field2bim_pipeline_api.py`
- `project_config.yaml`

### Pipeline scripts

- `run_arm0_setup.py`
- `pre_logic_engine.py`
- `integrated_logic_engine.py`
- `post_logic_engine.py`
- `bind_model_and_sensor_data.py`
- `build_arm1_dss_seeds.py`
- `dss_equations_api.py`
- `export_vendor_neutral_exchange.py`
- `build_unified_exchange_db.py`
- `ifclca_scenario.py`
- `okobaudat_api_reader.py`
- `apply_exchange_to_ifc.py`
- `cde_issue_notifier.py`
- `dt_sync.py`
- `ifc_validator.py`
- `ids_checker.py`
- `audit_reporter.py`

### Supporting modules

- `arm1_db.py`
- `import_bim_model_metadata.py`
- `import_sensor_evidence.py`
- `import_binding_ledger.py`

### Static project inputs

- `Inputs/arm1_schema.sql`
- `Inputs/model_register.csv`
- `Inputs/sensor_evidence.csv`
- `Inputs/binding_ledger.csv`
- `ifclca_material_mapping.csv`
- `okobaudat_cache.json`
- `Schemas/field2bim_structural.ids`
- `Field2BIM_DSS_Structural_Scope_v1.xlsx`
- `Models/` containing the pilot IFC supplied by the team

For unified economic MCDA mode, also include `economic_inputs.yaml`. The file must contain the selected source records, quantities, values, and explicit pilot assumptions. ARM0 blocks unified economic scoring if required values are missing.

Do not distribute previous `outputs/` run folders as deployment source material. They are evidence examples and historical results.

## 5. Configuration responsibilities

`project_config.yaml` contains project-level settings and relative paths. The team must review:

- `sensor_evidence_csv`
- `binding_ledger_csv`
- `model_register_csv`
- `ids_schema`
- `output_root`
- building metadata and GFA
- LCA scenario factors
- MCDA weights
- `run_mode`
- `dss_calculation_mode` and `workbook_fallback_enabled`
- `unified_economic_mcda` and `economic_inputs_file`

`run_mode: deployment` means missing Delphi evidence is reported as a warning and normative weights remain explicit. It does not mean Delphi evidence exists. Use `thesis_final` only when the required Delphi evidence is present and accepted by the research method owner.

The input IFC must be the original model. The writeback guard rejects an annotated IFC from being used as a new source input.

API-first mode uses `dss_equations_api.py` as the authoritative DSS calculator. The workbook is not required for an API run. It is retained only as a fallback/reference artifact and is used only when the configured workbook fallback is reached.

Unified economic mode requires four comparable scenario calculations: `NPV_BAU`, `NPV_REN`, `NPV_DIS`, and `NPV_DEM`. It also requires explicit currency, region, price basis, base year, cost source, discount-rate basis, and carbon valuation source. Missing values are a block, not a default.

## 6. One-command pilot procedure

Open PowerShell in the project folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap_deployment.ps1 -InputIfc .\Models\Gymnasium_Bolzano.ifc
.\bootstrap_deployment.ps1 -InputIfc .\Models\Gymnasium_Bolzano.ifc
```

If the team wants to select a specific interpreter, pass its command or full path:

```powershell
.\bootstrap_deployment.ps1 `
  -PythonCommand "C:\Path\To\python.exe" `
  -InputIfc "C:\Path\To\model.ifc"
```

The command installs packages into that interpreter, verifies imports, and launches `run_field2bim_pipeline_api.py` with that same interpreter. Do not install with one Python command and execute with another.

## 7. Workflow and gates

```text
Input IFC + CSV evidence + YAML + IDS
          |
          v
ARM0: configuration and readiness gate
          |
          v
ARM1a: model, sensor, and ledger staging
          |
          v
ARM1b: binding resolution and evidence integration
          |
          v
ARM1c: post-logic contracts and review queues
          |
          v
ARM2: DSS scoring and REN/DIS/DEM LCA
          |
          v
ARM3a: IFC property writeback
          |
          v
ARM3b/c: review issues and sync
          |
          v
ARM3: IFC validation, IDS validation, and audit
```

A nonzero dependency/setup result blocks the run. ARM0 `FAIL` blocks progression. LCA scenario failures are intended to be non-fatal in the current orchestrator, so the operator must inspect the run summary and LCA logs rather than treating process exit alone as substantive success.

Warnings require review:

- Missing Delphi evidence
- Low DIS or DEM sustainability score
- Missing optional LCA data
- Missing GWP B6 property
- Review rows or unresolved material mappings

## 8. Outputs to retain

Each execution creates a unique folder under `outputs/`, for example:

```text
outputs/Gymnasium_Bolzano_YYYYMMDDTHHMMSS_RUNID/
```

Retain these primary outputs:

- `ifc/*_Field2BIM_DSS_Annotated.ifc`
- `audit/audit_report_*.json`
- `validation/ifc_validation_*.json`
- `validation/ids_report_*.json`
- `ifclca/ifclca_whole_building_comparison.json`
- `exchange/openbim_property_update.csv`
- `exchange/bcf_issue_register.csv`
- `exchange/cde_status_register.csv`
- `exchange/workflow_run_log.csv`
- `logs/` for reproducibility and diagnosis

Retain `pre/`, `integrated/`, and `post/` when the team needs to trace evidence, bindings, review decisions, or DSS seed values. The `db/` folder is the machine-readable exchange database for that run.

The shared folders `outputs/arm0` and `outputs/sync` are not required as source inputs for a new run. The run-specific `arm0/` and `sync/` folders are the authoritative evidence for that execution.

## 9. How to judge a run

A technically completed run should show all of the following:

- ARM0 has no `FAIL` checks
- LCA scenario logs have return code 0 and result files exist
- IFC validator reports `overall: PASS`
- IDS report contains an actual ifctester result, not a fallback
- Audit and exchange row counts are reviewed for consistency
- Review queues are addressed before external approval
- Economic input provenance is complete when unified economic MCDA is enabled

Do not interpret `READY` counts alone as substantive evidence readiness. Compare them with DCS, triangulation, review, and audit counts.

Negative NPV values in the current output are signed net costs, not positive benefits. The implementation represents capital cost and maintenance as negative cash flows, with recovery and carbon value as positive offsets. A more negative value therefore means a larger net cost under this convention. It must not be described as a negative financial return unless the cash-flow sign convention is changed and the output is renamed accordingly.

For run `5460D846`, the corrected audit reports `6 READY`, `3465 REVIEW`, and `0 HALT`. The mean DCS is `0.0013`, with only 6 elements above DCS `0.6`. This is a technically completed run with very low evidence coverage, not evidence that the whole model is ready for approval.

## 10. Recovery procedure

### Dependency failure

Run the bootstrap again with the exact interpreter intended for execution. Check that `install_dependencies.py` reports `OK` for all seven imports. If a native IFC import fails, install or repair the Microsoft Visual C++ runtime and repeat the bootstrap.

### LCA failure

Open the relevant `logs/ARM2_IfcLCA_*.log`. Confirm the exact exception, the interpreter path, the `ifclca_material_mapping.csv`, and the ÖKOBAUDAT cache. Do not infer the cause from the final pipeline warning.

### IDS failure

Open `validation/ids_report_*.json` and `logs/ARM3_ids_checker.log`. A missing `ifctester`, invalid IDS XML, an ifctester API error, and an IFC content failure are different problems and require different fixes.

### Data or review failure

Inspect:

- `pre/bim_pre_logic_readiness_checks.csv`
- `integrated/bim_data_coverage_audit.csv`
- `integrated/integrated_review_required.csv`
- `exchange/bcf_issue_register.csv`
- `ifclca/ifclca_excluded_materials.csv`

Correct the responsible source data, then rerun from the original IFC. Do not manually edit generated run outputs as a substitute for correcting inputs.

## 11. Pilot ownership

- BIM manager: IFC identity, model register, IDS schema, and output acceptance
- Survey/data team: sensor evidence, calibration, timestamps, and binding ledger
- Structural/LCA team: structural scope, material mappings, scenario factors, and exclusions
- Research/governance team: MCDA weights, Delphi evidence, review thresholds, and methodological approval
- DSS/data manager: review queue, BCF issues, exchange package, and audit handoff

The pipeline automates processing. It does not replace responsible-person approval of evidence, material exclusions, review items, or methodological choices.
