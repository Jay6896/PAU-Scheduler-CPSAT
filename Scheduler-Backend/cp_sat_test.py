"""Minimal CP-SAT test for the backend.

Run (Windows / PowerShell):
    ./.venv/Scripts/python.exe PAU-Timetable-Scheduler/cp_sat_test.py

This is not wired into the timetable generator yet; it only verifies OR-Tools is
installed and the CP-SAT solver can run.
"""

from __future__ import annotations

from ortools.sat.python import cp_model


def main() -> None:
    model = cp_model.CpModel()

    x = model.new_int_var(0, 10, "x")
    y = model.new_int_var(0, 10, "y")

    model.add(x + y == 10)
    model.add(x >= 3)

    solver = cp_model.CpSolver()
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SystemExit(f"CP-SAT did not find a solution (status={status})")

    print("OR-Tools CP-SAT OK")
    print("x=", solver.value(x), "y=", solver.value(y))


if __name__ == "__main__":
    main()
