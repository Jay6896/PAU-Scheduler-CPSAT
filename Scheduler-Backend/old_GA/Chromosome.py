from old_GA.Gene import Gene
from entitities.Class import Class
from input_data import input_data
import copy
import random

from old_GA.timetable import Timetable


"""
A chromosome represents a complete timetable for all student groups.
It's a collection of genes, one for each (timeslot-student-room) combination.
The size of the chromosome will be dependent on the number of (student groups * time slots) and rooms.


In this code, a chromosome is a list of genes, one for each student group 
"""

class Chromosome:
    # Static variables equivalent to static fields in Java
    # crossoverrate = None
    # mutationrate = None
    # hours = None
    # days = None
    # nostgrp = None

    def __init__(self):
        # Initialize the static variables from input_data
        self.crossoverrate = input_data.cross_over_rate
        self.mutationrate = input_data.mutation_rate
        self.hours = input_data.hours
        self.days = input_data.days
        self.nostgrp = len(input_data.student_groups)
        self.rooms = input_data.rooms
        self.courses = input_data.courses

        self.fitness = 0
        self.point = 0
        self.gene = [None] * self.nostgrp

        # gene is an array of Genes for each student group, where you can access the slot for each group
        for i in range(self.nostgrp):
            self.gene[i] = Gene(i)

        # Calculate fitness
        self.fitness = self.get_fitness()

    def deep_clone(self):
        return copy.deepcopy(self)

    def get_fitness(self):  # the smaller the fitness, the better the solution
        self.point = 0


        # Hard constraint 1: No faculty overlap - no one teacher should teach two clases (within and across std grps/rows) at the same time (same column)
        # looping through slots across student groups.
        """
        the slot numbers for all the slots of a student group correspond to a range of indices in timetable.slots that belong to that student group
        """
        for i in range(self.hours * self.days):
            teacher_schedule = {}  # Dictionary to map teachers to the rooms they are assigned at this timeslot
            roomlist = []

            # checking the same slot across student groups
            for j in range(self.nostgrp):
                slot = None

                if Timetable.periods_list[self.gene[j].slotno[i]] is not None:
                    slot = Timetable.periods_list[self.gene[j].slotno[i]]
                    assigned_room = self.gene[j].room_assignment[i]  # Get the room assigned for this slot
                

                if slot is not None:
                    faculty_id = slot.faculty_id  # Get the faculty assigned to this slot

                    # Check for faculty clash
                    if faculty_id in teacher_schedule:
                        self.point += 1
                    else:
                        teacher_schedule[faculty_id] = assigned_room  # Assign the faculty to the room
                
                    # Check for room clash
                    if assigned_room in roomlist:
                        self.point += 1  # Room clash, bad solution
                    else:
                        roomlist.append(assigned_room)

                    # check for student group size and room capacity
                    # print(slot.student_group.categorize_group_size(), assigned_room.categorize_group_size())
                    # if slot.student_group.categorize_group_size() != assigned_room.categorize_group_size():
                    if slot.student_group.no_students <= assigned_room.capacity:
                        self.point += 1

                    # check for room type match
                    for course in self.courses:
                        if course.code == slot.course_id:
                            required_room_type = course.required_room_type

                    # print(required_room_type, assigned_room.room_type)
                    if required_room_type == assigned_room.room_type:
                        self.point += 1

        # Hard constraint 2: No two events can happen in the same room* and timeslot
        """
        taken care of due to the fact that array/slots is of fixed length where each row belongs to one student group
        """

        # Hard constraint 3: 
        
        self.fitness = 1 - (self.point / ((self.nostgrp - 1.0) * self.hours * self.days))
        self.point = 0
        return self.fitness

    def print_time_table(self):
        for i in range(self.nostgrp):
            status = False
            l = 0

            while not status:
                if Timetable.periods_list[self.gene[i].slotno[l]] is not None:
                    print(f"Batch {Timetable.periods_list[self.gene[i].slotno[l]].student_group.name} Timetable-")
                    status = True
                l += 1

            for j in range(self.days):
                for k in range(self.hours):
                    if Timetable.periods_list[self.gene[i].slotno[k + j * self.hours]] is not None:
                        # print(f"{Timetable.periods_list[self.gene[i].slotno[k + j * self.hours]].course_id} ", end="")
                        assigned_room = self.gene[i].room_assignment[k + j * self.hours]
                        print(f"{Timetable.periods_list[self.gene[i].slotno[k + j * self.hours]].course_id} in Room {assigned_room} ", end="")
                    else:
                        print("*FREE* ", end="")
                print("")
            print("\n\n\n end")

    def print_chromosome(self):
        for i in range(self.nostgrp):
            for j in range(self.hours * self.days):
                print(f"{self.gene[i].slotno[j]} ", end="")
            print("")

    def solution_repr(self):
        chrome = []
        for i in range(self.nostgrp):
            chrome.append(self.gene[i].slotno)
        return chrome

    def __lt__(self, other):
        return self.fitness > other.fitness

    def __eq__(self, other):
        return self.fitness == other.fitness

test_chromosome = Chromosome()
# print(test_chromosome.print_time_table())
# print(test_chromosome.print_chromosome())
# print(test_chromosome.solution_repr())