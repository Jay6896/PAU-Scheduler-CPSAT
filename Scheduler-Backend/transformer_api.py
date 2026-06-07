# transformer_api.py
"""
API-ready transformer module for converting the Timetable Excel template
into a JSON structure suitable for the timetable scheduling input system.

Provides:
- validate_excel_structure(file_or_path) -> (bool, message)
- transform_excel_to_json(file_or_path) -> dict

file_or_path may be:
- a filesystem path (str or pathlib.Path)
- a file-like object (has .read()) such as Werkzeug FileStorage.stream
- bytes / bytearray / io.BytesIO

This module does NOT write JSON files to disk; it returns dictionaries.
"""

from pathlib import Path
import json
import re
from collections import OrderedDict
from typing import Tuple, Union, Any, Optional, IO
import io

# pandas is intentionally imported lazily to avoid heavy import cost at API startup.
_PANDAS = None


def _get_pandas():
    global _PANDAS
    if _PANDAS is None:
        import importlib

        pd = importlib.import_module('pandas')
        # Opt-in to explicit behavior to avoid silent downcasting warnings
        try:
            pd.set_option('future.no_silent_downcasting', True)
        except Exception:
            pass
        _PANDAS = pd
    return _PANDAS

# Types accepted for file_or_path
FileInput = Union[str, Path, bytes, bytearray, IO]

# Required sheet names expected in the template
REQUIRED_SHEETS = ["Classrooms", "Lecturers", "Student Groups", "Courses"]

# Accept common aliases (case-insensitive) for sheet names
SHEET_ALIASES = {
    "Classrooms": ["classrooms", "rooms", "room", "venues", "classroom"],
    "Lecturers": ["lecturers", "faculty", "faculties", "teachers", "instructors"],
    "Student Groups": ["student groups", "studentgroups", "groups", "students", "cohorts"],
    "Courses": ["courses", "course list", "modules", "subjects"],
}

def _normalize(s: str) -> str:
    return str(s or '').strip().lower()

def _resolve_required_sheets(sheet_names):
    """Return a mapping of logical required sheet name -> actual sheet name in workbook.
    Uses case-insensitive matching and common aliases.
    """
    normalized_map = {_normalize(name): name for name in sheet_names}
    resolved = {}
    for logical in REQUIRED_SHEETS:
        # direct match
        if _normalize(logical) in normalized_map:
            resolved[logical] = normalized_map[_normalize(logical)]
            continue
        # alias match
        for alias in SHEET_ALIASES.get(logical, []):
            if alias in normalized_map:
                resolved[logical] = normalized_map[alias]
                break
        # fuzzy: allow replacing hyphens/extra spaces
        if logical not in resolved:
            for cand_norm, real in normalized_map.items():
                if cand_norm.replace('-', ' ').replace('_', ' ') == _normalize(logical).replace('-', ' ').replace('_', ' '):
                    resolved[logical] = real
                    break
    return resolved

def _open_excel(file_or_path: FileInput) -> Any:
    """
    Return a pandas.ExcelFile from a path, bytes, or file-like object.
    Raises helpful errors if reading fails.
    """
    try:
        pd = _get_pandas()
        if isinstance(file_or_path, (bytes, bytearray)):
            bio = io.BytesIO(file_or_path)
            return pd.ExcelFile(bio)
        if hasattr(file_or_path, "read") and not isinstance(file_or_path, (str, Path)):
            # file-like object (e.g., request.files['file'].stream or FileStorage)
            content = file_or_path.read()
            # If stream returns bytes, wrap; if returns str, attempt encoding
            if isinstance(content, str):
                content = content.encode("utf-8")
            return pd.ExcelFile(io.BytesIO(content))
        # else assume path-like
        path = Path(file_or_path)
        if not path.exists():
            raise FileNotFoundError(f"Excel file not found at path: {path}")
        return pd.ExcelFile(str(path))
    except Exception as e:
        raise RuntimeError(f"Failed to open Excel file: {e}") from e


def validate_excel_structure(file_or_path: FileInput) -> Tuple[bool, str]:
    """
    Validate the workbook contains required sheets and basic expected columns.
    Returns (True, "") when valid, otherwise (False, "reason").
    """
    pd = _get_pandas()
    try:
        xls = _open_excel(file_or_path)
    except Exception as e:
        return False, f"Could not open Excel: {e}"

    # Resolve required sheets with aliases
    sheet_map = _resolve_required_sheets(xls.sheet_names)
    missing = [s for s in REQUIRED_SHEETS if s not in sheet_map]
    if missing:
        return False, (
            "Workbook is missing required sheet(s): "
            + ", ".join(missing)
            + ". Found sheets: "
            + ", ".join(map(str, xls.sheet_names))
        )

    # Basic checks for Courses sheet: must have at least Course Code and a lecturer column
    try:
        courses_df = pd.read_excel(xls, sheet_name=sheet_map["Courses"], dtype=object)
    except Exception as e:
        return False, f"Failed to read 'Courses' sheet: {e}"

    # check Course Code header
    cols_lower = [str(c).strip().lower() for c in courses_df.columns]
    if not any(c in cols_lower for c in ("course code", "code", "course_code")):
        return False, "Courses sheet missing a 'Course Code' column."

    # Try to find an assigned lecturer column (heuristic)
    assigned_col = None
    for key in ("assigned lecturer emails", "assigned lecturers", "assigned lecturer", "lecturer email", "lecturer", "lecturer emails", "assigned lecturer email"):
        for col in courses_df.columns:
            if key in str(col).strip().lower():
                assigned_col = col
                break
        if assigned_col:
            break
    # fallback: any column containing 'lectur' substring
    if assigned_col is None:
        for col in courses_df.columns:
            if "lectur" in str(col).lower():
                assigned_col = col
                break

    if assigned_col is None:
        return False, "Courses sheet does not contain a detectable 'Assigned Lecturer' column."

    return True, ""


# ----------------------- helper functions -----------------------
def slugify_id(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r'[^A-Za-z0-9\-_]', '_', str(s)).strip('_')


def normalize_list_cell(raw: Any):
    """
    Convert a cell that may contain lists (strings separated by ',' or '/') into a list of strings.

    IMPORTANT: Do NOT split on whitespace. Names like "Dr John Marston" must remain a single lecturer.
    """
    if raw is None:
        return []
    pd = _get_pandas()
    if pd.isna(raw):
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []

    # Only comma or slash separate lecturers.
    if (',' not in s) and ('/' not in s):
        return [s]

    # Split on comma or slash, allowing surrounding spaces.
    parts = re.split(r'\s*[,/]\s*', s)
    return [p.strip() for p in parts if p and p.strip()]


def _parse_numeric_limit_cell(value: Any) -> Optional[int]:
    """Parse a numeric hour limit from an Excel cell.

    Rules:
    - Only digits are read (any other characters are ignored).
    - Valid range is 2..8 inclusive; values outside are clamped.
    - If no digits are present (blank/invalid), returns None.
    """
    if value is None:
        return None
    try:
        pd = _get_pandas()
        if pd.isna(value):
            return None
    except Exception:
        pass

    s = str(value).strip()
    if not s:
        return None

    m = re.search(r'(\d+)', s)
    if not m:
        return None

    try:
        n = int(m.group(1))
    except Exception:
        return None

    if n < 2:
        return 2
    if n > 8:
        return 8
    return n


def find_student_group_columns(columns):
    """
    Detect columns in Courses sheet that correspond to Student Group 1, Student Group 2, ...
    Fallback: any column containing 'group' (first few).
    """
    pattern = re.compile(r'(?i)^\s*student\s*group\s*(\d+)\s*$')
    matches = []
    for c in columns:
        m = pattern.match(str(c))
        if m:
            matches.append((int(m.group(1)), c))
    if matches:
        matches.sort(key=lambda x: x[0])
        return [col for _, col in matches]
    # fallback
    candidate = [c for c in columns if 'group' in str(c).lower()]
    return candidate[:3]


def find_assigned_lecturer_column(columns):
    """
    Return the best guess column name in columns for assigned lecturers.
    """
    low = {str(c).strip().lower(): c for c in columns}
    for key in ("assigned lecturer emails", "assigned lecturers", "assigned lecturer", "lecturer email", "lecturer emails", "email"):
        if key in low:
            return low[key]
    # look for column containing 'lectur' and optionally 'email'
    for c in columns:
        s = str(c).lower()
        if 'lectur' in s and 'email' in s:
            return c
    for c in columns:
        if 'lectur' in str(c).lower():
            return c
    return None


# ----------------------- main transform function -----------------------
def transform_excel_to_json(file_or_path: FileInput) -> dict:
    """
    Parse the timetable Excel template and return a dict containing parsed data:
    {
      "courses": [...],
      "rooms": [...],
      "studentgroups": [...],
      "faculties": [...]
    }

    Accepts file path, bytes, or file-like (see _open_excel).
    Raises RuntimeError on parsing problems (missing sheets/columns).
    """
    pd = _get_pandas()
    xls = _open_excel(file_or_path)

    # Resolve names using aliases
    sheet_map = _resolve_required_sheets(xls.sheet_names)
    for required in REQUIRED_SHEETS:
        if required not in sheet_map:
            raise RuntimeError(
                f"Required sheet '{required}' not found in workbook. Found: {xls.sheet_names}"
            )

    # Read required sheets into dataframes (as object dtype)
    sheets = {}
    for logical in REQUIRED_SHEETS:
        real_name = sheet_map[logical]
        df = pd.read_excel(xls, sheet_name=real_name, dtype=object).fillna("")
        # Infer object dtypes explicitly to avoid future warning (no silent downcasting)
        try:
            df = df.infer_objects(copy=False)
        except Exception:
            pass
        sheets[logical] = df

    # Build faculty map from Lecturers sheet
    lect_df = sheets["Lecturers"]
    email_col = None
    name_col = None
    for col in lect_df.columns:
        lc = str(col).strip().lower()
        if lc in ("faculty email", "lecturer email", "email", "email address"):
            email_col = col
        if lc in ("faculty name", "lecturer name", "name"):
            name_col = col
    # fallback heuristics
    if email_col is None:
        for col in lect_df.columns:
            if 'email' in str(col).lower():
                email_col = col
                break
    if name_col is None:
        for col in lect_df.columns:
            if 'name' in str(col).lower():
                name_col = col
                break

    faculty_by_lower = {}
    for _, r in lect_df.iterrows():
        raw_email = str(r.get(email_col) or "").strip() if email_col else ""
        raw_name = str(r.get(name_col) or "").strip() if name_col else ""
        dept = str(r.get("Department") or "").strip() if "Department" in lect_df.columns else ""
        status = str(r.get("Status") or "").strip() if "Status" in lect_df.columns else ""
        avail_days = []
        if "Available Days" in lect_df.columns:
            aval = str(r.get("Available Days") or "").strip()
            avail_days = [d.strip() for d in re.split(r'[ ,;]+', aval) if d.strip()] if aval else []
        # Prepare final list of cleaned times
        cleaned_avail_times = []
        if "Available Times" in lect_df.columns:
            aval_t = str(r.get("Available Times") or "").strip()
            raw_times = [t.strip() for t in re.split(r'[ ,;]+', aval_t) if t.strip()] if aval_t else []
            
            for t in raw_times:
                try:
                    if '-' in t:
                        parts = t.split('-')
                        start_str, end_str = parts[0].strip(), parts[1].strip()
                        
                        # Process Start
                        if ':' in start_str:
                            sh, sm = map(int, start_str.split(':'))
                        else:
                            sh, sm = int(start_str), 0
                        
                        if sm == 0:
                            s_new = f"{sh-1}:{30}"
                        else:
                            s_new = start_str
                            
                        # Process End
                        if ':' in end_str:
                            eh, em = map(int, end_str.split(':'))
                        else:
                            eh, em = int(end_str), 0
                            
                        if em == 0:
                            e_new = f"{eh}:{30}"
                        else:
                            e_new = end_str
                            
                        cleaned_avail_times.append(f"{s_new}-{e_new}")
                    else:
                        # Singleton
                        if ':' in t:
                            h, m = map(int, t.split(':'))
                        else:
                            h, m = int(t), 0
                            
                        if m == 0:
                            cleaned_avail_times.append(f"{h-1}:{30}")
                        else:
                            cleaned_avail_times.append(t)
                except:
                    cleaned_avail_times.append(t)
        
        # MAPPING LOGIC: Map Cleaned Times to Available Days
        # If 1 time -> All days get that time
        # If N times -> Day[i] gets Time[i] (fallback to last time if days > times)
        
        # We will now store avail_times as a DICTIONARY { 'DayStr': ['TimeRange'] }
        # To maintain backward compatibility with simplistic checks, 
        # we might need to be careful, but the request implies strict mapping.
        
        final_avail_times_map = {}
        
        if not cleaned_avail_times:
             # No times specified -> treat as empty or ALL depending on logic elsewhere
             # Currently we leave it empty, which defaults to unavailable or ALL later
             final_avail_times_map = [] # Keep as empty list to avoid breaking length checks immediately? 
             # Actually code below: if not avail_times: avail_times = ["ALL"]. 
             # Let's let it fall through to that, but that sets it to a list.
             pass
        else:
            # We have times. We have avail_days.
            # Normalize avail_days for reliable mapping
            normalized_days = [d.strip().capitalize() for d in avail_days]
            if not normalized_days and cleaned_avail_times:
                 # Times provided but no days? Assume Mon-Fri? Or just "All"?
                 # Existing logic below handles empty avail_days -> ["ALL"]
                 # If "ALL", we just map "ALL" -> times
                 pass

            if len(cleaned_avail_times) == 1:
                # One time applied to all days
                # If days is empty/ALL, map "ALL"
                if not normalized_days or (len(normalized_days)==1 and normalized_days[0].upper() == 'ALL'):
                    final_avail_times_map = {'All': cleaned_avail_times}
                else:
                    for day in normalized_days:
                        final_avail_times_map[day] = [cleaned_avail_times[0]]
            else:
                # Multiple times roughly corresponding to days
                if not normalized_days:
                     # Fallback
                     final_avail_times_map = {'All': cleaned_avail_times}
                else:
                    for i, day in enumerate(normalized_days):
                        # Use corresponding time index, or clamp to last available
                        t_idx = min(i, len(cleaned_avail_times)-1)
                        final_avail_times_map[day] = [cleaned_avail_times[t_idx]]
        
        # Replace the list with our map (or list if empty)
        avail_times = final_avail_times_map if final_avail_times_map else []

        # Lecturer workload limits (new columns)
        # Defaults when blank: 4 hours/day and 3 consecutive hours.
        available_hours = 4
        available_consecutive_hours = 3
        if "Available Hours" in lect_df.columns:
            parsed = _parse_numeric_limit_cell(r.get("Available Hours"))
            if parsed is not None:
                available_hours = parsed
        if "Available Consecutive Hours" in lect_df.columns:
            parsed = _parse_numeric_limit_cell(r.get("Available Consecutive Hours"))
            if parsed is not None:
                available_consecutive_hours = parsed

        # If the spreadsheet does not specify availability, default to ALL.
        # Leaving these empty makes the API scheduler treat the lecturer as unavailable.
        if not avail_days:
            avail_days = ["ALL"]
        if not avail_times:
            avail_times = ["ALL"]
        if raw_email:
            key = raw_email.lower()
            faculty_by_lower[key] = {
                "id": raw_email,
                "name": raw_name or raw_email,
                "department": dept,
                "status": status,
                "avail_days": avail_days,
                "avail_times": avail_times,
                "available_hours": available_hours,
                "available_consecutive_hours": available_consecutive_hours,
                "courseID": [],
            }
        else:
            synthetic = slugify_id(raw_name) or f"lect_{len(faculty_by_lower)+1}"
            faculty_by_lower[synthetic.lower()] = {
                "id": synthetic,
                "name": raw_name or synthetic,
                "department": dept,
                "status": status,
                "avail_days": avail_days,
                "avail_times": avail_times,
                "available_hours": available_hours,
                "available_consecutive_hours": available_consecutive_hours,
                "courseID": [],
            }

    # Rooms
    rooms = []
    rooms_df = sheets["Classrooms"]
    for idx, r in rooms_df.iterrows():
        name = str(r.get("Room Name") or "").strip()
        building = str(r.get("Building") or "").strip() if "Building" in rooms_df.columns else ""
        cap_raw = r.get("Capacity")
        try:
            capacity = int(cap_raw) if str(cap_raw).strip() else 0
        except Exception:
            capacity = 0
        room_type = str(r.get("Classroom Type") or "").strip() if "Classroom Type" in rooms_df.columns else "Classroom"
        notes = str(r.get("Location Notes") or "").strip() if "Location Notes" in rooms_df.columns else ""
        Id = slugify_id(name) or f"room_{idx+1}"
        rooms.append({"Id": Id, "name": name or Id, "capacity": capacity, "room_type": room_type, "building": building, "notes": notes})

    # Student groups
    groups = OrderedDict()
    declared_group_ids = set()
    groups_df = sheets["Student Groups"]
    for _, r in groups_df.iterrows():
        gid = str(r.get("Group ID") or "").strip()
        gname = str(r.get("Group Name") or "").strip()
        level = str(r.get("Level") or "").strip() if "Level" in groups_df.columns else ""
        dept = str(r.get("Department") or "").strip() if "Department" in groups_df.columns else ""
        building = str(r.get("Building") or "").strip() if "Building" in groups_df.columns else ""
        size_raw = r.get("Size") if "Size" in groups_df.columns else ""
        try:
            size = int(size_raw) if str(size_raw).strip() else 0
        except Exception:
            size = 0
        if not gid:
            gid = slugify_id(gname) or f"group_{len(groups)+1}"
        groups[gid] = {"id": gid, "name": gname or gid, "level": level, "dept": dept, "building": building, "no_students": size, "courseIDs": [], "teacherIDS": [], "hours_required": []}
        declared_group_ids.add(gid)

    # Courses
    course_df = sheets["Courses"]
    sg_cols = find_student_group_columns(list(course_df.columns))
    assigned_col = find_assigned_lecturer_column(list(course_df.columns))
    if assigned_col is None:
        raise RuntimeError("Could not detect the 'Assigned Lecturer' column in the Courses sheet.")

    courses = []
    unknown_course_student_groups = set()
    for _, r in course_df.iterrows():
        code = str(r.get("Course Code") or "").strip()
        if not code:
            continue
        name = str(r.get("Course Name") or "").strip()
        credits_raw = r.get("Credit Units") if "Credit Units" in course_df.columns else r.get("Credits")
        try:
            credits = int(credits_raw) if str(credits_raw).strip() else 0
        except Exception:
            credits = 0
        room_type = str(r.get("Classroom Type") or "").strip() if "Classroom Type" in course_df.columns else "Classroom"
        lecturers = normalize_list_cell(r.get(assigned_col))

        # Build student_groupsID strictly from sg_cols
        student_groups = []
        for col in sg_cols:
            val = str(r.get(col) or "").strip()
            if val:
                student_groups.append(val)
        seen = set()
        student_groups = [x for x in student_groups if not (x in seen or seen.add(x))]

        dept = str(r.get("Department") or "").strip() if "Department" in course_df.columns else ""
        req_raw = str(r.get("Special Requirements") or "").strip() if "Special Requirements" in course_df.columns else ""
        req_list = [p.strip() for p in re.split(r'[;,/]|[ \t]+', req_raw) if p.strip()] if req_raw else []

        facultyId = lecturers[0] if lecturers else None
        courses.append({"name": name, "code": code, "credits": credits, "student_groupsID": student_groups, "facultyId": facultyId, "required_room_type": room_type, "lecturers": lecturers, "dept": dept, "req": req_list})

        for g in student_groups:
            if g not in groups:
                # Hard validation: Courses references a group ID that isn't declared in Student Groups.
                unknown_course_student_groups.add(g)
                continue
            groups[g]["courseIDs"].append(code)
            # Keep duplicates aligned with courseIDs (as in original)
            groups[g]["teacherIDS"].append(lecturers[0] if lecturers else None)
            groups[g]["hours_required"].append(credits)

        # Append course code to each lecturer's courseID list
        for lect in lecturers:
            key = lect.strip().lower()
            if key in faculty_by_lower:
                if code not in faculty_by_lower[key]["courseID"]:
                    faculty_by_lower[key]["courseID"].append(code)
                if not faculty_by_lower[key].get("department") and dept:
                    faculty_by_lower[key]["department"] = dept
            else:
                faculty_by_lower[key] = {"id": lect.strip(), "name": lect.strip(), "department": dept, "status": "", "avail_days": [], "avail_times": [], "courseID": [code]}

    # Ensure any synthetic/auto-created faculty entries have sensible defaults.
    for f in faculty_by_lower.values():
        if not f.get("avail_days"):
            f["avail_days"] = ["ALL"]
        if not f.get("avail_times"):
            f["avail_times"] = ["ALL"]
        if f.get("available_hours") is None:
            f["available_hours"] = 4
        if f.get("available_consecutive_hours") is None:
            f["available_consecutive_hours"] = 3

    # finalize groups (coerce hours_required to ints)
    for gobj in groups.values():
        gobj["hours_required"] = [int(h) if str(h).strip() else 0 for h in (gobj.get("hours_required") or [])]

    if unknown_course_student_groups:
        missing_sorted = sorted(str(x) for x in unknown_course_student_groups if str(x).strip())
        declared_sorted = sorted(str(x) for x in declared_group_ids if str(x).strip())
        raise RuntimeError(
            "Unmatching data between sheets: The Courses sheet contains studentgroup IDs that do not exist in the Student Groups sheet. "
            f"Unknown IDs (from Courses): {missing_sorted}. Declared IDs (from Student Groups): {declared_sorted}"
        )

    # Build JSON-compatible structures
    course_json = [
        {
            "name": c["name"],
            "code": c["code"],
            "credits": int(c["credits"]),
            "student_groupsID": c["student_groupsID"],
            "facultyId": c["facultyId"],
            "required_room_type": c["required_room_type"],
            "lecturers": c.get("lecturers", []),
            "dept": c.get("dept", ""),
            "req": c.get("req", [])
        } for c in courses
    ]
    rooms_json = [
        {"Id": r["Id"], "name": r["name"], "capacity": int(r["capacity"]), "room_type": r["room_type"], "building": r["building"], "notes": r.get("notes", "")}
        for r in rooms
    ]
    studentgroups_json = [
        {
            "id": g["id"],
            "name": g["name"],
            "building": g.get("building") or "",
            "no_students": int(g.get("no_students") or 0),
            "courseIDs": g.get("courseIDs") or [],
            "teacherIDS": g.get("teacherIDS") or [],
            "hours_required": g.get("hours_required") or []
        } for g in groups.values()
    ]
    faculties_json = list(faculty_by_lower.values())

    result = {
        "courses": course_json,
        "rooms": rooms_json,
        "studentgroups": studentgroups_json,
        # Keep alternative key for compatibility
        "student_groups": studentgroups_json,
        "faculties": faculties_json,
        # include simple counts for convenience
        "_meta": {
            "course_count": len(course_json),
            "room_count": len(rooms_json),
            "studentgroup_count": len(studentgroups_json),
            "faculty_count": len(faculties_json),
        }
    }

    return result


# If module executed directly, allow quick local test (not used by app)
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python transformer_api.py <path-to-Excel>")
        sys.exit(1)
    path = sys.argv[1]
    ok, msg = validate_excel_structure(path)
    if not ok:
        print("Validation failed:", msg)
        sys.exit(2)
    data = transform_excel_to_json(path)
    print(json.dumps(data.get("_meta", {}), indent=2))
    # Optionally print sample course count
    print(f"Courses parsed: {len(data['courses'])}")
