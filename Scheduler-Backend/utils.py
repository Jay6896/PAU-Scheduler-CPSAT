from input_data import input_data

class Utility:

    @staticmethod
    def print_input_data():
        print(f"Nostgrp={input_data.nostudentgroup} Noteachers={len(input_data.faculties)} "
              f"daysperweek={input_data.days} hoursperday={input_data.hours}")
        
        for i in range(input_data.nostudentgroup):
            student_group = input_data.student_groups[i]
            print(f"{student_group.id} {student_group.name}")
            
            for j in range(student_group.no_courses):
                print(f"{student_group.courseIDs[j]} {student_group.hours_required[j]} hrs {student_group.teacherIDS[j]}")
            print("")

        for i in range(len(input_data.faculties)):
            teacher = input_data.faculties[i]
            print(f"{teacher.faculty_id} {teacher.name} {teacher.courseID}")
    

def print_timetable(individual, student_group, events_map, days, hours_per_day, day_start_time=8.5):
    # Create a blank timetable grid for the student group
    timetable = [['' for _ in range(days)] for _ in range(hours_per_day)]
    
    # First, fill break time slots
    break_hour = 4  # 12:30 is the 5th hour (index 4) starting from 8:30
    if break_hour < hours_per_day:
        for day in range(days):
            timetable[break_hour][day] = "BREAK"

    # Loop through the individual's chromosome to populate the timetable
    for room_idx, room_slots in enumerate(individual):
        for timeslot_idx, event in enumerate(room_slots):
            class_event = events_map.get(event)
            if class_event is not None and class_event.student_group.id == student_group.id:
                
                day = timeslot_idx // hours_per_day
                hour = timeslot_idx % hours_per_day
                if day < days and hour != break_hour:  # Don't overwrite break slots
                    timetable[hour][day] = f"Course: {class_event.course_id}, Lecturer: {class_event.faculty_id}, Room: {room_idx}"
    
    # Print the timetable for the student group
    print(f"Timetable for Student Group: {student_group.name}")
    print(" " * 15 + " | ".join([f"Day {d+1}" for d in range(days)]))
    print("-" * (20 + days * 15))
    
    for hour in range(hours_per_day):
        t = day_start_time + hour
        time_label = f"{int(t)}:{int((t%1)*60):02d}"
        row = [timetable[hour][day] if timetable[hour][day] else "Free" for day in range(days)]
        print(f"{time_label:<15} | " + " | ".join(row))
    print("\n")

def print_all_timetables(individual, events_map, days, hours_per_day, day_start_time=8.5):
    # Find all unique student groups in the individual
    student_groups = input_data.student_groups
    
    # Print timetable for each student group
    for student_group in student_groups:
        print_timetable(individual, student_group, events_map, days, hours_per_day, day_start_time)