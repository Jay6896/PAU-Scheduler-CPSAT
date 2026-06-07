import json
import logging
from collections import defaultdict
from pathlib import Path
from input_data import input_data
from constraints import Constraints
from entitities.time_slot import TimeSlot
import re

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


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

def verify_timetable_constraints():
    # 1. Load Data
    try:
        data_dir = Path("data")
        with open(data_dir / "fresh_timetable_data.json", "r", encoding='utf-8') as f:
            timetable_data = json.load(f)
        
        with open(data_dir / "rooms-data.json", "r", encoding='utf-8') as f:
            rooms_data = json.load(f)
            # Create a lookup for room details
            rooms_lookup = {r['name']: r for r in rooms_data}
            
        # Use the singleton input_data which is populated on import
        inp = input_data
        course_credits = {}
        for c in inp.courses:
            course_credits[c.code] = c.credits
        course_lookup = {c.code: c for c in inp.courses}
        faculty_lookup = {}
        for f in getattr(inp, 'faculties', []) or []:
            fid = str(getattr(f, 'faculty_id', '') or '').strip()
            name = str(getattr(f, 'name', '') or '').strip()
            if fid:
                faculty_lookup[fid.casefold()] = f
            if name:
                faculty_lookup[name.casefold()] = f
            
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        return

    violations = {
        'Hard_WrongBuilding': [],
        'Hard_RoomTypeMismatch': [],
        'Hard_ConsecutiveSlots': [],
        'Hard_StudentClash': [],
        'Hard_LecturerClash': [],
        'Hard_StudentGroupClash': [],
        'Hard_LecturerAvailability': [],
        'Hard_SameCourseMultipleRooms': [],
        'Hard_Capacity': []
    }

    # 2. Iterate Timetables
    # timetable_data is a list of objects: { "student_group": {...}, "timetable": [ ["9:00", ...], ... ] }
    
    # Store all events for global checks (clashes)
    # Map: (day_idx, hour_idx) -> List of (Group, Course, Room)
    global_schedule = defaultdict(list)
    
    # Map: Group -> Course -> List of (day_idx, hour_idx, room)
    group_course_schedule = defaultdict(lambda: defaultdict(list))

    days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
    hours_map = {0: "9:00", 1: "10:00", 2: "11:00", 3: "12:00", 4: "13:00", 5: "14:00", 6: "15:00", 7: "16:00", 8: "17:00"}
    
    for entry in timetable_data:
        group_info = entry['student_group']
        group_name = group_info['name']
        group_id = group_info['id']
        timetable_matrix = entry['timetable'] # List of rows (hours)

        # Determine if group is SST
        # Start with false, check manual logic or reuse entity logic if possible, 
        # but for verification let's replicate the logic to be sure.
        is_sst = False
        sst_prefixes = {'EEE', 'MEE', 'CSC', 'SEN', 'MCT', 'DTS'}
        sst_keywords = ['engineering', 'computer science', 'data science', 'mechatronics', 'software', 'technology', 'mechanical', 'electrical']
        
        prefix = group_id.split(' ')[0].upper()
        if prefix in sst_prefixes:
            is_sst = True
        elif any(k in group_name.lower() for k in sst_keywords):
            is_sst = True
            
        # Parse Matrix
        # Row 0: 9:00, Row 1: 10:00 ...
        for h_idx, row in enumerate(timetable_matrix):
            # Col 0 is time label, Cols 1..5 are Mon..Fri
            if len(row) < 6: continue

            start_minutes = _time_to_minutes(row[0])
            if start_minutes is None:
                start_minutes = (9 + h_idx) * 60
            
            for d_idx in range(5):
                cell = row[d_idx + 1] # +1 to skip time column
                if not cell or cell.strip() == "" or cell == "BREAK" or cell == "FREE":
                    continue
                
                course_code, room_name, lecturer = _parse_cell(cell)
                if not course_code:
                    continue
                course_code = course_code.strip()
                room_name = room_name.strip() if room_name else "Unknown"
                lecturer_s = str(lecturer or "").strip()
                lecturer_norm = lecturer_s.casefold() if lecturer_s else None
                
                # Update Global Schedule
                global_schedule[(d_idx, h_idx)].append({
                    'group': group_name,
                    'group_id': group_id,
                    'course': course_code,
                    'room': room_name,
                    'lecturer': lecturer_s
                })
                
                # Update Group Schedule
                group_course_schedule[group_id][course_code].append((d_idx, h_idx, room_name))

                # Room type mismatch
                course_obj = course_lookup.get(course_code)
                required_type = str(getattr(course_obj, 'required_room_type', '') or '').strip()
                room_info = rooms_lookup.get(room_name) or {}
                actual_type = str(room_info.get('room_type') or '').strip()
                if required_type and actual_type and required_type != actual_type:
                    violations['Hard_RoomTypeMismatch'].append(
                        f"Group {group_id}, Course {course_code}: required {required_type}, got {actual_type} in {room_name} at {days_map[d_idx]} {hours_map[h_idx]}"
                    )

                # Lecturer availability
                if lecturer_norm:
                    faculty = faculty_lookup.get(lecturer_norm)
                    if faculty is None:
                        faculty = faculty_lookup.get(lecturer_s.casefold())
                    if faculty is not None:
                        day_abbr = days_map[d_idx]
                        if not _is_available_day(getattr(faculty, 'avail_days', None), day_abbr):
                            violations['Hard_LecturerAvailability'].append(
                                f"{lecturer_s}: not available on {day_abbr} (avail_days={getattr(faculty,'avail_days',None)}, avail_times={getattr(faculty,'avail_times',None)})"
                            )
                        elif not _is_available_time(getattr(faculty, 'avail_times', None), start_minutes):
                            violations['Hard_LecturerAvailability'].append(
                                f"{lecturer_s}: not available at {row[0]} on {day_abbr} (avail_days={getattr(faculty,'avail_days',None)}, avail_times={getattr(faculty,'avail_times',None)})"
                            )

                # CHECK 1: Wrong Building (TYD in SST)
                # If not SST group, check if room is in SST building
                if not is_sst:
                    room_info = rooms_lookup.get(room_name)
                    if room_info and room_info.get('building') == 'SST':
                        violations['Hard_WrongBuilding'].append(
                            f"Group {group_name} ({group_id}) in {room_name} (SST) at {days_map[d_idx]} {hours_map[h_idx]}"
                        )

    # Lecturer clashes & same-student-group clashes
    for (d_idx, h_idx), event_list in global_schedule.items():
        by_lect = defaultdict(list)
        by_group = defaultdict(list)
        for e in event_list:
            lect = str(e.get('lecturer') or '').strip()
            if lect:
                by_lect[lect.casefold()].append(e)
            gid = str(e.get('group_id') or '').strip()
            if gid:
                by_group[gid].append(e)

        for lect_norm, items in by_lect.items():
            if len(items) > 1:
                lect_name = items[0].get('lecturer')
                details = "; ".join([f"{it.get('group_id')}:{it.get('course')}@{it.get('room')}" for it in items[:4]])
                if len(items) > 4:
                    details += f"; ...(+{len(items)-4})"
                violations['Hard_LecturerClash'].append(
                    f"{lect_name} double-booked at {days_map[d_idx]} {hours_map[h_idx]}: {details}"
                )

        for gid, items in by_group.items():
            if len(items) > 1:
                details = "; ".join([f"{it.get('course')}@{it.get('room')}" for it in items[:4]])
                if len(items) > 4:
                    details += f"; ...(+{len(items)-4})"
                violations['Hard_StudentGroupClash'].append(
                    f"{gid} has multiple events at {days_map[d_idx]} {hours_map[h_idx]}: {details}"
                )

    # 3. Post-Processing Checks

    # CHECK 2: Student Clashes (Already handled by strict matrix structure, implying 1 cell per slot per group, 
    # but we should check if a group somehow appears twice in global schedule? 
    # The JSON structure groups by student_group, so a group can't have 2 cells for same slot unless the JSON itself is malformed.
    # We trust the structure implies 0 clashes for *Same Group*, but verify if multiple entries for same slot? No, it's a grid.)
    
    # CHECK 3: Consecutive Slots
    for group_id, courses in group_course_schedule.items():
        for course_code, events in courses.items():
            credits = course_credits.get(course_code, 0)
            
            # 2-credit courses: Must be consecutive
            if credits == 2:
                # Should have exactly 2 slots (or more if split? usually 2)
                # Sort by day, then hour
                events.sort()
                
                if len(events) == 2:
                    d1, h1, _ = events[0]
                    d2, h2, _ = events[1]
                    
                    is_consecutive = (d1 == d2) and (h2 - h1 == 1)
                    if not is_consecutive:
                        violations['Hard_ConsecutiveSlots'].append(
                            f"Group {group_id}, Course {course_code} (2 cr): Slots {d1}/{h1} and {d2}/{h2} are not consecutive."
                        )

            # 3-credit courses: Must have at least one 2-hour block
            if credits == 3:
                events.sort()
                if len(events) >= 3:
                    # Check for any consecutive pair
                    has_block = False
                    for i in range(len(events)-1):
                        d1, h1, _ = events[i]
                        d2, h2, _ = events[i+1]
                        if d1 == d2 and h2 - h1 == 1:
                            has_block = True
                            break
                    if not has_block:
                         violations['Hard_ConsecutiveSlots'].append(
                            f"Group {group_id}, Course {course_code} (3 cr): No consecutive 2-hr block found."
                        )

    # CHECK 4: Same Course Multiple Rooms (Same Day)
    # Check global schedule: For a specific course+group, are they in different rooms on the same day?
    # Actually, the events are stored in `group_course_schedule`.
    for group_id, courses in group_course_schedule.items():
        for course_code, events in courses.items():
            # events is list of (d, h, room)
            rooms_per_day = defaultdict(set)
            for d, h, r in events:
                if r != "Unknown":
                    rooms_per_day[d].add(r)
            
            for d, rooms in rooms_per_day.items():
                if len(rooms) > 1:
                    violations['Hard_SameCourseMultipleRooms'].append(
                        f"Group {group_id}, Course {course_code} on {days_map[d]}: Multiple rooms {rooms}"
                    )

    # CHECK 5: Capacity
    # We already iterated cells. But simpler to check capacity via global overlap.
    # For every slot (d, h), check all groups in a specific room.
    for (d_idx, h_idx), event_list in global_schedule.items():
        room_occupancy = defaultdict(list)
        for event in event_list:
            room_occupancy[event['room']].append(event['group'])
        
        for room_name, groups in room_occupancy.items():
            if room_name == "Unknown": continue
            
            room_info = rooms_lookup.get(room_name)
            if not room_info: continue
            
            capacity = room_info.get('capacity', 0)
            
            # Sum up students? Or just check if ANY group > capacity?
            # The constraint usually is "Student Group size > Room Capacity"
            # And also "Multiple groups in same room" (unless merged?)
            
            for g_name in groups:
                # Need student group size. Since we don't have it loaded easily in step 2 (JSON only has names),
                # we rely on input_data loaded in step 1.
                # Find group obj
                g_obj = next((g for g in inp.student_groups if g.name == g_name), None)
                if g_obj:
                    if g_obj.no_students > capacity:
                         violations['Hard_Capacity'].append(
                            f"Room {room_name} (Cap {capacity}) overload by {g_name} (Size {g_obj.no_students})"
                        )

    # REPORT
    print("\n=== INDEPENDENT VERIFICATION REPORT ===")
    total_violations = 0
    for v_type, v_list in violations.items():
        count = len(v_list)
        total_violations += count
        print(f"[{v_type}]: {count} violations")
        if count > 0:
            for v in v_list[:5]: # Show first 5
                print(f"  - {v}")
            if count > 5: print(f"  ... (+{count-5} more)")
    
    if total_violations == 0:
        print("\nSUCCESS: No hard constraints violations found in fresh_timetable_data.json!")
    else:
        print(f"\nFAILED: Found {total_violations} hard constraint violations.")

if __name__ == "__main__":
    verify_timetable_constraints()