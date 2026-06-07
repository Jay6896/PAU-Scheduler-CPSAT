# from entitities.course import Course
from entitities.student_group import StudentGroup
import uuid

class Class:

    def __init__(self, student_group: StudentGroup = None, faculty_id: str = None, course_id: str = None):
        self.class_id = uuid.uuid4
        self.student_group = student_group
        self.faculty_id = faculty_id
        self.course_id = course_id

    def __repr__(self):
        return f"Class(student_group_id={self.student_group.id}, faculty_id={self.faculty_id}, course_code={self.course_id})"
       

"""
Class is an assignment of a student group to a course (in it's course list) and a faculty (with that course in it's list of courses taught)

data can all be gotten from moodle
"""     
    