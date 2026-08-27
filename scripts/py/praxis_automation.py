"""CLI for planning, running, and diagnosing declarative automation."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_lib"))

from automation_exec import AutomationRunner  # noqa: E402
from automation_plan import DEFAULT_MANIFEST, AutomationManifest, ManifestError  # noqa: E402


def _load(path: str) -> AutomationManifest:
    """Load a manifest and translate validation errors for the CLI."""
    return AutomationManifest.load(path or DEFAULT_MANIFEST)


def _print(value: object, as_json: bool) -> None:
    """Print structured output in JSON or a compact human-readable form."""
    if as_json:
        print(json.dumps(value, indent=2, sort_keys=True))
    else:
        print(value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    """Parse and execute an automation CLI command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "run", "report", "doctor"))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--workflow", default="performance")
    parser.add_argument("--input", default="", help="JSON run artifact for report")
    parser.add_argument("--output", default="", help="write a JSON run artifact")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            data = json.loads(Path(args.input).read_text(encoding="utf-8"))
            _print(data, args.json)
            return 0 if data.get("ok") else 1
        manifest = _load(args.manifest)
        workflow = manifest.workflow(args.workflow)
        if args.command == "plan":
            _print({"workflow": workflow.name, "steps": [step.step_id for step in workflow.plan()]}, args.json)
            return 0
        if args.command == "doctor":
            missing = sorted(
                {
                    step.command[0]
                    for step in workflow.steps
                    if step.command
                    and step.command[0] not in {"python", "python3"}
                    and shutil.which(step.command[0]) is None
                }
            )
            result = {"workflow": workflow.name, "manifest": args.manifest, "ok": not missing, "missing": missing}
            _print(result, args.json)
            return 0 if not missing else 1
        run = AutomationRunner().run(workflow, dry_run=args.dry_run)
        payload = run.as_dict()
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _print(payload, args.json)
        return 0 if run.ok or args.dry_run else 1
    except (ManifestError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
