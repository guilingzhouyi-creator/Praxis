.PHONY: install test test-fast test-extended test-all lint lint-fix format format-check typecheck coverage system-boundaries system-naming doc-index doc-stats changelog changelog-check clean dev hooks precommit push-both bump-version release-build automation-plan automation-run automation-report automation-doctor ts-install ts-test ts-typecheck rust-test rust-contract-test rust-test-domain rust-fmt-check rust-clippy rust-benchmark rust-benchmark-blocking rust-worker-benchmark rust-worker-batch-submit-benchmark rust-runtime-benchmark rust-runtime-batch-benchmark rust-session-benchmark rust-session-batch-benchmark rust-session-snapshot-page-benchmark rust-session-snapshot-page-contention-benchmark rust-registry-base-benchmark rust-agent-loop-benchmark rust-agent-loop-lookup-benchmark rust-agent-loop-batch-benchmark rust-agent-loop-snapshot-page-benchmark rust-terminal-benchmark rust-terminal-batch-benchmark rust-terminal-snapshot-page-benchmark rust-process-adapter-benchmark rust-managed-process-benchmark rust-process-bridge-benchmark rust-protocol-gate rust-session-store-probe rust-kernel-preflight rust-kernel-entry r2-baseline-bundle r2-baseline-analysis language-check

install:
	pip install -e ".[test]"

test:
	python tests/runner.py --batch 1

test-fast:
	python tests/runner.py --batch 1

test-extended:
	python tests/runner.py --batch 2

test-all:
	python tests/runner.py

lint:
	ruff check systems/python-reference-runtime/ tests/

lint-fix:
	ruff check --fix systems/python-reference-runtime/ tests/

format:
	ruff format systems/python-reference-runtime/ tests/

format-check:
	ruff format --check systems/python-reference-runtime/ tests/

typecheck:
	mypy systems/python-reference-runtime/ --no-namespace-packages --ignore-missing-imports --allow-untyped-calls --allow-untyped-decorators

coverage:
	python -m pytest tests/ -q --tb=short --cov=systems/python-reference-runtime --cov-report=term --cov-report=html --cov-fail-under=60 --ignore=tests/benchmarks/bench_card.py

system-naming:
	python scripts/py/check_system_naming.py

system-boundaries: system-naming
	python scripts/py/check_system_boundaries.py

doc-index:
	python scripts/py/check_doc_index.py

doc-stats:
	python scripts/py/gen_doc_stats.py
	python scripts/py/check_doc_stats.py --fix
	python scripts/py/gen_llms_txt.py
	python scripts/py/check_doc_index.py

hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit .githooks/commit-msg .githooks/post-checkout
	@# Ensure worktrees inherit the same hooksPath and executable bits.
	@for wt in $$(git worktree list --porcelain | awk '/^worktree /{print $$2}'); do \
		git -C "$$wt" config core.hooksPath .githooks 2>/dev/null || true; \
		chmod +x "$$wt/.githooks/commit-msg" "$$wt/.githooks/pre-commit" "$$wt/.githooks/post-checkout" 2>/dev/null || true; \
	done
	@# Commit template for strict Conventional Commits.
	@if [ -f .githooks/commit-template.txt ]; then git config commit.template .githooks/commit-template.txt; fi

precommit:
	pre-commit run --all-files

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in [pathlib.Path('.ruff_cache'), pathlib.Path('.pytest_cache'), pathlib.Path('htmlcov')]]"
	python -c "import os; [os.remove(f) for f in ['.coverage'] if os.path.exists(f)]"
	rm -rf *.egg-info 2>/dev/null; true

dev:
	python systems/python-reference-runtime/main.py boot

push-both:
	bash scripts/sh/push-both.sh

bump-version:
	python scripts/py/bump_version.py

release-build:
	python -m build

changelog:
	python scripts/py/generate_changelog.py

changelog-check:
	python scripts/py/check_changelog.py

layer-quality:
	python scripts/py/layer_quality.py

layer-quality-report:
	python scripts/py/layer_quality.py --report

layer-quality-baseline:
	python scripts/py/layer_quality.py --baseline > config/quality/layer-baseline.yaml

perf-quality:
	python scripts/py/perf_quality.py

perf-quality-report:
	python scripts/py/perf_quality.py --report

perf-quality-baseline:
	python scripts/py/perf_quality.py --baseline > config/quality/perf-baseline.yaml

quality-all:
	python scripts/py/layer_quality.py && python scripts/py/perf_quality.py

automation-plan:
	python scripts/py/praxis_automation.py plan --workflow performance

automation-run:
	python scripts/py/praxis_automation.py run --workflow performance --output .praxis/automation/run.json --json

automation-report:
	python scripts/py/praxis_automation.py report --input .praxis/automation/run.json --json

automation-doctor:
	python scripts/py/praxis_automation.py doctor --workflow performance --json

ts-install:
	npm ci --prefix systems/typescript-shell-engine

ts-test: ts-install
	npm test --prefix systems/typescript-shell-engine

ts-typecheck: ts-install
	npm run typecheck --prefix systems/typescript-shell-engine

rust-test:
	cargo test --workspace --manifest-path systems/rust-kernel-engine/Cargo.toml

rust-contract-test:
	cargo test --tests --manifest-path systems/rust-kernel-engine/Cargo.toml

rust-test-domain:
	@test -n "$(RUST_TEST_DOMAIN)" || (echo "set RUST_TEST_DOMAIN to a Cargo test target, e.g. process_group_runtime" >&2; exit 2)
	cargo test --manifest-path systems/rust-kernel-engine/Cargo.toml --test "$(RUST_TEST_DOMAIN)"

rust-fmt-check:
	cargo fmt --manifest-path systems/rust-kernel-engine/Cargo.toml --all -- --check

rust-clippy:
	cargo clippy --manifest-path systems/rust-kernel-engine/Cargo.toml --workspace --all-targets --all-features -- -D warnings

rust-benchmark:
	PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-kernel-bench

rust-benchmark-blocking:
	PRAXIS_RUST_QUEUE_MODE=blocking \
	PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-kernel-bench

rust-worker-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-worker-bench

rust-worker-batch-submit-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-worker-batch-submit-bench

rust-runtime-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-runtime-bench

rust-runtime-batch-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-runtime-batch-bench

rust-session-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-session-bench

rust-session-batch-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-session-batch-bench

rust-session-snapshot-page-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-session-snapshot-page-bench

rust-session-snapshot-page-contention-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-session-snapshot-page-contention-bench

rust-agent-loop-snapshot-page-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-agent-loop-snapshot-page-bench

rust-terminal-snapshot-page-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-terminal-snapshot-page-bench

rust-registry-base-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-registry-base-bench

rust-terminal-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-terminal-bench

rust-terminal-batch-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-terminal-batch-bench

rust-agent-loop-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-agent-loop-bench

rust-agent-loop-lookup-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-agent-loop-lookup-bench

rust-agent-loop-batch-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-agent-loop-batch-bench

# Process benchmarks construct an explicit direct self-child argv; no platform shell fallback is injected.
rust-process-adapter-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-process-adapter-bench

rust-managed-process-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-managed-process-bench

rust-process-bridge-benchmark:
	@PRAXIS_GIT_REVISION="$${PRAXIS_GIT_REVISION:-$$(git rev-parse --short HEAD 2>/dev/null || printf unknown)}" \
		cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-process-bridge-bench

rust-protocol-gate:
	cargo run --manifest-path systems/rust-kernel-engine/Cargo.toml --release --bin rust-protocol-gate

rust-session-store-probe:
	cargo build --manifest-path systems/rust-kernel-engine/Cargo.toml --bin rust-session-store-probe

rust-kernel-preflight:
	cargo build --manifest-path systems/rust-kernel-engine/Cargo.toml --bin rust-kernel-preflight

rust-kernel-entry:
	cargo build --manifest-path systems/rust-kernel-engine/Cargo.toml --bin rust-kernel-entry

r2-baseline-bundle:
	python scripts/py/r2_baseline_bundle.py --output .praxis/automation/r2-baseline-bundle.json

r2-baseline-analysis: r2-baseline-bundle
	python scripts/py/r2_baseline_analyze.py \
		--input .praxis/automation/r2-baseline-bundle.json \
		--output .praxis/automation/r2-baseline-analysis.json

language-check: ts-test ts-typecheck rust-test rust-fmt-check rust-clippy
