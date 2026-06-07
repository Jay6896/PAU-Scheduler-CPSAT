from typing import List, Union
from enums import RoomType

class Course:
    def __init__(self, name: str, code: str, credits: int, student_groupsID: List[str], facultyId: Union[str, List[str]], required_room_type: str):
        self.code = code
        self.name = name
        self.credits = credits
        self.student_groupsID = student_groupsID
        
        # Handle both string and array formats for backward compatibility
        if isinstance(facultyId, list):
            self.facultyId = facultyId
        else:
            self.facultyId = [facultyId] if facultyId else []
            
        self.required_room_type = required_room_type
    
    @property
    def primary_faculty_id(self):
        """Returns the primary (first) faculty ID for display and assignment purposes"""
        return self.facultyId[0] if self.facultyId else None
    
    @property
    def all_faculty_ids(self):
        """Returns all faculty IDs for this course"""
        return self.facultyId

    def __repr__(self):
        return f"Course(name={self.name}, code={self.code}, credits={self.credits}, student_groupsID={self.student_groupsID})"
