# Automation Perimeter — Declarative DAG Runner

The automation perimeter turns repeatable build, performance, and quality
checks into validated workflows without bypassing Praxis execution controls.

## Components

| Component | Responsibility |
|---|---|
| `config/discovery/automation.yaml` | Versioned workflow and step declarations |
| `scripts/py/automation_manifest.py` | YAML validation and dependency-graph-port-backed deterministic DAG planning |
| `scripts/py/automation_runner.py` | Serial execution through `ProcessPort` and optional side-channel ports |
| `scripts/py/praxis_automation.py` | `plan`, `run`, `report`, and `doctor` CLI |

## Contract

- Commands are argument arrays; no manifest field is interpreted as a shell
  string. `python` is resolved to the active interpreter.
- Every step has a positive timeout and a unique id. Missing dependencies and
  cycles fail before execution. When boot wiring is available, planning uses
  the registered `DependencyGraphPort` (currently backed by the runtime DVG);
  standalone plan/doctor commands retain a local equivalent for pre-boot use.
- A failed step blocks dependents and produces explicit `skipped` results.
- One run-wide `trace_id` flows through every step. Best-effort
  `TracePort`, `ObservabilityPort`, and `EvidencePort` hooks record
  `automation.step.*` without changing the protected process result. When no
  boot adapter is registered, these side channels degrade to no-ops.
- `--dry-run` emits the planned shape without executing commands; it does not
  claim a passing run.

## Usage

```bash
python scripts/py/praxis_automation.py plan --workflow performance
python scripts/py/praxis_automation.py doctor --workflow performance --json
python scripts/py/praxis_automation.py run --workflow performance \
  --output .praxis/automation/run.json --json
python scripts/py/praxis_automation.py report --input .praxis/automation/run.json --json
```

The runner is intentionally serial in this phase. Parallel scheduling and
artifact/provenance publication are later additions built on the same manifest
and evidence contract. The runner imports only `ProcessPort`/`ProcessResult`
and the L1 side-channel port contracts; it never imports L3 observability,
security-evidence, trace, or DVG implementations.
