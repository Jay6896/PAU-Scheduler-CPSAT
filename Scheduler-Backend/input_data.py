from typing import List
from entitities.course import Course
from entitities.faculty import Faculty
from entitities.room import Room
from entitities.student_group import StudentGroup
from entitities.Class import Class
import json
from enums import Size, RoomType
from entitities.time_slot import TimeSlot
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"


class inputData():
    def __init__(self) -> None:
        self.courses = []
        self.rooms = []
        self.student_groups = []    
        self.faculties = []
        self.constraints = []
        self.classes = []
        self.nostudentgroup = len(self.student_groups)
        self.hours = 10
        self.days = 5
        self._course_map = None
        self._room_map = None
        self._student_group_map = None
        self._faculty_map = None

    def addCourse(self, name: str, code: str, credits: int, student_groupsID: List[str], facultyId, required_room_type: str ):
        self.courses.append(Course(name, code, credits, student_groupsID, facultyId, required_room_type))
        self._course_map = None

    def addRoom(self, Id: str, name:str, capacity:int, room_type:str, building:str):
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
        avail_days: list = [],
        avail_times: list = [],
        available_hours: int = 4,
        available_consecutive_hours: int = 3,
    ):
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
        time_slots = []
        for day in range(no_days_per_week):
            for hour in range(no_hours_per_day):
                time_slots.append(TimeSlot(id=len(time_slots), day=day, start_time=hour, available=True))
        # print(time_slots, len(time_slots))
        return time_slots
    
    
    def assign_class_to_course_and_faculty(self, student_group: StudentGroup):
        for course_x in student_group.courseIDs:
            for course in input_data.courses:
                if course_x == course.code:
                    facultyId = course.facultyId
                    self.classes.append(Class(student_group, facultyId, course.code))

    # def __repr__(self):
    #     return f"inputData(courses={self.courses}, rooms={self.rooms}, student_groups={self.student_groups}, faculties={self.faculties}, constraints={self.constraints}, classes={self.classes})"
        
    

    # def getConstraints(self, constraint_type: str) -> List[Constraint]:
    #     constraints = []
    #     for constraint in self.constraints:
    #         if constraint.constraint_type == constraint_type:
    #             constraints.append(constraint)
    #     return constraints
    
    # def getConstraintsByCourse(self, course_code: str) -> List[Constraint]:
    #     constraints = []
    #     for constraint in self.constraints:
    #         if constraint.course_code == course_code:
    #             constraints.append(constraint)
    #     return constraints
    

input_data = inputData()

# Read course data from JSON file
with open( DATA_DIR / 'course-data.json', encoding='utf-8') as file:
    course_data = json.load(file)
    for course in course_data:
        input_data.addCourse(course['name'], course['code'], course['credits'], course['student_groupsID'], course['facultyId'], course['required_room_type'])

# Read room data from JSON file
with open( DATA_DIR / 'rooms-data.json', encoding='utf-8') as file:
    room_data = json.load(file)
    for room in room_data:
        input_data.addRoom(room['Id'], room['name'], room['capacity'], room['room_type'], room['building'])

# Read student group data from JSON file
with open( DATA_DIR / 'studentgroup-data.json', encoding='utf-8') as file:
    student_group_data = json.load(file)
    for student_group in student_group_data:
        input_data.addStudentGroup(
            student_group['id'],
            student_group['name'],
            student_group['no_students'],
            student_group['courseIDs'],
            student_group['teacherIDS'],
            student_group['hours_required'],
            building=student_group.get('building', ''),
        )

# Read faculty data from JSON file
with open( DATA_DIR / 'faculty-data.json', encoding='utf-8') as file:
    faculty_data = json.load(file)
    for faculty in faculty_data:
        input_data.addFaculty(
            faculty['id'],
            faculty['name'],
            faculty['department'],
            faculty['courseID'],
            faculty.get('avail_days', []),
            faculty.get('avail_times', []),
            available_hours=faculty.get('available_hours', 4),
            available_consecutive_hours=faculty.get('available_consecutive_hours', 3),
        )

# timeslot
# [print(time_slot.day, time_slot.start_time) for time_slot in input_data.create_time_slots(7, 5, 9)]

for student_group in input_data.student_groups:
    input_data.assign_class_to_course_and_faculty(student_group)

input_data.nostudentgroup = len(input_data.student_groups)

# print(repr(input_data))
# print("\n")

# for course in input_data.courses:
#     print(Course.__repr__(course))

# print("\n")

# for room in input_data.rooms:
#     print(Room.__repr__(room))

# print("\n")

# for student_group in input_data.student_groups:
#     print(StudentGroup.__repr__(student_group))

# print("\n")

# for faculty in input_data.faculties:
#     print(Faculty.__repr__(faculty))

# print("\n")

# for class_obj in input_data.classes:
#     print(Class.__repr__(class_obj))

# print("\n")

# for time_slot in input_data.create_time_slots(7, 5, 9):
#     print(TimeSlot.__repr__(time_slot))

        