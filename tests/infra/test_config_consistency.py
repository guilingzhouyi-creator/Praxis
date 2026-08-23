"""Config consistency audit — guards the config layer against regressions.

Covers: tools.yaml param type vocabulary (must stay within the ParamSpec
type_map whitelist), full tools.yaml loadability, discovery YAML
parseability, and the subagent_specs location contract.
"""

from __future__ import annotations

import glob
import json
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CONFIG = os.path.join(ROOT, "config")

VALID_PARAM_TYPES = {"string", "int", "bool", "list", "dict"}


def _load_yaml(rel_path: str) -> dict:
    """Load a repo YAML file relative to the repo root."""
    with open(os.path.join(ROOT, rel_path), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _all_tool_defs() -> list[tuple[str, str, str, dict]]:
    """Yield (layer, domain, tool_name, definition) tuples from tools.yaml."""
    data = _load_yaml("config/tools.yaml")
    for layer in ("layer_1", "layer_2", "layer_3"):
        domains = data.get(layer) or {}
        for domain, tools in domains.items():
            if not isinstance(tools, dict):
                continue
            for name, defn in tools.items():
                if name.startswith("_"):
                    continue
                yield layer, domain, name, defn


def test_tools_yaml_param_types_in_whitelist() -> None:
    """Param ``type`` values must stay within the ParamSpec type_map whitelist."""
    bad: list[str] = []
    for layer, domain, name, defn in _all_tool_defs():
        for p in defn.get("params") or []:
            if isinstance(p, dict) and p.get("type") not in VALID_PARAM_TYPES:
                bad.append(f"{layer}.{domain}.{name}.{p.get('name')}: type={p.get('type')!r}")
    assert not bad, f"param types outside whitelist {sorted(VALID_PARAM_TYPES)}: {bad}"


def test_tools_yaml_full_load() -> None:
    """Every tools.yaml definition must load into TOOL_REGISTRY without skips."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from l3.tool_system.tool_config import ToolConfig

    defined = sum(1 for _ in _all_tool_defs())
    loaded = ToolConfig.load(os.path.join(CONFIG, "tools.yaml"))
    assert loaded == defined, f"loaded {loaded}/{defined} tools — check handler paths"


def test_discovery_yaml_parseable() -> None:
    """All config/discovery/*.yaml files must parse cleanly as mappings."""
    for fpath in sorted(glob.glob(os.path.join(CONFIG, "discovery", "*.yaml"))):
        with open(fpath, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data is None or isinstance(data, dict), f"{fpath} must be a mapping or empty (comment-only)"


def test_subagent_specs_location() -> None:
    """subagent_specs must live in config/discovery, not commands.yaml."""
    commands = _load_yaml("config/commands.yaml")
    assert "subagent_specs" not in commands, "subagent_specs must move to config/discovery/subagent_specs.yaml"
    discovery = _load_yaml("config/discovery/subagent_specs.yaml")
    specs = discovery.get("subagent_specs")
    assert isinstance(specs, dict) and len(specs) >= 8, "subagent_specs registry missing or incomplete"


def test_commit_policy_json_mirror_matches_yaml() -> None:
    """The generated Node mirror must match the YAML policy inputs."""
    policy_path = os.path.join(CONFIG, "discovery", "commits.yaml")
    with open(policy_path, encoding="utf-8") as policy_file:
        policy = yaml.safe_load(policy_file) or {}
    mirror_path = os.path.join(CONFIG, "discovery", "commits.json")
    with open(mirror_path, encoding="utf-8") as mirror_file:
        mirror = json.load(mirror_file)
    mirror_keys = (
        "types",
        "scope_dirs",
        "agents",
        "scopes",
        "placeholder",
        "max_subject_chars",
        "body",
        "strictness",
        "type_content_rules",
    )
    assert mirror == {key: policy[key] for key in mirror_keys if key in policy}
    assert os.path.isfile(os.path.join(ROOT, "scripts", "py", "gen_commits_json.py"))


def test_commit_policy_docs_match_generated_mirror_contract() -> None:
    """Workflow docs must describe the checked-in Node mirror and generator."""
    with open(os.path.join(ROOT, "docs", "workflow", "commits.md"), encoding="utf-8") as docs_file:
        docs = docs_file.read()
    assert "generated `config/discovery/commits.json` mirror" in docs
    assert "`scripts/py/gen_commits_json.py`" in docs
    assert "intentionally absent" not in docs
