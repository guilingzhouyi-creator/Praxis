.PHONY: install test test-fast test-extended test-all lint lint-fix format format-check typecheck coverage doc-index doc-stats changelog changelog-check clean dev hooks precommit push-both bump-version release-build

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
	ruff check src/ tests/

lint-fix:
	ruff check --fix src/ tests/

format:
	ruff format src/ tests/

format-check:
	ruff format --check src/ tests/

typecheck:
	mypy src/ --no-namespace-packages --ignore-missing-imports --allow-untyped-calls --allow-untyped-decorators

coverage:
	python -m pytest tests/ -q --tb=short --cov=src --cov-report=term --cov-report=html --cov-fail-under=60 --ignore=tests/benchmarks/bench_card.py

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

precommit:
	pre-commit run --all-files

clean:
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
	python -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in [pathlib.Path('.ruff_cache'), pathlib.Path('.pytest_cache'), pathlib.Path('htmlcov')]]"
	python -c "import os; [os.remove(f) for f in ['.coverage'] if os.path.exists(f)]"
	rm -rf *.egg-info 2>/dev/null; true

dev:
	python src/main.py boot

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
