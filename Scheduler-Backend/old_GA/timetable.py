import uuid
from entitities.Class import Class
from old_GA.Gene import Gene
from entitities.room import Room
from entitities.time_slot import TimeSlot
from input_data import input_data

# rooms = [] #alist of rooms, when a room is assigned to a class, it is removed from the list
# def assign_class_to_room(class_obj: Class, room: Room, time_slot: TimeSlot) -> Gene:
#     gene_id = uuid.uuid4()
#     gene = Gene(gene_id, class.id, room.Id, time_slot.id)

class Timetable:
    def __init__(self):
        self.days = input_data.days
        self.hours = input_data.hours
        self.no_student_groups = len(input_data.student_groups)
        total_periods = self.days * self.hours * self.no_student_groups
        self.periods_list = [None] * total_periods
        self.cnt = 0

        for student_group in input_data.student_groups:
            periods = 0
            # Assign classes for each course
            for i in range(student_group.no_courses):
                if i < len(student_group.teacherIDS) and i < len(student_group.courseIDs):
                    if self.cnt < total_periods:
                        self.periods_list[self.cnt] = Class(student_group, student_group.teacherIDS[i], student_group.courseIDs[i])
                        self.cnt += 1
                        periods += 1
                    else:
                        print(f"Warning: periods_list full while assigning courses for {student_group.name}")
                else:
                    print(f"Warning: Index {i} out of range for student_group {student_group.name}")
            # Pad remaining periods with None
            while periods < self.days * self.hours and self.cnt < total_periods:
                self.periods_list[self.cnt] = None
                self.cnt += 1
                periods += 1


Timetable = Timetable()
# print(Timetable)
classes = Timetable.periods_list
# print(classes)

# Example: Display assigned rooms for each class (no hardcoded indices)
# for idx, class_obj in enumerate(classes):
#     if class_obj is not None:
#         # Assign a room from input_data.rooms (e.g., round-robin or based on your logic)
#         room_idx = idx % len(input_data.rooms)
#         room_obj = input_data.rooms[room_idx]
#         room_display = getattr(room_obj, "name", getattr(room_obj, "Id", str(room_idx)))
#         print(f"Class: {class_obj.course_id}, Room: {room_display}")


