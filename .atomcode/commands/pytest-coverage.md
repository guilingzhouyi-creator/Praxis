Run pytest with coverage report.

## Usage

```
/pytest-coverage [file_or_directory]
```

## Examples

```
/pytest-coverage            # Run all tests with coverage
/pytest-coverage tests/l2   # Run L2 tests with coverage
```

## Notes

Uses `pytest-cov` configured in pyproject.toml. Coverage threshold: 60%.
