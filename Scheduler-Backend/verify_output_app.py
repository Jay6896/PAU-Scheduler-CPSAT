import argparse
import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from typing import Any

import numpy as np

# For app.py runs, we want to build the exact same InputData instance used by the API pipeline.
from input_data_api import initialize_input_data_from_json
from constraints import Constraints


logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


_DAYS_MAP = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}


def _time_to_minutes(time_str: str) -> int | None:
    s = str(time_str or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    return hh * 60 + mm


def _is_available_day(avail_days: list, day_abbr: str) -> bool:
    if not avail_days:
        return True
    normalized = {str(d).strip().upper() for d in avail_days if d is not None}
    if "ALL" in normalized:
        return True
    return day_abbr.strip().upper() in normalized


def _is_available_time(avail_times: list, start_minutes: int) -> bool:
    if not avail_times:
        return True
    normalized = [str(t).strip() for t in avail_times if t is not None]
    if any(t.upper() == "ALL" for t in normalized):
        return True
    for t in normalized:
        m = re.match(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$", t)
        if not m:
            continue
        start = _time_to_minutes(m.group(1))
        end = _time_to_minutes(m.group(2))
        if start is None or end is None:
            continue
        # END-EXCLUSIVE: 9:00-14:00 means hours 9,10,11,12,13 (not 14).
        if start <= start_minutes < end:
            return True
    return False


def _parse_cell(cell: str) -> tuple[str | None, str | None, str | None]:
    """Return (course_code, room_name, lecturer_name) from a timetable cell.

    Supports:
    - Newline format: "CODE\nROOM\nLECTURER"
    - Labeled format: "Course: CODE, Lecturer: X, Room: Y"
    """
    if not cell:
        return None, None, None

    s = str(cell).strip()
    if not s or s in {"BREAK", "FREE"}:
        return None, None, None

    if "\n" in s:
        parts = [p.strip() for p in s.split("\n") if p.strip()]
        if not parts:
            return None, None, None
        course_code = parts[0]
        room_name = parts[1] if len(parts) > 1 else None
        lecturer = parts[2] if len(parts) > 2 else None
        return course_code, room_name, lecturer

    m_course = re.search(r"\bCourse\s*:\s*([^,]+)", s, flags=re.IGNORECASE)
    m_lect = re.search(r"\bLecturer\s*:\s*([^,]+)", s, flags=re.IGNORECASE)
    m_room = re.search(r"\bRoom\s*:\s*(.+)$", s, flags=re.IGNORECASE)
    course_code = m_course.group(1).strip() if m_course else None
    lecturer = m_lect.group(1).strip() if m_lect else None
    room_name = m_room.group(1).strip() if m_room else None
    return course_code, room_name, lecturer


def _build_room_lookup(input_json: dict) -> dict[str, dict]:
    rooms = input_json.get("rooms") or []
    lookup = {}
    for r in rooms:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()
        rid = str(r.get("Id") or r.get("id") or "").strip()
        if name:
            lookup[name] = r
        if rid:
            lookup[rid] = r
    return lookup


def _jsonable(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        # Canonicalize known list fields where order is not semantically meaningful
        out = {}
        for k, v in obj.items():
            key = str(k)
            if key == 'rooms' and isinstance(v, list):
                out[key] = sorted([str(x) for x in v if x is not None])
            elif key == 'courses' and isinstance(v, str) and ',' in v:
                # Some outputs encode multiple courses as a single comma-separated string.
                # Normalize ordering so diffs don't flag equivalent data.
                parts = [p.strip() for p in v.split(',') if p.strip()]
                out[key] = ', '.join(sorted(parts, key=lambda s: s.lower()))
            else:
                out[key] = _jsonable(v)
        return out
    return str(obj)


def _stable_key(v: Any) -> str:
    try:
        return json.dumps(_jsonable(v), sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(v)


def _normalize_violation_dict(d: dict) -> dict:
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        if isinstance(v, list):
            out[str(k)] = sorted([_jsonable(x) for x in v], key=_stable_key)
        else:
            out[str(k)] = _jsonable(v)
    return out


def _diff_violation_dict(expected: dict, actual: dict) -> dict:
    exp = _normalize_violation_dict(expected)
    act = _normalize_violation_dict(actual)
    all_keys = sorted(set(exp.keys()) | set(act.keys()))
    diff = {
        'keys_only_in_expected': [k for k in exp.keys() if k not in act],
        'keys_only_in_actual': [k for k in act.keys() if k not in exp],
        'count_differences': {},
        'examples': {},
    }
    for k in all_keys:
        ev = exp.get(k, [])
        av = act.get(k, [])
        if isinstance(ev, list) and isinstance(av, list):
            if len(ev) != len(av):
                diff['count_differences'][k] = {'expected': len(ev), 'actual': len(av)}
            # show small example mismatch sets
            ev_set = set(_stable_key(x) for x in ev)
            av_set = set(_stable_key(x) for x in av)
            missing = sorted(ev_set - av_set)[:5]
            extra = sorted(av_set - ev_set)[:5]
            if missing or extra:
                diff['examples'][k] = {
                    'missing_examples': missing,
                    'extra_examples': extra,
                }
    return diff


def _compute_app_violation_breakdown(timetables_data: list, rooms_data: list, input_data) -> dict:
    """Compute the same per-constraint breakdown used by the frontend Errors dropdown.

    app.py recomputes and stores this via Dash_UI.recompute_constraint_violations_simplified.
    We call that exact function here so this script can be 1:1 with the UI.
    """
    try:
        import Dash_UI  # local module

        # Dash_UI.recompute_constraint_violations_simplified relies on a module-global `input_data`
        # when available, so we inject the same InputData instance built from the transformer JSON.
        Dash_UI.input_data = input_data
        recomputed = Dash_UI.recompute_constraint_violations_simplified(timetables_data, rooms_data) or {}
        return _normalize_violation_dict(recomputed)
    except Exception as e:
        logger.error(f"Failed to recompute violations via Dash_UI (matching app.py): {e}")
        return {}


def _build_chromosome_from_timetable(timetables_data: list, input_data) -> tuple[np.ndarray, dict]:
    """Reconstruct a chromosome-like grid (rooms x timeslots) from timetables JSON.

    This lets us run the exact constraint engine checks (constraints.py) against a saved timetable.
    Returns: (chromosome, diagnostics)
    """

    rooms = getattr(input_data, 'rooms', []) or []
    hours_per_day = int(getattr(input_data, 'hours', 9) or 9)
    days_per_week = int(getattr(input_data, 'days', 5) or 5)
    timeslots_count = hours_per_day * days_per_week

    # room name/id -> room_idx
    room_index: dict[str, int] = {}
    for idx, r in enumerate(rooms):
        name = str(getattr(r, 'name', '') or '').strip()
        rid = str(getattr(r, 'id', '') or getattr(r, 'Id', '') or '').strip()
        if name:
            room_index[name] = idx
        if rid:
            room_index[rid] = idx

    cons = Constraints(input_data)

    # pool[(group_id, course_code)] = deque([event_id, event_id, ...])
    pool: dict[tuple[str, str], list[int]] = defaultdict(list)
    for event_id, event in (cons.events_map or {}).items():
        try:
            gid = str(getattr(event.student_group, 'id', '') or '').strip()
            course_code = str(getattr(event, 'course_id', '') or '').strip()
            if gid and course_code:
                pool[(gid, course_code)].append(int(event_id))
        except Exception:
            continue
    # determinism
    for k in list(pool.keys()):
        pool[k] = sorted(pool[k])

    chromosome = np.empty((len(rooms), timeslots_count), dtype=object)
    chromosome[:] = None

    diagnostics = {
        'unknown_rooms': [],
        'unknown_groups': [],
        'missing_event_ids': [],
        'slot_collisions': [],
    }

    # group name -> group_id (from input_data)
    group_name_to_id: dict[str, str] = {}
    for g in getattr(input_data, 'student_groups', []) or []:
        gname = str(getattr(g, 'name', '') or '').strip()
        gid = str(getattr(g, 'id', '') or '').strip()
        if gname and gid:
            group_name_to_id[gname] = gid

    for entry in timetables_data or []:
        sg_obj = entry.get('student_group') or {}
        group_id = str(sg_obj.get('id') or '').strip() if isinstance(sg_obj, dict) else str(getattr(sg_obj, 'id', '') or '').strip()
        group_name = str(sg_obj.get('name') or '').strip() if isinstance(sg_obj, dict) else str(getattr(sg_obj, 'name', '') or sg_obj or '').strip()
        if not group_id and group_name:
            group_id = group_name_to_id.get(group_name, '')

        if not group_id:
            if group_name:
                diagnostics['unknown_groups'].append(group_name)
            continue

        rows = entry.get('timetable') or []
        for h_idx, row in enumerate(rows):
            if not isinstance(row, list) or len(row) < 2:
                continue
            if h_idx >= hours_per_day:
                continue
            for d_idx in range(min(days_per_week, max(0, len(row) - 1))):
                cell = row[d_idx + 1]
                course_code, room_name, _lect = _parse_cell(cell)
                if not course_code:
                    continue
                course_code = str(course_code).strip()
                room_name = str(room_name or '').strip()

                room_idx = room_index.get(room_name)
                if room_idx is None:
                    diagnostics['unknown_rooms'].append(room_name or 'Unknown')
                    continue

                timeslot_idx = (d_idx * hours_per_day) + h_idx
                if timeslot_idx < 0 or timeslot_idx >= timeslots_count:
                    continue

                key = (group_id, course_code)
                if not pool.get(key):
                    diagnostics['missing_event_ids'].append({'group_id': group_id, 'group': group_name, 'course': course_code})
                    continue

                event_id = pool[key].pop(0)

                existing = chromosome[room_idx, timeslot_idx]
                if existing is not None:
                    diagnostics['slot_collisions'].append({'room': room_name, 'day': d_idx, 'hour_index': h_idx})
                    # Keep the first assignment for engine stability.
                    continue

                chromosome[room_idx, timeslot_idx] = event_id

    return chromosome, diagnostics


def _compute_engine_violation_breakdown(timetables_data: list, input_data) -> tuple[dict, dict]:
    """Compute the authoritative constraint breakdown via constraints.py."""
    chromosome, diagnostics = _build_chromosome_from_timetable(timetables_data, input_data)
    cons = Constraints(input_data)
    detailed = cons.get_detailed_constraint_violations(chromosome)
    return _normalize_violation_dict(detailed), diagnostics


def verify(schedule_path: Path, input_path: Path, *, fail_on_violations: bool = False, mode: str = 'engine'):
    script_dir = Path(__file__).resolve().parent
    if not schedule_path.is_absolute():
        schedule_path = (script_dir / schedule_path).resolve()
    if not input_path.is_absolute():
        input_path = (script_dir / input_path).resolve()

    try:
        if input_path.exists():
            input_json = json.loads(input_path.read_text(encoding="utf-8"))
        else:
            # Fallback: build a transformer-shaped input JSON from the repo's static datasets.
            data_dir = script_dir / "data"
            courses = json.loads((data_dir / "course-data.json").read_text(encoding="utf-8"))
            rooms = json.loads((data_dir / "rooms-data.json").read_text(encoding="utf-8"))
            studentgroups = json.loads((data_dir / "studentgroup-data.json").read_text(encoding="utf-8"))
            faculties = json.loads((data_dir / "faculty-data.json").read_text(encoding="utf-8"))

            input_json = {
                "hours": 9,
                "days": 5,
                "courses": courses,
                "rooms": rooms,
                "studentgroups": studentgroups,
                "faculties": faculties,
            }

        input_data = initialize_input_data_from_json(input_json)
    except Exception as e:
        logger.error(f"Failed to load/initialize input data from {input_path}: {e}")
        return 2

    try:
        timetable_data = json.loads(schedule_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Failed to load schedule from {schedule_path}: {e}")
        return 2

    rooms_data = input_json.get('rooms') or []

    mode_norm = str(mode or 'engine').strip().lower()
    if mode_norm == 'dash':
        app_breakdown = _compute_app_violation_breakdown(timetable_data, rooms_data, input_data)
        diagnostics = {}
        label = 'APP (Dash/UI)'
    else:
        app_breakdown, diagnostics = _compute_engine_violation_breakdown(timetable_data, input_data)
        label = 'APP (Constraint Engine)'

    print(f"\n=== {label} CONSTRAINT VIOLATION BREAKDOWN ===")
    total = 0
    for k in sorted(app_breakdown.keys()):
        vals = app_breakdown.get(k) or []
        if isinstance(vals, list):
            count = len(vals)
            total += count
            print(f"[{k}]: {count}")
            for v in vals[:5]:
                print(f"  - {v}")
            if len(vals) > 5:
                print(f"  ... (+{len(vals)-5} more)")
        else:
            print(f"[{k}]: {vals}")

    if diagnostics:
        # Only print when non-empty, to keep output readable.
        diag_nonempty = {k: v for k, v in diagnostics.items() if v}
        if diag_nonempty:
            print("\n=== RECONSTRUCTION DIAGNOSTICS ===")
            for k, v in diag_nonempty.items():
                print(f"[{k}]: {len(v) if isinstance(v, list) else v}")

    # Optional: compare against the exact file the frontend uses
    compare_path = script_dir / "data" / "constraint_violations.json"
    diff_matches_file = None
    if compare_path.exists():
        try:
            expected = json.loads(compare_path.read_text(encoding='utf-8'))
            diff = _diff_violation_dict(expected, app_breakdown)
            has_diffs = bool(diff['keys_only_in_expected'] or diff['keys_only_in_actual'] or diff['count_differences'] or diff['examples'])
            diff_matches_file = (not has_diffs)
            print("\n=== DIFF VS data/constraint_violations.json ===")
            if not has_diffs:
                print("MATCH: verify_output_app.py output matches data/constraint_violations.json")
            else:
                if diff['keys_only_in_expected']:
                    print(f"Keys only in file: {diff['keys_only_in_expected']}")
                if diff['keys_only_in_actual']:
                    print(f"Keys only in computed: {diff['keys_only_in_actual']}")
                if diff['count_differences']:
                    print("Count differences:")
                    for ck, cv in diff['count_differences'].items():
                        print(f"  - {ck}: file={cv['expected']} computed={cv['actual']}")
                if diff['examples']:
                    print("Example item mismatches (stable-json strings):")
                    for ck, ex in list(diff['examples'].items())[:6]:
                        print(f"  - {ck}:")
                        if ex.get('missing_examples'):
                            print(f"      missing: {ex['missing_examples']}")
                        if ex.get('extra_examples'):
                            print(f"      extra: {ex['extra_examples']}")
        except Exception as e:
            print(f"Warning: could not diff against {compare_path}: {e}")

    # Write computed breakdown for easy diffing
    out_path = script_dir / "data" / "verify_constraint_violations.json"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(app_breakdown, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\nWrote computed breakdown to: {out_path}")
    except Exception as e:
        print(f"Warning: could not write verify output JSON: {e}")

    if total == 0:
        print("\nOK: No issues detected.")
    else:
        src = 'Dash/UI recompute' if mode_norm == 'dash' else 'constraint engine'
        print(f"\nOK: {total} total issues detected (per {src}).")

    # Exit code semantics:
    # - If we can compare to the frontend file, success means the breakdown matches (not "no violations")
    # - If fail_on_violations is enabled, treat any violations as failure
    if diff_matches_file is False:
        return 1
    if fail_on_violations and total > 0:
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Verify fresh_timetable_data.json against the app.py (transformer) input dataset")
    parser.add_argument("--schedule", default="data/fresh_timetable_data.json", help="Path to schedule JSON")
    parser.add_argument("--input", default="data/last_input_data.json", help="Path to last transformer input JSON saved by app.py")
    parser.add_argument(
        "--mode",
        choices=["engine", "dash"],
        default="engine",
        help="Constraint breakdown source: 'engine' uses constraints.py (authoritative); 'dash' uses Dash_UI recompute (simplified).",
    )
    parser.add_argument(
        "--fail-on-violations",
        action="store_true",
        help="Exit non-zero if any violations exist (default: only fail when breakdown mismatches the frontend file).",
    )
    args = parser.parse_args()

    return verify(Path(args.schedule), Path(args.input), fail_on_violations=args.fail_on_violations, mode=args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
