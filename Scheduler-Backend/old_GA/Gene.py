# class Gene:
#     def __init__(self, gene_id, class_id, room_id, timeslot_id):
#         self.gene_id = gene_id
#         self.class_id = class_id
#         self.room_id = room_id
#         self.timeslot_id = timeslot_id

"""
A gene represents a single decision point in the timetable. 
The logic here is assigning a class_id to a time_slot ID and room_ID

assign class_id to room_id
then reandomly/sequentially assign that to a timeslot
"""

import random
import copy
from input_data import input_data

class Gene:

    """
    A gene is a list of 40 random numbers that correspond to the indexes
    of a student group's timetable slot in the timetable.slot array.
    """

    def __init__(self, i):
        self.days = input_data.days
        self.hours = input_data.hours
        self.rooms = input_data.rooms

        self.slotno = [None] * (self.days * self.hours)
        self.room_assignment = [None] * (self.days * self.hours)
        
        flag = [False] * (self.days * self.hours)
        
        for j in range(self.days * self.hours):
            # Assign a random timeslot
            rnd = random.randint(0, self.days * self.hours - 1)
            while flag[rnd]:
                rnd = random.randint(0, self.days * self.hours - 1)
            flag[rnd] = True
            self.slotno[j] = i * self.days * self.hours + rnd

            # Randomly assign a room from the available rooms
            self.room_assignment[j] = random.choice(self.rooms)

            # If you want to print the subject or "break"
            # slot = TimeTable.returnSlots()
            # if slot[self.slotno[j]] is not None:
            #     print(slot[self.slotno[j]].subject, end=" ")
            # else:
            #     print("break", end=" ")


    def deep_clone(self):
        return copy.deepcopy(self)

gene = Gene(2)
# print(gene.slotno)
# print(gene.room_assignment)
