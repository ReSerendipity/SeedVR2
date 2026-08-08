"""Performance test scripts (not collected by pytest).

This package contains locust-based performance test scripts that require
the `locust` package, which is not a standard test dependency. These
scripts are meant to be run manually via:

    locust -f tests/perf/load_test.py --headless -u 20 -r 2 -t 5m

To prevent pytest from trying to collect/import these modules (which
would fail with ModuleNotFoundError when locust is not installed),
this __init__.py declares collect_ignore_glob for all modules.
"""

# Prevent pytest from collecting modules in this package
collect_ignore_glob = ["*"]
