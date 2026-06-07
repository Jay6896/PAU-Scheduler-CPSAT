"""
API-compatible utility functions that work with dynamic InputData instances
instead of static imports.
"""
from typing import List, Dict, Any, Optional
from input_data_api import InputData


class Utility:
    """Utility functions for working with InputData instances"""

    @staticmethod
    def print_input_data(input_data: InputData):
        """Print input data summary - now takes InputData instance as parameter"""
        print(f"Nostgrp={input_data.nostudentgroup} Noteachers={len(input_data.faculties)} "
              f"daysperweek={input_data.days} hoursperday={input_data.hours}")
        
        for i in range(input_data.nostudentgroup):
            student_group = input_data.student_groups[i]
            print(f"{student_group.id} {student_group.name}")
            
            # Handle courseIDs and hours_required as lists
            course_ids = student_group.courseIDs if isinstance(student_group.courseIDs, list) else [student_group.courseIDs]
            hours_req = student_group.hours_required if isinstance(student_group.hours_required, list) else [student_group.hours_required]
            teacher_ids = student_group.teacherIDS if isinstance(student_group.teacherIDS, list) else [student_group.teacherIDS]
            
            for j in range(len(course_ids)):
                hours = hours_req[j] if j < len(hours_req) else 0
                teacher = teacher_ids[j] if j < len(teacher_ids) else "Unknown"
                print(f"{course_ids[j]} {hours} hrs {teacher}")
            print("")

        for i in range(len(input_data.faculties)):
            teacher = input_data.faculties[i]
            course_id = teacher.courseID if hasattr(teacher, 'courseID') else "Unknown"
            print(f"{teacher.faculty_id} {teacher.name} {course_id}")

    @staticmethod
    def print_slots(periods_list: List, input_data: InputData):
        """Print time slots - now takes periods list and InputData as parameters"""
        days = input_data.days
        hours = input_data.hours
        nostgrp = input_data.nostudentgroup
        
        print("----Slots----")
        for i in range(min(len(periods_list), days * hours * nostgrp)):
            slot = periods_list[i]
            if slot is not None:
                student_group_name = getattr(slot.student_group, 'name', 'Unknown') if hasattr(slot, 'student_group') else 'Unknown'
                course_id = getattr(slot, 'course_id', 'Unknown')
                faculty_id = getattr(slot, 'faculty_id', 'Unknown')
                print(f"{i}- {student_group_name} {course_id} {faculty_id}")
            
            if (i + 1) % (hours * days) == 0:
                print("******************************")


def print_timetable(individual, student_group, events_map: Dict, days: int, hours_per_day: int, day_start_time: float = 8.5):
    """
    Print timetable for a specific student group
    
    Args:
        individual: The solution chromosome/individual
        student_group: The student group to print timetable for
        events_map: Dictionary mapping event IDs to event objects
        days: Number of days per week
        hours_per_day: Number of hours per day
        day_start_time: Starting hour (24-hour format)
    """
    # Create a blank timetable grid for the student group
    timetable = [['' for _ in range(days)] for _ in range(hours_per_day)]
    
    # First, fill break time slots
    break_hour = 4  # 12:30 is the 5th hour (index 4) starting from 8:30
    if break_hour < hours_per_day:
        for day in range(days):
            timetable[break_hour][day] = "BREAK"

    # Handle different individual formats
    try:
        if hasattr(individual, '__len__') and len(individual) > 0:
            # Loop through the individual's chromosome to populate the timetable
            for room_idx, room_slots in enumerate(individual):
                if room_slots is None:
                    continue
                    
                # Handle different room_slots formats
                if hasattr(room_slots, '__len__'):
                    for timeslot_idx, event in enumerate(room_slots):
                        if event is None:
                            continue
                            
                        class_event = events_map.get(event) if events_map else None
                        
                        # Check if this event belongs to the current student group
                        if class_event is not None:
                            event_group_id = getattr(class_event.student_group, 'id', None) if hasattr(class_event, 'student_group') else None
                            student_group_id = getattr(student_group, 'id', None)
                            
                            if event_group_id == student_group_id:
                                day = timeslot_idx // hours_per_day
                                hour = timeslot_idx % hours_per_day
                                
                                if day < days and hour != break_hour and hour < hours_per_day:  # Don't overwrite break slots
                                    course_id = getattr(class_event, 'course_id', 'Unknown')
                                    faculty_id = getattr(class_event, 'faculty_id', 'Unknown')
                                    timetable[hour][day] = f"Course: {course_id}, Lecturer: {faculty_id}, Room: {room_idx}"
    except Exception as e:
        print(f"Warning: Error processing individual for timetable: {e}")
    
    # Print the timetable for the student group
    student_group_name = getattr(student_group, 'name', 'Unknown Group')
    print(f"Timetable for Student Group: {student_group_name}")
    print(" " * 15 + " | ".join([f"Day {d+1}" for d in range(days)]))
    print("-" * (20 + days * 15))
    
    for hour in range(hours_per_day):
        time_label = f"{day_start_time + hour}:00"
        row = [timetable[hour][day] if timetable[hour][day] else "Free" for day in range(days)]
        print(f"{time_label:<15} | " + " | ".join(row))
    print("\n")


def print_all_timetables(individual, input_data: InputData, events_map: Dict, days: int, hours_per_day: int, day_start_time: int = 9):
    """
    Print timetables for all student groups
    
    Args:
        individual: The solution chromosome/individual
        input_data: InputData instance containing student groups
        events_map: Dictionary mapping event IDs to event objects
        days: Number of days per week
        hours_per_day: Number of hours per day
        day_start_time: Starting hour (24-hour format)
    """
    # Get all student groups from the InputData instance
    student_groups = input_data.student_groups
    
    # Print timetable for each student group
    for student_group in student_groups:
        print_timetable(individual, student_group, events_map, days, hours_per_day, day_start_time)


def generate_timetable_grid(individual, student_group, events_map: Dict, days: int, hours_per_day: int, day_start_time: int = 9) -> List[List[str]]:
    """
    Generate timetable grid for a specific student group (returns data structure instead of printing)
    
    Returns:
        List of lists representing the timetable grid
    """
    # Create a blank timetable grid for the student group
    timetable = [['Free' for _ in range(days)] for _ in range(hours_per_day)]
    
    # First, fill break time slots
    break_hour = 4  # 13:00 is the 5th hour (index 4) starting from 9:00
    if break_hour < hours_per_day:
        for day in range(days):
            timetable[break_hour][day] = "BREAK"

    # Handle different individual formats
    try:
        if hasattr(individual, '__len__') and len(individual) > 0:
            # Loop through the individual's chromosome to populate the timetable
            for room_idx, room_slots in enumerate(individual):
                if room_slots is None:
                    continue
                    
                # Handle different room_slots formats
                if hasattr(room_slots, '__len__'):
                    for timeslot_idx, event in enumerate(room_slots):
                        if event is None:
                            continue
                            
                        class_event = events_map.get(event) if events_map else None
                        
                        # Check if this event belongs to the current student group
                        if class_event is not None:
                            event_group_id = getattr(class_event.student_group, 'id', None) if hasattr(class_event, 'student_group') else None
                            student_group_id = getattr(student_group, 'id', None)
                            
                            if event_group_id == student_group_id:
                                day = timeslot_idx // hours_per_day
                                hour = timeslot_idx % hours_per_day
                                
                                if day < days and hour != break_hour and hour < hours_per_day:  # Don't overwrite break slots
                                    course_id = getattr(class_event, 'course_id', 'Unknown')
                                    faculty_id = getattr(class_event, 'faculty_id', 'Unknown')
                                    timetable[hour][day] = f"Course: {course_id}, Lecturer: {faculty_id}, Room: {room_idx}"
    except Exception as e:
        print(f"Warning: Error generating timetable grid: {e}")
    
    return timetable


def get_timetable_summary(input_data: InputData) -> Dict[str, Any]:
    """
    Get a summary of the timetable data
    
    Returns:
        Dictionary with summary statistics
    """
    try:
        total_courses = len(input_data.courses)
        total_rooms = len(input_data.rooms)
        total_student_groups = len(input_data.student_groups)
        total_faculties = len(input_data.faculties)
        
        total_students = sum(getattr(sg, 'no_students', 0) for sg in input_data.student_groups)
        total_room_capacity = sum(getattr(r, 'capacity', 0) for r in input_data.rooms)
        
        # Calculate total required hours
        total_required_hours = 0
        for sg in input_data.student_groups:
            hours_req = getattr(sg, 'hours_required', [])
            if isinstance(hours_req, list):
                total_required_hours += sum(hours_req)
            else:
                total_required_hours += hours_req if hours_req else 0
        
        return {
            'total_courses': total_courses,
            'total_rooms': total_rooms,
            'total_student_groups': total_student_groups,
            'total_faculties': total_faculties,
            'total_students': total_students,
            'total_room_capacity': total_room_capacity,
            'total_required_hours': total_required_hours,
            'days_per_week': input_data.days,
            'hours_per_day': input_data.hours
        }
    except Exception as e:
        print(f"Warning: Error generating timetable summary: {e}")
        return {
            'error': str(e),
            'total_courses': 0,
            'total_rooms': 0,
            'total_student_groups': 0,
            'total_faculties': 0
        }