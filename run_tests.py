"""
GhostTrace Automated Test Runner
Discovers and executes all unit and integration tests across tests/
"""

import sys
import os
import time
import inspect
import importlib.util
import unittest

# Add workspace to sys.path
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

# Fix pytest shadowing if present in Python root
site_pytest_path = os.path.join(sys.prefix, "Lib", "site-packages", "pytest", "__init__.py")
if os.path.exists(site_pytest_path):
    spec = importlib.util.spec_from_file_location("pytest", site_pytest_path)
    real_pytest = importlib.util.module_from_spec(spec)
    sys.modules["pytest"] = real_pytest
    spec.loader.exec_module(real_pytest)

def run_all_tests():
    test_files = [
        "test_data_generator.py",
        "test_graph_engine.py",
        "test_cycle_bounds.py",
        "test_dashboard_correctness.py",
        "test_investigators.py",
        "test_sar_generator.py",
        "test_benchmark.py",
        "test_amlsim_adapter.py",
        "test_amlsim_adapter_verification.py",
        "test_amlsim_official_sample.py",
    ]

    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    skipped_tests = 0

    print("=" * 70)
    print("GHOSTTRACE TEST EXECUTION SUITE")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    for tf in test_files:
        path = os.path.join(WORKSPACE_DIR, "tests", tf)
        if not os.path.exists(path):
            print(f"[SKIP] {tf} not found")
            continue

        module_name = f"tests.{tf[:-3]}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)

        # Find test functions
        test_funcs = [
            (name, func) for name, func in inspect.getmembers(mod, inspect.isfunction)
            if name.startswith("test_")
        ]

        print(f"\n[SUITE] {tf} ({len(test_funcs)} tests)")
        for name, func in test_funcs:
            total_tests += 1
            t0 = time.perf_counter()
            try:
                func()
                elapsed = (time.perf_counter() - t0) * 1000.0
                print(f"  [PASS] {name:<40} ({elapsed:.1f}ms)")
                passed_tests += 1
            except unittest.SkipTest as e:
                elapsed = (time.perf_counter() - t0) * 1000.0
                print(f"  [SKIP] {name:<40} ({elapsed:.1f}ms) - {e}")
                skipped_tests += 1
            except AssertionError as e:
                elapsed = (time.perf_counter() - t0) * 1000.0
                print(f"  [FAIL] {name:<40} ({elapsed:.1f}ms) - Assertion: {e}")
                failed_tests += 1
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000.0
                print(f"  [ERROR] {name:<40} ({elapsed:.1f}ms) - Exception: {e}")
                failed_tests += 1

    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed_tests}/{total_tests} tests passed "
          f"({failed_tests} failed, {skipped_tests} skipped).")
    print("=" * 70)

    if failed_tests > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    run_all_tests()
