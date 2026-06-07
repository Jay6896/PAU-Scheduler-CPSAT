# input_data_api.py
"""
API-compatible version of input_data that can be initialized from JSON data
instead of static files.
"""

from typing import List, Dict, Any
from entitities.course import Course
from entitities.faculty import Faculty
from entitities.room import Room
from entitities.student_group import StudentGroup
from entitities.Class import Class
from entitities.time_slot import TimeSlot


class InputData:
    def __init__(self) -> None:
        self.courses = []
        self.rooms = []
        self.student_groups = []    
        self.faculties = []
        self.classes = []
        self.nostudentgroup = 0
        # Keep API defaults aligned with the non-API scheduler (see input_data.py).
        # Can be overridden via initialize_input_data_from_json(...).
        self.hours = 10
        self.days = 5
        self._course_map = None
        self._room_map = None
        self._student_group_map = None
        self._faculty_map = None

    def addCourse(self, name: str, code: str, credits: int, student_groupsID: List[str], facultyId, required_room_type: str):
        self.courses.append(Course(name, code, credits, student_groupsID, facultyId, required_room_type))
        self._course_map = None

    def addRoom(self, Id: str, name: str, capacity: int, room_type: str, building: str):
        self.rooms.append(Room(Id, name, capacity, room_type, building))
        self._room_map = None

    def addStudentGroup(self, id: str, name: str, no_students: int, courseIDs: str, teacherIDS: str, hours_required: List[int], building: str = None):
        normalized_teachers = []
        for t in (teacherIDS or []):
            try:
                ts = str(t).strip()
                if '@' in ts:
                    ts = ts.lower()
                normalized_teachers.append(ts)
            except Exception:
                normalized_teachers.append(t)
        self.student_groups.append(StudentGroup(id, name, no_students, courseIDs, normalized_teachers, hours_required, building=building))
        self._student_group_map = None

    def addFaculty(
        self,
        id: str,
        name: str,
        department: str,
        courseID: str,
        avail_days=None,
        avail_times=None,
        available_hours: int = 4,
        available_consecutive_hours: int = 3,
    ):
        # If not provided, default to ALL (matches the static JSON dataset and core scheduler).
        if not avail_days:
            avail_days = ["ALL"]
        if not avail_times:
            avail_times = ["ALL"]
        normalized_id = str(id).strip()
        if '@' in normalized_id:
            normalized_id = normalized_id.lower()
        self.faculties.append(
            Faculty(
                normalized_id,
                name,
                department,
                courseID,
                avail_days,
                avail_times,
                available_hours=available_hours,
                available_consecutive_hours=available_consecutive_hours,
            )
        )
        self._faculty_map = None

    def getCourse(self, code: str) -> Course:
        if not hasattr(self, '_course_map') or self._course_map is None:
            self._course_map = {course.code: course for course in self.courses}
        return self._course_map.get(code)
    
    def getRoom(self, Id: str) -> Room:
        if not hasattr(self, '_room_map') or self._room_map is None:
            self._room_map = {room.Id: room for room in self.rooms}
        return self._room_map.get(Id)
    
    def getStudentGroup(self, id: str) -> StudentGroup:
        if not hasattr(self, '_student_group_map') or self._student_group_map is None:
            self._student_group_map = {sg.id: sg for sg in self.student_groups}
        return self._student_group_map.get(id)
    
    def getFaculty(self, id: str) -> Faculty:
        if not hasattr(self, '_faculty_map') or self._faculty_map is None:
            self._faculty_map = {}
            for faculty in self.faculties:
                fid = getattr(faculty, 'faculty_id', None)
                if fid is not None:
                    fid_s = str(fid).strip()
                    self._faculty_map[fid_s.lower() if '@' in fid_s else fid_s] = faculty
                    
        target = str(id).strip()
        target_norm = target.lower() if '@' in target else target
        return self._faculty_map.get(target_norm)
    
    def create_time_slots(self, no_hours_per_day, no_days_per_week, day_start_time):
        """
        Create TimeSlot entries.
        Note: start_time is stored as an integer hour index within the day (0-based),
        e.g., 0 => 9:00, 1 => 10:00 when day_start_time=9.
        This matches constraints.py which uses arithmetic like `timeslot.start_time + 9`.
        """
        time_slots = []
        for day in range(no_days_per_week):
            for hour in range(no_hours_per_day):
                # Store 0-based hour index for numeric arithmetic in constraints
                start_time_index = hour
                time_slots.append(TimeSlot(
                    id=len(time_slots), 
                    day=day, 
                    start_time=start_time_index, 
                    available=True
                ))
        return time_slots
    
    def assign_class_to_course_and_faculty(self, student_group: StudentGroup):
        for course_x in student_group.courseIDs:
            for course in self.courses:
                if course_x == course.code:
                    facultyId = course.facultyId
                    self.classes.append(Class(student_group.id, facultyId, course.code))

    def get_data_summary(self) -> Dict[str, Any]:
        """Return summary statistics for API responses"""
        return {
            'courses': len(self.courses),
            'rooms': len(self.rooms),
            'student_groups': len(self.student_groups),
            'faculties': len(self.faculties),
            'total_student_capacity': sum(sg.no_students for sg in self.student_groups),
            'total_room_capacity': sum(r.capacity for r in self.rooms)
        }


def initialize_input_data_from_json(json_data: Dict[str, Any]) -> InputData:
    """
    Initialize InputData instance from transformer JSON output.
    This replaces the static file loading approach.
    """
    input_data = InputData()

    # If caller provided an empty merged JSON (no courses/rooms/student groups),
    # attempt to load per-entity JSON files from the repository `data/` folder
    # so the API and CP-SAT can run against the original transformer outputs.
    try:
        has_courses = bool(json_data.get('courses'))
        has_rooms = bool(json_data.get('rooms'))
        has_studentgroups = bool(json_data.get('studentgroups') or json_data.get('student_groups'))
    except Exception:
        has_courses = has_rooms = has_studentgroups = False

    if not (has_courses and has_rooms and has_studentgroups):
        # Attempt to load from data/*.json in the project directory
        try:
            from pathlib import Path
            base = Path(__file__).resolve().parent
            data_dir = base / 'data'
            if data_dir.exists():
                # Helper to load JSON array files if present and not already present
                def _load_if_missing(key, filename):
                    if json_data.get(key):
                        return
                    p = data_dir / filename
                    if p.exists():
                        try:
                            import json as _json
                            json_data[key] = _json.loads(p.read_text(encoding='utf-8'))
                        except Exception:
                            pass

                _load_if_missing('courses', 'course-data.json')
                _load_if_missing('rooms', 'rooms-data.json')
                # Support both keys used across the codebase
                if not json_data.get('studentgroups') and not json_data.get('student_groups'):
                    p = data_dir / 'studentgroup-data.json'
                    if p.exists():
                        try:
                            import json as _json
                            json_data['studentgroups'] = _json.loads(p.read_text(encoding='utf-8'))
                        except Exception:
                            pass
                _load_if_missing('faculties', 'faculty-data.json')
        except Exception:
            pass

    # Allow the caller to override calendar configuration.
    # If not present, we keep the API defaults (aligned with the core scheduler).
    try:
        if 'hours' in json_data and json_data['hours'] is not None:
            input_data.hours = int(json_data['hours'])
        if 'days' in json_data and json_data['days'] is not None:
            input_data.days = int(json_data['days'])
    except (TypeError, ValueError):
        # Fall back to defaults if invalid values were provided.
        pass
    
    # Load courses
    for course_data in json_data.get('courses', []):
        input_data.addCourse(
            name=course_data['name'],
            code=course_data['code'],
            credits=course_data['credits'],
            student_groupsID=course_data['student_groupsID'],
            facultyId=course_data.get('facultyId'),
            required_room_type=course_data['required_room_type']
        )
    
    # Load rooms
    for room_data in json_data.get('rooms', []):
        input_data.addRoom(
            Id=room_data['Id'],
            name=room_data['name'],
            capacity=room_data['capacity'],
            room_type=room_data['room_type'],
            building=room_data.get('building', '')
        )
    
    # Load student groups (support both 'studentgroups' and 'student_groups' keys)
    student_groups_data = json_data.get('studentgroups', json_data.get('student_groups', []))
    for sg_data in student_groups_data:
        input_data.addStudentGroup(
            id=sg_data['id'],
            name=sg_data['name'],
            building=sg_data.get('building', ''),
            no_students=sg_data['no_students'],
            courseIDs=sg_data['courseIDs'],
            teacherIDS=sg_data['teacherIDS'],
            hours_required=sg_data['hours_required']
        )
    
    def _parse_int_field(value, default: int) -> int:
        try:
            if value is None:
                return int(default)
            if isinstance(value, str):
                v = value.strip()
                if v == "":
                    return int(default)
                return int(float(v))
            return int(value)
        except Exception:
            return int(default)

    def _get_faculty_limit(faculty_data: Dict[str, Any], *keys: str, default: int) -> int:
        for key in keys:
            if key in faculty_data and faculty_data.get(key) is not None:
                return _parse_int_field(faculty_data.get(key), default)
        return int(default)

    # Load faculties
    for faculty_data in json_data.get('faculties', []):
        available_hours = _get_faculty_limit(
            faculty_data,
            'available_hours',
            'availableHours',
            'available hours',
            'available_hours_per_day',
            'available hours per day',
            default=4,
        )
        available_consecutive_hours = _get_faculty_limit(
            faculty_data,
            'available_consecutive_hours',
            'availableConsecutiveHours',
            'available consecutive hours',
            'available_consecutive_hours_per_day',
            'available consecutive hours per day',
            default=3,
        )
        input_data.addFaculty(
            id=faculty_data['id'],
            name=faculty_data['name'],
            department=faculty_data.get('department', ''),
            courseID=faculty_data.get('courseID', []),
            avail_days=faculty_data.get('avail_days', []),
            avail_times=faculty_data.get('avail_times', []),
            available_hours=available_hours,
            available_consecutive_hours=available_consecutive_hours,
        )
    
    # Create classes for each student group
    for student_group in input_data.student_groups:
        input_data.assign_class_to_course_and_faculty(student_group)
    
    input_data.nostudentgroup = len(input_data.student_groups)
    
    return input_data