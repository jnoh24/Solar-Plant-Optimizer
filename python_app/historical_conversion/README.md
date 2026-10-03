# Historical Conversion Checks

These files freeze the pre-assumption-update Python model and its conversion
tests. They are not imported by the dashboard or current correctness tests.
Run from `python_app` with:

```bash
python3 historical_conversion/verify_conversion.py
```

The tests read the unchanged parent `reference.json`, comparing the archived
Python implementation to stored historical JavaScript outputs. They do not run
or require the old JavaScript application. Old rapid hourly degradation and
inspection recovery are intentionally retained here only to document the
original conversion, not as current modeling assumptions.
