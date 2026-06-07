
import uuid
from entitities.Class import Class
from Gene import Gene
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
        self.hourcount = 1
        self.subject_no = 0
        self.cnt = 0

        # array of all periods possible
        self.periods_list = [(None)]*self.days*self.hours*self.no_student_groups

        # populating a slot with a CLASS for each course of each student group 
        for student_group in input_data.student_groups:
            periods = 0
            for i in range(student_group.no_courses):
                self.hourcount = 1 
                while self.hourcount <= student_group.hours_required[i]:
                    tid = student_group.teacherIDS[i]
                    if isinstance(tid, list) and len(tid) > 0:
                        tid = tid[0]
                    self.periods_list[self.cnt] = Class(student_group, tid, student_group.courseIDs[i])
                    self.hourcount += 1
                    self.cnt += 1
                    periods += 1

            # if the number of periods occupied with classes is still less than the total number of periods available for a student group
            while periods < self.days*self.hours:
                periods += 1
                self.cnt += 1  


Timetable = Timetable()
# print(Timetable)
classes = Timetable.periods_list
# print(classes)
                
                
