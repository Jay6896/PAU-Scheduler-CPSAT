# Updated transformer runner: checks for Excel in data/Timetable_Input_Template.xlsx first,
# falls back to /mnt/data/Timetable_Input_Template.xlsx if not found.
# Then runs the transformer logic and prints first 5 entries for each JSON output.

import pandas as pd, json, re, sys
from pathlib import Path
from collections import OrderedDict

# Base path relative to this script's location
SCRIPT_DIR = Path(__file__).resolve().parent

# Look for any Excel file in the data directory first, then in the script directory
data_dir = SCRIPT_DIR / "data"
excel_files = []

# Search for Excel files in data directory
if len(sys.argv) > 1:
    candidate = Path(sys.argv[1])
    if not candidate.exists():
        raise FileNotFoundError(f"Specified Excel file not found: {candidate}")
    excel_path = candidate
else:
    # Look in data/ first, then script dir
    if data_dir.exists():
        excel_files.extend(list(data_dir.glob("*.xlsx")))
        excel_files.extend(list(data_dir.glob("*.xls")))

    if not excel_files:
        excel_files.extend(list(SCRIPT_DIR.glob("*.xlsx")))
        excel_files.extend(list(SCRIPT_DIR.glob("*.xls")))

    excel_path = None
    if excel_files:
        excel_path = excel_files[0]
        if len(excel_files) > 1:
            print(f"Found multiple Excel files: {[f.name for f in excel_files]}")
            print(f"Using: {excel_path.name}")
    else:
        raise FileNotFoundError(f"No Excel files (.xlsx or .xls) found in {data_dir} or {SCRIPT_DIR}")

print("Using Excel file at:", excel_path)

OUT_DIR = SCRIPT_DIR / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def slugify_id(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r'[^A-Za-z0-9\-_]', '_', str(s)).strip('_')

def normalize_list_cell(raw):
    if raw is None:
        return []
    if pd.isna(raw):
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []
    parts = re.split(r'[;,/]|[ \t]+', s)
    return [p.strip() for p in parts if p.strip()]


def _parse_numeric_limit_cell(raw):
    """Parse numeric/limit cell values for available hours fields.

    Accepts numbers, numeric strings, or blank. Returns int or None.
    """
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)) and not pd.isna(raw):
            return int(raw)
        s = str(raw).strip()
        if not s:
            return None
        # Extract leading integer
        m = re.match(r"^(\d+)", s)
        if m:
            return int(m.group(1))
    except Exception:
        return None
    return None

def find_student_group_columns(columns):
    pattern = re.compile(r'(?i)^\s*student\s*group\s*(\d+)\s*$')
    matches = []
    for c in columns:
        m = pattern.match(str(c))
        if m:
            matches.append((int(m.group(1)), c))
    if matches:
        matches.sort(key=lambda x: x[0])
        return [col for _, col in matches]
    candidate = [c for c in columns if 'group' in str(c).lower()]
    return candidate[:3]

def find_assigned_lecturer_column(columns):
    low = {str(c).strip().lower(): c for c in columns}
    for key in ("assigned lecturer emails", "assigned lecturers", "assigned lecturer"):
        if key in low:
            return low[key]
    for c in columns:
        s = str(c).lower()
        if 'lectur' in s and 'email' in s:
            return c
    for c in columns:
        if 'lectur' in str(c).lower():
            return c
    return None

# Read sheets
xls = pd.ExcelFile(excel_path)
required = ["Classrooms", "Lecturers", "Student Groups", "Courses"]
sheets = {}
for name in required:
    if name not in xls.sheet_names:
        raise FileNotFoundError(f"Required sheet '{name}' not found in workbook. Found: {xls.sheet_names}")
    df = pd.read_excel(excel_path, sheet_name=name, dtype=object).fillna("")
    sheets[name] = df

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
if email_col is None:
    for col in lect_df.columns:
        if 'email' in str(col).lower():
            email_col = col; break
if name_col is None:
    for col in lect_df.columns:
        if 'name' in str(col).lower():
            name_col = col; break

faculty_by_lower = {}
for _, r in lect_df.iterrows():
    raw_email = str(r.get(email_col) or "").strip() if email_col else ""
    raw_name  = str(r.get(name_col) or "").strip() if name_col else ""
    dept = str(r.get("Department") or "").strip() if "Department" in lect_df.columns else ""
    status = str(r.get("Status") or "").strip() if "Status" in lect_df.columns else ""
    avail_days = []

    # Fuzzy search for "Available Days" column
    aval_days_col = None
    for c in lect_df.columns:
        sc = str(c).strip().lower()
        if "avail" in sc and "day" in sc:
            aval_days_col = c
            break

    if aval_days_col:
        aval = str(r.get(aval_days_col) or "").strip()
        avail_days = [d.strip() for d in re.split(r'[ ,;]+', aval) if d.strip()] if aval else []

    avail_times = []

    # Fuzzy search for "Available Times" column
    aval_times_col = None
    for c in lect_df.columns:
        sc = str(c).strip().lower()
        if "avail" in sc and "time" in sc:
            aval_times_col = c
            break

    if aval_times_col:
        aval_t = str(r.get(aval_times_col) or "").strip()
        raw_times = [t.strip() for t in re.split(r'[ ,;/]+', aval_t) if t.strip()] if aval_t else []

        # TRANSFORMATION: Rollback support for whole number times (e.g. 9:00 -> 8:30)
        cleaned_avail_times = []
        for t in raw_times:
            try:
                if '-' in t:
                    parts = t.split('-')
                    start_str, end_str = parts[0].strip(), parts[1].strip()
                    if ':' in start_str:
                        sh, sm = map(int, start_str.split(':'))
                    else:
                        sh, sm = int(start_str), 0
                    if sm == 0:
                        s_new = f"{sh-1}:{30}"
                    else:
                        s_new = start_str
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

        final_avail_times_map = {}
        if not cleaned_avail_times:
            pass
        else:
            normalized_days = [d.strip().capitalize() for d in avail_days]
            if not normalized_days and cleaned_avail_times:
                pass
            if len(cleaned_avail_times) == 1:
                if not normalized_days or (len(normalized_days)==1 and normalized_days[0].upper() == 'ALL'):
                    final_avail_times_map = {'All': cleaned_avail_times}
                else:
                    for day in normalized_days:
                        final_avail_times_map[day] = [cleaned_avail_times[0]]
            else:
                if not normalized_days:
                    final_avail_times_map = {'All': cleaned_avail_times}
                else:
                    for i, day in enumerate(normalized_days):
                        t_idx = min(i, len(cleaned_avail_times)-1)
                        final_avail_times_map[day] = [cleaned_avail_times[t_idx]]
        avail_times = final_avail_times_map if final_avail_times_map else []
    else:
        avail_times = []

    # Lecturer workload limits (defaults)
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

# Courses
course_df = sheets["Courses"]
sg_cols = find_student_group_columns(list(course_df.columns))
assigned_col = find_assigned_lecturer_column(list(course_df.columns))
if assigned_col is None:
    raise RuntimeError("Could not detect the 'Assigned Lecturer Emails' column in the Courses sheet.")

courses = []
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
    seen=set(); student_groups=[x for x in student_groups if not (x in seen or seen.add(x))]

    dept = str(r.get("Department") or "").strip() if "Department" in course_df.columns else ""
    req_raw = str(r.get("Special Requirements") or "").strip() if "Special Requirements" in course_df.columns else ""
    req_list = [p.strip() for p in re.split(r'[;,/]|[ \t]+', req_raw) if p.strip()] if req_raw else []

    # facultyId is now an array of all lecturers, with the first one being primary
    facultyId = lecturers if lecturers else []
    courses.append({"name": name, "code": code, "credits": credits, "student_groupsID": student_groups, "facultyId": facultyId, "required_room_type": room_type, "lecturers": lecturers, "dept": dept, "req": req_list})

    for g in student_groups:
        if g not in groups:
            groups[g] = {"id": g, "name": g, "level": "", "dept": dept, "building": "", "no_students": 0, "courseIDs": [], "teacherIDS": [], "hours_required": []}
        groups[g]["courseIDs"].append(code)
        # CHANGED: append only the primary lecturer (first one) to maintain one-to-one mapping with courseIDs
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

# finalize groups
for gobj in groups.values():
    # REMOVED DEDUPLICATION of teacherIDS → keep duplicates aligned with courseIDs
    gobj["hours_required"]=[int(h) if str(h).strip() else 0 for h in (gobj.get("hours_required") or [])]

# Prepare JSON arrays
course_json = [{"name": c["name"], "code": c["code"], "credits": int(c["credits"]), "student_groupsID": c["student_groupsID"], "facultyId": c["facultyId"], "required_room_type": c["required_room_type"]} for c in courses]
rooms_json = [{"Id": r["Id"], "name": r["name"], "capacity": int(r["capacity"]), "room_type": r["room_type"], "building": r["building"]} for r in rooms]
studentgroups_json = [
    {
        "id": g["id"],
        "name": g["name"],
        "building": g.get("building") or "",
        "no_students": int(g.get("no_students") or 0),
        "courseIDs": g.get("courseIDs") or [],
        "teacherIDS": g.get("teacherIDS") or [],
        "hours_required": g.get("hours_required") or [],
    }
    for g in groups.values()
]
faculties_json = list(faculty_by_lower.values())

# Write JSON files (overwrite)
def write_json(obj, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)

write_json(course_json, OUT_DIR / "course-data.json")
write_json(rooms_json, OUT_DIR / "rooms-data.json")
write_json(studentgroups_json, OUT_DIR / "studentgroup-data.json")
write_json(faculties_json, OUT_DIR / "faculty-data.json")

print("Wrote JSON files to:", OUT_DIR.resolve())