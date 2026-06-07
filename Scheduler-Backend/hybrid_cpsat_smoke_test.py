"""Smoke test: DE initialization seed -> CP-SAT repair -> verify hard fitness is 0."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np

from input_data_api import initialize_input_data_from_json
from constraints import Constraints
from differential_evolution_api import DifferentialEvolution
from cp_sat_scheduler import (
    CpSatInfeasibleError,
    CPSAT_REPORT_HARD_KEYS,
    CPSAT_REPORT_PRIORITY_SOFT_KEYS,
    analyze_constraint_feasibility,
    build_hybrid_cpsat_config,
    build_hybrid_cpsat_relaxed_config,
    print_unsatisfied_constraint_report,
    repair_timetable_with_cpsat,
)
import output_data
import time


def main() -> None:
    root = Path(__file__).resolve().parent
    data_path = root / "data" / "last_input_data.json"

    if data_path.exists():
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    else:
        payload = {}

    # Initialize InputData. The initializer will fall back to per-entity JSON files
    # (data/course-data.json, data/rooms-data.json, etc.) if `last_input_data.json` is empty.
    input_data = initialize_input_data_from_json(payload)

    def _print_violation_breakdown(violations: dict, hard_keys: list[str], detailed_violations: dict) -> dict:
        """Print and return a structured hard/soft breakdown for the given violations."""
        total = float(violations.get("total", 0) or 0)
        hard_breakdown = {k: float(violations.get(k, 0) or 0) for k in hard_keys}
        soft_keys = [k for k in violations.keys() if k not in set(hard_keys) and k != "total"]
        # Promote high-priority soft constraints to the front
        priority_soft = list(CPSAT_REPORT_PRIORITY_SOFT_KEYS)
        # Build ordered soft_keys: priority first (if present), then the rest
        ordered_soft = []
        for k in priority_soft:
            if k in soft_keys:
                ordered_soft.append(k)
        for k in soft_keys:
            if k not in ordered_soft:
                ordered_soft.append(k)
        soft_breakdown = {k: float(violations.get(k, 0) or 0) for k in ordered_soft}

        def _count_items(value) -> int:
            if value is None:
                return 0
            if isinstance(value, list):
                return len(value)
            if isinstance(value, dict):
                return sum(_count_items(v) for v in value.values())
            try:
                return int(round(float(value)))
            except Exception:
                return 0

        def _detail_count(label: str, *, predicate=None, penalty=None, divisor=None) -> int:
            items = detailed_violations.get(label, []) if isinstance(detailed_violations, dict) else []
            if isinstance(items, list) and items:
                if predicate is None:
                    return len(items)
                return sum(1 for item in items if predicate(item))
            if penalty is not None and divisor:
                try:
                    return int(round(float(penalty) / float(divisor)))
                except Exception:
                    return 0
            return 0

        occurrence_counts = {
            'room_constraints': _detail_count(
                'Room Capacity/Type Conflicts',
                predicate=lambda item: str(item.get('type', '')).strip() != 'Wrong Building (TYD in SST)',
                penalty=violations.get('room_constraints', 0),
            ),
            'student_group_constraints': _detail_count('Same Student Group Overlaps', penalty=violations.get('student_group_constraints', 0)),
            'lecturer_availability': _detail_count('Lecturer Clashes', penalty=violations.get('lecturer_availability', 0)),
            'room_time_conflict': _detail_count('Different Student Group Overlaps', penalty=violations.get('room_time_conflict', 0)),
            'building_assignments': _detail_count(
                'Room Capacity/Type Conflicts',
                predicate=lambda item: str(item.get('type', '')).strip() == 'Wrong Building (TYD in SST)',
                penalty=violations.get('building_assignments', 0),
            ),
            'same_course_same_room_per_day': _detail_count('Same Course in Multiple Rooms on Same Day', penalty=violations.get('same_course_same_room_per_day', 0)),
            'break_time_constraint': _detail_count('Classes During Break Time', penalty=violations.get('break_time_constraint', 0)),
            'course_allocation_completeness': _detail_count('Missing or Extra Classes', penalty=violations.get('course_allocation_completeness', 0)),
            'lecturer_schedule_constraints': _detail_count('Lecturer Schedule Conflicts (Day/Time)', penalty=violations.get('lecturer_schedule_constraints', 0)),
            'lecturer_workload_constraints': _detail_count('Lecturer Workload Violations', penalty=violations.get('lecturer_workload_constraints', 0)),
            'no_free_day': _detail_count('No Free Day Violations', penalty=violations.get('no_free_day', 0), divisor=25.0),
            'three_unit_split_across_days_TYD': _detail_count('Three Unit Split Violations', penalty=violations.get('three_unit_split_across_days_TYD', 0), divisor=50.0),
            'single_event_per_day': _detail_count('Single Event Per Day Violations', penalty=violations.get('single_event_per_day', 0), divisor=0.05),
            'consecutive_timeslots': _detail_count('Consecutive Slot Violations', penalty=violations.get('consecutive_timeslots', 0), divisor=50.0),
            'spread_events': _detail_count('Spread Events Violations', penalty=violations.get('spread_events', 0), divisor=6.0),
            'extremely_late_classes': _detail_count('Late Classes', penalty=violations.get('extremely_late_classes', 0)),
        }

        hard_count = int(sum(occurrence_counts.get(k, 0) for k in hard_keys))
        soft_count = int(sum(occurrence_counts.get(k, 0) for k in soft_keys))
        total_count = hard_count + soft_count

        nonzero_hard = {k: v for k, v in hard_breakdown.items() if abs(v) > 1e-9}
        nonzero_soft = {k: v for k, v in soft_breakdown.items() if abs(v) > 1e-9}

        print("\nViolation breakdown")
        print(f"  total_fitness={total} (occurrences={total_count})")
        print(f"  hard_fitness={sum(nonzero_hard.values())} (occurrences={hard_count})")
        print(f"  soft_fitness={sum(nonzero_soft.values())} (occurrences={soft_count})")

        # Always print all hard constraints (show occurrences and penalties)
        print("  hard terms (MUST BE 0):")
        for key in hard_keys:
            val = hard_breakdown.get(key, 0.0)
            occ = occurrence_counts.get(key, 0)
            print(f"    - {key}: {occ} occurrences (Penalty: {val})")

        print("  priority soft terms (target 0 after hard):")
        for key in priority_soft:
            val = soft_breakdown.get(key, 0.0)
            print(f"    - {key} *: {occurrence_counts.get(key, 0)} occurrences (Penalty: {val})")

        print("  other soft terms:")

        # Print any remaining soft terms that were violated
        for key, value in sorted(nonzero_soft.items(), key=lambda kv: -abs(kv[1])):
            if key not in priority_soft:
                print(f"    - {key}: {occurrence_counts.get(key, 0)} occurrences (Penalty: {value})")

        return {
            "total": total,
            "total_occurrences": total_count,
            "hard_fitness": sum(nonzero_hard.values()),
            "hard_occurrences": hard_count,
            "soft_fitness": sum(nonzero_soft.values()),
            "soft_occurrences": soft_count,
            "hard_breakdown": hard_breakdown,
            "soft_breakdown": soft_breakdown,
            "occurrence_counts": occurrence_counts,
        }

    def _serialize_timetables_for_output_data(all_timetables: list) -> list:
        """Convert timetable objects into the JSON shape expected by output_data.py."""
        serialized = []
        for item in all_timetables or []:
            try:
                student_group = item.get("student_group")
                group_name = None
                group_id = None
                group_building = ""
                group_effective_building = ""

                if student_group is not None:
                    try:
                        group_name = str(getattr(student_group, "name", None) or "")
                    except Exception:
                        group_name = ""
                    for attr in ("id", "student_group_id", "group_id"):
                        try:
                            value = getattr(student_group, attr, None)
                            if value is not None:
                                group_id = str(value)
                                break
                        except Exception:
                            continue
                    try:
                        group_building = str(getattr(student_group, "building", "") or "").strip()
                    except Exception:
                        group_building = ""
                    try:
                        group_effective_building = "SST" if bool(getattr(student_group, "is_sst", False)) else "TYD"
                    except Exception:
                        group_effective_building = ""

                rows = []
                for row in item.get("timetable", []) or []:
                    rows.append([str(cell) if cell is not None else "" for cell in row])

                serialized.append({
                    "student_group": {
                        "name": group_name or "Unknown Group",
                        "id": group_id,
                        "building": group_building,
                        "effective_building": group_effective_building,
                    },
                    "timetable": rows,
                })
            except Exception:
                continue
        return serialized

    def _save_output_data_json(serialized_timetables: list) -> None:
        """Persist JSON using the same file layout the regular DE flow uses."""
        out_dir = root / "data"
        out_dir.mkdir(parents=True, exist_ok=True)

        fresh_path = out_dir / "fresh_timetable_data.json"
        with open(fresh_path, "w", encoding="utf-8") as f:
            json.dump(serialized_timetables, f, ensure_ascii=False, indent=2)
        print(f"Saved fresh_timetable_data.json to: {fresh_path}")

        wrapped_path = out_dir / "timetable_data.json"
        wrapped_payload = {
            "upload_id": "hybrid_smoke_test",
            "timetables": serialized_timetables,
            "manual_cells": [],
        }
        with open(wrapped_path, "w", encoding="utf-8") as f:
            json.dump(wrapped_payload, f, ensure_ascii=False, indent=2)
        print(f"Saved timetable_data.json to: {wrapped_path}")

    def _save_output_workbooks(serialized_timetables: list) -> None:
        """Generate the same workbook styles used by output_data.py."""
        out_dir = root / "output_data" / "Hybrid-Timetables"
        out_dir.mkdir(parents=True, exist_ok=True)

        export_jobs = [
            ("SST", output_data.export_sst_timetables_bytes_from_data, serialized_timetables),
            ("TYD", output_data.export_tyd_timetables_bytes_from_data, serialized_timetables),
            ("Lecturer", output_data.export_lecturer_timetables_bytes_from_data, serialized_timetables),
            ("Classrooms", output_data.export_classrooms_scheduled_bytes_from_data, (serialized_timetables, list(getattr(input_data, 'rooms', []) or []), "hybrid_smoke_test")),
        ]

        for label, exporter_fn, payload in export_jobs:
            try:
                if label == "Classrooms":
                    excel_bytes, filename = exporter_fn(*payload)
                else:
                    excel_bytes, filename = exporter_fn(payload)
                if not excel_bytes:
                    print(f"{label} export skipped: {filename}")
                    continue
                out_path = out_dir / (filename or f"{label}_Timetables_hybrid_smoke_test.xlsx")
                with open(out_path, "wb") as f:
                    f.write(excel_bytes)
                print(f"Saved {label} export to: {out_path}")
            except Exception as exc:
                print(f"Failed to save {label} export: {exc}")

    def _summarize_hard_fitness(chromosome) -> float:
        violations = Constraints(input_data).get_constraint_violations(chromosome)
        return float(sum(float(violations.get(k, 0) or 0) for k in CPSAT_REPORT_HARD_KEYS))

    # Auto-heal lecturer availability if it makes the dataset infeasible.
    cons_probe = Constraints(input_data)
    events_by_faculty = {}
    teaches_three_credit = set()
    for ev in cons_probe.events_map.values():
        fid = getattr(ev, 'faculty_id', None)
        if fid is None:
            continue
        fid = str(fid)
        events_by_faculty[fid] = events_by_faculty.get(fid, 0) + 1

        try:
            course = input_data.getCourse(getattr(ev, 'course_id', None))
        except Exception:
            course = None
        try:
            if course is not None and int(getattr(course, 'credits', 0) or 0) == 3:
                teaches_three_credit.add(fid)
        except Exception:
            pass

    days_map = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri'}
    hours = int(getattr(input_data, 'hours', 10) or 10)

    def is_break_slot(t_idx: int) -> bool:
        day = t_idx // hours
        return (day in (0, 2, 4)) and (t_idx == (day * hours + 4))

    impossible_constraints = []
    
    def _add_impossible(kind, message):
        impossible_constraints.append({'type': kind, 'message': message})

    expanded = []
    for faculty in getattr(input_data, 'faculties', []) or []:
        fid = str(getattr(faculty, 'faculty_id', None) or '').strip()
        needed = int(events_by_faculty.get(fid, 0) or 0)
        if not fid or needed <= 0:
            continue

        # 3-credit courses require spreading across >=2 days.
        try:
            if fid in teaches_three_credit:
                avail_days = set()
                for day_abbr in ('Mon', 'Tue', 'Wed', 'Thu', 'Fri'):
                    if cons_probe._is_faculty_available_day(faculty, day_abbr):
                        avail_days.add(day_abbr)
                if len(avail_days) < 2:
                    _add_impossible('three_unit_split_across_days_TYD', f"Lecturer {fid} teaches a 3-credit course but is available on <2 days ({sorted(avail_days)}). Split is impossible.")
                    faculty.avail_days = ['ALL']
                    faculty.avail_times = ['ALL']
                    expanded.append((fid, f"3-credit needs >=2 days; had {sorted(avail_days)}", None))
        except Exception:
            pass
        slots = 0
        days_with_any_slot = set()
        for t_idx, ts in enumerate(cons_probe.timeslots):
            if is_break_slot(t_idx):
                continue
            day_abbr = days_map.get(int(getattr(ts, 'day', 0)), '')
            slot_hour = float(getattr(ts, 'start_time', 0) or 0) + 8.5
            if cons_probe._is_faculty_available_day(faculty, day_abbr) and cons_probe._is_faculty_available_time(faculty, slot_hour, day_abbr):
                slots += 1
                try:
                    days_with_any_slot.add(int(getattr(ts, 'day', 0)))
                except Exception:
                    pass
        if needed > slots:
            _add_impossible('lecturer_availability', f"Lecturer {fid} has {needed} events but only {slots} available slots.")
            faculty.avail_days = ['ALL']
            faculty.avail_times = ['ALL']
            expanded.append((fid, needed, slots))

        # Workload feasibility auto-heal (match app.py policy)
        eff_days = max(1, len(days_with_any_slot) or 0)

        try:
            ah = int(getattr(faculty, 'available_hours', 4) or 4)
            ac = int(getattr(faculty, 'available_consecutive_hours', 3) or 3)
        except Exception:
            ah = 4
            ac = 3

        ah = max(2, min(8, ah))
        ac = max(2, min(8, ac))
        cap = eff_days * ah
        if needed > cap:
            target = int(math.ceil(float(needed) / float(eff_days)))
            target = max(ah, min(8, target))
            try:
                _add_impossible('lecturer_workload_constraints', f"Workload cap is impossible for {fid}: needs {needed} events but capacity is {cap}.")
                faculty.available_hours = target
                faculty.available_consecutive_hours = max(ac, target)
                expanded.append((fid, f"workload infeasible: needs {needed}/week but days*hours={cap}; set hours={target}", None))
            except Exception:
                pass

        # Stronger feasibility check using actual day/hour availability and max-consecutive.
        try:
            days_count = int(getattr(input_data, 'days', 0) or 0)
            if days_count <= 0:
                days_count = 5
        except Exception:
            days_count = 5

        try:
            hours_count = int(getattr(input_data, 'hours', 0) or 0)
            if hours_count <= 0:
                hours_count = 10
        except Exception:
            hours_count = 10

        try:
            avail_by_day = {d: [False] * hours_count for d in range(days_count)}
            for t_idx, ts in enumerate(cons_probe.timeslots):
                if is_break_slot(t_idx):
                    continue
                day_idx = int(getattr(ts, 'day', 0) or 0)
                hour_idx = int(getattr(ts, 'start_time', 0) or 0)
                if day_idx < 0 or day_idx >= days_count or hour_idx < 0 or hour_idx >= hours_count:
                    continue
                day_abbr = days_map.get(int(getattr(ts, 'day', 0)), '')
                slot_hour = float(getattr(ts, 'start_time', 0) or 0) + 8.5
                if cons_probe._is_faculty_available_day(faculty, day_abbr) and cons_probe._is_faculty_available_time(faculty, slot_hour, day_abbr):
                    avail_by_day[day_idx][hour_idx] = True

            def max_picks_for_day(avail_list, max_consec_allowed: int) -> int:
                max_consec_allowed = max(2, min(8, int(max_consec_allowed)))
                neg = -10**9
                dp = [neg] * (max_consec_allowed + 1)
                dp[0] = 0
                for ok in avail_list:
                    nxt = [neg] * (max_consec_allowed + 1)
                    best = max(dp)
                    nxt[0] = max(nxt[0], best)
                    if ok:
                        for run in range(max_consec_allowed):
                            if dp[run] > neg:
                                nxt[run + 1] = max(nxt[run + 1], dp[run] + 1)
                    dp = nxt
                return int(max(dp))

            weekly_max = 0
            for d in range(days_count):
                day_max = max_picks_for_day(avail_by_day.get(d, [False] * hours_count), int(getattr(faculty, 'available_consecutive_hours', 3) or 3))
                weekly_max += int(min(int(getattr(faculty, 'available_hours', 4) or 4), day_max))

            if needed > weekly_max:
                _add_impossible('lecturer_workload_constraints', f"Workload under availability is impossible for {fid}: needs {needed} but max feasible is {weekly_max}.")
                faculty.available_hours = 8
                faculty.available_consecutive_hours = 8
                faculty.avail_days = ['ALL']
                faculty.avail_times = ['ALL']
                expanded.append((fid, f"workload infeasible under availability: needs {needed} but max feasible is {weekly_max}; relaxed to 8/8 + ALL", None))
        except Exception:
            pass

    if expanded:
        print('expanded lecturers:', expanded)

    print("\nInitializing DE to create starting seed...")
    de = DifferentialEvolution(input_data, pop_size=1, F=0.4, CR=0.9)
    pop = getattr(de, "population", None)
    assert pop is not None and len(pop) > 0

    seed_chromosome = pop[0].copy()
    if hasattr(de, 'repair_multi_hour_blocks'):
        seed_chromosome = de.repair_multi_hour_blocks(seed_chromosome, max_passes=2)
    if hasattr(de, 'reduce_lecturer_clashes'):
        seed_chromosome = de.reduce_lecturer_clashes(seed_chromosome, max_passes=2)
    if hasattr(de, 'verify_and_repair_course_allocations'):
        seed_chromosome = de.verify_and_repair_course_allocations(seed_chromosome)

    hard_keys = list(CPSAT_REPORT_HARD_KEYS)

    print("\nStarting CP-SAT solver to enforce hard constraints, then priority soft constraints...")
    print("Setting time limit to 600s...")
    
    cfg = build_hybrid_cpsat_config(time_limit_seconds=600.0)
    
    try:
        print("Attempting fast hard-feasible pass (no soft optimization)...")
        hard_only_cfg = replace(
            cfg,
            time_limit_seconds=min(180.0, float(cfg.time_limit_seconds)),
            optimize_soft_terms=False,
            stop_after_first_solution=True,
        )
        repaired = repair_timetable_with_cpsat(
            input_data,
            seed_chromosome=seed_chromosome,
            config=hard_only_cfg,
        )
        print("Hard-feasible pass completed. Skipping soft optimization for speed.")
    except CpSatInfeasibleError as e:
        print(f"\nCP-SAT Infeasible/Timeout: {e}")
        
        try:
            print("\n=== AUTO-DIAGNOSING INFEASIBLE CONSTRAINTS ===")
            print("Testing which hard rules are mathematically clashing with your dataset...")
            feasibility = analyze_constraint_feasibility(input_data, seed_chromosome, cfg)
            
            infeasible = [k for k, v in feasibility.items() if not v]
            if infeasible:
                print(f"\n=> The following constraints are MATHEMATICALLY IMPOSSIBLE to satisfy together:")
                for inf in infeasible:
                    print(f"   - {inf}")
            else:
                print("\n=> All constraints seem feasible individually. The combination is too complex or conflicting.")
            print("==============================================\n")
        except Exception as diag_e:
            print(f"Auto-diagnosis failed: {diag_e}")

        # Try a few fallback repair strategies aiming to find ANY hard-feasible solution
        repaired = None
        try:
            print("\nAttempting fallback: relaxed priority soft (hard + consecutive still enforced)...")
            quick_cfg = build_hybrid_cpsat_relaxed_config(
                time_limit_seconds=min(180.0, float(cfg.time_limit_seconds)),
            )
            candidate = repair_timetable_with_cpsat(input_data, seed_chromosome=seed_chromosome, config=quick_cfg)
            # Verify hard fitness
            hard_val = _summarize_hard_fitness(candidate)
            if hard_val <= 1e-9:
                print("Found hard-feasible fallback (quick search). Using it.")
                repaired = candidate
            else:
                print(f"Quick fallback produced non-zero hard fitness={hard_val}; discarding.")
        except Exception as quick_e:
            print(f"Quick fallback failed: {quick_e}")

        if repaired is None:
            try:
                print("\nAttempting fallback: optimize remaining soft terms (consecutive still hard)...")
                soft_cfg = build_hybrid_cpsat_relaxed_config(
                    time_limit_seconds=float(cfg.time_limit_seconds),
                )
                candidate = repair_timetable_with_cpsat(input_data, seed_chromosome=seed_chromosome, config=soft_cfg)
                hard_val = _summarize_hard_fitness(candidate)
                if hard_val <= 1e-9:
                    print("Found hard-feasible solution optimizing soft terms. Using it.")
                    repaired = candidate
                else:
                    print(f"Soft-optimized fallback produced non-zero hard fitness={hard_val}; discarding.")
            except Exception as soft_e:
                print(f"Soft-optimized fallback failed: {soft_e}")

        # If still not repaired, run auto-diagnosis to help the user and fall back to seed
        if repaired is None:
            try:
                print("\n=== AUTO-DIAGNOSING INFEASIBLE CONSTRAINTS ===")
                print("Testing which hard rules are mathematically clashing with your dataset...")
                analyze_constraint_feasibility(input_data, seed_chromosome, cfg)
                print("==============================================\n")
            except Exception as diag_e:
                print(f"Auto-diagnosis failed: {diag_e}")
            repaired = seed_chromosome

    selected_seed_index = 0

    required_priority_soft_keys = list(CPSAT_REPORT_PRIORITY_SOFT_KEYS)
    feasibility_diag = None

    is_ok = False
    if repaired is not None and getattr(repaired, 'size', 0) > 0:
        final_violations = Constraints(input_data).get_constraint_violations(repaired)
        hard_total = float(sum(float(final_violations.get(k, 0) or 0) for k in hard_keys))
        soft_required_total = float(sum(float(final_violations.get(k, 0) or 0) for k in required_priority_soft_keys))
        is_ok = (hard_total <= 1e-9 and soft_required_total <= 1e-9)
    else:
        final_violations = {}

    if not is_ok:
        try:
            feasibility_diag = analyze_constraint_feasibility(input_data, seed_chromosome, cfg)
        except Exception:
            feasibility_diag = None
        detailed_pre = Constraints(input_data).get_detailed_constraint_violations(repaired)
        print_unsatisfied_constraint_report(
            final_violations,
            hard_keys=hard_keys,
            priority_soft_keys=required_priority_soft_keys,
            detailed_violations=detailed_pre,
            feasibility=feasibility_diag,
        )
        print('Exporting the lowest-penalty fallback schedule anyway...\n')

    # Serialize in the same JSON shape used by the regular DE flow, then export
    # through output_data.py so the workbook styling matches the main app.
    try:
        print("Exporting repaired timetable using output_data.py format...")
        days = int(getattr(input_data, 'days', 5) or 5)
        hours = int(getattr(input_data, 'hours', 10) or 10)
        day_start_time = 8.5

        if hasattr(de, 'print_all_timetables'):
            all_timetables = de.print_all_timetables(repaired, days, hours, day_start_time)
        else:
            all_timetables = []

        serialized_timetables = _serialize_timetables_for_output_data(all_timetables)
        if serialized_timetables:
            _save_output_data_json(serialized_timetables)
            _save_output_workbooks(serialized_timetables)
        else:
            print("No timetables produced to export.")
    except Exception as e:
        print("Failed to export repaired timetable:", e)

    cons = Constraints(input_data)
    v = cons.get_constraint_violations(repaired)
    detailed_v = cons.get_detailed_constraint_violations(repaired)

    hard_keys = list(CPSAT_REPORT_HARD_KEYS)
    hard = float(sum(float(v.get(k, 0) or 0) for k in hard_keys))

    print("hard_fitness=", hard)
    print("total_fitness=", float(v.get("total", -1)))

    breakdown = _print_violation_breakdown(v, hard_keys, detailed_v)

    # Save a machine-readable breakdown next to the Excel output for later inspection.
    try:
        out_dir = root / 'data'
        out_dir.mkdir(parents=True, exist_ok=True)
        # Write to a fixed filename and overwrite previous breakdowns
        breakdown_path = out_dir / "smoke_test_breakdown.json"
        with open(breakdown_path, 'w', encoding='utf-8') as bf:
            json.dump(breakdown, bf, indent=2)
        print(f"Saved violation breakdown (overwritten): {breakdown_path}")
    except Exception as e:
        print("Failed to save violation breakdown:", e)

    if feasibility_diag:
        infeasible = [k for k, v in feasibility_diag.items() if not v]
        if infeasible:
            print("\n=== MATHEMATICALLY IMPOSSIBLE CONSTRAINTS (CP-SAT TESTS) ===")
            for name in infeasible:
                print(f"  - {name}")
            print("============================================================")

    if impossible_constraints:
        print("\n=== MATHEMATICALLY IMPOSSIBLE CONSTRAINTS DETECTED ===")
        for ic in impossible_constraints:
            print(f"  - [{ic['type']}] {ic['message']}")
        print("======================================================")

    if hard > 1e-9:
        raise SystemExit("Hard constraints not satisfied")


if __name__ == "__main__":
    main()