"""CP-SAT-based timetable repair/finish step.

Goal
 Take a DE-initialized chromosome (room x timeslot grid of event_ids) as a *seed*.
- Use OR-Tools CP-SAT to produce a timetable with *zero hard-constraint violations*.
- Prefer minimal changes relative to the seed so the DE initialization is preserved.

Notes
- The existing Constraints.evaluate_fitness() mixes hard penalties and soft costs.
  In practice, a fitness of exactly 0 is only guaranteed for *hard* constraints.
  Some soft costs (e.g., `check_single_event_per_day`) cannot reach 0 for realistic
  loads. This module therefore targets hard-feasibility (hard sum == 0) and uses
  an objective to minimize changes and (optionally) soft costs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional, Tuple
import time

import numpy as np
from ortools.sat.python import cp_model

from constraints import Constraints


class CpSatInfeasibleError(RuntimeError):
    def __init__(self, message: str, *, diagnostic: Optional[dict] = None):
        super().__init__(message)
        self.diagnostic = diagnostic or {}


@dataclass(frozen=True)
class CpSatRepairConfig:
    time_limit_seconds: float = 600.0  # 0-violation mode: allow up to 10 minutes (600s) for hard-feasibility
    num_workers: int = 8
    minimize_changes: bool = False  # Prioritize hard-feasibility over minimal changes
    log_search: bool = False
    two_stage: bool = False  # Single-stage: find 0 hard violations (no soft optimization phase)
    optimize_soft_terms: bool = False  # When False, skip soft objective (hard-feasible only)
    stop_after_first_solution: bool = False  # When True, return first hard-feasible solution
    use_presolve: bool = True  # Disable to avoid heavy presolve on large models

    # Constraint toggles (0-violation mode: enforce ALL)
    enforce_break_time: bool = True
    enforce_same_course_same_room_per_day: bool = True
    enforce_no_free_day: bool = True
    enforce_three_unit_split_across_days: bool = True
    enforce_lecturer_workload: bool = True
    enforce_building_assignments: bool = True  # NEW: enforce building assignments as hard
    enforce_late_classes: bool = True  # NEW: enforce late classes (no classes after hour 18)
    enforce_consecutive_slots: bool = True  # NEW: enforce consecutive slot preference as hard

    # Priority soft bands forced to 0 after structural + hard placement rules.
    # `consecutive_timeslots` is enforced via hard_must_hold (not this tuple).
    required_soft_zero_bands: Tuple[str, ...] = (
        'lecturer_workload',
        'building_assignments',
        'same_course_same_room_per_day',
    )


_DAYS_MAP = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

# Keys reported to the UI / smoke-test breakdown (mirrors Constraints.get_constraint_violations).
CPSAT_REPORT_HARD_KEYS: Tuple[str, ...] = (
    'room_constraints',
    'student_group_constraints',
    'lecturer_availability',
    'lecturer_schedule_constraints',
    'room_time_conflict',
    'course_allocation_completeness',
    'same_course_same_room_per_day',
    'break_time_constraint',
    'consecutive_timeslots',
)

CPSAT_REPORT_PRIORITY_SOFT_KEYS: Tuple[str, ...] = (
    'lecturer_workload_constraints',
    'building_assignments',
)

CPSAT_REPORT_OTHER_SOFT_KEYS: Tuple[str, ...] = (
    'three_unit_split_across_days_TYD',
    'no_free_day',
    'single_event_per_day',
    'spread_events',
    'extremely_late_classes',
)


def build_hybrid_cpsat_config(*, time_limit_seconds: float = 600.0) -> CpSatRepairConfig:
    """Shared hybrid CP-SAT settings used by app.py and hybrid_cpsat_smoke_test.py."""
    return CpSatRepairConfig(
        time_limit_seconds=float(time_limit_seconds),
        minimize_changes=False,
        two_stage=False,
        optimize_soft_terms=True,
        stop_after_first_solution=False,
        use_presolve=True,
        enforce_break_time=True,
        enforce_same_course_same_room_per_day=True,
        enforce_no_free_day=True,
        enforce_three_unit_split_across_days=True,
        enforce_lecturer_workload=True,
        enforce_building_assignments=False,
        enforce_late_classes=True,
        enforce_consecutive_slots=True,
        required_soft_zero_bands=(
            'lecturer_workload',
            'building_assignments',
            'same_course_same_room_per_day',
        ),
    )


def build_hybrid_cpsat_relaxed_config(*, time_limit_seconds: float = 600.0) -> CpSatRepairConfig:
    """Fallback: keep hard placement + consecutive; relax priority soft to best-effort."""
    return CpSatRepairConfig(
        time_limit_seconds=float(time_limit_seconds),
        minimize_changes=True,
        two_stage=False,
        optimize_soft_terms=True,
        stop_after_first_solution=False,
        use_presolve=True,
        enforce_break_time=True,
        enforce_same_course_same_room_per_day=True,
        enforce_no_free_day=True,
        enforce_three_unit_split_across_days=True,
        enforce_lecturer_workload=True,
        enforce_building_assignments=False,
        enforce_late_classes=True,
        enforce_consecutive_slots=True,
        required_soft_zero_bands=(),
    )


def format_unsatisfied_constraint_report(
    violations: Dict[str, Any],
    *,
    hard_keys: Optional[Iterable[str]] = None,
    priority_soft_keys: Optional[Iterable[str]] = None,
    detailed_violations: Optional[Dict[str, Any]] = None,
    feasibility: Optional[Dict[str, bool]] = None,
) -> List[Dict[str, str]]:
    """Build a structured list of constraints that still have penalty > 0."""
    hard_keys = list(hard_keys or CPSAT_REPORT_HARD_KEYS)
    priority_soft_keys = list(priority_soft_keys or CPSAT_REPORT_PRIORITY_SOFT_KEYS)
    out: List[Dict[str, str]] = []

    for key in hard_keys + priority_soft_keys:
        val = float(violations.get(key, 0) or 0)
        if val <= 1e-9:
            continue
        tier = 'hard' if key in hard_keys else 'priority_soft'
        out.append({
            'type': key,
            'tier': tier,
            'penalty': str(val),
            'message': f"{key} could not be driven to 0 (penalty={val}).",
        })

    if feasibility:
        label_map = {
            'break_time': 'break_time_constraint',
            'same_course_same_room_per_day': 'same_course_same_room_per_day',
            'no_free_day': 'no_free_day',
            'three_unit_split': 'three_unit_split_across_days_TYD',
            'lecturer_workload': 'lecturer_workload_constraints',
            'building_assignments': 'building_assignments',
            'late_classes': 'extremely_late_classes',
            'consecutive_slots': 'consecutive_timeslots',
        }
        for test_name, ok in feasibility.items():
            if ok:
                continue
            key = label_map.get(test_name, test_name)
            if any(item.get('type') == key for item in out):
                continue
            out.append({
                'type': key,
                'tier': 'diagnostic',
                'penalty': 'n/a',
                'message': (
                    f"CP-SAT isolation test: {test_name} is infeasible on its own "
                    f"(conflicts with base placement rules or input data)."
                ),
            })

    if detailed_violations:
        for label, items in detailed_violations.items():
            if not isinstance(items, list) or not items:
                continue
            if len(items) <= 3:
                sample = '; '.join(
                    str(i.get('reason') or i.get('violation') or i.get('location') or i)[:120]
                    for i in items[:3]
                )
            else:
                sample = f"{len(items)} detailed occurrence(s) — open constraint breakdown in the UI."
            out.append({
                'type': label,
                'tier': 'detail',
                'penalty': str(len(items)),
                'message': sample,
            })

    return out


def print_unsatisfied_constraint_report(
    violations: Dict[str, Any],
    *,
    hard_keys: Optional[Iterable[str]] = None,
    priority_soft_keys: Optional[Iterable[str]] = None,
    detailed_violations: Optional[Dict[str, Any]] = None,
    feasibility: Optional[Dict[str, bool]] = None,
) -> List[Dict[str, str]]:
    """Print human-readable unsatisfied constraint lines; return structured report."""
    report = format_unsatisfied_constraint_report(
        violations,
        hard_keys=hard_keys,
        priority_soft_keys=priority_soft_keys,
        detailed_violations=detailed_violations,
        feasibility=feasibility,
    )
    if not report:
        return report

    print("\n--- Constraints that could not be fully satisfied ---")
    for item in report:
        tier = item.get('tier', '')
        prefix = f"[{tier}] " if tier else ""
        print(f"  {prefix}{item.get('type')}: {item.get('message')}")
    print("-----------------------------------------------------\n")
    return report


def analyze_constraint_feasibility(
    input_data: Any,
    seed_chromosome: np.ndarray,
    base_config: Optional[CpSatRepairConfig] = None,
) -> Dict[str, bool]:
    """Analyze which constraints can be satisfied individually (0-violation diagnostic).
    
    For each major constraint, try solving with only that constraint enabled (+ base hard constraints).
    Returns a dict of {constraint_name: can_be_satisfied_with_0_violations}.
    
    This helps identify which soft constraints are mathematically impossible to satisfy.
    Useful when 0-violation mode times out or fails.
    """
    if base_config is None:
        base_config = CpSatRepairConfig()
    
    print("[ANALYSIS] Testing constraint feasibility individually (30s per test)...")
    cfg_minimal = replace(
        base_config,
        time_limit_seconds=30.0,
        log_search=False,
        optimize_soft_terms=False,
        stop_after_first_solution=True,
    )
    
    constraints_to_test = [
        ('break_time', 'enforce_break_time'),
        ('same_course_same_room_per_day', 'enforce_same_course_same_room_per_day'),
        ('no_free_day', 'enforce_no_free_day'),
        ('three_unit_split', 'enforce_three_unit_split_across_days'),
        ('lecturer_workload', 'enforce_lecturer_workload'),
        ('building_assignments', 'enforce_building_assignments'),
        ('late_classes', 'enforce_late_classes'),
        ('consecutive_slots', 'enforce_consecutive_slots'),
    ]
    
    results = {}
    cons_probe = Constraints(input_data)
    for constraint_name, config_attr in constraints_to_test:
        try:
            # Create a minimal config with only this constraint enabled
            test_cfg_dict = {attr: False for _, attr in constraints_to_test}
            test_cfg_dict[config_attr] = True
            test_cfg = replace(cfg_minimal, **test_cfg_dict)
            
            print(f"  Testing {constraint_name}...", end=" ", flush=True)
            start = time.time()
            repair_timetable_with_cpsat(input_data, seed_chromosome=seed_chromosome, config=test_cfg)
            elapsed = time.time() - start
            results[constraint_name] = True
            print(f"✓ FEASIBLE ({elapsed:.1f}s)")
        except CpSatInfeasibleError as e:
            elapsed = time.time() - start
            results[constraint_name] = False
            print(f"✗ INFEASIBLE ({elapsed:.1f}s)")

            # Extra detail for break_time infeasibility.
            if constraint_name == 'break_time':
                diag = getattr(e, 'diagnostic', {}) or {}
                empty_details = diag.get('empty_event_details', []) if isinstance(diag, dict) else []
                if empty_details:
                    print("    Break-time diagnostic: some events have zero allowed placements once break-time is enforced.")

                    def _count_allowed_without_break(event_id: int) -> int:
                        try:
                            ev = cons_probe.events_map.get(event_id)
                            if ev is None:
                                return 0
                            group = getattr(ev, 'student_group', None)
                            faculty_id = getattr(ev, 'faculty_id', None)
                            course = None
                            try:
                                course = input_data.getCourse(ev.course_id)
                            except Exception:
                                course = None

                            required_type = str(getattr(course, 'required_room_type', '') or '').strip() if course is not None else ''
                            group_size = int(getattr(group, 'no_students', 0) or 0) if group is not None else 0

                            rooms_by_type: Dict[str, List[Any]] = {}
                            for room in cons_probe.rooms:
                                try:
                                    rt = str(getattr(room, 'room_type', '') or '').strip()
                                except Exception:
                                    rt = ''
                                rooms_by_type.setdefault(rt, []).append(room)

                            enforce_capacity = True
                            try:
                                candidates = rooms_by_type.get(required_type, [])
                                if candidates:
                                    if not any(int(getattr(r, 'capacity', 0) or 0) >= group_size for r in candidates):
                                        enforce_capacity = False
                            except Exception:
                                enforce_capacity = True

                            count = 0
                            for room in cons_probe.rooms:
                                try:
                                    if course is not None:
                                        if str(getattr(room, 'room_type', '') or '').strip() != required_type:
                                            continue
                                    if enforce_capacity and group is not None and getattr(group, 'no_students', 0) > getattr(room, 'capacity', 0):
                                        continue

                                    rb = _room_building(room)
                                    is_sst_group = bool(getattr(group, 'is_sst', False)) if group is not None else False
                                    if rb == "SST" and (not is_sst_group):
                                        continue
                                except Exception:
                                    continue

                                for t_idx, ts in enumerate(cons_probe.timeslots):
                                    # Ignore break-time exclusion here
                                    if faculty_id is not None:
                                        faculty = None
                                        try:
                                            faculty = input_data.getFaculty(faculty_id)
                                        except Exception:
                                            faculty = None

                                        if faculty is not None:
                                            day_abbr = _DAYS_MAP.get(int(getattr(ts, "day", 0)), "")
                                            try:
                                                slot_hour = float(getattr(ts, "start_time", 0)) + 8.5
                                            except Exception:
                                                slot_hour = float(getattr(ts, "start_time", 0) or 0) + 8.5
                                            if not cons_probe._is_faculty_available_day(faculty, day_abbr):
                                                continue
                                            if not cons_probe._is_faculty_available_time(faculty, slot_hour, day_abbr):
                                                continue
                                    count += 1
                            return count
                        except Exception:
                            return 0

                    # Print a small sample of the empty events with/without break-time.
                    for detail in empty_details[:5]:
                        ev_id = detail.get('event_id')
                        if ev_id is None:
                            continue
                        no_break = _count_allowed_without_break(int(ev_id))
                        after_avail = detail.get('candidate_timeslots_after_availability')
                        print(
                            f"    Event {ev_id} ({detail.get('course_code')} / {detail.get('group_name')}): "
                            f"allowed w/out break={no_break}, allowed with break+availability={after_avail}"
                        )
        except Exception as e:
            elapsed = time.time() - start
            results[constraint_name] = False
            print(f"✗ ERROR ({elapsed:.1f}s): {str(e)[:50]}")
    
    print("\n[ANALYSIS] Summary of constraint feasibility:")
    feasible = [k for k, v in results.items() if v]
    infeasible = [k for k, v in results.items() if not v]
    print(f"  Feasible (can be satisfied): {feasible}")
    print(f"  Infeasible (conflicts): {infeasible}")
    
    return results


def _room_building(room: Any) -> str:
    b = ""
    try:
        b = str(getattr(room, "building", "") or "").upper().strip()
    except Exception:
        b = ""

    if b:
        return b

    # Heuristics consistent with constraints.check_building_assignments
    for attr in ("name", "room_id"):
        try:
            v = str(getattr(room, attr, "") or "").upper()
        except Exception:
            v = ""
        if "SST" in v:
            return "SST"
        if "TYD" in v:
            return "TYD"

    return ""


def _is_break_timeslot(input_data: Any, timeslot_idx: int) -> bool:
    """Mirror Constraints.check_break_time_constraint()."""
    try:
        hours = int(getattr(input_data, "hours", 0) or 0)
        days = int(getattr(input_data, "days", 0) or 0)
    except Exception:
        return False

    if hours <= 0 or days <= 0:
        return False

    break_hour = 4  # fixed by constraints.py
    day_idx = timeslot_idx // hours
    if day_idx not in (0, 2, 4):
        return False
    return timeslot_idx == (day_idx * hours + break_hour)


def _canonical_course_key(input_data: Any, event_course_id: str) -> str:
    course = None
    try:
        course = input_data.getCourse(event_course_id)
    except Exception:
        course = None

    if course is None:
        return str(event_course_id)

    for attr in ("course_id", "id", "code"):
        v = getattr(course, attr, None)
        if v:
            return str(v)

    return str(event_course_id)


def repair_timetable_with_cpsat(
    input_data: Any,
    *,
    seed_chromosome: Optional[np.ndarray] = None,
    config: Optional[CpSatRepairConfig] = None,
) -> np.ndarray:
    """Return a repaired chromosome (rooms x timeslots) using CP-SAT (0-violation mode).
    
    This function now enforces 0 violations for all selected constraints.
    It may take several minutes depending on problem complexity.
    Use analyze_constraint_feasibility() to diagnose which constraints are
    mathematically impossible to satisfy together.
    """

    cfg = config or CpSatRepairConfig()
    # 0-violation mode: keep all constraints enabled (no relaxation)
    cons = Constraints(input_data)

    rooms = cons.rooms
    timeslots = cons.timeslots
    events_map = cons.events_map

    room_count = len(rooms)
    timeslot_count = len(timeslots)
    event_ids = sorted(events_map.keys())

    if room_count <= 0 or timeslot_count <= 0 or not event_ids:
        raise CpSatInfeasibleError(
            "CP-SAT repair cannot run: missing rooms/timeslots/events",
            diagnostic={"rooms": room_count, "timeslots": timeslot_count, "events": len(event_ids)},
        )

    # Seed position lookup: event_id -> (room_idx, timeslot_idx)
    seed_pos: Dict[int, Tuple[int, int]] = {}
    if seed_chromosome is not None:
        try:
            for r in range(min(room_count, seed_chromosome.shape[0])):
                for t in range(min(timeslot_count, seed_chromosome.shape[1])):
                    ev = seed_chromosome[r][t]
                    if ev is None:
                        continue
                    if isinstance(ev, (int, np.integer)):
                        seed_pos[int(ev)] = (r, t)
        except Exception:
            seed_pos = {}

    # Allowed positions per event (room,time) after filtering hard feasibility.
    allowed: Dict[int, List[Tuple[int, int]]] = {eid: [] for eid in event_ids}

    # Soft priority bands requested by the user:
    # 1) lecturer workload
    # 2) building assignments
    # Precompute room-type availability and best capacity per type.
    rooms_by_type: Dict[str, List[Any]] = {}
    for room in rooms:
        try:
            rt = str(getattr(room, 'room_type', '') or '').strip()
        except Exception:
            rt = ''
        rooms_by_type.setdefault(rt, []).append(room)

    # We'll optionally add a soft objective to avoid placing SST groups in TYD rooms.
    # (constraints.check_building_assignments treats this as a soft preference.)

    for eid in event_ids:
        ev = events_map[eid]
        group = getattr(ev, "student_group", None)
        faculty_id = getattr(ev, "faculty_id", None)

        course = None
        try:
            course = input_data.getCourse(ev.course_id)
        except Exception:
            course = None

        required_type = str(getattr(course, 'required_room_type', '') or '').strip() if course is not None else ''
        group_size = int(getattr(group, 'no_students', 0) or 0) if group is not None else 0

        # Capacity is treated as a hard constraint only when it is satisfiable for this (course, group).
        enforce_capacity = True
        try:
            candidates = rooms_by_type.get(required_type, [])
            if candidates:
                if not any(int(getattr(r, 'capacity', 0) or 0) >= group_size for r in candidates):
                    enforce_capacity = False
        except Exception:
            enforce_capacity = True

        for r_idx, room in enumerate(rooms):
            # Room type/capacity (hard)
            try:
                if course is not None:
                    if str(getattr(room, 'room_type', '') or '').strip() != required_type:
                        continue
                if enforce_capacity and group is not None and getattr(group, "no_students", 0) > getattr(room, "capacity", 0):
                    continue
            except Exception:
                continue

            # Building assignment (hard-as-scored: must be 0 penalty)
            try:
                rb = _room_building(room)
                is_sst_group = bool(getattr(group, "is_sst", False)) if group is not None else False
                if rb == "SST" and (not is_sst_group):
                    continue
                # NOTE: SST-in-TYD is a *soft* preference in constraints.py; allow it here and
                # handle it as an objective term (minimize such placements).
            except Exception:
                pass

            for t_idx, ts in enumerate(timeslots):
                # Break time (hard when enabled)
                if cfg.enforce_break_time and _is_break_timeslot(input_data, t_idx):
                    continue

                # Lecturer schedule day/time availability (hard)
                if faculty_id is not None:
                    faculty = None
                    try:
                        faculty = input_data.getFaculty(faculty_id)
                    except Exception:
                        faculty = None

                    if faculty is not None:
                        day_abbr = _DAYS_MAP.get(int(getattr(ts, "day", 0)), "")
                        # constraints.py uses slot_hour = start_time + 8.5
                        try:
                            slot_hour = float(getattr(ts, "start_time", 0)) + 8.5
                        except Exception:
                            slot_hour = float(getattr(ts, "start_time", 0) or 0) + 8.5

                        if not cons._is_faculty_available_day(faculty, day_abbr):
                            continue
                        if not cons._is_faculty_available_time(faculty, slot_hour, day_abbr):
                            continue

                allowed[eid].append((r_idx, t_idx))

    # Fail fast if any event has no feasible placements.
    empty_events = [eid for eid, pos in allowed.items() if not pos]
    if empty_events:
        details = []
        try:
            for eid in empty_events[:15]:
                ev = events_map.get(eid)
                if ev is None:
                    continue
                group = getattr(ev, 'student_group', None)
                gid = getattr(group, 'id', None)
                gname = getattr(group, 'name', None)
                is_sst = bool(getattr(group, 'is_sst', False)) if group is not None else False

                course = None
                try:
                    course = input_data.getCourse(ev.course_id)
                except Exception:
                    course = None

                req_type = getattr(course, 'required_room_type', None) if course is not None else None
                credits = getattr(course, 'credits', None) if course is not None else None
                code = getattr(course, 'code', None) if course is not None else ev.course_id

                fid = getattr(ev, 'faculty_id', None)
                faculty = None
                try:
                    faculty = input_data.getFaculty(fid) if fid is not None else None
                except Exception:
                    faculty = None

                # Count candidate rooms (type/capacity)
                rooms_type_ok = 0
                rooms_building_ok = 0
                for room in rooms:
                    try:
                        if course is not None and getattr(room, 'room_type', None) != req_type:
                            continue
                        if group is not None and getattr(group, 'no_students', 0) > getattr(room, 'capacity', 0):
                            continue
                        rooms_type_ok += 1

                        rb = _room_building(room)
                        if rb == 'SST' and (not is_sst):
                            continue
                        rooms_building_ok += 1
                    except Exception:
                        continue

                # Count candidate timeslots (break + faculty availability)
                times_ok = 0
                for t_idx, ts in enumerate(timeslots):
                    if _is_break_timeslot(input_data, t_idx):
                        continue
                    if faculty is not None:
                        day_abbr = _DAYS_MAP.get(int(getattr(ts, 'day', 0)), '')
                        try:
                            slot_hour = float(getattr(ts, 'start_time', 0)) + 8.5
                        except Exception:
                            slot_hour = float(getattr(ts, 'start_time', 0) or 0) + 8.5
                        if not cons._is_faculty_available_day(faculty, day_abbr):
                            continue
                        if not cons._is_faculty_available_time(faculty, slot_hour, day_abbr):
                            continue
                    times_ok += 1

                details.append({
                    'event_id': int(eid),
                    'group_id': gid,
                    'group_name': gname,
                    'group_is_sst': is_sst,
                    'course_code': code,
                    'course_credits': credits,
                    'required_room_type': req_type,
                    'faculty_id': fid,
                    'faculty_avail_days': getattr(faculty, 'avail_days', None) if faculty is not None else None,
                    'faculty_avail_times': getattr(faculty, 'avail_times', None) if faculty is not None else None,
                    'candidate_rooms_type_capacity': rooms_type_ok,
                    'candidate_rooms_after_building': rooms_building_ok,
                    'candidate_timeslots_after_availability': times_ok,
                })
        except Exception:
            details = []
        raise CpSatInfeasibleError(
            f"CP-SAT repair infeasible: {len(empty_events)} events have no allowed placements",
            diagnostic={
                'empty_count': len(empty_events),
                'empty_event_ids': empty_events[:25],
                'empty_event_details': details,
            },
        )

    model = cp_model.CpModel()

    # Scalable formulation:
    # - One IntVar per event representing a flattened (room_idx * timeslot_count + timeslot_idx)
    # - Global AllDifferent on positions to enforce room-time uniqueness
    # - Derived room/timeslot/day vars to express overlap and other constraints

    # Derived time parameters
    try:
        hours_per_day = int(getattr(input_data, "hours", 0) or 0)
        days = int(getattr(input_data, "days", 0) or 0)
    except Exception:
        hours_per_day = 0
        days = 0

    # Build group/faculty index sets
    events_by_group: Dict[str, List[int]] = {}
    events_by_faculty: Dict[str, List[int]] = {}
    for eid in event_ids:
        ev = events_map[eid]
        gid = getattr(getattr(ev, "student_group", None), "id", None)
        if gid is not None:
            events_by_group.setdefault(str(gid), []).append(eid)

        fid = getattr(ev, "faculty_id", None)
        if fid is not None:
            events_by_faculty.setdefault(str(fid), []).append(eid)

    # Always compute course-group buckets (used by multiple constraints).
    events_by_course_group: Dict[Tuple[str, str], List[int]] = {}
    for eid in event_ids:
        ev = events_map[eid]
        gid = getattr(getattr(ev, "student_group", None), "id", None)
        if gid is None:
            continue
        course_key = _canonical_course_key(input_data, ev.course_id)
        events_by_course_group.setdefault((course_key, str(gid)), []).append(eid)

    # Decision vars
    pos_var: Dict[int, cp_model.IntVar] = {}
    room_var: Dict[int, cp_model.IntVar] = {}
    t_var: Dict[int, cp_model.IntVar] = {}
    day_var: Dict[int, cp_model.IntVar] = {}
    hour_var: Dict[int, cp_model.IntVar] = {}
    allowed_flat_set: Dict[int, set[int]] = {}

    for eid, positions in allowed.items():
        values = [int(r * timeslot_count + t) for (r, t) in positions]
        allowed_flat_set[eid] = set(values)
        domain = cp_model.Domain.FromValues(values)
        p = model.new_int_var_from_domain(domain, f"pos_e{eid}")
        pos_var[eid] = p

        r = model.new_int_var(0, room_count - 1, f"room_e{eid}")
        tt = model.new_int_var(0, timeslot_count - 1, f"t_e{eid}")
        room_var[eid] = r
        t_var[eid] = tt
        model.add_division_equality(r, p, timeslot_count)
        model.add_modulo_equality(tt, p, timeslot_count)

        if hours_per_day > 0 and days > 0:
            d = model.new_int_var(0, days - 1, f"day_e{eid}")
            h = model.new_int_var(0, max(0, hours_per_day - 1), f"hour_e{eid}")
            day_var[eid] = d
            hour_var[eid] = h
            model.add_division_equality(d, tt, hours_per_day)
            model.add_modulo_equality(h, tt, hours_per_day)

        # Seed hint (helps even when we are just looking for feasibility).
        if seed_pos and eid in seed_pos:
            sr, st = seed_pos[eid]
            seed_flat = int(sr * timeslot_count + st)
            if seed_flat in allowed_flat_set.get(eid, set()):
                model.add_hint(p, seed_flat)

    # Room-time uniqueness across all events.
    model.add_all_different([pos_var[eid] for eid in event_ids])

    # Non-overlap: groups and lecturers cannot have two events in same timeslot.
    for gid, eids in events_by_group.items():
        if len(eids) > 1:
            model.add_all_different([t_var[eid] for eid in eids])

    for fid, eids in events_by_faculty.items():
        if len(eids) > 1:
            model.add_all_different([t_var[eid] for eid in eids])

    # Helpers for reified equalities used by multiple constraints.
    is_day: Dict[Tuple[int, int], cp_model.IntVar] = {}
    is_timeslot: Dict[Tuple[int, int], cp_model.IntVar] = {}

    def _is_event_on_day(eid: int, d_idx: int) -> cp_model.IntVar:
        key = (eid, d_idx)
        if key in is_day:
            return is_day[key]
        b = model.new_bool_var(f"isday_e{eid}_d{d_idx}")
        model.add(day_var[eid] == d_idx).OnlyEnforceIf(b)
        model.add(day_var[eid] != d_idx).OnlyEnforceIf(b.Not())
        is_day[key] = b
        return b

    def _is_event_at_timeslot(eid: int, t_idx: int) -> cp_model.IntVar:
        key = (eid, t_idx)
        if key in is_timeslot:
            return is_timeslot[key]
        b = model.new_bool_var(f"ist_e{eid}_t{t_idx}")
        model.add(t_var[eid] == t_idx).OnlyEnforceIf(b)
        model.add(t_var[eid] != t_idx).OnlyEnforceIf(b.Not())
        is_timeslot[key] = b
        return b

    # -------------------------------------------------------------------------
    # SOFT CONSTRAINTS (Added to objective to find the lowest penalty solution)
    # -------------------------------------------------------------------------
    objective_terms: List[cp_model.IntVar] = []
    
    soft_priority_terms: Dict[str, List[cp_model.IntVar]] = {
        'same_course_same_room_per_day': [],
        'no_free_day': [],
        'lecturer_workload': [],
        'building_assignments': [],
        'extremely_late_classes': [],
        'three_unit_split_across_days_TYD': [],
        'spread_events': [],
    }
    # Violation indicators that must be 0 (true hard constraints in CP-SAT).
    hard_must_hold: List[cp_model.IntVar] = []

    # 1. Minimize changes relative to DE seed
    if cfg.minimize_changes and seed_pos:
        for eid in event_ids:
            if eid in seed_pos:
                sr, st = seed_pos[eid]
                seed_flat = int(sr * timeslot_count + st)
                if seed_flat in allowed_flat_set.get(eid, set()):
                    keep = model.new_bool_var(f"keep_seed_e{eid}")
                    model.add(pos_var[eid] == seed_flat).OnlyEnforceIf(keep)
                    model.add(pos_var[eid] != seed_flat).OnlyEnforceIf(keep.Not())
                    chg = model.new_int_var(0, 1, f"chg_e{eid}")
                    model.add(chg + keep == 1)
                    objective_terms.append(chg)

    # 2. Same course same room per day (Penalty: 25)
    if cfg.enforce_same_course_same_room_per_day and hours_per_day > 0 and days > 0:
        for (course_key, gid), eids in events_by_course_group.items():
            if len(eids) < 2:
                continue
            for d_idx in range(days):
                for i in range(len(eids)):
                    for j in range(i+1, len(eids)):
                        e1, e2 = eids[i], eids[j]
                        b1 = model.new_bool_var(f"b1_{e1}_{d_idx}")
                        model.add(day_var[e1] == d_idx).OnlyEnforceIf(b1)
                        model.add(day_var[e1] != d_idx).OnlyEnforceIf(b1.Not())
                        b2 = model.new_bool_var(f"b2_{e2}_{d_idx}")
                        model.add(day_var[e2] == d_idx).OnlyEnforceIf(b2)
                        model.add(day_var[e2] != d_idx).OnlyEnforceIf(b2.Not())
                        
                        same_day = model.new_bool_var(f"sday_{e1}_{e2}_{d_idx}")
                        model.add_bool_and([b1, b2]).OnlyEnforceIf(same_day)
                        model.add_bool_or([b1.Not(), b2.Not()]).OnlyEnforceIf(same_day.Not())
                        
                        diff_room = model.new_bool_var(f"droom_{e1}_{e2}_{d_idx}")
                        model.add(room_var[e1] != room_var[e2]).OnlyEnforceIf(diff_room)
                        model.add(room_var[e1] == room_var[e2]).OnlyEnforceIf(diff_room.Not())
                        
                        viol = model.new_bool_var(f"scsr_viol_{e1}_{e2}_{d_idx}")
                        model.add_bool_and([same_day, diff_room]).OnlyEnforceIf(viol)
                        model.add_bool_or([same_day.Not(), diff_room.Not()]).OnlyEnforceIf(viol.Not())
                        
                        soft_priority_terms['same_course_same_room_per_day'].append(220000 * viol)

    # 3. No free day (Penalty: 25)
    if cfg.enforce_no_free_day and hours_per_day > 0 and days > 0:
        for gid, eids in events_by_group.items():
            if len(eids) < days:
                continue
            for d_idx in range(days):
                has_event = model.new_bool_var(f"has_event_g{gid}_d{d_idx}")
                b_vars = [_is_event_on_day(eid, d_idx) for eid in eids]
                model.add_bool_or(b_vars).OnlyEnforceIf(has_event)
                model.add_bool_and([b.Not() for b in b_vars]).OnlyEnforceIf(has_event.Not())
                soft_priority_terms['no_free_day'].append(1500000 * has_event.Not())

    # 3b. Spread events across the week (soft)
    if hours_per_day > 0 and days > 0:
        for gid, eids in events_by_group.items():
            total = len(eids)
            if total <= 1:
                continue
            target_days = min(days, total)
            day_used_vars = []
            for d_idx in range(days):
                d_used = model.new_bool_var(f"spread_used_g{gid}_d{d_idx}")
                b_vars = [_is_event_on_day(eid, d_idx) for eid in eids]
                model.add_bool_or(b_vars).OnlyEnforceIf(d_used)
                model.add_bool_and([b.Not() for b in b_vars]).OnlyEnforceIf(d_used.Not())
                day_used_vars.append(d_used)

            days_used = model.new_int_var(0, days, f"spread_days_used_g{gid}")
            model.add(days_used == sum(day_used_vars))

            missing = model.new_int_var(0, days, f"spread_missing_g{gid}")
            model.add(missing >= target_days - days_used)
            model.add(missing >= 0)
            soft_priority_terms['spread_events'].append(80000 * missing)

            # Soft target: at least 3 active days when possible.
            min_days_target = min(3, total, days)
            if min_days_target > 0:
                min_days_short = model.new_int_var(0, days, f"spread_min_days_short_g{gid}")
                model.add(min_days_short >= min_days_target - days_used)
                model.add(min_days_short >= 0)
                soft_priority_terms['spread_events'].append(30000 * min_days_short)

            # Soft target: at least 2 free hours every day.
            max_daily = max(0, hours_per_day - 2)
            for d_idx in range(days):
                day_count = model.new_int_var(0, len(eids), f"spread_day_count_g{gid}_d{d_idx}")
                model.add(day_count == sum(_is_event_on_day(eid, d_idx) for eid in eids))

                over = model.new_int_var(0, hours_per_day, f"spread_over_g{gid}_d{d_idx}")
                model.add(over >= day_count - max_daily)
                model.add(over >= 0)
                soft_priority_terms['spread_events'].append(50000 * over)

    # 4. Consecutive slots (HARD): 2-credit = 2 consecutive; SST 3-credit = 3-hour block;
    # TYD 3-credit = at least one 2-hour consecutive block on one day.
    if cfg.enforce_consecutive_slots and hours_per_day > 0 and days > 0:
        for (course_key, gid), eids in events_by_course_group.items():
            course = None
            try:
                course = input_data.getCourse(course_key)
            except Exception:
                course = None
            if not course:
                continue
            credits = int(getattr(course, 'credits', 0) or 0)

            is_sst_group = False
            try:
                sample_ev = events_map.get(eids[0]) if eids else None
                grp = getattr(sample_ev, 'student_group', None) if sample_ev is not None else None
                is_sst_group = bool(getattr(grp, 'is_sst', False)) if grp is not None else False
            except Exception:
                is_sst_group = False

            if credits == 2 and len(eids) >= 2:
                e1, e2 = eids[0], eids[1]
                same_day = model.new_bool_var(f"c_same_day_{e1}_{e2}")
                model.add(day_var[e1] == day_var[e2]).OnlyEnforceIf(same_day)
                model.add(day_var[e1] != day_var[e2]).OnlyEnforceIf(same_day.Not())

                adj1 = model.new_bool_var(f"c_adj1_{e1}_{e2}")
                model.add(hour_var[e1] - hour_var[e2] == 1).OnlyEnforceIf(adj1)
                model.add(hour_var[e1] - hour_var[e2] != 1).OnlyEnforceIf(adj1.Not())

                adj2 = model.new_bool_var(f"c_adj2_{e1}_{e2}")
                model.add(hour_var[e2] - hour_var[e1] == 1).OnlyEnforceIf(adj2)
                model.add(hour_var[e2] - hour_var[e1] != 1).OnlyEnforceIf(adj2.Not())

                adj_any = model.new_bool_var(f"c_adj_any_{e1}_{e2}")
                model.add_bool_or([adj1, adj2]).OnlyEnforceIf(adj_any)
                model.add_bool_and([adj1.Not(), adj2.Not()]).OnlyEnforceIf(adj_any.Not())

                consec = model.new_bool_var(f"c_consec_{e1}_{e2}")
                model.add_bool_and([same_day, adj_any]).OnlyEnforceIf(consec)
                model.add_bool_or([same_day.Not(), adj_any.Not()]).OnlyEnforceIf(consec.Not())

                viol = model.new_bool_var(f"c_consec_viol_{e1}_{e2}")
                model.add(viol == 1).OnlyEnforceIf(consec.Not())
                model.add(viol == 0).OnlyEnforceIf(consec)
                hard_must_hold.append(viol)

            elif credits == 3 and len(eids) >= 3:
                e1, e2, e3 = eids[0], eids[1], eids[2]
                if is_sst_group:
                    same_day = model.new_bool_var(f"c3_same_day_{course_key}_{gid}")
                    model.add(day_var[e1] == day_var[e2]).OnlyEnforceIf(same_day)
                    model.add(day_var[e1] != day_var[e2]).OnlyEnforceIf(same_day.Not())
                    model.add(day_var[e2] == day_var[e3]).OnlyEnforceIf(same_day)
                    model.add(day_var[e2] != day_var[e3]).OnlyEnforceIf(same_day.Not())

                    model.add_all_different([hour_var[e1], hour_var[e2], hour_var[e3]])
                    h_min = model.new_int_var(0, hours_per_day - 1, f"c3_hmin_{course_key}_{gid}")
                    h_max = model.new_int_var(0, hours_per_day - 1, f"c3_hmax_{course_key}_{gid}")
                    model.add_min_equality(h_min, [hour_var[e1], hour_var[e2], hour_var[e3]])
                    model.add_max_equality(h_max, [hour_var[e1], hour_var[e2], hour_var[e3]])

                    span_ok = model.new_bool_var(f"c3_span_{course_key}_{gid}")
                    model.add(h_max - h_min == 2).OnlyEnforceIf(span_ok)
                    model.add(h_max - h_min != 2).OnlyEnforceIf(span_ok.Not())

                    block_ok = model.new_bool_var(f"c3_block_{course_key}_{gid}")
                    model.add_bool_and([same_day, span_ok]).OnlyEnforceIf(block_ok)
                    model.add_bool_or([same_day.Not(), span_ok.Not()]).OnlyEnforceIf(block_ok.Not())

                    viol = model.new_bool_var(f"c3_viol_{course_key}_{gid}")
                    model.add(viol == 1).OnlyEnforceIf(block_ok.Not())
                    model.add(viol == 0).OnlyEnforceIf(block_ok)
                    hard_must_hold.append(viol)
                else:
                    has_block_vars = []
                    for i in range(len(eids)):
                        for j in range(i + 1, len(eids)):
                            ea, eb = eids[i], eids[j]
                            same_day = model.new_bool_var(f"sday_3c_{ea}_{eb}")
                            model.add(day_var[ea] == day_var[eb]).OnlyEnforceIf(same_day)
                            model.add(day_var[ea] != day_var[eb]).OnlyEnforceIf(same_day.Not())

                            adj1 = model.new_bool_var(f"adj1_3c_{ea}_{eb}")
                            model.add(hour_var[ea] - hour_var[eb] == 1).OnlyEnforceIf(adj1)
                            model.add(hour_var[ea] - hour_var[eb] != 1).OnlyEnforceIf(adj1.Not())

                            adj2 = model.new_bool_var(f"adj2_3c_{ea}_{eb}")
                            model.add(hour_var[eb] - hour_var[ea] == 1).OnlyEnforceIf(adj2)
                            model.add(hour_var[eb] - hour_var[ea] != 1).OnlyEnforceIf(adj2.Not())

                            adj_any = model.new_bool_var(f"adj_any_3c_{ea}_{eb}")
                            model.add_bool_or([adj1, adj2]).OnlyEnforceIf(adj_any)
                            model.add_bool_and([adj1.Not(), adj2.Not()]).OnlyEnforceIf(adj_any.Not())

                            block = model.new_bool_var(f"block_3c_{ea}_{eb}")
                            model.add_bool_and([same_day, adj_any]).OnlyEnforceIf(block)
                            model.add_bool_or([same_day.Not(), adj_any.Not()]).OnlyEnforceIf(block.Not())
                            has_block_vars.append(block)

                    has_any_block = model.new_bool_var(f"has_any_block_{course_key}_{gid}")
                    model.add_bool_or(has_block_vars).OnlyEnforceIf(has_any_block)
                    model.add_bool_and([v.Not() for v in has_block_vars]).OnlyEnforceIf(has_any_block.Not())

                    viol = model.new_bool_var(f"tyd_3c_viol_{course_key}_{gid}")
                    model.add(viol == 1).OnlyEnforceIf(has_any_block.Not())
                    model.add(viol == 0).OnlyEnforceIf(has_any_block)
                    hard_must_hold.append(viol)

    # 4b. TYD 3-unit 2+1 day split (SOFT preference only; SST uses full 3-hour hard block above).
    if cfg.enforce_three_unit_split_across_days and hours_per_day > 0 and days > 0:
        for (course_key, gid), eids in events_by_course_group.items():
            if len(eids) < 3:
                continue
            course = None
            try:
                course = input_data.getCourse(course_key)
            except Exception:
                course = None
            if not course or int(getattr(course, 'credits', 0) or 0) != 3:
                continue
            sample_ev = events_map.get(eids[0])
            grp = getattr(sample_ev, 'student_group', None) if sample_ev is not None else None
            if grp is None or bool(getattr(grp, 'is_sst', False)):
                continue

            e1, e2, e3 = eids[0], eids[1], eids[2]
            pair_days = []
            for ea, eb in ((e1, e2), (e2, e3), (e1, e3)):
                same_day = model.new_bool_var(f"tyd_split_sday_{ea}_{eb}")
                model.add(day_var[ea] == day_var[eb]).OnlyEnforceIf(same_day)
                model.add(day_var[ea] != day_var[eb]).OnlyEnforceIf(same_day.Not())

                adj1 = model.new_bool_var(f"tyd_split_adj1_{ea}_{eb}")
                model.add(hour_var[ea] - hour_var[eb] == 1).OnlyEnforceIf(adj1)
                model.add(hour_var[ea] - hour_var[eb] != 1).OnlyEnforceIf(adj1.Not())

                adj2 = model.new_bool_var(f"tyd_split_adj2_{ea}_{eb}")
                model.add(hour_var[eb] - hour_var[ea] == 1).OnlyEnforceIf(adj2)
                model.add(hour_var[eb] - hour_var[ea] != 1).OnlyEnforceIf(adj2.Not())

                adj_any = model.new_bool_var(f"tyd_split_adj_any_{ea}_{eb}")
                model.add_bool_or([adj1, adj2]).OnlyEnforceIf(adj_any)
                model.add_bool_and([adj1.Not(), adj2.Not()]).OnlyEnforceIf(adj_any.Not())

                pair_block = model.new_bool_var(f"tyd_split_pair_{ea}_{eb}")
                model.add_bool_and([same_day, adj_any]).OnlyEnforceIf(pair_block)
                model.add_bool_or([same_day.Not(), adj_any.Not()]).OnlyEnforceIf(pair_block.Not())
                pair_days.append(pair_block)

            has_pair = model.new_bool_var(f"tyd_split_has_pair_{course_key}_{gid}")
            model.add_bool_or(pair_days).OnlyEnforceIf(has_pair)
            model.add_bool_and([p.Not() for p in pair_days]).OnlyEnforceIf(has_pair.Not())

            all_same_day = model.new_bool_var(f"tyd_split_all_day_{course_key}_{gid}")
            sd12 = model.new_bool_var(f"tyd_sd12_{course_key}_{gid}")
            model.add(day_var[e1] == day_var[e2]).OnlyEnforceIf(sd12)
            model.add(day_var[e1] != day_var[e2]).OnlyEnforceIf(sd12.Not())
            sd23 = model.new_bool_var(f"tyd_sd23_{course_key}_{gid}")
            model.add(day_var[e2] == day_var[e3]).OnlyEnforceIf(sd23)
            model.add(day_var[e2] != day_var[e3]).OnlyEnforceIf(sd23.Not())
            model.add_bool_and([sd12, sd23]).OnlyEnforceIf(all_same_day)
            model.add_bool_or([sd12.Not(), sd23.Not()]).OnlyEnforceIf(all_same_day.Not())

            split_ok = model.new_bool_var(f"tyd_split_ok_{course_key}_{gid}")
            d12 = model.new_bool_var(f"tyd_d12_{course_key}_{gid}")
            model.add(day_var[e1] == day_var[e2]).OnlyEnforceIf(d12)
            model.add(day_var[e1] != day_var[e2]).OnlyEnforceIf(d12.Not())
            d13 = model.new_bool_var(f"tyd_d13_{course_key}_{gid}")
            model.add(day_var[e1] == day_var[e3]).OnlyEnforceIf(d13)
            model.add(day_var[e1] != day_var[e3]).OnlyEnforceIf(d13.Not())
            d23 = model.new_bool_var(f"tyd_d23_{course_key}_{gid}")
            model.add(day_var[e2] == day_var[e3]).OnlyEnforceIf(d23)
            model.add(day_var[e2] != day_var[e3]).OnlyEnforceIf(d23.Not())
            model.add_bool_or([d12.Not(), d13.Not(), d23.Not()]).OnlyEnforceIf(split_ok)
            model.add_bool_and([d12, d13, d23]).OnlyEnforceIf(split_ok.Not())

            pattern_ok = model.new_bool_var(f"tyd_pattern_ok_{course_key}_{gid}")
            model.add_bool_and([has_pair, split_ok]).OnlyEnforceIf(pattern_ok)
            model.add_bool_or([has_pair.Not(), split_ok.Not()]).OnlyEnforceIf(pattern_ok.Not())

            viol = model.new_bool_var(f"tyd_split_viol_{course_key}_{gid}")
            model.add_bool_or([all_same_day, pattern_ok.Not()]).OnlyEnforceIf(viol)
            model.add_bool_and([all_same_day.Not(), pattern_ok]).OnlyEnforceIf(viol.Not())
            soft_priority_terms['three_unit_split_across_days_TYD'].append(5000 * viol)

    # 5. Lecturer Workload (slightly stronger daily/consecutive pressure + day-spread encouragement)
    if cfg.enforce_lecturer_workload and hours_per_day > 0 and days > 0:
        for fid, eids in events_by_faculty.items():
            faculty = None
            try: faculty = input_data.getFaculty(fid)
            except Exception: pass

            max_hours = 4
            max_consec = 3
            if faculty:
                max_hours = max(2, min(8, int(getattr(faculty, 'available_hours', 4) or 4)))
                max_consec = max(2, min(8, int(getattr(faculty, 'available_consecutive_hours', 3) or 3)))
            max_hours = max(2, min(8, max_hours))
            max_consec = max(2, min(8, max_consec))

            day_used_bools = []
            for d_idx in range(days):
                day_count = model.new_int_var(0, len(eids), f"day_count_{fid}_{d_idx}")
                model.add(day_count == sum(_is_event_on_day(eid, d_idx) for eid in eids))

                day_used = model.new_bool_var(f"day_used_{fid}_{d_idx}")
                model.add(day_count >= 1).OnlyEnforceIf(day_used)
                model.add(day_count == 0).OnlyEnforceIf(day_used.Not())
                day_used_bools.append(day_used)
                
                overload = model.new_int_var(0, len(eids), f"over_{fid}_{d_idx}")
                model.add(overload >= day_count - max_hours)
                model.add(overload >= 0)
                soft_priority_terms['lecturer_workload'].append(260 * overload)

                window = max_consec + 1
                if window <= hours_per_day:
                    for start in range(0, hours_per_day - window + 1):
                        win_sum = model.new_int_var(0, window, f"win_sum_{fid}_{d_idx}_{start}")
                        model.add(win_sum == sum(_is_event_at_timeslot(eid, d_idx * hours_per_day + h) for h in range(start, start + window) for eid in eids))
                        
                        win_over = model.new_int_var(0, window, f"win_over_{fid}_{d_idx}_{start}")
                        model.add(win_over >= win_sum - max_consec)
                        model.add(win_over >= 0)
                        soft_priority_terms['lecturer_workload'].append(36000 * win_over)

            # Encourage spreading lecturer sessions onto other available days so daily/consecutive
            # workload pressure can be reduced without violating hard constraints.
            available_days_count = days
            try:
                raw_days = getattr(faculty, 'available_days', None)
                if isinstance(raw_days, str):
                    parts = [p.strip() for p in raw_days.replace(';', ',').split(',') if p.strip()]
                    available_days_count = max(1, min(days, len(parts))) if parts else days
                elif isinstance(raw_days, (list, tuple, set)):
                    available_days_count = max(1, min(days, len([d for d in raw_days if str(d).strip()])))
            except Exception:
                available_days_count = days

            teaching_days = model.new_int_var(0, days, f"teaching_days_{fid}")
            model.add(teaching_days == sum(day_used_bools))

            desired_days = min(
                max(1, available_days_count),
                max(1, (len(eids) + max_hours - 1) // max_hours),
            )
            if len(eids) >= 3 and available_days_count >= 2:
                desired_days = max(desired_days, 2)

            day_shortfall = model.new_int_var(0, days, f"day_shortfall_{fid}")
            model.add(day_shortfall >= desired_days - teaching_days)
            model.add(day_shortfall >= 0)
            soft_priority_terms['lecturer_workload'].append(4500 * day_shortfall)

    # 6. Building assignments (SST group in TYD room: Penalty 2)
    tyd_room_idxs: List[int] = []
    for r_idx, room in enumerate(rooms):
        if _room_building(room) == 'TYD':
            tyd_room_idxs.append(r_idx)

    if cfg.enforce_building_assignments and tyd_room_idxs:
        for eid in event_ids:
            ev = events_map[eid]
            group = getattr(ev, 'student_group', None)
            is_sst_group = bool(getattr(group, 'is_sst', False)) if group is not None else False
            
            if is_sst_group:
                is_tyd = model.new_bool_var(f"sst_in_tyd_e{eid}")
                pairs = []
                tyd_set = set(tyd_room_idxs)
                for r_idx in range(room_count):
                    pairs.append([r_idx, 1 if r_idx in tyd_set else 0])
                model.add_allowed_assignments([room_var[eid], is_tyd], pairs)
                soft_priority_terms['building_assignments'].append(2000 * is_tyd)

    # 7. Extremely late classes (17:30). Strongly discourage unless absolutely necessary.
    if cfg.enforce_late_classes and hours_per_day > 0 and days > 0:
        for eid in event_ids:
            ev = events_map[eid]
            group = getattr(ev, 'student_group', None)
            
            late = model.new_bool_var(f"late_e{eid}")
            model.add(hour_var[eid] == hours_per_day - 1).OnlyEnforceIf(late)
            model.add(hour_var[eid] != hours_per_day - 1).OnlyEnforceIf(late.Not())
            
            late_weight = 60000
            if group is not None:
                if not bool(getattr(group, 'is_sst', False)):
                    late_weight += 40000
                
                req_hours = sum(int(x) for x in getattr(group, 'hours_required', []) or [])
                has_4c = False
                for cid in getattr(group, 'courseIDs', []) or []:
                    c = None
                    try: c = input_data.getCourse(cid)
                    except Exception: pass
                    if c and int(getattr(c, 'credits', 0) or 0) >= 4:
                        has_4c = True; break
                if req_hours > 0 and req_hours <= 18 and not has_4c:
                    late_weight += 450000
                    
            soft_priority_terms['extremely_late_classes'].append(late_weight * 1200000 * late)

    for viol in hard_must_hold:
        model.add(viol == 0)

    for band, terms_list in soft_priority_terms.items():
        if not terms_list:
            continue
        if band in cfg.required_soft_zero_bands:
            for term in terms_list:
                model.add(term == 0)
        else:
            objective_terms.extend(terms_list)

    if cfg.optimize_soft_terms and objective_terms:
        model.minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    
    # RE-ENABLE THE TIME LIMIT (It will stop at 120 seconds)
    solver.parameters.max_time_in_seconds = float(cfg.time_limit_seconds)
    
    solver.parameters.num_search_workers = int(max(1, cfg.num_workers))
    
    # FORCE LOGGING TO TRUE so you can see it calculating in the terminal
    solver.parameters.log_search_progress = True
    solver.parameters.stop_after_first_solution = bool(cfg.stop_after_first_solution)
    solver.parameters.cp_model_presolve = bool(cfg.use_presolve)

    status = solver.solve(model)

    # Accept both OPTIMAL and FEASIBLE. For web apps, we must not wait for perfection.
    # FEASIBLE = hard constraints satisfied, soft penalties may not be ideal
    # OPTIMAL = best possible soft penalties found before timeout
    if status == cp_model.INFEASIBLE:
        raise CpSatInfeasibleError(
            f"CP-SAT: Hard constraints are mathematically impossible to satisfy (status={status})",
            diagnostic={
                "status": int(status),
                "time_limit_seconds": cfg.time_limit_seconds,
                "events": len(event_ids),
                "rooms": room_count,
                "timeslots": timeslot_count,
                "note": "The problem is overconstrained. Consider relaxing some hard constraints.",
            },
        )
    elif status == cp_model.UNKNOWN:
        # 0-violation mode timeout: provide diagnostic suggestion
        print(f"[DIAGNOSTIC] CP-SAT timeout at {cfg.time_limit_seconds}s in 0-violation mode.")
        print(f"[DIAGNOSTIC] This may indicate one or more constraints are mathematically incompatible.")
        print(f"[DIAGNOSTIC] Use analyze_constraint_feasibility() to identify the problematic constraint(s).")
        raise CpSatInfeasibleError(
            f"CP-SAT timeout (status=UNKNOWN): No solution with 0 violations found within {cfg.time_limit_seconds}s",
            diagnostic={
                "status": int(status),
                "time_limit_seconds": cfg.time_limit_seconds,
                "events": len(event_ids),
                "rooms": room_count,
                "timeslots": timeslot_count,
                "mode": "0-violation (hard-feasible)",
                "note": "Some constraints may be mathematically impossible to satisfy together. Run analyze_constraint_feasibility() to diagnose.",
            },
        )
    # Status is OPTIMAL or FEASIBLE: both are acceptable for web apps
    elif status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise CpSatInfeasibleError(
            f"CP-SAT unexpected status (status={status})",
            diagnostic={
                "status": int(status),
                "time_limit_seconds": cfg.time_limit_seconds,
            },
        )

    out = np.empty((room_count, timeslot_count), dtype=object)
    out[:, :] = None

    for eid in event_ids:
        p = int(solver.value(pos_var[eid]))
        r = int(p // timeslot_count)
        t = int(p % timeslot_count)
        if out[r][t] is not None:
            raise CpSatInfeasibleError(
                f"Internal error: duplicate placement at room={r}, timeslot={t}",
                diagnostic={"event_id": int(eid), "other_event_id": int(out[r][t])},
            )
        out[r][t] = int(eid)

    # 0-violation mode: no two-stage (single-stage hard-feasibility already enforced soft==0)
    return out
