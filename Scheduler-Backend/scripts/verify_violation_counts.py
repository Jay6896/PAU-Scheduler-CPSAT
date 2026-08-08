"""
Simple verifier for backend result JSON vs detailed constraint violations.

Usage: run from repo root. It reads:
 - data/timetable_data.json (latest saved result produced by the backend)
 - data/constraint_violations.json (detailed per-violation lists)

It computes several metrics and reports mismatches so the frontend badge number
can be validated against the detailed breakdown.
"""
import json
import os
from typing import Any, Dict

BASE = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE, 'data')

def load_json(path: str) -> Any:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Could not load {path}: {e}")
        return None


def main():
    timetable_path = os.path.join(DATA_DIR, 'timetable_data.json')
    fresh_path = os.path.join(DATA_DIR, 'fresh_timetable_data.json')
    violations_path = os.path.join(DATA_DIR, 'constraint_violations.json')

    result = load_json(timetable_path) or load_json(fresh_path) or {}
    detailed = load_json(violations_path) or {}

    impossible = result.get('impossible_constraints') or []
    unsatisfied = result.get('unsatisfied_constraints') or []

    badge_aggregate_count = len(impossible) + len(unsatisfied)
    badge_unique_types = len({(i.get('type'), i.get('message')) for i in (impossible + unsatisfied) if isinstance(i, dict)})

    total_detailed_occurrences = 0
    nonzero_types = 0
    for k, v in (detailed or {}).items():
        if isinstance(v, list):
            n = len(v)
            total_detailed_occurrences += n
            if n > 0:
                nonzero_types += 1

    print("Verifier report:\n------------------")
    print(f"Result file used: {timetable_path if os.path.exists(timetable_path) else fresh_path}")
    print(f"Badge aggregate count (impossible + unsatisfied length): {badge_aggregate_count}")
    print(f"Badge unique (type+message) entries: {badge_unique_types}")
    print(f"Detailed violation types with occurrences: {nonzero_types}")
    print(f"Total detailed violation occurrences: {total_detailed_occurrences}")

    if badge_aggregate_count != total_detailed_occurrences:
        print('\nMismatch detected: badge count != total detailed occurrences')
    else:
        print('\nCounts match: badge aggregate equals total detailed occurrences')

    print('\nTypes reported by backend (impossible+unsatisfied):')
    seen = set()
    for i in impossible + unsatisfied:
        if not isinstance(i, dict):
            continue
        t = i.get('type') or i.get('label') or i.get('message')
        if t in seen:
            continue
        seen.add(t)
        print(f" - {t}")

    print('\nDetailed violation keys with counts:')
    for k, v in (detailed or {}).items():
        if isinstance(v, list) and len(v) > 0:
            print(f" - {k}: {len(v)}")

    if badge_aggregate_count != total_detailed_occurrences:
        print('\nVERIFICATION: FAIL')
        raise SystemExit(2)
    else:
        print('\nVERIFICATION: PASS')


if __name__ == '__main__':
    main()