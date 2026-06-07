import random
from typing import List
import copy
from utils import Utility
from entitities.Class import Class
from input_data import input_data
import numpy as np
from constraints import Constraints
import re
import dash

# Create global constraint checker for real-time validation
global_constraints = Constraints(input_data)
from dash import dcc, html, Input, Output, State, clientside_callback
from dash.dependencies import ALL
import dash.exceptions
import dash.dependencies
import json
import os
import shutil
import traceback

# Global constraint violation tracking for persistence
original_algorithm_violations = {}  # Store original violations from the algorithm
global_violation_tracking = {}  # Track all violations to ensure persistence

def store_original_violations(violations_dict):
    """Store the original violations from the DE algorithm."""
    global original_algorithm_violations
    original_algorithm_violations = violations_dict.copy()
    print(f"🔒 Stored {len(violations_dict)} original violation types from algorithm")

# population initialization using input_data
class DifferentialEvolution:
    def __init__(self, input_data, pop_size: int, F: float, CR: float):
        self.desired_fitness = 0
        self.input_data = input_data
        self.rooms = input_data.rooms
        self.timeslots = input_data.create_time_slots(no_hours_per_day=input_data.hours, no_days_per_week=input_data.days, day_start_time=9)
        self.student_groups = input_data.student_groups
        self.courses = input_data.courses
        self.events_list, self.events_map = self.create_events()
        self.pop_size = pop_size
        self.F = F
        self.CR = CR
        self.constraints = Constraints(input_data)
        
        # Optimization: Cache fitness values to avoid recalculation
        self.fitness_cache = {}
        
        # Optimization: Pre-calculate building assignments for rooms to speed up evaluation
        self.room_building_cache = {}
        for idx, room in enumerate(self.rooms):
            self.room_building_cache[idx] = self.get_room_building(room)
        
        # Optimization: Pre-calculate engineering groups to avoid repeated checks
        self.engineering_groups = set()
        for student_group in self.student_groups:
            group_name = student_group.name.lower()
            if any(keyword in group_name for keyword in [
                'engineering', 'eng', 'computer science', 'software engineering', 'data science',
                'mechatronics', 'electrical', 'mechanical', 'csc', 'sen', 'data', 'ds'
            ]):
                self.engineering_groups.add(student_group.id)
        
        self.population = self.initialize_population()  # List to hold all chromosomes

    def create_events(self):
        events_list = []
        event_map = {}

        idx = 0
        for student_group in self.student_groups:
            for i in range(student_group.no_courses):
                # Get the course to check its credits
                course = input_data.getCourse(student_group.courseIDs[i])
                
                # SPECIAL HANDLING FOR 1-CREDIT COURSES:
                # If course has 1 credit, it must have 3 hours (with 2 consecutive rule)
                if course and course.credits == 1:
                    required_hours = 3  # Force 1-credit courses to have 3 hours
                    print(f"📚 1-CREDIT COURSE: {course.name} ({course.code}) - Converting to 3 hours")
                else:
                    # Use original hours required for other courses
                    required_hours = student_group.hours_required[i]
                
                # Reset hourcount for each new course to correctly group events
                hourcount = 1 
                while hourcount <= required_hours:
                    event = Class(student_group, student_group.teacherIDS[i], student_group.courseIDs[i])
                    events_list.append(event)
                    
                    # Add the event to the index map with the current index
                    event_map[idx] = event
                    idx += 1
                    hourcount += 1
                    
        return events_list, event_map

    def initialize_population(self):
        population = [] 
        for i in range(self.pop_size):
            chromosome = self.create_chromosome()
            population.append(chromosome)
        return np.array(population)

    def create_chromosome(self):
        chromosome = np.empty((len(self.rooms), len(self.timeslots)), dtype=object)
        
        # Group events by student group and course to handle them as blocks
        events_by_group_course = {}
        for idx, event in enumerate(self.events_list):
            key = (event.student_group.id, event.course_id)
            if key not in events_by_group_course:
                events_by_group_course[key] = []
            events_by_group_course[key].append(idx)

        # --- STRATEGY: Prioritize placing larger courses first ("big rocks first") ---
        course_items = sorted(
            events_by_group_course.items(),
            key=lambda item: len(item[1]),
            reverse=True
        )

        # Trackers for optimized placement
        hours_per_day_for_group = {sg.id: [0] * input_data.days for sg in self.student_groups}

        for (student_group_id, course_id), event_indices in course_items:
            course = input_data.getCourse(course_id)
            student_group = input_data.getStudentGroup(student_group_id)
            hours_required = len(event_indices)

            if hours_required == 0:
                continue

            # --- STRATEGY: Stricter split strategies to enforce consecutive constraints ---
            split_strategies = []
            if hours_required >= 4: # 4-hour courses and above
                split_strategies = [(4,), (2, 2), (3, 1)]
            elif hours_required == 3: # 3-hour courses (including 1-credit courses converted to 3 hours)
                # For 1-credit courses: prioritize 3 consecutive, fallback to 2 consecutive + 1 separate
                split_strategies = [(3,), (2, 1)]
            elif hours_required == 2: # 2-hour courses
                split_strategies = [(2,)] # MUST be consecutive
            else: # 1-hour courses (only original 1-hour courses that weren't 1-credit)
                split_strategies = [(1,)]

            course_placed = False
            for split_strategy in split_strategies:
                if course_placed:
                    break

                placements_for_strategy = []
                all_blocks_found = True
                temp_chromosome = chromosome.copy()
                
                event_idx_counter = 0
                
                temp_hours_per_day = hours_per_day_for_group[student_group_id][:]
                temp_course_days_used = set()

                for block_hours in split_strategy:
                    placed = False
                    block_event_indices = event_indices[event_idx_counter : event_idx_counter + block_hours]
                    
                    available_days = [d for d in range(input_data.days) if d not in temp_course_days_used]
                    sorted_days = sorted(available_days, key=lambda d: temp_hours_per_day[d])

                    for day_idx in sorted_days:
                        day_start = day_idx * input_data.hours
                        day_end = (day_idx + 1) * input_data.hours
                        
                        possible_slots = []
                        for room_idx, room in enumerate(self.rooms):
                            # --- STRATEGY: Enforce building constraints during placement ---
                            is_engineering_group = student_group.id in self.engineering_groups
                            room_building = self.room_building_cache.get(room_idx, 'UNKNOWN')
                            
                            # Non-engineering groups cannot use SST rooms
                            if not is_engineering_group and room_building == 'SST':
                                continue # Skip this room entirely for this group

                            if self.is_room_suitable(room, course):
                                for timeslot_start in range(day_start, day_end - block_hours + 1):
                                    is_block_placeable = True
                                    for i in range(block_hours):
                                        ts = timeslot_start + i
                                        event_for_slot = self.events_list[block_event_indices[i]]
                                        if not (self.is_slot_available_for_event(temp_chromosome, room_idx, ts, event_for_slot) and
                                                self._is_student_group_available(temp_chromosome, student_group_id, ts) and
                                                self._is_lecturer_available(temp_chromosome, event_for_slot.faculty_id, ts)):
                                            is_block_placeable = False
                                            break
                                    
                                    if is_block_placeable:
                                        possible_slots.append((room_idx, timeslot_start))
                        
                        if possible_slots:
                            # Prefer slots that don't cause building conflicts if possible
                            preferred_slots = []
                            for r_idx, t_start in possible_slots:
                                room_bldg = self.room_building_cache.get(r_idx, 'UNKNOWN')
                                is_eng_grp = student_group.id in self.engineering_groups
                                if is_eng_grp and room_bldg != 'SST':
                                    pass # This is a potential soft conflict
                                else:
                                    preferred_slots.append((r_idx, t_start))
                            
                            if preferred_slots:
                                room_idx, timeslot_start = random.choice(preferred_slots)
                            else: # If all options cause a soft conflict, just pick one
                                room_idx, timeslot_start = random.choice(possible_slots)

                            for i in range(block_hours):
                                ts = timeslot_start + i
                                event_id = block_event_indices[i]
                                placements_for_strategy.append((room_idx, ts, event_id))
                                temp_chromosome[room_idx, ts] = event_id
                            
                            temp_hours_per_day[day_idx] += block_hours
                            temp_course_days_used.add(day_idx)
                            placed = True
                            event_idx_counter += block_hours
                            break 
                    
                    if not placed:
                        all_blocks_found = False
                        break
                
                if all_blocks_found:
                    for r, t, e_id in placements_for_strategy:
                        chromosome[r, t] = e_id
                    
                    hours_per_day_for_group[student_group_id] = temp_hours_per_day
                    
                    course_placed = True
                    break

        # Final verification to place any unassigned events
        chromosome = self.verify_and_repair_course_allocations(chromosome)
        
        # Basic clash prevention only
        chromosome = self.prevent_student_group_clashes(chromosome)
        
        return chromosome

    def find_consecutive_slots(self, chromosome, course):
        # Randomly find consecutive time slots in the same room
        two_slot_rooms = []
        for room_idx, room in enumerate(self.rooms):
            if self.is_room_suitable(room, course):
                # Collect pairs of consecutive available time slots
                for i in range(len(self.timeslots) - 1):
                    if self.is_slot_available(chromosome, room_idx, i) and self.is_slot_available(chromosome, room_idx, i + 1):
                        two_slot_rooms.append((room_idx, i, i+1))

        if len(two_slot_rooms) != 0:
            _room_idx, slot1, slot2 = random.choice(two_slot_rooms)           
            return _room_idx, slot1, slot2
        
        return None, None, None

    def find_single_slot(self, chromosome, course):
        # Randomly find a single available slot
        single_slot_rooms = []
        for room_idx, room in enumerate(self.rooms):
            if self.is_room_suitable(room, course):
                for i in range(len(self.timeslots)):
                    if self.is_slot_available(chromosome, room_idx, i):
                        single_slot_rooms.append((room_idx, i))
        
        # Randomly pick from the available single slots
        if len(single_slot_rooms) > 0:
            return random.choice(single_slot_rooms)
        
        # If no valid single slots are found
        return None, None

    def is_slot_available(self, chromosome, room_idx, timeslot_idx):
        # Check if the slot is available (i.e., not already assigned)
        if chromosome[room_idx][timeslot_idx] is not None:
            return False
        
        # Check if this is break time (13:00 - 14:00)
        # Break time is the 5th hour (index 4) of each day starting from 9:00
        break_hour = 4  # 13:00 is the 5th hour (index 4) starting from 9:00
        day = timeslot_idx // input_data.hours
        hour_in_day = timeslot_idx % input_data.hours
        
        # No break time on Tuesday (1) and Thursday (3)
        if hour_in_day == break_hour and day not in [1, 3]:
            return False  # Break time slot is not available
        
        return True

    def is_slot_available_for_event(self, chromosome, room_idx, timeslot_idx, event):
        """
        Checks if a slot is available for a specific event, considering lecturer availability.
        """
        # Check if the slot is physically empty
        if chromosome[room_idx][timeslot_idx] is not None:
            return False

        # Check for break time
        break_hour = 4
        day = timeslot_idx // input_data.hours
        hour_in_day = timeslot_idx % input_data.hours
        if hour_in_day == break_hour and day not in [1, 3]:
            return False

        # Check lecturer schedule constraints
        if event and event.faculty_id is not None:
            faculty = input_data.getFaculty(event.faculty_id)
            if faculty:
                days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
                day_abbr = days_map.get(day)
                slot_hour = self.timeslots[timeslot_idx].start_time + 9

                # Check day availability
                is_day_ok = False
                avail_days = faculty.avail_days
                if not avail_days or (isinstance(avail_days, str) and avail_days.upper() == "ALL"):
                    is_day_ok = True
                else:
                    if isinstance(avail_days, str):
                        avail_days_list = [d.strip().capitalize() for d in avail_days.split(',')]
                    else: # is a list
                        avail_days_list = [d.strip().capitalize() for d in avail_days]
                    if "All" in avail_days_list or day_abbr in avail_days_list:
                        is_day_ok = True
                
                if not is_day_ok:
                    return False

                # Check time availability (Corrected Logic)
                is_time_ok = False
                avail_times = faculty.avail_times
                if not avail_times or (isinstance(avail_times, str) and avail_times.upper() == "ALL") or \
                   (isinstance(avail_times, list) and any(str(t).strip().upper() == 'ALL' for t in avail_times)):
                    is_time_ok = True
                else:
                    time_list = avail_times if isinstance(avail_times, list) else [avail_times]
                    for time_spec in time_list:
                        time_spec_str = str(time_spec).strip()
                        if '-' in time_spec_str:
                            try:
                                start_str, end_str = time_spec_str.split('-')
                                start_h = int(start_str.split(':')[0])
                                end_h = int(end_str.split(':')[0])
                                if start_h <= slot_hour < end_h:
                                    is_time_ok = True
                                    break
                            except (ValueError, IndexError):
                                continue
                        else:
                            try:
                                h = int(time_spec_str.split(':')[0])
                                if h == slot_hour:
                                    is_time_ok = True
                                    break
                            except (ValueError, IndexError):
                                continue
                
                if not is_time_ok:
                    return False

        return True

    def is_room_suitable(self, room, course):
        if course is None:
            return False
        return room.room_type == course.required_room_type
    
    def get_room_building(self, room):
        """Helper method to determine room building"""
        if hasattr(room, 'building'):
            return room.building.upper()
        elif hasattr(room, 'name') and room.name:
            room_name = room.name.upper()
            if 'SST' in room_name:
                return 'SST'
            elif 'TYD' in room_name:
                return 'TYD'
        elif hasattr(room, 'room_id'):
            room_id = str(room.room_id).upper()
            if 'SST' in room_id:
                return 'SST'
            elif 'TYD' in room_id:
                return 'TYD'
        return 'UNKNOWN'

    def _is_student_group_available(self, chromosome, student_group_id, timeslot_idx):
        """Checks if a student group is already scheduled at a given timeslot."""
        for r_idx in range(len(self.rooms)):
            event_id = chromosome[r_idx][timeslot_idx]
            if event_id is not None:
                event = self.events_map.get(event_id)
                if event and event.student_group.id == student_group_id:
                    return False  # Clash: Student group is not available
        return True

    def _is_lecturer_available(self, chromosome, faculty_id, timeslot_idx):
        """Checks if a lecturer is already scheduled at a given timeslot."""
        for r_idx in range(len(self.rooms)):
            event_id = chromosome[r_idx][timeslot_idx]
            if event_id is not None:
                event = self.events_map.get(event_id)
                if event and event.faculty_id == faculty_id:
                    return False  # Clash: Lecturer is not available
        return True

    def find_clash(self, chromosome):
        """Finds a random timeslot with a student or lecturer clash."""
        clash_slots = []
        for t_idx in range(len(self.timeslots)):
            simultaneous_events = chromosome[:, t_idx]
            
            student_group_watch = set()
            lecturer_watch = set()
            
            has_student_clash = False
            has_lecturer_clash = False
            
            event_ids_in_slot = [e for e in simultaneous_events if e is not None]
            if len(event_ids_in_slot) <= 1:
                continue

            for event_id in event_ids_in_slot:
                event = self.events_map.get(event_id)
                if not event: continue
                
                # Check for student clash
                if event.student_group.id in student_group_watch:
                    has_student_clash = True
                student_group_watch.add(event.student_group.id)
                
                # Check for lecturer clash
                if event.faculty_id and event.faculty_id in lecturer_watch:
                    has_lecturer_clash = True
                if event.faculty_id:
                    lecturer_watch.add(event.faculty_id)
            
            if has_student_clash or has_lecturer_clash:
                clash_slots.append(t_idx)
                
        if clash_slots:
            return random.choice(clash_slots)
        return None
    
    def hamming_distance(self, chromosome1, chromosome2):
        return np.sum(chromosome1.flatten() != chromosome2.flatten())

    def calculate_population_diversity(self):
        # Optimization: Sample diversity calculation instead of full O(n²)
        if self.pop_size <= 10:
            # For small populations, calculate full diversity
            total_distance = 0
            comparisons = 0
            
            for i in range(self.pop_size):
                for j in range(i + 1, self.pop_size):
                    total_distance += self.hamming_distance(self.population[i], self.population[j])
                    comparisons += 1
            
            return total_distance / comparisons if comparisons > 0 else 0
        else:
            # For larger populations, sample 10 random pairs
            total_distance = 0
            comparisons = 10
            
            for _ in range(comparisons):
                i, j = random.sample(range(self.pop_size), 2)
                total_distance += self.hamming_distance(self.population[i], self.population[j])
            
            return total_distance / comparisons


    def mutate(self, target_idx):
        mutant_vector = self.population[target_idx].copy()
        
        # Increase mutation attempts to encourage exploration
        mutation_attempts = random.randint(3, 8)

        for _ in range(mutation_attempts):
            strategy = random.choice(['resolve_clash', 'safe_swap', 'safe_move'])

            # Strategy 1: Find a clash and try to resolve it by moving one event
            if strategy == 'resolve_clash':
                clash_timeslot = self.find_clash(mutant_vector)
                if clash_timeslot is not None:
                    # Find events involved in the clash
                    events_in_slot = [(r, mutant_vector[r, clash_timeslot]) for r in range(len(self.rooms)) if mutant_vector[r, clash_timeslot] is not None]
                    if not events_in_slot: continue
                    
                    # Pick one event to move
                    room_to_move_from, event_id_to_move = random.choice(events_in_slot)
                    event_to_move = self.events_map.get(event_id_to_move)
                    if not event_to_move: continue

                    # Find a new, valid, empty slot for this event
                    new_pos = self.find_safe_empty_slot_for_event(mutant_vector, event_to_move, ignore_pos=(room_to_move_from, clash_timeslot))
                    if new_pos:
                        new_r, new_t = new_pos
                        mutant_vector[new_r, new_t] = event_id_to_move
                        mutant_vector[room_to_move_from, clash_timeslot] = None
                        continue # Move successful, try another mutation

            # Strategy 2: Swap two existing events if it's safe
            elif strategy == 'safe_swap':
                occupied_slots = np.argwhere(mutant_vector != None)
                if len(occupied_slots) < 2: continue
                
                idx1, idx2 = random.sample(range(len(occupied_slots)), 2)
                pos1, pos2 = tuple(occupied_slots[idx1]), tuple(occupied_slots[idx2])
                
                event1_id, event2_id = mutant_vector[pos1], mutant_vector[pos2]
                event1, event2 = self.events_map.get(event1_id), self.events_map.get(event2_id)
                
                if not event1 or not event2: continue

                # Check if swapping is feasible
                course1, course2 = self.input_data.getCourse(event1.course_id), self.input_data.getCourse(event2.course_id)
                
                # Check room suitability
                room1_ok_for_event2 = self.is_room_suitable(self.rooms[pos1[0]], course2)
                room2_ok_for_event1 = self.is_room_suitable(self.rooms[pos2[0]], course1)

                if room1_ok_for_event2 and room2_ok_for_event1:
                    # Check clash constraints for the swap
                    # Is event2 OK at pos1's timeslot?
                    clash_free_at_pos1 = not self.constraints.check_student_group_clash_at_slot(mutant_vector, event2.student_group.id, pos1[1], ignore_room_idx=pos2[0]) and \
                                         not self.constraints.check_lecturer_clash_at_slot(mutant_vector, event2.faculty_id, pos1[1], ignore_room_idx=pos2[0])
                    
                    # Is event1 OK at pos2's timeslot?
                    clash_free_at_pos2 = not self.constraints.check_student_group_clash_at_slot(mutant_vector, event1.student_group.id, pos2[1], ignore_room_idx=pos1[0]) and \
                                         not self.constraints.check_lecturer_clash_at_slot(mutant_vector, event1.faculty_id, pos2[1], ignore_room_idx=pos1[0])

                    if clash_free_at_pos1 and clash_free_at_pos2:
                        mutant_vector[pos1], mutant_vector[pos2] = event2_id, event1_id
                        continue

            # Strategy 3: Move a single event to a new, safe, empty location
            elif strategy == 'safe_move':
                occupied_slots = np.argwhere(mutant_vector != None)
                if not len(occupied_slots): continue
                
                pos_to_move = tuple(random.choice(occupied_slots))
                event_id_to_move = mutant_vector[pos_to_move]
                event_to_move = self.events_map.get(event_id_to_move)
                if not event_to_move: continue

                # Find a new, valid, empty slot
                new_pos = self.find_safe_empty_slot_for_event(mutant_vector, event_to_move, ignore_pos=pos_to_move)
                if new_pos:
                    new_r, new_t = new_pos
                    mutant_vector[new_r, new_t] = event_id_to_move
                    mutant_vector[pos_to_move] = None
                    continue

        return mutant_vector

    def find_safe_empty_slot_for_event(self, chromosome, event, ignore_pos=None):
        """Finds a random empty slot that is safe for the given event."""
        course = self.input_data.getCourse(event.course_id)
        if not course: return None

        possible_slots = []
        for r_idx, room in enumerate(self.rooms):
            if self.is_room_suitable(room, course):
                for t_idx in range(len(self.timeslots)):
                    if (r_idx, t_idx) == ignore_pos: continue
                    
                    # Check if slot is physically empty and available (break time, etc.)
                    if chromosome[r_idx, t_idx] is None and self.is_slot_available_for_event(chromosome, r_idx, t_idx, event):
                        # Check for potential clashes if we place the event here
                        student_clash = self.constraints.check_student_group_clash_at_slot(chromosome, event.student_group.id, t_idx, ignore_room_idx=ignore_pos[0] if ignore_pos else -1)
                        lecturer_clash = self.constraints.check_lecturer_clash_at_slot(chromosome, event.faculty_id, t_idx, ignore_room_idx=ignore_pos[0] if ignore_pos else -1)
                        
                        if not student_clash and not lecturer_clash:
                            possible_slots.append((r_idx, t_idx))
        
        return random.choice(possible_slots) if possible_slots else None

    def ensure_valid_solution(self, mutant_vector):
        """Ensure same course on same day appears in same room and handle course splits."""
        course_day_room_mapping = {}
        
        # First pass: collect course-day-room mappings
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = mutant_vector[room_idx][timeslot_idx]
                if event_id is not None:
                    class_event = self.events_map.get(event_id)
                    if class_event:
                        day_idx = timeslot_idx // input_data.hours
                        course = input_data.getCourse(class_event.course_id)
                        course_id = getattr(course, 'course_id', None) or getattr(course, 'id', None) or getattr(course, 'code', None) if course else class_event.course_id
                        course_day_key = (course_id, day_idx, class_event.student_group.id)
                        
                        if course_day_key not in course_day_room_mapping:
                            course_day_room_mapping[course_day_key] = room_idx
        
        # Second pass: fix room violations
        events_to_move = []
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = mutant_vector[room_idx][timeslot_idx]
                if event_id is not None:
                    class_event = self.events_map.get(event_id)
                    if class_event:
                        day_idx = timeslot_idx // input_data.hours
                        course = input_data.getCourse(class_event.course_id)
                        course_id = getattr(course, 'course_id', None) or getattr(course, 'id', None) or getattr(course, 'code', None) if course else class_event.course_id
                        course_day_key = (course_id, day_idx, class_event.student_group.id)
                        expected_room = course_day_room_mapping.get(course_day_key)
                        
                        if expected_room is not None and room_idx != expected_room:
                            mutant_vector[room_idx][timeslot_idx] = None
                            events_to_move.append((event_id, expected_room, timeslot_idx))
        
        # Third pass: place moved events in correct rooms
        for event_id, correct_room, original_timeslot in events_to_move:
            placed = False
            # Try to find an available slot in the correct room
            for timeslot in range(len(self.timeslots)):
                if self.is_slot_available(mutant_vector, correct_room, timeslot):
                    mutant_vector[correct_room][timeslot] = event_id
                    placed = True
                    break
            
            # If not placed, it will be handled by the repair function
        
        # Repair course allocations to ensure all events are scheduled
        mutant_vector = self.verify_and_repair_course_allocations(mutant_vector)
        
        # Final pass to ensure multi-hour courses are consecutive
        mutant_vector = self.ensure_consecutive_slots(mutant_vector)
        
        # CRITICAL SAFETY: Ensure NO student group clashes after mutation
        mutant_vector = self.prevent_student_group_clashes(mutant_vector)
        
        return mutant_vector

    def prevent_student_group_clashes(self, chromosome):
        """
        Smart clash prevention that tries to move conflicting events rather than just deleting them.
        This prevents missing classes while still eliminating student group clashes.
        """
        max_attempts = 5  # Increased attempts
        
        for attempt in range(max_attempts):
            clashes_found = False
            
            # Check each timeslot for student group conflicts
            for t_idx in range(len(self.timeslots)):
                student_groups_seen = {}
                conflicting_events = []
                
                # First pass: identify all conflicts in this timeslot
                for r_idx in range(len(self.rooms)):
                    event_id = chromosome[r_idx, t_idx]
                    if event_id is not None:
                        event = self.events_map.get(event_id)
                        if event:
                            sg_id = event.student_group.id
                            if sg_id in student_groups_seen:
                                # Conflict detected - both events clash
                                conflicting_events.append((r_idx, event_id))
                                clashes_found = True
                            else:
                                student_groups_seen[sg_id] = (r_idx, event_id)
                
                # Second pass: try to move conflicting events to other slots
                for r_idx, event_id in conflicting_events:
                    event = self.events_map.get(event_id)
                    course = input_data.getCourse(event.course_id)
                    
                    # Clear the conflicting position
                    chromosome[r_idx, t_idx] = None
                    
                    # Try to find an alternative slot for this event
                    moved = False
                    alternative_slots = []
                    
                    for alt_r_idx, room in enumerate(self.rooms):
                        if self.is_room_suitable(room, course):
                            for alt_t_idx in range(len(self.timeslots)):
                                if (chromosome[alt_r_idx, alt_t_idx] is None and
                                    self.is_slot_available_for_event(chromosome, alt_r_idx, alt_t_idx, event) and
                                    self._is_student_group_available(chromosome, event.student_group.id, alt_t_idx) and
                                    self._is_lecturer_available(chromosome, event.faculty_id, alt_t_idx)):
                                    alternative_slots.append((alt_r_idx, alt_t_idx))
                    
                    if alternative_slots:
                        # Move to a good alternative slot
                        alt_r, alt_t = random.choice(alternative_slots)
                        chromosome[alt_r, alt_t] = event_id
                        moved = True
                    else:
                        # If no perfect slot, try to find any suitable room slot
                        for alt_r_idx, room in enumerate(self.rooms):
                            if self.is_room_suitable(room, course):
                                for alt_t_idx in range(len(self.timeslots)):
                                    if (chromosome[alt_r_idx, alt_t_idx] is None and
                                        self.is_slot_available_for_event(chromosome, alt_r_idx, alt_t_idx, event)):
                                        chromosome[alt_r_idx, alt_t_idx] = event_id
                                        moved = True
                                        break
                                if moved:
                                    break
                    
                    # If we couldn't move it anywhere, it becomes a missing class
                    # This will be handled by the repair function later
            
            if not clashes_found:
                break
        
        return chromosome

    def verify_no_student_group_clashes(self, chromosome):
        """
        VERIFICATION FUNCTION: Checks that absolutely NO student group clashes exist.
        Returns True if no clashes, False if clashes found.
        """
        for t_idx in range(len(self.timeslots)):
            student_groups_seen = set()
            
            for r_idx in range(len(self.rooms)):
                event_id = chromosome[r_idx, t_idx]
                if event_id is not None:
                    event = self.events_map.get(event_id)
                    if event:
                        sg_id = event.student_group.id
                        if sg_id in student_groups_seen:
                            print(f"❌ CRITICAL ERROR: Student group clash detected at timeslot {t_idx}!")
                            print(f"   Student group {sg_id} appears multiple times at the same time!")
                            return False
                        student_groups_seen.add(sg_id)
        
        print("✅ VERIFIED: NO student group clashes detected!")
        return True

    def count_non_none(self, arr):
        # Flatten the 2D array and count elements that are not None
        return np.count_nonzero(arr != None)
    
    def crossover(self, target_vector, mutant_vector):
        """
        Simple, robust crossover that avoids creating student group clashes.
        """
        trial_vector = target_vector.copy()
        num_rooms, num_timeslots = target_vector.shape
        
        # Ensure at least one gene from the mutant vector is picked (j_rand)
        j_rand_r = random.randrange(num_rooms)
        j_rand_t = random.randrange(num_timeslots)

        for r in range(num_rooms):
            for t in range(num_timeslots):
                if random.random() < self.CR or (r == j_rand_r and t == j_rand_t):
                    mutant_event_id = mutant_vector[r, t]
                    
                    # Simple placement - if mutant slot is None, just place it
                    if mutant_event_id is None:
                        trial_vector[r, t] = None
                    else:
                        # For non-None events, check basic safety
                        mutant_event = self.events_map.get(mutant_event_id)
                        if mutant_event:
                            # Simple clash check - only place if student group is available
                            if self._is_student_group_available(trial_vector, mutant_event.student_group.id, t):
                                trial_vector[r, t] = mutant_event_id
                    
        return trial_vector

    
    def evaluate_fitness(self, chromosome):
        # Optimization: Use cached fitness if available
        chromosome_key = str(chromosome.tobytes())
        if chromosome_key in self.fitness_cache:
            return self.fitness_cache[chromosome_key]
        
        # Use the centralized Constraints class for consistent evaluation
        fitness = self.constraints.evaluate_fitness(chromosome)
        
        # Cache management: prevent unlimited growth (reduced frequency for speed)
        if len(self.fitness_cache) > 1000:  # Reduced from 2000 for faster cache management
            # Keep only the most recent 500 entries
            keys_to_remove = list(self.fitness_cache.keys())[:-500]
            for key in keys_to_remove:
                del self.fitness_cache[key]
        
        # Cache the result
        self.fitness_cache[chromosome_key] = fitness
        return fitness

    # Original DE constraint methods preserved for reference
    # These are now replaced by the centralized Constraints class above   

    def check_room_constraints(self, chromosome):
        """
        rooms must meet the capacity and type of the scheduled event
        """
        point = 0
        for room_idx in range(len(self.rooms)):
            room = self.rooms[room_idx]
            for timeslot_idx in range(len(self.timeslots)):
                class_event = self.events_map.get(chromosome[room_idx][timeslot_idx])
                if class_event is not None:
                    course = input_data.getCourse(class_event.course_id)
                    # H1: Room capacity and type constraints
                    if room.room_type != course.required_room_type or class_event.student_group.no_students > room.capacity:
                        point += 1

        return point
       
    
    def check_student_group_constraints(self, chromosome):
        penalty = 0
        for i in range(len(self.timeslots)):
            simultaneous_class_events = chromosome[:, i]
            student_group_watch = set()
            for class_event_idx in simultaneous_class_events:
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    student_group = class_event.student_group
                    if student_group.id in student_group_watch:
                        penalty += 1
                    else:
                        student_group_watch.add(student_group.id)

        return penalty
    
    def check_lecturer_availability(self, chromosome):
        penalty = 0
        for i in range(len(self.timeslots)):
            simultaneous_class_events = chromosome[:, i]
            lecturer_watch = set()
            for class_event_idx in simultaneous_class_events:
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    faculty_id = class_event.faculty_id
                    if faculty_id in lecturer_watch:
                        penalty += 1
                    else:
                        lecturer_watch.add(faculty_id)

        return penalty


    # def check_room_time_conflict(self, chromosome):
        penalty = 0

        # Check if multiple events are scheduled in the same room at the same time
        for room_idx, room_schedule in enumerate(chromosome):
            for timeslot_idx, class_event in enumerate(room_schedule):
                if class_event is not None:
                    # H3: Ensure only one event is scheduled per timeslot per room
                    if isinstance(class_event, list) and len(class_event) > 1:
                        penalty += 1000  # Penalty for multiple events in the same room at the same time

        return penalty
# -------------------------------------------
    # def check_valid_timeslot(self, chromosome):
    #     penalty = 0
        
    #     for room_idx, room_schedule in enumerate(chromosome):
    #         for timeslot_idx, class_event in enumerate(room_schedule):
    #             if class_event is not None:  # Event scheduled
    #                 # H5: Ensure the timeslot is valid for this event
    #                 if not self.timeslots[timeslot_idx].is_valid_for_event(class_event):
    #                     penalty += 500  # Moderate penalty for invalid timeslot

    #     return penalty


    def select(self, target_idx, trial_vector):
        trial_violations = self.constraints.get_constraint_violations(trial_vector)
        target_violations = self.constraints.get_constraint_violations(self.population[target_idx])

        # Define which constraints are "hard" and must be prioritized
        hard_constraints = [
            'student_group_constraints', 
            'lecturer_availability', 
            'course_allocation_completeness',
            'room_time_conflict',
            'break_time_constraint',
            'room_constraints',
            'same_course_same_room_per_day',
            'lecturer_schedule_constraints',
            'lecturer_workload_constraints'
        ]

        trial_hard_violations = sum(trial_violations.get(c, 0) for c in hard_constraints)
        target_hard_violations = sum(target_violations.get(c, 0) for c in hard_constraints)

        accept = False
        if trial_hard_violations < target_hard_violations:
            accept = True
        elif trial_hard_violations == target_hard_violations:
            # If hard constraints are equal, compare total fitness (which includes soft constraints)
            if trial_violations.get('total', float('inf')) <= target_violations.get('total', float('inf')):
                accept = True

        if accept:
            # Decouple repair from selection: Accept the trial vector as is.
            # The repair function will be called on all population members later in the main loop.
            self.population[target_idx] = trial_vector


    def run(self, max_generations):
        # Population already initialized in __init__, don't reinitialize
        fitness_history = []
        best_solution = self.population[0]
        diversity_history = []
        
        # Optimization: Calculate initial fitness and find best solution
        initial_fitness = [self.evaluate_fitness(ind) for ind in self.population]
        best_idx = np.argmin(initial_fitness)
        best_solution = self.population[best_idx].copy()
        best_fitness = initial_fitness[best_idx]
        
        # Track fitness for early convergence detection
        stagnation_counter = 0
        last_improvement = best_fitness

        for generation in range(max_generations):
            generation_improved = False
            
            for i in range(self.pop_size):
                # Step 1: Mutation
                mutant_vector = self.mutate(i)
                
                # Step 2: Crossover
                target_vector = self.population[i]
                trial_vector = self.crossover(target_vector, mutant_vector)
                
                # Step 3: Repair course allocations FIRST (highest priority)
                trial_vector = self.verify_and_repair_course_allocations(trial_vector)
                
                # Step 4: THEN handle clashes (lower priority)
                trial_vector = self.prevent_student_group_clashes(trial_vector)
                
                # Step 5: Final repair to catch any missing events after clash resolution
                trial_vector = self.verify_and_repair_course_allocations(trial_vector)

                # Step 6: Evaluation and Selection
                self.select(i, trial_vector)
                
            # Optimization: Find best solution more efficiently
            current_fitness = [self.evaluate_fitness(ind) for ind in self.population]
            current_best_idx = np.argmin(current_fitness)
            current_best_fitness = current_fitness[current_best_idx]
            
            if current_best_fitness < best_fitness:
                best_solution = self.population[current_best_idx].copy()
                best_fitness = current_best_fitness
                stagnation_counter = 0
                last_improvement = best_fitness
            else:
                stagnation_counter += 1
            
            fitness_history.append(best_fitness)

            # Optimization: Calculate diversity less frequently for speed
            if generation % 20 == 0:  # Only every 20 generations (reduced from 10)
                population_diversity = self.calculate_population_diversity()
                diversity_history.append(population_diversity)

            print(f"Best solution for generation {generation+1}/{max_generations} has a fitness of: {best_fitness}")

            if best_fitness == self.desired_fitness:
                print(f"Solution with desired fitness of {self.desired_fitness} found at Generation {generation}! 🎉")
                break  # Stop if the best solution has no constraint violations
            
            # Early termination if no improvement for 20 generations (reduced from 50)
            if stagnation_counter >= 20:
                print(f"Early termination due to stagnation after {stagnation_counter} generations without improvement at generation {generation+1}")
                print(f"Final fitness achieved: {best_fitness}")
                break
            
            # Additional early termination if no improvement for many generations and fitness is acceptable
            if stagnation_counter > 50 and best_fitness < 100:
                print(f"Early termination due to convergence at generation {generation+1}")
                break

        # CRITICAL: Ensure the final best solution has NO missing classes
        # Track fitness before post-algorithm repairs
        pre_repair_fitness = self.evaluate_fitness(best_solution)
        print(f"\n🔧 APPLYING POST-ALGORITHM REPAIRS...")
        print(f"   Fitness before repairs: {pre_repair_fitness:.4f}")
        
        best_solution = self.verify_and_repair_course_allocations(best_solution)
        best_solution = self.ensure_consecutive_slots(best_solution)
        best_solution = self.prevent_student_group_clashes(best_solution)
        
        # FINAL repair pass to absolutely guarantee no missing classes
        best_solution = self.verify_and_repair_course_allocations(best_solution)
        
        # Track fitness after repairs
        post_repair_fitness = self.evaluate_fitness(best_solution)
        repair_impact = post_repair_fitness - pre_repair_fitness
        print(f"   Fitness after repairs: {post_repair_fitness:.4f}")
        
        if abs(repair_impact) > 0.01:
            impact_direction = "improved" if repair_impact < 0 else "worsened"
            print(f"   🎯 Repair impact: {impact_direction} fitness by {abs(repair_impact):.4f} points")
        else:
            print(f"   ✅ Repair impact: minimal change ({repair_impact:.4f})")
        print(f"🔧 POST-ALGORITHM REPAIRS COMPLETE\n")
        
        return best_solution, fitness_history, generation, diversity_history


    def print_timetable(self, individual, student_group, days, hours_per_day, day_start_time=9):
        timetable = [["" for _ in range(days)] for _ in range(hours_per_day)]
        
        # First, fill break time slots on Mon, Wed, Fri
        break_hour = 4  # 13:00 is the 5th hour (index 4) starting from 9:00
        if break_hour < hours_per_day:
            for day in range(days):
                if day in [0, 2, 4]: # Monday, Wednesday, Friday
                    timetable[break_hour][day] = "BREAK"
        
        for room_idx, room_slots in enumerate(individual):
            for timeslot_idx, event in enumerate(room_slots):
                class_event = self.events_map.get(event)
                if class_event is not None and class_event.student_group.id == student_group.id:
                    day = timeslot_idx // hours_per_day
                    hour = timeslot_idx % hours_per_day
                    
                    # Check if it's a break slot that should be skipped in the display
                    is_display_break = (hour == break_hour and day in [0, 2, 4])

                    if day < days and not is_display_break:
                        course = input_data.getCourse(class_event.course_id)
                        faculty = input_data.getFaculty(class_event.faculty_id)
                        course_code = course.code if course is not None else "Unknown"
                        
                        # Use faculty name if available, otherwise use faculty email (ID)
                        if faculty is not None:
                            faculty_display = faculty.name if faculty.name else faculty.faculty_id
                        else:
                            faculty_display = "Unknown"
                        
                        room_obj = input_data.rooms[room_idx]
                        room_display = getattr(room_obj, "name", getattr(room_obj, "Id", str(room_idx)))
                        
                        # Format as: Course Code\nRoom Name\nFaculty Name
                        timetable[hour][day] = f"{course_code}\n{room_display}\n{faculty_display}"
        return timetable

    def print_all_timetables(self, individual, days, hours_per_day, day_start_time=9):
        # app.layout = html.Div([
        #     html.H1("Timetable"),
        #     html.Div([
        #         html.Label("Select Student Group:"),
        #         dcc.Dropdown(
        #             id='student-group-dropdown',
        #             options=[{'label': student_group.name, 'value': student_group.id} for student_group in input_data.student_groups],
        #             value=input_data.student_groups[0].id
        #         ),
        #     ]),
        #     html.Div(id='timetable-container')
        # ])
        data = []
        # Find all unique student groups in the individual
        student_groups = input_data.student_groups
        
        # Print timetable for each student group
        for student_group in student_groups:
            timetable = self.print_timetable(individual, student_group, days, hours_per_day, day_start_time)
            rows = []
            for hour in range(hours_per_day):
                time_label = f"{day_start_time + hour}:00"
                row = [time_label] + [timetable[hour][day] for day in range(days)]
                rows.append(row)
            data.append({"student_group": student_group, "timetable": rows})
        return data

    def ensure_consecutive_slots(self, chromosome):
        """
        Scans the timetable and attempts to repair any multi-hour courses
        that have been split into non-consecutive slots.
        """
        # Group all scheduled events by course and student group
        events_by_course = {}
        for r_idx in range(len(self.rooms)):
            for t_idx in range(len(self.timeslots)):
                event_id = chromosome[r_idx, t_idx]
                if event_id is not None:
                    event = self.events_map.get(event_id)
                    if not event: continue
                    
                    course_key = (event.student_group.id, event.course_id)
                    if course_key not in events_by_course:
                        events_by_course[course_key] = []
                    events_by_course[course_key].append({'event_id': event_id, 'pos': (r_idx, t_idx)})

        for course_key, events in events_by_course.items():
            hours_required = len(events)
            if hours_required < 2:
                continue # Not a multi-hour course that needs checking

            # Check if the events are consecutive
            positions = sorted([e['pos'] for e in events], key=lambda p: p[1])
            is_consecutive = True
            for i in range(len(positions) - 1):
                # Check if they are in the same room and adjacent timeslots
                if not (positions[i][0] == positions[i+1][0] and positions[i][1] + 1 == positions[i+1][1]):
                    is_consecutive = False
                    break
            
            if is_consecutive:
                continue # This course is fine, move to the next one

            # --- If not consecutive, attempt to repair ---
            # 1. Find a new, valid, consecutive block of slots for the entire course
            student_group_id, course_id = course_key
            course = self.input_data.getCourse(course_id)
            
            possible_blocks = []
            for r_idx, room in enumerate(self.rooms):
                if self.is_room_suitable(room, course):
                    for t_start in range(len(self.timeslots) - hours_required + 1):
                        is_block_valid = True
                        # Temporarily clear old positions to check availability
                        temp_chromosome = chromosome.copy()
                        for event_info in events:
                            r, t = event_info['pos']
                            temp_chromosome[r, t] = None
                        
                        for i in range(hours_required):
                            t_check = t_start + i
                            event_to_place = self.events_list[events[i]['event_id']]
                            
                            # Check if the new slot is valid for this event
                            if not (self.is_slot_available_for_event(temp_chromosome, r_idx, t_check, event_to_place) and
                                    self._is_student_group_available(temp_chromosome, student_group_id, t_check) and
                                    self._is_lecturer_available(temp_chromosome, event_to_place.faculty_id, t_check)):
                                is_block_valid = False
                                break
                        
                        if is_block_valid:
                            possible_blocks.append((r_idx, t_start))
            
            # 2. If a valid block is found, perform the move
            if possible_blocks:
                new_r, new_t_start = random.choice(possible_blocks)
                
                # Clear the old, non-consecutive event positions
                for event_info in events:
                    r, t = event_info['pos']
                    chromosome[r, t] = None
                
                # Place the events in the new consecutive block
                for i in range(hours_required):
                    chromosome[new_r, new_t_start + i] = events[i]['event_id']

        return chromosome

    def verify_and_repair_course_allocations(self, chromosome):
        """
        AGGRESSIVE method to ensure every required event is scheduled exactly once.
        MISSING CLASSES MUST NEVER OCCUR - this is the highest priority.
        """
        max_repair_passes = 5  # Increased from 3
        
        for pass_num in range(max_repair_passes):
            # --- Phase 1: Count scheduled events ---
            scheduled_event_counts = {}
            for r_idx in range(len(self.rooms)):
                for t_idx in range(len(self.timeslots)):
                    event_id = chromosome[r_idx, t_idx]
                    if event_id is not None:
                        scheduled_event_counts[event_id] = scheduled_event_counts.get(event_id, 0) + 1

            # --- Phase 2: Remove duplicates ---
            extra_event_ids = {event_id for event_id, count in scheduled_event_counts.items() if count > 1}
            
            if extra_event_ids:
                positions_to_clear = []
                for event_id in extra_event_ids:
                    locations = np.argwhere(chromosome == event_id)
                    # Keep one, mark the rest for removal
                    for i in range(1, len(locations)):
                        positions_to_clear.append(tuple(locations[i]))
                
                for r_idx, t_idx in positions_to_clear:
                    chromosome[r_idx, t_idx] = None
            
            # --- Phase 3: AGGRESSIVELY place missing events ---
            scheduled_events = set(np.unique([e for e in chromosome.flatten() if e is not None]))
            all_required_events = set(range(len(self.events_list)))
            missing_events = list(all_required_events - scheduled_events)
            random.shuffle(missing_events)

            if not missing_events:
                break  # All events are scheduled

            for event_id in missing_events:
                event = self.events_list[event_id]
                course = input_data.getCourse(event.course_id)
                if not course: continue

                placed = False
                
                # Strategy 1: Find perfect slots (no conflicts)
                perfect_slots = []
                for r_idx, room in enumerate(self.rooms):
                    if self.is_room_suitable(room, course):
                        for t_idx in range(len(self.timeslots)):
                            if (chromosome[r_idx, t_idx] is None and
                                self.is_slot_available_for_event(chromosome, r_idx, t_idx, event) and
                                self._is_student_group_available(chromosome, event.student_group.id, t_idx) and
                                self._is_lecturer_available(chromosome, event.faculty_id, t_idx)):
                                perfect_slots.append((r_idx, t_idx))
                
                if perfect_slots:
                    r, t = random.choice(perfect_slots)
                    chromosome[r, t] = event_id
                    placed = True
                    continue
                
                # Strategy 2: Accept student/lecturer conflicts but respect room/time constraints
                acceptable_slots = []
                for r_idx, room in enumerate(self.rooms):
                    if self.is_room_suitable(room, course):
                        for t_idx in range(len(self.timeslots)):
                            if (chromosome[r_idx, t_idx] is None and
                                self.is_slot_available_for_event(chromosome, r_idx, t_idx, event)):
                                acceptable_slots.append((r_idx, t_idx))
                
                if acceptable_slots:
                    r, t = random.choice(acceptable_slots)
                    chromosome[r, t] = event_id
                    placed = True
                    continue
                
                # Strategy 3: FORCE placement by displacing an existing event
                if not placed:
                    # Find any suitable room and displace whatever is there
                    for r_idx, room in enumerate(self.rooms):
                        if self.is_room_suitable(room, course):
                            for t_idx in range(len(self.timeslots)):
                                # Check basic availability (break time, lecturer schedule)
                                if self.is_slot_available_for_event(chromosome, r_idx, t_idx, event):
                                    # Force place this event, even if it displaces another
                                    displaced_event_id = chromosome[r_idx, t_idx]
                                    chromosome[r_idx, t_idx] = event_id
                                    placed = True
                                    
                                    # If we displaced something, try to reschedule it quickly
                                    if displaced_event_id is not None:
                                        self._try_quick_reschedule(chromosome, displaced_event_id)
                                    break
                            if placed:
                                break
                
                # If STILL not placed, something is very wrong - but we continue

        return chromosome
    
    def _try_quick_reschedule(self, chromosome, displaced_event_id):
        """Helper to quickly try to reschedule a displaced event"""
        displaced_event = self.events_list[displaced_event_id]
        displaced_course = input_data.getCourse(displaced_event.course_id)
        
        # Try to find any suitable empty slot
        for r_idx, room in enumerate(self.rooms):
            if self.is_room_suitable(room, displaced_course):
                for t_idx in range(len(self.timeslots)):
                    if (chromosome[r_idx, t_idx] is None and
                        self.is_slot_available_for_event(chromosome, r_idx, t_idx, displaced_event)):
                        chromosome[r_idx, t_idx] = displaced_event_id
                        return True
        return False

    def count_course_occurrences(self, chromosome, student_group):
        """
        Count how many times each course appears for a specific student group
        """
        course_counts = {}
        
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    event = self.events_map.get(event_id)
                    if event and event.student_group.id == student_group.id:
                        course_id = event.course_id
                        course_counts[course_id] = course_counts.get(course_id, 0) + 1
        
        return course_counts

    def diagnose_course_allocations(self, chromosome):
        """
        Diagnostic method to check course allocations for debugging
        """
        print("\n=== COURSE ALLOCATION DIAGNOSIS ===")
        
        # Count total scheduled events
        scheduled_events = set()
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    scheduled_events.add(event_id)
        
        print(f"Total events: {len(self.events_list)}")
        print(f"Scheduled events: {len(scheduled_events)}")
        print(f"Missing events: {len(self.events_list) - len(scheduled_events)}")
        
        # Check each student group
        for student_group in self.student_groups:
            print(f"\nStudent Group: {student_group.name}")
            course_counts = self.count_course_occurrences(chromosome, student_group)
            
            # Calculate expected hours considering 1-credit = 3-hour conversion
            expected_hours = []
            for i in range(len(student_group.hours_required)):
                required_hours = student_group.hours_required[i]
                if required_hours == 1:
                    required_hours = 3
                expected_hours.append(required_hours)
            
            total_expected = sum(expected_hours)
            total_actual = sum(course_counts.values())
            
            print(f"  Total hours: Expected {total_expected}, Got {total_actual}")
            
            for i, course_id in enumerate(student_group.courseIDs):
                expected = expected_hours[i]
                actual = course_counts.get(course_id, 0)
                status = "✓" if actual == expected else "✗"
                print(f"  {course_id}: Expected {expected}, Got {actual} {status}")
        
        print("=== END DIAGNOSIS ===\n")

# Create DE instance and run optimization
print("Starting Differential Evolution")
de = DifferentialEvolution(input_data, 50, 0.4, 0.9)
best_solution, fitness_history, generation, diversity_history = de.run(1)
print("Differential Evolution completed")

# Get final fitness and detailed breakdown (solution is already repaired inside run())
final_fitness = de.evaluate_fitness(best_solution)

# CONSISTENCY CHECK: Ensure constraint violations total matches evaluate_fitness
violations_debug = de.constraints.get_constraint_violations(best_solution, debug=True)
violations_total = violations_debug.get('total', 0)

# Verify consistency between the two fitness calculations
if abs(final_fitness - violations_total) > 0.01:  # Allow small floating point differences
    print(f"⚠️  FITNESS CALCULATION DISCREPANCY DETECTED:")
    print(f"   - evaluate_fitness(): {final_fitness:.4f}")
    print(f"   - violations total:   {violations_total:.4f}")
    print(f"   - Difference:         {abs(final_fitness - violations_total):.4f}")
    print(f"   Using evaluate_fitness() as authoritative value.")
else:
    print(f"✅ Fitness calculations are consistent: {final_fitness:.4f}")

# CRITICAL VERIFICATION: Ensure NO student group clashes in final solution
print("\n--- VERIFYING STUDENT GROUP CLASH PREVENTION ---")
clash_free = de.verify_no_student_group_clashes(best_solution)
if not clash_free:
    print("❌ APPLYING EMERGENCY CLASH PREVENTION...")
    best_solution = de.prevent_student_group_clashes(best_solution)
    print("✅ Emergency prevention applied!")
    de.verify_no_student_group_clashes(best_solution)
print("--- VERIFICATION COMPLETE ---\n")

print("\n--- Running Debugging on Final Solution ---")
violations = de.constraints.get_constraint_violations(best_solution, debug=True)
print("--- Debugging Complete ---\n")

# Store original solution and constraint details for undo and error display
original_best_solution = [row[:] for row in best_solution]  # Deep copy of original solution
constraint_details = de.constraints.get_detailed_constraint_violations(best_solution)

# Store ALL original violations for persistence tracking (both the function above and this)
store_original_violations(constraint_details)

# Store original consecutive violations globally to track them separately
global original_consecutive_violations
original_consecutive_violations = constraint_details.get('Consecutive Slot Violations', []).copy()
print(f"🔒 Stored {len(original_consecutive_violations)} original consecutive violations for tracking")

# Debug: Print initial constraint details for UI debugging
print("\n--- Initial Constraint Details for UI ---")
for constraint_type, violations_list in constraint_details.items():
    if violations_list:
        print(f"  - {constraint_type}: {len(violations_list)} violations")
print("--- End Initial Constraint Details ---\n")

print("\n--- Final Timetable Fitness Breakdown ---")
print(f"Final Fitness Score: {final_fitness:.2f}\n")

print("Constraint Violation Details:")

descriptive_names = {
    'room_constraints': "Room Capacity/Type Conflicts",
    'student_group_constraints': "Student Group Clashes",
    'lecturer_availability': "Lecturer Clashes (Overlapping)",
    'lecturer_schedule_constraints': "Lecturer Schedule Conflicts (Day/Time)",
    'lecturer_workload_constraints': "Lecturer Workload Violations",
    'room_time_conflict': "Room Time Slot Conflicts",
    'building_assignments': "Building Assignment Conflicts",
    'same_course_same_room_per_day': "Same Course in Multiple Rooms on Same Day",
    'break_time_constraint': "Classes During Break Time",
    'course_allocation_completeness': "Missing or Extra Classes",
    'single_event_per_day': "Multiple Events on Same Day (Soft)",
    'consecutive_timeslots': "Consecutive Slot Violations",
    'spread_events': "Poor Event Spreading (Soft)"
}

penalty_info = {
    'room_constraints': "1 point per violation",
    'student_group_constraints': "1 point per violation",
    'lecturer_availability': "1 point per violation",
    'lecturer_schedule_constraints': "10 points per violation",
    'lecturer_workload_constraints': "50 points per extra daily hour, 30 points per extra consecutive hour",
    'room_time_conflict': "10 points per conflict",
    'building_assignments': "0.5 points per violation",
    'same_course_same_room_per_day': "5 points per extra room used",
    'break_time_constraint': "100 points per scheduled class",
    'course_allocation_completeness': "2-5 points per missing hour",
    'single_event_per_day': "0.05 points per extra event on same day",
    'consecutive_timeslots': "0.05 points per hour of multi-hour course",
    'spread_events': "0.025 points per group with clustered events"
}

# Define the desired order for printing constraints
hard_constraint_order = [
    'student_group_constraints',
    'lecturer_availability',
    'lecturer_schedule_constraints',
    'lecturer_workload_constraints',
    'consecutive_timeslots',
    'course_allocation_completeness',
    'same_course_same_room_per_day',
    'room_constraints',
    'room_time_conflict',
    'break_time_constraint'
]

soft_constraint_order = [
    'building_assignments',
    'single_event_per_day',
    'spread_events'
]

# Prepare lines for printing
lines_to_print = {}
max_len = 0

all_constraints_in_violations = [c for c in hard_constraint_order if c in violations] + \
                                [c for c in soft_constraint_order if c in violations]

other_violated_constraints = {k: v for k, v in violations.items() if k not in set(hard_constraint_order + soft_constraint_order) and k != 'total'}
all_constraints_in_violations += sorted(other_violated_constraints.keys())

for constraint in all_constraints_in_violations:
    if constraint in violations:
        points = violations[constraint]
        display_name = descriptive_names.get(constraint, constraint.replace('_', ' ').title())
        
        # Format points to have a consistent look
        if isinstance(points, float):
            # Show 2 decimal places for floats, unless it's a round number
            if points == int(points):
                points_str = str(int(points))
            else:
                points_str = f"{points:.2f}"
        else:
            points_str = str(points)
            
        line_start = f"- {display_name}: {points_str}"
        max_len = max(max_len, len(line_start))
        
        penalty_str = penalty_info.get(constraint, "...")
        lines_to_print[constraint] = (line_start, penalty_str)

print("HARD CONSTRAINTS")
for constraint in hard_constraint_order:
    if constraint in lines_to_print:
        line_start, penalty_str = lines_to_print[constraint]
        # ljust pads the string to the right
        print(f"{line_start.ljust(max_len + 4)}({penalty_str})")

print("\nSOFT CONSTRAINTS")
for constraint in soft_constraint_order:
    if constraint in lines_to_print:
        line_start, penalty_str = lines_to_print[constraint]
        print(f"{line_start.ljust(max_len + 4)}({penalty_str})")

# Print any other constraints that might not be in the main lists
all_printed_constraints = set(hard_constraint_order + soft_constraint_order)
other_constraints_to_print = {k: v for k, v in lines_to_print.items() if k not in all_printed_constraints}

if other_constraints_to_print:
    print("\nOTHER CONSTRAINTS")
    for constraint, (line_start, penalty_str) in sorted(other_constraints_to_print.items()):
        print(f"{line_start.ljust(max_len + 4)}({penalty_str})")

print(f"\n📊 FINAL FITNESS SUMMARY")
print(f"Final Fitness (after post-algorithm repairs): {final_fitness:.2f}")
print(f"Constraint Breakdown Total: {violations.get('total', 'N/A')}")

# Show discrepancy if any
if 'total' in violations and abs(final_fitness - violations['total']) > 0.01:
    print(f"⚠️  Discrepancy: {abs(final_fitness - violations['total']):.4f}")
    print("   (Using Final Total Fitness as authoritative)")
print("--- End of Fitness Breakdown ---\n")

# Get the timetable data from the DE optimization
all_timetables = de.print_all_timetables(best_solution, input_data.days, input_data.hours, 9)

# Convert student_group objects to dictionaries for JSON serialization
for timetable_data in all_timetables:
    if hasattr(timetable_data['student_group'], 'name'):
        timetable_data['student_group'] = {
            'name': timetable_data['student_group'].name,
            'id': getattr(timetable_data['student_group'], 'id', None)
        }

# Save fresh optimization data for download functionality
def save_fresh_optimization_data(data):
    """Save fresh DE optimization data for export functionality"""
    fresh_data_path = os.path.join(os.path.dirname(__file__), 'data', 'fresh_timetable_data.json')
    try:
        with open(fresh_data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✅ Saved fresh optimization data: {len(data)} groups")
    except Exception as e:
        print(f"❌ Error saving fresh optimization data: {e}")

# Save the fresh data
save_fresh_optimization_data(all_timetables)

# Load rooms data for classroom selection
rooms_data = []
try:
    with open(os.path.join(os.path.dirname(__file__), 'data', 'rooms-data.json'), 'r', encoding='utf-8') as f:
        rooms_data = json.load(f)
    print(f"📚 Loaded {len(rooms_data)} rooms for classroom selection")
except Exception as e:
    print(f"❌ Error loading rooms data: {e}")
    rooms_data = []

# Try to load saved timetable if it exists
def load_saved_timetable():
    import os
    import traceback
    
    save_path = os.path.join(os.path.dirname(__file__), 'data', 'timetable_data.json')
    
    print(f"🔍 Checking for saved timetable at: {save_path}")
    
    if os.path.exists(save_path):
        try:
            with open(save_path, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
            
            # MODIFIED: Check for new format {timetables: [...], manual_cells: [...]}
            if isinstance(saved_data, dict) and 'timetables' in saved_data:
                timetables = saved_data.get('timetables', [])
                manual_cells = saved_data.get('manual_cells', [])
                print(f"📁 Loaded new format: {len(timetables)} groups, {len(manual_cells)} manual cells")
                return timetables, manual_cells
            else:
                # Handle old format (just a list of timetables) for backward compatibility
                print(f"📁 Loaded old format: {len(saved_data)} groups")
                return saved_data, []

        except Exception as e:
            print(f"❌ Error loading saved timetable: {e}")
            traceback.print_exc()
    
    return None, None

def clear_saved_timetable():
    """Clear the saved timetable file to start fresh on next run"""
    import os
    save_path = os.path.join(os.path.dirname(__file__), 'data', 'timetable_data.json')
    backup_path = os.path.join(os.path.dirname(__file__), 'data', 'timetable_data_backup.json')
    
    try:
        if os.path.exists(save_path):
            os.remove(save_path)
            print("🗑️ Cleared saved timetable file")
        if os.path.exists(backup_path):
            os.remove(backup_path)
            print("🗑️ Cleared backup timetable file")
    except Exception as e:
        print(f"❌ Error clearing saved files: {e}")

# Always use freshly optimized data on startup - user changes are handled via UI callbacks
print("\n=== LOADING TIMETABLE DATA ===")

# Always start with fresh DE optimization results
print("✅ Using freshly optimized timetable data")
print(f"   Generated {len(all_timetables)} student groups from DE optimization")

# Clear any old saved data to ensure fresh start
clear_saved_timetable()

print("=== TIMETABLE DATA LOADING COMPLETE ===\n")

days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
hours = [f"{9 + i}:00" for i in range(input_data.hours)]

# Session tracker to know if we've made any swaps
session_has_swaps = False

# Store original consecutive violations from the algorithm
original_consecutive_violations = []

def has_any_room_conflicts(all_timetables_data):
    """Check if there are any conflicts (room or lecturer) across all student groups"""
    if not all_timetables_data:
        return False
    
    # Check each time slot across all groups
    for group_idx in range(len(all_timetables_data)):
        conflicts = detect_conflicts(all_timetables_data, group_idx)
        if conflicts:
            return True
    
    return False

def extract_course_and_faculty_from_cell(cell_content):
    """Extract course code and faculty from cell content with new format: Course Code\\nRoom Name\\nFaculty"""
    if not cell_content or cell_content in ["FREE", "BREAK"]:
        return None, None
    
    # Split by newlines and get the first line (course code) and third line (faculty)
    lines = cell_content.split('\n')
    course_code = lines[0].strip() if len(lines) > 0 and lines[0].strip() else None
    faculty_name = lines[2].strip() if len(lines) > 2 and lines[2].strip() else None
    
    return course_code, faculty_name

def extract_room_from_cell(cell_content):
    """Extract room name from cell content with new format: Course Code\\nRoom Name\\nFaculty"""
    if not cell_content or cell_content in ["FREE", "BREAK"]:
        return None
    
    # Split by newlines and get the second line (room name)
    lines = cell_content.split('\n')
    if len(lines) > 1 and lines[1].strip():
        return lines[1].strip()
    return None

def detect_conflicts(all_timetables_data, current_group_idx):
    """Detect both room conflicts and lecturer conflicts across all student groups at each time slot"""
    conflicts = {}
    
    if not all_timetables_data:
        return conflicts
    
    # Get all time slots from the current group's timetable
    current_timetable = all_timetables_data[current_group_idx]['timetable']
    
    for row_idx in range(len(current_timetable)):
        for col_idx in range(1, len(current_timetable[row_idx])):  # Skip time column
            timeslot_key = f"{row_idx}_{col_idx-1}"
            room_usage = {}  # room_name -> [(group_idx, group_name, course_info), ...]
            lecturer_usage = {}  # faculty_name -> [(group_idx, group_name, course_info), ...]
            
            # Check all groups for this time slot
            for group_idx, timetable_data in enumerate(all_timetables_data):
                timetable_rows = timetable_data['timetable']
                if row_idx < len(timetable_rows) and col_idx < len(timetable_rows[row_idx]):
                    cell_content = timetable_rows[row_idx][col_idx]
                    
                    if cell_content and cell_content not in ["FREE", "BREAK"]:
                        room_name = extract_room_from_cell(cell_content)
                        course_code, faculty_name = extract_course_and_faculty_from_cell(cell_content)
                        
                        group_name = timetable_data['student_group']['name'] if isinstance(timetable_data['student_group'], dict) else timetable_data['student_group'].name
                        
                        # Track room usage
                        if room_name:
                            if room_name not in room_usage:
                                room_usage[room_name] = []
                            room_usage[room_name].append((group_idx, group_name, cell_content))
                        
                        # Track lecturer usage
                        if faculty_name and faculty_name != "Unknown":
                            if faculty_name not in lecturer_usage:
                                lecturer_usage[faculty_name] = []
                            lecturer_usage[faculty_name].append((group_idx, group_name, cell_content))
            
            # Check for room conflicts
            for room_name, usage_list in room_usage.items():
                if len(usage_list) > 1:
                    for group_idx, group_name, cell_content in usage_list:
                        if group_idx == current_group_idx:
                            conflicts[timeslot_key] = {
                                'type': 'room',
                                'resource': room_name,
                                'conflicting_groups': [u for u in usage_list if u[0] != current_group_idx]
                            }
            
            # Check for lecturer conflicts
            for faculty_name, usage_list in lecturer_usage.items():
                if len(usage_list) > 1:
                    for group_idx, group_name, cell_content in usage_list:
                        if group_idx == current_group_idx:
                            # If there's already a room conflict, mark it as both
                            if timeslot_key in conflicts:
                                conflicts[timeslot_key]['type'] = 'both'
                                conflicts[timeslot_key]['lecturer'] = faculty_name
                                conflicts[timeslot_key]['lecturer_conflicting_groups'] = [u for u in usage_list if u[0] != current_group_idx]
                            else:
                                conflicts[timeslot_key] = {
                                    'type': 'lecturer',
                                    'resource': faculty_name,
                                    'conflicting_groups': [u for u in usage_list if u[0] != current_group_idx]
                                }
    
    return conflicts

def detect_room_conflicts(all_timetables_data, current_group_idx):
    """Legacy function - now uses the comprehensive detect_conflicts function"""
    return detect_conflicts(all_timetables_data, current_group_idx)

app = dash.Dash(__name__)

# Add CSS styles to the app for drag and drop functionality
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * {
                font-family: 'Poppins', sans-serif;
            }
            .cell {
                padding: 12px 10px;
                border: 1px solid #e0e0e0;
                border-radius: 3px;
                cursor: grab;
                min-height: 45px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 400;
                font-size: 12px;
                transition: all 0.2s ease;
                user-select: none;
                line-height: 1.2;
                text-align: center;
                background-color: white;
                white-space: pre-line;
                word-wrap: break-word;
                overflow-wrap: break-word;
            }
            .cell:hover {
                transform: translateY(-1px);
                box-shadow: 0 2px 6px rgba(0,0,0,0.1);
                border-color: #ccc;
            }
            .cell.dragging {
                opacity: 0.6;
                transform: rotate(2deg);
                cursor: grabbing;
                box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            }
            .cell.drag-over {
                background-color: #fff3cd !important;
                border-color: #ffc107 !important;
                transform: scale(1.02);
                box-shadow: 0 2px 8px rgba(255, 193, 7, 0.6);
            }
            .cell.break-time {
                background-color: #ff5722 !important;
                color: white;
                cursor: not-allowed;
                font-weight: 500;
            }
            .cell.break-time:hover {
                transform: none;
                box-shadow: none;
            }
            .cell.room-conflict {
                background-color: #ffebee !important;
                color: #d32f2f !important;
                border-color: #f44336 !important;
                font-weight: 600 !important;
            }
            .cell.room-conflict:hover {
                background-color: #ffcdd2 !important;
                box-shadow: 0 2px 8px rgba(244, 67, 54, 0.4);
            }
            .cell.lecturer-conflict {
                background-color: #fff0cc !important;
                color: #d4942f !important;
                border-color: #d4942f !important;
                font-weight: 600 !important;
            }
            .cell.lecturer-conflict:hover {
                background-color: #fff8e8 !important;
                box-shadow: 0 2px 8px rgba(244, 67, 54, 0.4);
            }
            .cell.both-conflict {
                background-color: #ffdcec !important;
                color: #d42fa2 !important;
                border-color: #d42fa2 !important;
                font-weight: 600 !important;
            }
            .cell.both-conflict:hover {
                background-color: #ffdcec !important;
                box-shadow: 0 2px 8px rgba(244, 67, 54, 0.4);
            }
            .cell.manual-schedule {
                border: 3px solid #72B7F4 !important;
                box-shadow: 0 0 8px rgba(33, 150, 243, 0.4) !important;
                background-color: #e3f2fd !important;
                position: relative;
            }
            .cell.manual-schedule:hover {
                box-shadow: 0 2px 12px rgba(33, 150, 243, 0.7) !important;
                border-color: #1976d2 !important;
                transform: translateY(-1px);
            }
            .cell.manual-schedule.room-conflict {
                background-color: #ffebee !important;
                border: 3px solid #72B7F4 !important;
                box-shadow: 0 0 8px rgba(33, 150, 243, 0.5) !important;
            }
            .cell.manual-schedule.lecturer-conflict {
                background-color: #fff0cc !important;
                border: 3px solid #72B7F4 !important;
                box-shadow: 0 0 8px rgba(33, 150, 243, 0.5) !important;
            }
            .cell.manual-schedule.both-conflict {
                background-color: #ffebee !important;
                border: 3px solid #72B7F4 !important;
                box-shadow: 0 0 8px rgba(33, 150, 243, 0.5) !important;
            }
            .room-selection-modal {
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: white;
                border-radius: 12px;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
                padding: 25px;
                z-index: 1000;
                max-width: 800px;
                width: 95%;
                max-height: 80vh;
                overflow-y: auto;
                font-family: 'Poppins', sans-serif;
            }
            .modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                z-index: 999;
            }
            .modal-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding-bottom: 15px;
                border-bottom: 2px solid #f0f0f0;
            }
            .modal-title {
                font-size: 18px;
                font-weight: 600;
                color: #11214D;
                margin: 0;
            }
            .modal-close {
                background: none;
                border: none;
                font-size: 24px;
                color: #666;
                cursor: pointer;
                padding: 5px;
                border-radius: 50%;
                transition: all 0.2s ease;
            }
            .modal-close:hover {
                background-color: #f5f5f5;
                color: #333;
            }
            .room-search {
                width: calc(100% - 32px);
                padding: 12px 16px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                font-size: 14px;
                font-family: 'Poppins', sans-serif;
                margin-bottom: 15px;
                transition: border-color 0.2s ease;
                box-sizing: border-box;
            }
            .room-search:focus {
                outline: none;
                border-color: #11214D;
            }
            .room-options {
                max-height: 300px;
                overflow-y: auto;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                background: white;
            }
            .room-option {
                padding: 12px 16px;
                border-bottom: 1px solid #f0f0f0;
                cursor: pointer;
                transition: background-color 0.2s ease;
                font-size: 13px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .room-option:last-child {
                border-bottom: none;
            }
            .room-option:hover {
                background-color: #f8f9fa;
            }
            .room-option.available {
                color: #2e7d32;
                font-weight: 500;
            }
            .room-option.occupied {
                color: #d32f2f;
                font-weight: 500;
            }
            .room-option.selected {
                background-color: #e3f2fd;
                border-left: 4px solid #11214D;
            }
            .room-info {
                font-size: 11px;
                color: #666;
            }
            .conflict-warning {
                position: fixed;
                top: 20px;
                left: 20px;
                background: #ffebee;
                border: 2px solid #f44336;
                border-radius: 8px;
                padding: 15px;
                max-width: 350px;
                z-index: 1001;
                font-family: 'Poppins', sans-serif;
                box-shadow: 0 4px 12px rgba(244, 67, 54, 0.3);
            }
            .conflict-warning-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .conflict-warning-title {
                font-weight: 600;
                color: #d32f2f;
                font-size: 14px;
            }
            .conflict-warning-close {
                background: none;
                border: none;
                font-size: 18px;
                color: #d32f2f;
                cursor: pointer;
                padding: 2px;
            }
            .conflict-warning-content {
                color: #b71c1c;
                font-size: 12px;
                line-height: 1.4;
            }
            .student-group-container {
                margin-bottom: 30px;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                padding: 15px;
                background-color: #fafafa;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                max-width: 1200px;
                margin: 0 auto 30px auto;
            }
            .dropdown-container {
                max-width: 1200px;
                margin: 0 auto;
                padding: 0 15px;
            }
            table {
                font-family: 'Poppins', sans-serif;
                font-size: 12px;
                border-collapse: separate;
                border-spacing: 0;
                width: 100%;
                background-color: white;
                border-radius: 6px;
                overflow: hidden;
                box-shadow: 0 2px 6px rgba(0,0,0,0.08);
            }
            th {
                background-color: #11214D !important;
                color: white !important;
                padding: 12px 10px !important;
                font-size: 13px !important;
                font-weight: 600 !important;
                text-align: center !important;
                border: 1px solid #0d1a3d !important;
                font-family: 'Poppins', sans-serif !important;
            }
            td {
                padding: 0 !important;
                border: 1px solid #e0e0e0 !important;
                background-color: white;
            }
            .time-cell {
                background-color: #11214D !important;
                color: white !important;
                padding: 12px 10px !important;
                font-weight: 600 !important;
                text-align: center !important;
                font-size: 12px !important;
                border: 1px solid #0d1a3d !important;
                font-family: 'Poppins', sans-serif !important;
            }
            .timetable-title {
                color: #11214D;
                font-weight: 600;
                margin-bottom: 20px;
                font-size: 20px;
                font-family: 'Poppins', sans-serif;
            }
            .timetable-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding: 0 10px;
            }

            .help-modal {
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: white;
                border-radius: 12px;
                box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
                padding: 30px;
                z-index: 1000;
                max-width: 600px;
                width: 90%;
                max-height: 80vh;
                overflow-y: auto;
                font-family: 'Poppins', sans-serif;
            }
            .help-modal h3 {
                color: #11214D;
                font-weight: 600;
                margin-bottom: 20px;
                font-size: 20px;
                text-align: center;
            }
            .help-section {
                margin-bottom: 20px;
            }
            .help-section h4 {
                color: #11214D;
                font-weight: 600;
                margin-bottom: 10px;
                font-size: 16px;
            }
            .help-section p {
                color: #555;
                line-height: 1.6;
                margin-bottom: 10px;
                font-size: 14px;
            }
            .help-note {
                background-color: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 8px;
                padding: 15px;
                margin-bottom: 20px;
                color: #856404;
                font-weight: 500;
            }
            .color-legend {
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            .color-item {
                display: flex;
                align-items: center;
                gap: 10px;
            }
            .color-box {
                width: 20px;
                height: 20px;
                border-radius: 4px;
                border: 1px solid #ccc;
            }
            .color-box.manual { background-color: #72b7f4; }
            .color-box.normal { background-color: white; }
            .color-box.break { background-color: #ff5722; }
            .color-box.room-conflict { background-color: #ffebee; border-color: #f44336; }
            .color-box.lecturer-conflict { background-color: #ffd982; border-color: #d4942f; }
            .color-box.both-conflict { background-color: #ffdcec; border-color: #d42fa2; }

            .nav-arrows {
                display: flex;
                align-items: center;
                gap: 15px;
            }
            .nav-arrow {
                background: #11214D;
                color: white;
                border: none;
                border-radius: 15%;
                width: 40px;
                height: 40px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
                transition: all 0.2s ease;
                font-family: 'Poppins', sans-serif;
            }
            .nav-arrow:hover {
                background: #0d1a3d;
                transform: scale(1.05);
                box-shadow: 0 2px 8px rgba(17, 33, 77, 0.3);
            }
            .nav-arrow:disabled {
                background: #ccc;
                cursor: not-allowed;
                transform: none;
                box-shadow: none;
            }
            .save-error {
                position: fixed;
                top: 20px;
                left: 50%;
                transform: translateX(-50%);
                background: #ffebee;
                border: 2px solid #f44336;
                border-radius: 8px;
                padding: 15px 20px;
                max-width: 400px;
                z-index: 1001;
                font-family: 'Poppins', sans-serif;
                box-shadow: 0 4px 12px rgba(244, 67, 54, 0.3);
                text-align: center;
            }
            .save-error-title {
                font-weight: 600;
                color: #d32f2f;
                font-size: 14px;
                margin-bottom: 8px;
            }
            .save-error-content {
                color: #b71c1c;
                font-size: 12px;
                line-height: 1.4;
            }
            .constraint-dropdown {
                margin-bottom: 15px;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                overflow: hidden;
            }
            .constraint-header {
                background-color: #f8f9fa;
                padding: 12px 16px;
                cursor: pointer;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-weight: 600;
                font-size: 14px;
                color: #11214D;
                border-bottom: 1px solid #e0e0e0;
                transition: background-color 0.2s ease;
                gap: 15px;
            }
            .constraint-header:hover {
                background-color: #e9ecef;
            }
            .constraint-header.active {
                background-color: #11214D;
                color: white;
            }
            .constraint-count {
                color: white;
                padding: 4px 8px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: 600;
            }
            .constraint-count.zero {
                background-color: #28a745;
            }
            .constraint-count.non-zero {
                background-color: #dc3545;
            }
            .constraint-header.active .constraint-count {
                background-color: rgba(255, 255, 255, 0.2);
            }
            .constraint-details {
                padding: 0;
                max-height: 0;
                overflow: hidden;
                transition: max-height 0.3s ease-out;
                background: white;
            }
            .constraint-details.expanded {
                max-height: 300px;
                overflow-y: auto;
                border-top: 1px solid #e0e0e0;
            }
            .constraint-item {
                padding: 10px 16px;
                border-bottom: 1px solid #f0f0f0;
                font-size: 13px;
                line-height: 1.4;
                color: #666;
                word-wrap: break-word;
                overflow-wrap: break-word;
            }
            .constraint-item:last-child {
                border-bottom: none;
            }
            .constraint-arrow {
                font-weight: bold;
                transition: transform 0.3s ease;
                font-family: monospace;
                font-size: 16px;
            }
            .constraint-arrow.rotated {
                transform: rotate(180deg);
            }
            .errors-button {
                position: relative;
                background: #dc3545;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 14px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s ease;
                font-family: 'Poppins', sans-serif;
                box-shadow: 0 2px 4px rgba(220, 53, 69, 0.3);
            }
            .errors-button:hover {
                background: #c82333;
                transform: translateY(-1px);
                box-shadow: 0 4px 8px rgba(220, 53, 69, 0.4);
            }
            .errors-button:disabled {
                background: #6c757d;
                cursor: not-allowed;
                transform: none;
                box-shadow: none;
            }
            .error-notification {
                position: absolute;
                top: -8px;
                right: -8px;
                background: rgba(255, 255, 255, 0.9);
                color: #dc3545;
                border: 2px solid #dc3545;
                border-radius: 50%;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                font-weight: 700;
                font-family: 'Poppins', sans-serif;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

app.layout = html.Div([
    # Title and dropdown on the same line
    html.Div([
        html.H1("Interactive Drag & Drop Timetable - DE Optimization Results", 
                style={"color": "#11214D", "fontWeight": "600", "fontSize": "24px", 
                      "fontFamily": "Poppins, sans-serif", "margin": "0", "flex": "1"}),
        
        html.Div([
            dcc.Dropdown(
                id='student-group-dropdown',
                options=[{'label': timetable_data['student_group']['name'] if isinstance(timetable_data['student_group'], dict) 
                                  else timetable_data['student_group'].name, 'value': idx} 
                        for idx, timetable_data in enumerate(all_timetables)],
                value=0,
                searchable=True,
                clearable=False,
                style={"width": "280px", "fontSize": "13px", "fontFamily": "Poppins, sans-serif"}
            )
        ], style={"display": "flex", "alignItems": "center"})
    ], style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", 
             "marginTop": "30px", "marginBottom": "30px", "maxWidth": "1200px", 
             "margin": "30px auto", "padding": "0 15px"}),
    
    # Store for timetable data
    dcc.Store(id="all-timetables-store", data=all_timetables),
    
    # Store for rooms data
    dcc.Store(id="rooms-data-store", data=rooms_data),
    
    # Store for original timetable (for undo functionality)
    dcc.Store(id="original-timetables-store", data=[timetable_data.copy() for timetable_data in all_timetables]),
    
    # Store for constraint violation details (for errors popup)
    dcc.Store(id="constraint-details-store", data=constraint_details),
    
    # Store for communicating swaps
    dcc.Store(id="swap-data", data=None),
    
    # Store for room changes
    dcc.Store(id="room-change-data", data=None),
    
    # Store for missing class scheduling
    dcc.Store(id="missing-class-data", data=None),
    
    # Store for manually scheduled cells
    dcc.Store(id="manual-cells-store", data=[]),
    
    # Hidden div to trigger the setup
    html.Div(id="trigger", style={"display": "none"}),
    
    # Timetable container
    html.Div(id="timetable-container"),
    
    # Room selection modal (initially hidden)
    html.Div([
        html.Div(className="modal-overlay", id="modal-overlay", style={"display": "none"}),
        html.Div([
            html.Div([
                html.H3("Select Classroom", className="modal-title"),
                html.Button("×", className="modal-close", id="modal-close-btn")
            ], className="modal-header"),
            
            dcc.Input(
                id="room-search-input",
                type="text",
                placeholder="Search classrooms...",
                className="room-search"
            ),
            
            html.Div(id="room-options-container", className="room-options"),
            
            html.Div([                html.Button("Cancel", id="room-cancel-btn", 
                           style={"backgroundColor": "#f5f5f5", "color": "#666", "padding": "8px 16px", 
                                 "border": "1px solid #ddd", "borderRadius": "5px", "marginRight": "10px",
                                 "cursor": "pointer", "fontFamily": "Poppins, sans-serif"}),
                html.Button("DELETE SCHEDULE", id="room-delete-btn", 
                           style={"backgroundColor": "#dc3545", "color": "white", "padding": "8px 16px", 
                                 "border": "none", "borderRadius": "5px", "cursor": "pointer", "marginRight": "10px",
                                 "fontFamily": "Poppins, sans-serif", "fontWeight": "600", "display": "none"}),
                html.Button("Confirm", id="room-confirm-btn", 
                           style={"backgroundColor": "#11214D", "color": "white", "padding": "8px 16px", 
                                 "border": "none", "borderRadius": "5px", "cursor": "pointer",
                                 "fontFamily": "Poppins, sans-serif"})
            ], style={"textAlign": "right", "marginTop": "20px", "paddingTop": "15px", 
                     "borderTop": "1px solid #f0f0f0"})
        ], className="room-selection-modal", id="room-selection-modal", style={"display": "none"})
    ]),
    
    # Missing classes modal (initially hidden)
    html.Div([
        html.Div(className="modal-overlay", id="missing-modal-overlay", style={"display": "none"}),
        html.Div([
            html.Div([
                html.H3("Missing Classes", className="modal-title"),
                html.Button("×", className="modal-close", id="missing-modal-close-btn")
            ], className="modal-header"),
            
            html.Div(id="missing-classes-container", className="room-options"),
            
            html.Div([
                html.Button("Cancel", id="missing-cancel-btn", 
                           style={"backgroundColor": "#f5f5f5", "color": "#666", "padding": "8px 16px", 
                                 "border": "1px solid #ddd", "borderRadius": "5px", "cursor": "pointer",
                                 "fontFamily": "Poppins, sans-serif"})
            ], style={"textAlign": "right", "marginTop": "20px", "paddingTop": "15px", 
                     "borderTop": "1px solid #f0f0f0"})
        ], className="room-selection-modal", id="missing-classes-modal", style={"display": "none"})
    ]),
    
    # Errors modal (initially hidden)
    html.Div([
        html.Div(className="modal-overlay", id="errors-modal-overlay", style={"display": "none"}),
        html.Div([
            html.Div([
                html.H3("Constraint Violations", className="modal-title"),
                html.Button("×", className="modal-close", id="errors-modal-close-btn")
            ], className="modal-header"),
            
            html.Div(id="errors-content"),
            
            html.Div([
                html.Button("Close", id="errors-close-btn", 
                           style={"backgroundColor": "#11214D", "color": "white", "padding": "8px 16px", 
                                 "border": "none", "borderRadius": "5px", "cursor": "pointer",
                                 "fontFamily": "Poppins, sans-serif"})
            ], style={"textAlign": "right", "marginTop": "20px", "paddingTop": "15px", 
                     "borderTop": "1px solid #f0f0f0"})
        ], className="room-selection-modal", id="errors-modal", style={"display": "none"})
    ]),
    
    # Download modal (initially hidden)
    html.Div([
        html.Div(className="modal-overlay", id="download-modal-overlay", style={"display": "none"}),
        html.Div([
            html.Div([
                html.H3("Download Timetables", className="modal-title"),
                html.Button("×", className="modal-close", id="download-modal-close-btn")
            ], className="modal-header"),
            
            html.Div([
                # SST Timetables row
                html.Div([
                    html.Span("Download SST Timetables", style={"flex": "1", "fontSize": "16px", "fontWeight": "500"}),
                    html.Button("Download", id="download-sst-btn", 
                               style={"backgroundColor": "#11214D", "color": "white", "padding": "8px 16px", 
                                     "border": "none", "borderRadius": "5px", "cursor": "pointer",
                                     "fontFamily": "Poppins, sans-serif", "fontSize": "14px"})
                ], style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", 
                         "padding": "15px", "borderBottom": "1px solid #f0f0f0"}),
                
                # TYD Timetables row
                html.Div([
                    html.Span("Download TYD Timetables", style={"flex": "1", "fontSize": "16px", "fontWeight": "500"}),
                    html.Button("Download", id="download-tyd-btn", 
                               style={"backgroundColor": "#11214D", "color": "white", "padding": "8px 16px", 
                                     "border": "none", "borderRadius": "5px", "cursor": "pointer",
                                     "fontFamily": "Poppins, sans-serif", "fontSize": "14px"})
                ], style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", 
                         "padding": "15px", "borderBottom": "1px solid #f0f0f0"}),
                
                # Lecturer Timetables row
                html.Div([
                    html.Span("Download all Lecturer Timetables", style={"flex": "1", "fontSize": "16px", "fontWeight": "500"}),
                    html.Button("Download", id="download-lecturer-btn", 
                               style={"backgroundColor": "#11214D", "color": "white", "padding": "8px 16px", 
                                     "border": "none", "borderRadius": "5px", "cursor": "pointer",
                                     "fontFamily": "Poppins, sans-serif", "fontSize": "14px"})
                ], style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", 
                         "padding": "15px"})
            ]),
            
            html.Div([
                html.Button("Close", id="download-close-btn", 
                           style={"backgroundColor": "#6c757d", "color": "white", "padding": "8px 16px", 
                                 "border": "none", "borderRadius": "5px", "cursor": "pointer",
                                 "fontFamily": "Poppins, sans-serif"})
            ], style={"textAlign": "right", "marginTop": "20px", "paddingTop": "15px", 
                     "borderTop": "1px solid #f0f0f0"})
        ], className="room-selection-modal", id="download-modal", style={"display": "none"})
    ]),
    
    # Conflict warning popup (initially hidden)
    html.Div([
        html.Div([
            html.Span("⚠️ Classroom Conflict", className="conflict-warning-title"),
            html.Button("×", className="conflict-warning-close", id="conflict-close-btn")
        ], className="conflict-warning-header"),
        html.Div(id="conflict-warning-text", className="conflict-warning-content")
    ], className="conflict-warning", id="conflict-warning", style={"display": "none"}),
    
    # Save error popup (initially hidden)
    html.Div([
        html.Div("❌ Cannot Save Timetable", className="save-error-title"),
        html.Div("Please resolve all classroom conflicts before saving the timetable.", className="save-error-content")
    ], className="save-error", id="save-error", style={"display": "none"}),
    
    # Button to download timetables
    html.Div([
        html.Button("Download Timetables", id="download-button", 
                   style={"backgroundColor": "#11214D", "color": "white", "padding": "10px 20px", 
                         "border": "none", "borderRadius": "5px", "fontSize": "14px", "cursor": "pointer",
                         "fontWeight": "600", "boxShadow": "0 1px 3px rgba(0,0,0,0.1)",
                         "transition": "all 0.2s ease", "fontFamily": "Poppins, sans-serif"}),
        html.Div(id="download-status", style={"marginTop": "12px", "fontWeight": "600", 
                                         "fontFamily": "Poppins, sans-serif", "fontSize": "12px"})
    ], style={"textAlign": "center", "marginTop": "30px", "maxWidth": "1200px", "margin": "30px auto 0 auto"}),
    
    # Feedback area
    html.Div(id="feedback", style={
        "marginTop": "20px", 
        "textAlign": "center", 
        "fontSize": "16px", 
        "fontWeight": "bold",
        "minHeight": "30px",
        "maxWidth": "1200px",
        "margin": "20px auto 0 auto"
    }),
    
    # Help modal (initially hidden)
    html.Div([
        html.Div(className="modal-overlay", id="help-modal-overlay", style={"display": "none"}),
        html.Div([
            html.Div([
                html.H3("Timetable Help Guide", className="modal-title"),
                html.Button("×", className="modal-close", id="help-modal-close-btn")
            ], className="modal-header"),
            
            html.Div([
                html.Div([
                    html.Strong("NOTE: "),
                    "Ensure all Lecturer names, emails and other details are inputted correctly to prevent errors"
                ], className="help-note"),
                
                html.Div([
                    html.H4("How to Use the Timetable:"),
                    html.P("• Click and drag any class cell to swap it with another cell"),
                    html.P("• Double-click any cell to view and change the classroom for that class"),
                    html.P("• Use the navigation arrows (‹ ›) to switch between different student groups"),
                    html.P("• Click 'View Errors' to see constraint violations and conflicts")
                ], className="help-section"),
                
                html.Div([
                    html.H4("Cell Color Meanings:"),
                    html.Div([
                        html.Div([
                            html.Div(className="color-box normal"),
                            html.Span("Normal class - No conflicts")
                        ], className="color-item"),
                        html.Div([
                            html.Div(className="color-box manual"),
                            html.Span("Manually Scheduled - Class scheduled manually from the 'Missing Classes' list.")
                        ], className="color-item"),
                        html.Div([
                            html.Div(className="color-box break"),
                            html.Span("Break time - Classes cannot be scheduled")
                        ], className="color-item"),
                        html.Div([
                            html.Div(className="color-box room-conflict"),
                            html.Span("Room conflict - Same classroom used by multiple groups")
                        ], className="color-item"),
                        html.Div([
                            html.Div(className="color-box lecturer-conflict"),
                            html.Span("Lecturer conflict - Same lecturer teaching multiple groups")
                        ], className="color-item"),
                        html.Div([
                            html.Div(className="color-box both-conflict"),
                            html.Span("Multiple conflicts - Both room and lecturer issues")
                        ], className="color-item")
                    ], className="color-legend")
                ], className="help-section")
            ]),
            
            html.Div([
                html.Button("Close", id="help-close-btn", 
                           style={"backgroundColor": "#11214D", "color": "white", "padding": "10px 20px", 
                                 "border": "none", "borderRadius": "8px", "cursor": "pointer",
                                 "fontFamily": "Poppins, sans-serif", "fontSize": "14px", "fontWeight": "600"})
            ], style={"textAlign": "center", "marginTop": "25px", "paddingTop": "20px", 
                     "borderTop": "2px solid #f0f0f0"})
        ], className="help-modal", id="help-modal", style={"display": "none"})
    ])
])

@app.callback(
    [Output("timetable-container", "children"),
     Output("trigger", "children")],
    [Input("student-group-dropdown", "value")],
    [State("all-timetables-store", "data"),
     State("manual-cells-store", "data")]
)
def create_timetable(selected_group_idx, all_timetables_data, manual_cells):
    # Only load saved data if we're in an active session and there have been changes
    # Don't load on fresh startup - use the fresh DE results
    global all_timetables
    
    if selected_group_idx is None or not all_timetables_data:
        return html.Div("No data available"), "trigger"
    
    # Ensure selected_group_idx is within bounds
    if selected_group_idx >= len(all_timetables_data):
        print(f"Selected group index {selected_group_idx} out of bounds (max: {len(all_timetables_data)-1})")
        selected_group_idx = 0
        
    # Get the selected student group data
    timetable_data = all_timetables_data[selected_group_idx]
    student_group_name = timetable_data['student_group']['name'] if isinstance(timetable_data['student_group'], dict) else timetable_data['student_group'].name
    timetable_rows = timetable_data['timetable']
    
    # Detect conflicts (both room and lecturer) across all time slots
    conflicts = detect_conflicts(all_timetables_data, selected_group_idx)
    
    # Create table rows
    rows = []
    
    # Header row
    header_cells = [html.Th("Time", style={
        "backgroundColor": "#11214D", 
        "color": "white", 
        "padding": "12px 10px",
        "fontWeight": "600",
        "fontSize": "13px",
        "textAlign": "center",
        "border": "1px solid #0d1a3d",
        "fontFamily": "Poppins, sans-serif"
    })]
    
    for day in days_of_week:
        header_cells.append(html.Th(day, style={
            "backgroundColor": "#11214D", 
            "color": "white", 
            "padding": "12px 10px",
            "fontWeight": "600",
            "fontSize": "13px",
            "textAlign": "center",
            "border": "1px solid #0d1a3d",
            "fontFamily": "Poppins, sans-serif"
        }))
    
    rows.append(html.Thead(html.Tr(header_cells)))
    
    # Data rows
    body_rows = []
    
    for row_idx in range(len(timetable_rows)):
        cells = [html.Td(timetable_rows[row_idx][0], className="time-cell")]  # Time column with special class
        
        for col_idx in range(1, len(timetable_rows[row_idx])):  # Skip time column
            cell_content = timetable_rows[row_idx][col_idx] if timetable_rows[row_idx][col_idx] else "FREE"
            cell_id = {"type": "cell", "group": selected_group_idx, "row": row_idx, "col": col_idx-1}
            
            # Check if this is a break time
            is_break = cell_content == "BREAK"
            
            # Check for conflicts (room, lecturer, or both)
            timeslot_key = f"{row_idx}_{col_idx-1}"
            has_conflict = timeslot_key in conflicts
            conflict_type = conflicts.get(timeslot_key, {}).get('type', 'none') if has_conflict else 'none'
            
            # Check if this is a manually scheduled cell
            manual_cell_key = f"{selected_group_idx}_{row_idx}_{col_idx-1}"
            is_manual = manual_cells and manual_cell_key in manual_cells
            
            # Determine cell class based on conflict type and manual scheduling
            if is_break:
                cell_class = "cell break-time"
                draggable = "false"
            elif is_manual:
                # Manual cells get blue outline regardless of conflicts
                if conflict_type == 'room':
                    cell_class = "cell room-conflict manual-schedule"
                elif conflict_type == 'lecturer':
                    cell_class = "cell lecturer-conflict manual-schedule"
                elif conflict_type == 'both':
                    cell_class = "cell both-conflict manual-schedule"
                else:
                    cell_class = "cell manual-schedule"
                draggable = "true"
            elif conflict_type == 'room':
                cell_class = "cell room-conflict"
                draggable = "true"
            elif conflict_type == 'lecturer':
                cell_class = "cell lecturer-conflict"
                draggable = "true"
            elif conflict_type == 'both':
                cell_class = "cell both-conflict"
                draggable = "true"
            else:
                cell_class = "cell"
                draggable = "true"
            
            cells.append(
                html.Td(
                    html.Div(
                        cell_content,
                        id=cell_id,
                        className=cell_class,
                        draggable=draggable,
                        n_clicks=0
                    ),
                    style={"padding": "0", "border": "1px solid #e0e0e0"}
                )
            )
        
        body_rows.append(html.Tr(cells))
    
    rows.append(html.Tbody(body_rows))
    
    table = html.Table(rows, style={
        "width": "100%",
        "borderCollapse": "separate",
        "borderSpacing": "0",
        "backgroundColor": "white",
        "borderRadius": "6px",
        "overflow": "hidden",
        "fontSize": "12px",
        "boxShadow": "0 2px 6px rgba(0,0,0,0.08)",
        "fontFamily": "Poppins, sans-serif"
    })
    
    return html.Div([
        html.Div([
            html.Div([
                html.H2(f"Timetable for {student_group_name}", 
                       className="timetable-title",
                       style={"color": "#11214D", "fontWeight": "600", "fontSize": "20px", 
                             "fontFamily": "Poppins, sans-serif", "margin": "0"})
            ], className="timetable-title-container"),
            html.Div([
                html.Button("‹", className="nav-arrow", id="prev-group-btn",
                           disabled=selected_group_idx == 0),
                html.Button("›", className="nav-arrow", id="next-group-btn", 
                           disabled=selected_group_idx == len(all_timetables_data) - 1)
            ], className="nav-arrows")
        ], className="timetable-header"),
        
        # New buttons row with help button
        html.Div([
            html.Button([
                "View Errors",
                html.Div(id="error-notification-badge", className="error-notification")
            ], id="errors-btn", className="errors-button"),
            html.Button("Undo All Changes", id="undo-all-btn", 
                       style={"backgroundColor": "#6c757d", "color": "white", "padding": "8px 16px", 
                             "border": "none", "borderRadius": "5px", "fontSize": "14px", "cursor": "pointer",
                             "fontWeight": "500", "fontFamily": "Poppins, sans-serif"}),
            html.Button("?", id="help-icon-btn", title="Help", 
                       className="nav-arrow", style={"marginLeft": "auto"})
        ], style={"marginBottom": "15px", "marginRight": "10px", "textAlign": "left", "display": "flex", "gap": "10px", "alignItems": "flex-start"}),
        
        table
    ], className="student-group-container"), "trigger"

# Callback to update timetable content when swaps occur (without changing dropdown)
@app.callback(
    Output("timetable-container", "children", allow_duplicate=True),
    Input("all-timetables-store", "data"),
    [State("student-group-dropdown", "value"),
     State("manual-cells-store", "data")],
    prevent_initial_call=True
)
def update_timetable_content(all_timetables_data, selected_group_idx, manual_cells):
    """Update timetable content when data changes (e.g., from swaps) without affecting navigation"""
    print(f"📊 Update timetable content triggered - group: {selected_group_idx}")
    
    if selected_group_idx is None or not all_timetables_data:
        print(f"📊 Preventing update - invalid data: group={selected_group_idx}, data_exists={bool(all_timetables_data)}")
        raise dash.exceptions.PreventUpdate
    
    # CRITICAL FIX: Ensure we're working with the right group index
    # Don't allow updates if the selected group index seems out of sync
    if selected_group_idx >= len(all_timetables_data):
        print(f"📊 Preventing update - group index {selected_group_idx} out of bounds (max: {len(all_timetables_data) - 1})")
        raise dash.exceptions.PreventUpdate
        
    # Get the selected student group data
    timetable_data = all_timetables_data[selected_group_idx]
    student_group_name = timetable_data['student_group']['name'] if isinstance(timetable_data['student_group'], dict) else timetable_data['student_group'].name
    timetable_rows = timetable_data['timetable']
    
    # Detect conflicts (both room and lecturer) across all time slots
    conflicts = detect_conflicts(all_timetables_data, selected_group_idx)
    
    # Create table rows (same logic as create_timetable but only return the container content)
    rows = []
    
    # Header row
    header_cells = [html.Th("Time", style={
        "backgroundColor": "#11214D", 
        "color": "white", 
        "padding": "12px 10px",
        "fontSize": "13px",
        "fontWeight": "600",
        "textAlign": "center",
        "border": "1px solid #0d1a3d",
        "fontFamily": "Poppins, sans-serif"
    })]
    
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for day in days_of_week:
        header_cells.append(html.Th(day, style={
            "backgroundColor": "#11214D",
            "color": "white",
            "padding": "12px 10px",
            "fontSize": "13px",
            "fontWeight": "600",
            "textAlign": "center",
            "border": "1px solid #0d1a3d",
            "fontFamily": "Poppins, sans-serif"
        }))
    
    rows.append(html.Thead(html.Tr(header_cells)))
    
    # Data rows
    body_rows = []
    hours = [f"{9 + i}:00" for i in range(len(timetable_rows))]
    
    for row_idx in range(len(timetable_rows)):
        row_cells = []
        
        # Time cell
        row_cells.append(html.Td(hours[row_idx], className="time-cell"))
        
        # Data cells for each day
        for col_idx in range(1, len(timetable_rows[row_idx])):
            cell_content = timetable_rows[row_idx][col_idx] if timetable_rows[row_idx][col_idx] else "FREE"
            
            # Create cell ID for drag and drop (consistent with create_timetable format)
            cell_id = {"type": "cell", "group": selected_group_idx, "row": row_idx, "col": col_idx - 1}
            
            # Determine cell styling
            is_break = cell_content == "BREAK"
            timeslot_key = f"{row_idx}_{col_idx-1}"
            has_conflict = timeslot_key in conflicts
            conflict_type = conflicts.get(timeslot_key, {}).get('type', 'none') if has_conflict else 'none'
            
            # Check if this is a manually scheduled cell
            manual_cell_key = f"{selected_group_idx}_{row_idx}_{col_idx-1}"
            is_manual = manual_cells and manual_cell_key in manual_cells
            
            if is_break:
                cell_class = "cell break-time"
                draggable = False
            elif is_manual:
                # Manual cells get blue outline regardless of conflicts
                if conflict_type == 'room':
                    cell_class = "cell room-conflict manual-schedule"
                elif conflict_type == 'lecturer':
                    cell_class = "cell lecturer-conflict manual-schedule"
                elif conflict_type == 'both':
                    cell_class = "cell both-conflict manual-schedule"
                else:
                    cell_class = "cell manual-schedule"
                draggable = True
            elif conflict_type == 'room':
                cell_class = "cell room-conflict"
                draggable = True
            elif conflict_type == 'lecturer':
                cell_class = "cell lecturer-conflict"
                draggable = True
            elif conflict_type == 'both':
                cell_class = "cell both-conflict"
                draggable = True
            else:
                cell_class = "cell"
                draggable = True
            
            row_cells.append(html.Td(
                html.Div(
                    cell_content,
                    className=cell_class,
                    id=cell_id,
                    draggable=draggable,
                    n_clicks=0
                )
            ))
        
        body_rows.append(html.Tr(row_cells))
    
    rows.append(html.Tbody(body_rows))
    
    table = html.Table(rows, style={
        "width": "100%",
        "borderCollapse": "separate",
        "borderSpacing": "0",
        "backgroundColor": "white",
        "borderRadius": "6px",
        "overflow": "hidden",
        "fontSize": "12px",
        "boxShadow": "0 2px 6px rgba(0,0,0,0.08)",
        "fontFamily": "Poppins, sans-serif"
    })
    
    return html.Div([
        html.Div([
            html.Div([
                html.H2(f"Timetable for {student_group_name}", className="timetable-title")
            ], className="timetable-title-container"),
            html.Div([
                html.Button("‹", className="nav-arrow", id="prev-group-btn",
                           disabled=selected_group_idx == 0),
                html.Button("›", className="nav-arrow", id="next-group-btn", 
                           disabled=selected_group_idx == len(all_timetables_data) - 1)
            ], className="nav-arrows")
        ], className="timetable-header"),
        
        # New buttons row with help button
        html.Div([
            html.Button([
                "View Errors",
                html.Div(id="error-notification-badge", className="error-notification")
            ], id="errors-btn", className="errors-button"),
            html.Button("Undo All Changes", id="undo-all-btn", 
                       style={"backgroundColor": "#6c757d", "color": "white", "padding": "8px 16px", 
                             "border": "none", "borderRadius": "5px", "fontSize": "14px", "cursor": "pointer",
                             "fontWeight": "500", "fontFamily": "Poppins, sans-serif"}),
            html.Button("?", id="help-icon-btn", title="Help", 
                       className="nav-arrow", style={"marginLeft": "auto"})
        ], style={"marginBottom": "15px", "marginRight": "10px", "textAlign": "left", "display": "flex", "gap": "10px", "alignItems": "flex-start"}),
        
        table
    ], className="student-group-container")

# Callback to handle navigation arrows
@app.callback(
    Output("student-group-dropdown", "value"),
    [Input("prev-group-btn", "n_clicks"),
     Input("next-group-btn", "n_clicks")],
    [State("student-group-dropdown", "value"),
     State("all-timetables-store", "data")],
    prevent_initial_call=True
)
def handle_navigation(prev_clicks, next_clicks, current_value, all_timetables_data):
    ctx = dash.callback_context
    if not ctx.triggered or not all_timetables_data:
        raise dash.exceptions.PreventUpdate
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    click_value = ctx.triggered[0]['value']
    
    # Add debugging to detect unexpected triggers
    print(f"🔍 Navigation callback triggered by: {button_id}")
    print(f"🔍 Context triggered: {ctx.triggered}")
    print(f"🔍 Current value: {current_value}")
    print(f"🔍 Click value: {click_value}")
    
    # CRITICAL FIX: Ignore navigation if click value is None or 0 (spurious triggers)
    if click_value is None or click_value == 0:
        print(f"🚫 Ignoring spurious navigation trigger - click value is {click_value}")
        raise dash.exceptions.PreventUpdate
    
    # Ensure we have a valid current value
    if current_value is None:
        current_value = 0
    
    # Ensure current_value is within bounds
    max_index = len(all_timetables_data) - 1
    current_value = max(0, min(current_value, max_index))
    
    if button_id == "prev-group-btn" and current_value > 0:
        new_value = current_value - 1
        print(f"✅ Navigation: Moving from group {current_value} to {new_value} (prev)")
        return new_value
    elif button_id == "next-group-btn" and current_value < max_index:
        new_value = current_value + 1
        print(f"✅ Navigation: Moving from group {current_value} to {new_value} (next)")
        return new_value
    else:
        print(f"❌ Navigation: Invalid navigation attempt - button: {button_id}, current: {current_value}, max: {max_index}")
    
    raise dash.exceptions.PreventUpdate

# Client-side callback for drag and drop functionality and double-click room selection
clientside_callback(
    """
    function(trigger) {
        console.log('Setting up drag and drop and double-click functionality...');
        
        // Global variables for drag state
        window.draggedElement = null;
        window.dragStartData = null;
        window.selectedCell = null;
        
        function setupDragAndDrop() {
            const cells = document.querySelectorAll('.cell');
            console.log('Found', cells.length, 'draggable cells');
            
            // Clear any existing global drag state when setting up
            window.draggedElement = null;
            window.dragStartData = null;
            window.selectedCell = null;
            
            cells.forEach(function(cell) {
                // Clear existing listeners
                cell.ondragstart = null;
                cell.ondragover = null;
                cell.ondragenter = null;
                cell.ondragleave = null;
                cell.ondrop = null;
                cell.ondragend = null;
                cell.ondblclick = null;
                
                // Remove any existing drag-related classes
                cell.classList.remove('dragging', 'drag-over');
                
                // Double-click handler for room selection and FREE cell scheduling
                cell.ondblclick = function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    console.log('Double-click detected on cell');
                    
                    // Handle FREE cell double-click for manual scheduling
                    if (this.textContent.trim() === 'FREE') {
                        console.log('FREE cell double-clicked - showing missing classes');
                        window.selectedCell = this;
                        
                        // Show missing classes modal
                        const modal = document.getElementById('missing-classes-modal');
                        const overlay = document.getElementById('missing-modal-overlay');
                        
                        if (modal && overlay) {
                            modal.style.display = 'block';
                            overlay.style.display = 'block';
                            
                            // Trigger missing classes loading
                            window.dash_clientside.set_props("missing-class-data", {
                                data: {
                                    action: 'show_missing',
                                    cell_id: this.id,
                                    timestamp: Date.now()
                                }
                            });
                        }
                        return;
                    }
                    
                    // Don't allow room selection for break times
                    if (this.classList.contains('break-time') || 
                        this.textContent.trim() === 'BREAK') {
                        console.log('Cannot select room for break time');
                        return;
                    }
                    
                    // Store the selected cell
                    window.selectedCell = this;
                    
                    // Show room selection modal
                    const modal = document.getElementById('room-selection-modal');
                    const overlay = document.getElementById('modal-overlay');
                    const deleteBtn = document.getElementById('room-delete-btn');
                    
                    if (modal && overlay) {
                        modal.style.display = 'block';
                        overlay.style.display = 'block';
                        
                        // Show delete button only for manually scheduled cells
                        if (deleteBtn) {
                            if (this.classList.contains('manual-schedule')) {
                                deleteBtn.style.display = 'inline-block';
                                deleteBtn.textContent = 'DELETE SCHEDULE';
                                console.log('Showing DELETE SCHEDULE button for manual cell');
                            } else {
                                deleteBtn.style.display = 'none';
                                console.log('Hiding DELETE SCHEDULE button for non-manual cell');
                            }
                        }
                        
                        // Trigger room options loading
                        window.dash_clientside.set_props("room-change-data", {
                            data: {
                                action: 'show_modal',
                                cell_id: this.id,
                                cell_content: this.textContent.trim(),
                                is_manual: this.classList.contains('manual-schedule'),
                                timestamp: Date.now()
                            }
                        });
                        
                        // Focus on search input
                        setTimeout(function() {
                            const searchInput = document.getElementById('room-search-input');
                            if (searchInput) {
                                searchInput.focus();
                            }
                        }, 100);
                    }
                };
                
                cell.ondragstart = function(e) {
                    console.log('Drag started on cell:', this.id);
                    
                    // Prevent dragging break times
                    if (this.classList.contains('break-time') || this.textContent.trim() === 'BREAK') {
                        console.log('Cannot drag break time');
                        e.preventDefault();
                        return false;
                    }
                    
                    // Clear any previous drag state
                    window.draggedElement = null;
                    window.dragStartData = null;
                    
                    window.draggedElement = this;
                    
                    // Get row and col from the element's ID
                    const idStr = this.id;
                    try {
                        const idObj = JSON.parse(idStr);
                        window.dragStartData = {
                            group: idObj.group,
                            row: idObj.row,
                            col: idObj.col,
                            content: this.textContent.trim(),
                            cellId: idStr  // Store the exact cell ID for verification
                        };
                        console.log('Drag data stored:', window.dragStartData);
                    } catch (e) {
                        console.error('Could not parse ID:', idStr);
                        window.draggedElement = null;
                        window.dragStartData = null;
                        return false;
                    }
                    
                    this.classList.add('dragging');
                    e.dataTransfer.effectAllowed = 'move';
                    e.dataTransfer.setData('text/html', this.id);
                };
                
                cell.ondragover = function(e) {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    return false;
                };
                
                cell.ondragenter = function(e) {
                    e.preventDefault();
                    // Don't allow dropping on break times
                    if (this !== window.draggedElement && 
                        !this.classList.contains('break-time') && 
                        this.textContent.trim() !== 'BREAK') {
                        this.classList.add('drag-over');
                    }
                    return false;
                };
                
                cell.ondragleave = function(e) {
                    this.classList.remove('drag-over');
                };
                
                cell.ondrop = function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    console.log('Drop detected on cell:', this.id);
                    
                    // Prevent dropping on break times
                    if (this.classList.contains('break-time') || this.textContent.trim() === 'BREAK') {
                        console.log('Cannot drop on break time');
                        this.classList.remove('drag-over');
                        return false;
                    }
                    
                    // Validate we have a valid drag operation
                    if (!window.draggedElement || !window.dragStartData) {
                        console.log('No valid drag operation in progress');
                        this.classList.remove('drag-over');
                        return false;
                    }
                    
                    // Don't drop on the same element
                    if (this === window.draggedElement) {
                        console.log('Cannot drop on the same element');
                        this.classList.remove('drag-over');
                        return false;
                    }
                    
                    // Verify the dragged element still exists and matches our stored data
                    if (window.draggedElement.id !== window.dragStartData.cellId) {
                        console.log('Drag state mismatch - aborting');
                        this.classList.remove('drag-over');
                        return false;
                    }
                    
                    // Get target data
                    const targetIdStr = this.id;
                    try {
                        const targetIdObj = JSON.parse(targetIdStr);
                        const targetData = {
                            group: targetIdObj.group,
                            row: targetIdObj.row,
                            col: targetIdObj.col,
                            content: this.textContent.trim(),
                            cellId: targetIdStr
                        };
                        
                        // Ensure both elements are in the same group
                        if (window.dragStartData.group !== targetData.group) {
                            console.log('Cannot swap between different groups');
                            this.classList.remove('drag-over');
                            return false;
                        }
                        
                        console.log('Swapping:', window.dragStartData, 'with:', targetData);
                        
                        // Check if either cell is manually scheduled to preserve manual status
                        const sourceIsManual = window.draggedElement.classList.contains('manual-schedule');
                        const targetIsManual = this.classList.contains('manual-schedule');
                        
                        // Perform the swap
                        const tempContent = window.draggedElement.textContent;
                        window.draggedElement.textContent = this.textContent;
                        this.textContent = tempContent;
                        
                        // Preserve manual-schedule classes after swap
                        if (sourceIsManual) {
                            this.classList.add('manual-schedule');
                            window.draggedElement.classList.remove('manual-schedule');
                        }
                        if (targetIsManual) {
                            window.draggedElement.classList.add('manual-schedule');
                            this.classList.remove('manual-schedule');
                        }
                        
                        // Trigger callback to update backend data
                        window.dash_clientside.set_props("swap-data", {
                            data: {
                                source: window.dragStartData,
                                target: targetData,
                                sourceIsManual: sourceIsManual,
                                targetIsManual: targetIsManual,
                                timestamp: Date.now()
                            }
                        });
                        
                        // Update feedback
                        const feedback = document.getElementById('feedback');
                        if (feedback) {
                            feedback.innerHTML = '✅ Swapped "' + window.dragStartData.content + '" with "' + targetData.content + '"';
                            feedback.style.color = 'green';
                            feedback.style.backgroundColor = '#e8f5e8';
                            feedback.style.padding = '10px';
                            feedback.style.borderRadius = '5px';
                            feedback.style.border = '2px solid #4caf50';
                        }
                        
                        console.log('✅ Swap completed successfully - UI updated');
                        
                        // Clear drag state immediately after successful swap
                        window.draggedElement = null;
                        window.dragStartData = null;
                        
                    } catch (e) {
                        console.error('Could not parse target ID:', targetIdStr, e);
                    }
                    
                    this.classList.remove('drag-over');
                    return false;
                };
                
                cell.ondragend = function(e) {
                    console.log('Drag ended - cleaning up');
                    
                    // Remove dragging class from this element
                    this.classList.remove('dragging');
                    
                    // Clean up all drag-over classes from all cells
                    const allCells = document.querySelectorAll('.cell');
                    allCells.forEach(function(c) {
                        c.classList.remove('drag-over', 'dragging');
                    });
                    
                    // Clear global drag state
                    window.draggedElement = null;
                    window.dragStartData = null;
                    
                    console.log('Drag state cleared');
                };
            });
        }
        
        // Setup modal close handlers
        function setupModalHandlers() {
            const modalCloseBtn = document.getElementById('modal-close-btn');
            const roomCancelBtn = document.getElementById('room-cancel-btn');
            const overlay = document.getElementById('modal-overlay');
            const conflictCloseBtn = document.getElementById('conflict-close-btn');
            
            function closeModal() {
                const modal = document.getElementById('room-selection-modal');
                const overlay = document.getElementById('modal-overlay');
                if (modal && overlay) {
                    modal.style.display = 'none';
                    overlay.style.display = 'none';
                }
                window.selectedCell = null;
            }
            
            function closeConflictWarning() {
                const warning = document.getElementById('conflict-warning');
                if (warning) {
                    warning.style.display = 'none';
                }
            }
            
            if (modalCloseBtn) {
                modalCloseBtn.onclick = closeModal;
            }
            
            if (roomCancelBtn) {
                roomCancelBtn.onclick = closeModal;
            }
            
            if (overlay) {
                overlay.onclick = closeModal;
            }
            
            if (conflictCloseBtn) {
                conflictCloseBtn.onclick = closeConflictWarning;
            }
        }
        
        // Setup immediately and after a short delay
        setTimeout(function() {
            setupDragAndDrop();
            setupModalHandlers();
        }, 100);
        
        // Also setup when DOM changes (but debounce to prevent excessive calls)
        let setupTimeout = null;
        const observer = new MutationObserver(function(mutations) {
            let shouldSetup = false;
            mutations.forEach(function(mutation) {
                if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                    for (let i = 0; i < mutation.addedNodes.length; i++) {
                        const node = mutation.addedNodes[i];
                        if (node.nodeType === 1 && (node.classList.contains('cell') || node.querySelector('.cell'))) {
                            shouldSetup = true;
                            break;
                        }
                    }
                }
            });
            if (shouldSetup) {
                // Clear any existing timeout
                if (setupTimeout) {
                    clearTimeout(setupTimeout);
                }
                // Set a new timeout to debounce the setup calls
                setupTimeout = setTimeout(function() {
                    console.log('DOM changed - re-initializing drag and drop');
                    // Only re-initialize if no drag operation is in progress
                    if (!window.draggedElement && !window.dragStartData) {
                        setupDragAndDrop();
                        setupModalHandlers();
                    } else {
                        console.log('Skipping re-initialization - drag in progress');
                    }
                    setupTimeout = null;
                }, 150);
            }
        });
        
        const container = document.getElementById('timetable-container');
        if (container) {
            observer.observe(container, {
                childList: true,
                subtree: true
            });
        }
        
        console.log('Drag and drop and double-click setup complete');
        return window.dash_clientside.no_update;
    }
    """,
    Output("feedback", "style"),
    Input("trigger", "children"),
    prevent_initial_call=False
)

# Client-side callback for room option selection highlighting
clientside_callback(
    """
    function(children) {
        if (!children) return window.dash_clientside.no_update;
        
        // Add click handlers for room options
        setTimeout(function() {
            const roomOptions = document.querySelectorAll('.room-option');
            
            roomOptions.forEach(function(option) {
                option.onclick = function() {
                    // Remove selected class from all options
                    roomOptions.forEach(function(opt) {
                        opt.classList.remove('selected');
                    });
                    
                    // Add selected class to clicked option
                    this.classList.add('selected');
                };
            });
        }, 100);
        
        return window.dash_clientside.no_update;
    }
    """,
    Output("room-options-container", "style"),
    Input("room-options-container", "children"),
    prevent_initial_call=True
)

# Client-side callback to close modal after room confirmation
clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) {
            // Close the modal
            const modal = document.getElementById('room-selection-modal');
            const overlay = document.getElementById('modal-overlay');
            
            if (modal && overlay) {
                modal.style.display = 'none';
                overlay.style.display = 'none';
            }
            
            // Clear the selected cell
            window.selectedCell = null;
            
            // Show success feedback
            const feedback = document.getElementById('feedback');
            if (feedback) {
                feedback.innerHTML = '✅ Classroom updated successfully';
                feedback.style.color = 'green';
                feedback.style.backgroundColor = '#e8f5e8';
                feedback.style.padding = '10px';
                feedback.style.borderRadius = '5px';
                feedback.style.border = '2px solid #4caf50';
            }
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("room-confirm-btn", "style"),
    Input("room-confirm-btn", "n_clicks"),
    prevent_initial_call=True
)

# Client-side callback to auto-hide save error popup
clientside_callback(
    """
    function(style) {
        if (style && style.display === 'block') {
            // Auto-hide after 4 seconds
            setTimeout(function() {
                const saveError = document.getElementById('save-error');
                if (saveError) {
                    saveError.style.display = 'none';
                }
            }, 4000);
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("save-error", "children"),
    Input("save-error", "style"),
    prevent_initial_call=True
)

# Client-side callback to handle missing class modal closing
clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) {
            // Close the missing classes modal
            const modal = document.getElementById('missing-classes-modal');
            const overlay = document.getElementById('missing-modal-overlay');
            
            if (modal && overlay) {
                modal.style.display = 'none';
                overlay.style.display = 'none';
            }
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("missing-cancel-btn", "style"),
    Input("missing-cancel-btn", "n_clicks"),
    prevent_initial_call=True
)

# Client-side callback to handle missing class option clicks
clientside_callback(
    """
    function(children) {
        if (!children) return window.dash_clientside.no_update;
        
        // Add click handlers for missing class options
        setTimeout(function() {
            const missingOptions = document.querySelectorAll('[id*="missing-class-option"]');
            
            missingOptions.forEach(function(option) {
                option.onclick = function() {
                    // DO NOT close the modal here.
                    // The server-side callback will handle closing the modal after processing.
                    
                    // Show feedback immediately for a better user experience
                    const feedback = document.getElementById('feedback');
                    if (feedback) {
                        feedback.innerHTML = '✅ Class scheduled successfully';
                        feedback.style.color = 'green';
                        feedback.style.backgroundColor = '#e8f5e8';
                        feedback.style.padding = '10px';
                        feedback.style.borderRadius = '5px';
                        feedback.style.border = '2px solid #4caf50';
                    }
                };
            });
        }, 100);
        return window.dash_clientside.no_update;
    }
    """,
    Output("missing-classes-container", "style"),
    Input("missing-classes-container", "children"),
    prevent_initial_call=True
)



# Callback to handle room selection modal and search
@app.callback(
    [Output("room-options-container", "children"),
     Output("room-selection-modal", "style"),
     Output("modal-overlay", "style"),
     Output("room-delete-btn", "style")],
    [Input("room-change-data", "data"),
     Input("room-search-input", "value")],
    [State("all-timetables-store", "data"),
     State("rooms-data-store", "data"),
     State("student-group-dropdown", "value"),
     State("manual-cells-store", "data")],
    prevent_initial_call=True
)
def handle_room_modal(room_change_data, search_value, all_timetables_data, rooms_data, selected_group_idx, manual_cells):
    if not room_change_data or room_change_data.get('action') != 'show_modal':
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
    if not rooms_data or not all_timetables_data:
        return html.Div("No rooms data available"), {"display": "block"}, {"display": "block"}, {"display": "none"}
    
    # Parse cell information
    try:
        cell_id_str = room_change_data['cell_id']
        cell_id = json.loads(cell_id_str)
        row_idx = cell_id['row']
        col_idx = cell_id['col']
        group_idx = cell_id['group']
    except:
        return html.Div("Error parsing cell data"), {"display": "block"}, {"display": "block"}, {"display": "none"}
    
    # Get current room usage for this time slot across all groups
    current_room_usage = get_room_usage_at_timeslot(all_timetables_data, row_idx, col_idx)
    
    # Filter rooms based on search
    filtered_rooms = rooms_data
    if search_value:
        search_lower = search_value.lower()
        filtered_rooms = [room for room in rooms_data 
                         if search_lower in room['name'].lower() or 
                            search_lower in room.get('building', '').lower() or
                            search_lower in room.get('room_type', '').lower()]
    
    # Create room options
    room_options = []
    for room in filtered_rooms:
        room_name = room['name']
        is_available = room_name not in current_room_usage
        
        # Determine styling
        if is_available:
            option_class = "room-option available"
        else:
            option_class = "room-option occupied"
        
        # Create conflict info if room is occupied
        conflict_info = ""
        if not is_available:
            conflicting_groups = current_room_usage[room_name]
            conflict_info = f" (Used by: {', '.join(conflicting_groups)})"
        
        room_options.append(
            html.Div([
                html.Div([
                    html.Span(room_name, style={"fontWeight": "600"}),
                    html.Span(conflict_info, style={"fontSize": "11px", "color": "#666", "marginLeft": "8px"})
                ], style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"}),
                html.Div([
                    html.Span(f"Cap: {room['capacity']}", className="room-info"),
                    html.Span(f" | {room['building']}", className="room-info"),
                    html.Span(f" | {room.get('room_type', 'N/A')}", className="room-info")
                ])
            ], 
            className=option_class,
            id={"type": "room-option", "room_id": room['Id'], "room_name": room_name},
            n_clicks=0)
        )
    
    # Determine if DELETE SCHEDULE button should be shown
    manual_cell_key = f"{group_idx}_{row_idx}_{col_idx}"
    is_manual_cell = manual_cells and manual_cell_key in manual_cells
    
    delete_btn_style = {
        "backgroundColor": "#dc3545", 
        "color": "white", 
        "padding": "8px 16px", 
        "border": "none", 
        "borderRadius": "5px", 
        "cursor": "pointer", 
        "marginRight": "10px",
        "fontFamily": "Poppins, sans-serif", 
        "fontWeight": "600", 
        "display": "inline-block" if is_manual_cell else "none"
    }
    
    return room_options, {"display": "block"}, {"display": "block"}, delete_btn_style

# Callback to handle missing class selection and scheduling
@app.callback(
    [Output("all-timetables-store", "data", allow_duplicate=True),
     Output("manual-cells-store", "data", allow_duplicate=True),
     Output("missing-classes-modal", "style", allow_duplicate=True),
     Output("missing-modal-overlay", "style", allow_duplicate=True)],
    [Input({"type": "missing-class-option", "index": ALL, "course": ALL, "faculty": ALL}, "n_clicks")],
    [State({"type": "missing-class-option", "index": ALL, "course": ALL, "faculty": ALL}, "id"),
     State("missing-class-data", "data"),
     State("all-timetables-store", "data"),
     State("student-group-dropdown", "value"),
     State("manual-cells-store", "data"),
     State("rooms-data-store", "data")],
    prevent_initial_call=True
)
def handle_missing_class_selection(n_clicks_list, class_ids, missing_data, all_timetables_data, selected_group_idx, manual_cells, rooms_data):
    if not any(n_clicks_list) or not missing_data:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # Find which class was clicked
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    try:
        triggered_class = json.loads(triggered_id)
        selected_course = triggered_class['course']
        # We get this from the button just for fallback, but will re-verify it
        selected_faculty_from_id = triggered_class.get('faculty', 'Unknown Faculty')
    except:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # Parse cell information from missing_data
    try:
        cell_id_str = missing_data['cell_id']
        cell_id = json.loads(cell_id_str)
        row_idx = cell_id['row']
        col_idx = cell_id['col']
        group_idx = cell_id['group']
    except:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    # Update timetable with manual scheduling
    updated_timetables = json.loads(json.dumps(all_timetables_data))

    # Find a random available room
    available_room = "Room-001"  # Default
    if rooms_data:
        import random
        available_room = random.choice(rooms_data)['name']

    # NEW: Re-fetch the lecturer name to ensure correctness
    current_group_name = all_timetables_data[group_idx]['student_group']['name']
    faculty_name = find_lecturer_for_course(selected_course, current_group_name)

    # If lookup fails, fallback to the name from the button ID, then to a default
    if faculty_name == "Unknown":
        faculty_name = selected_faculty_from_id
    if faculty_name == "Unknown" or not faculty_name:
        faculty_name = 'Unknown Faculty'

    # Preserve the actual course name instead of just 'MANUAL-CLASS'
    course_display_name = selected_course
    if course_display_name == 'Unknown Course' or not course_display_name:
        course_display_name = 'MANUAL-CLASS'

    manual_class_content = f"{course_display_name}\n{available_room}\n{faculty_name}"
    updated_timetables[group_idx]['timetable'][row_idx][col_idx + 1] = manual_class_content

    # Track this as a manually scheduled cell
    manual_cell_key = f"{group_idx}_{row_idx}_{col_idx}"
    updated_manual_cells = manual_cells.copy() if manual_cells else []
    if manual_cell_key not in updated_manual_cells:
        updated_manual_cells.append(manual_cell_key)

    return updated_timetables, updated_manual_cells, {"display": "none"}, {"display": "none"}

def find_lecturer_for_course(course_identifier, group_name):
    """Find the lecturer assigned to teach a specific course for a specific group using code, ID, or name."""
    try:
        # Look through the input data to find the lecturer for this course and group
        for student_group in input_data.student_groups:
            if student_group.name == group_name:
                for i, course_id_from_group in enumerate(student_group.courseIDs):
                    course = input_data.getCourse(course_id_from_group)
                    # MODIFIED: Safely check against course ID, code, or name, ignoring case and whitespace.
                    if course and (
                        str(course_id_from_group).strip().lower() == str(course_identifier).strip().lower() or
                        str(getattr(course, 'code', '')).strip().lower() == str(course_identifier).strip().lower() or
                        str(getattr(course, 'name', '')).strip().lower() == str(course_identifier).strip().lower()
                    ):
                        # Found the course, get the lecturer
                        faculty_id = student_group.teacherIDS[i]
                        faculty = input_data.getFaculty(faculty_id)
                        if faculty:
                            return faculty.name if faculty.name else faculty.faculty_id
                        break  # Found the course, no need to check other courses for this group
        return "Unknown"
    except Exception as e:
        print(f"Error finding lecturer for course {course_identifier}: {e}")
        return "Unknown"

def get_room_usage_at_timeslot(all_timetables_data, row_idx, col_idx):
    """Get which rooms are being used at a specific time slot and by which groups"""
    room_usage = {}  # room_name -> [group_names]
    
    for timetable_data in all_timetables_data:
        timetable_rows = timetable_data['timetable']
        if row_idx < len(timetable_rows) and (col_idx + 1) < len(timetable_rows[row_idx]):
            cell_content = timetable_rows[row_idx][col_idx + 1]  # +1 to skip time column
            room_name = extract_room_from_cell(cell_content)
            
            if room_name:
                group_name = timetable_data['student_group']['name'] if isinstance(timetable_data['student_group'], dict) else timetable_data['student_group'].name
                if room_name not in room_usage:
                    room_usage[room_name] = []
                room_usage[room_name].append(group_name)
    
    return room_usage

# Callback to handle missing classes modal
@app.callback(
    [Output("missing-classes-container", "children"),
     Output("missing-classes-modal", "style"),
     Output("missing-modal-overlay", "style")],
    [Input("missing-class-data", "data")],
    [State("constraint-details-store", "data"),
     State("student-group-dropdown", "value"),
     State("all-timetables-store", "data")],
    prevent_initial_call=True
)
def handle_missing_classes_modal(missing_data, constraint_details, selected_group_idx, all_timetables_data):
    if not missing_data or missing_data.get('action') != 'show_missing':
        return dash.no_update, dash.no_update, dash.no_update
    
    if not constraint_details or not all_timetables_data:
        return html.Div("No constraint data available"), {"display": "block"}, {"display": "block"}
    
    # Get current student group
    current_group = all_timetables_data[selected_group_idx]['student_group']
    group_name = current_group['name'] if isinstance(current_group, dict) else current_group.name
    
    # Filter missing classes for current student group
    missing_classes = []
    
    # Only check the 3 specific constraint types
    target_constraints = ['Missing or Extra Classes', 'Same Student Group Overlaps', 'Classes During Break Time']
    
    for constraint_type in target_constraints:
        if constraint_type not in constraint_details:
            continue
            
        for violation in constraint_details[constraint_type]:
            if not isinstance(violation, dict):
                continue
                
            # Check if this violation involves the current group
            if constraint_type == 'Missing or Extra Classes':
                if violation.get('group') == group_name:
                    course_code = violation.get('course', 'Unknown Course')
                    faculty_name = find_lecturer_for_course(course_code, group_name)
                    if faculty_name == "Unknown":
                        faculty_name = violation.get('faculty', 'Unknown Faculty')
                    
                    missing_classes.append({
                        'course': course_code,
                        'faculty': faculty_name,
                        'type': 'Missing Class',
                        'reason': violation.get('reason', 'Missing from schedule')
                    })
            
            elif constraint_type == 'Same Student Group Overlaps':
                # Based on constraints.py, the violation structure has 'group', 'courses' array, and 'location'
                if violation.get('group') == group_name and 'courses' in violation:
                    courses = violation.get('courses', [])
                    # Take the first course from the clashing courses for this group
                    course_code = courses[0] if courses else 'Unknown Course'
                    faculty_name = find_lecturer_for_course(course_code, group_name)
                    if faculty_name == "Unknown":
                        faculty_name = violation.get('lecturer', 'Unknown Faculty')
                    
                    missing_classes.append({
                        'course': course_code,
                        'faculty': faculty_name,
                        'type': 'Student Group Clash',
                        'reason': violation.get('location', 'Clash detected')
                    })
                # Handle case where violation has 'groups' and 'courses' arrays (multiple groups)
                elif 'groups' in violation and 'courses' in violation:
                    groups = violation.get('groups', [])
                    courses = violation.get('courses', [])
                    if group_name in groups:
                        try:
                            idx = groups.index(group_name)
                            course_code = courses[idx] if idx < len(courses) else courses[0] if courses else 'Unknown Course'
                            faculty_name = find_lecturer_for_course(course_code, group_name)
                            if faculty_name == "Unknown":
                                faculty_name = violation.get('lecturer', 'Unknown Faculty')
                        except (ValueError, IndexError):
                            course_code = courses[0] if courses else 'Unknown Course'
                            faculty_name = find_lecturer_for_course(course_code, group_name)
                        
                        missing_classes.append({
                            'course': course_code,
                            'faculty': faculty_name,
                            'type': 'Student Group Clash',
                            'reason': violation.get('location', 'Clash detected')
                        })
            
            elif constraint_type == 'Classes During Break Time':
                if violation.get('group') == group_name:
                    course_code = violation.get('course', 'Unknown Course')
                    # Find the correct lecturer for this course and group
                    faculty_name = find_lecturer_for_course(course_code, group_name)
                    if faculty_name == "Unknown":
                        faculty_name = violation.get('faculty', 'Unknown Faculty')
                    
                    missing_classes.append({
                        'course': course_code,
                        'faculty': faculty_name,
                        'type': 'Break Time Violation',
                        'reason': 'Scheduled during break time'
                    })
    

    

    
    if not missing_classes:
        return html.Div("No missing classes found for this student group", 
                       style={"padding": "20px", "textAlign": "center"}), {"display": "block"}, {"display": "block"}
    
    # Create missing class options
    class_options = []
    for idx, missing_class in enumerate(missing_classes):
        # Use actual course and faculty names, don't convert to MANUAL-CLASS
        display_course = missing_class['course']
        display_faculty = missing_class.get('faculty', 'Unknown Faculty')
        
        class_options.append(
            html.Button([
                html.Div([
                    html.Span(display_course, style={"fontWeight": "600"}),
                    html.Span(f" ({missing_class['type']})", style={"fontSize": "11px", "color": "#666", "marginLeft": "8px"})
                ]),
                html.Div(
                    display_faculty,
                    style={"fontSize": "12px", "color": "#666", "marginTop": "4px"}
                )
            ], 
            className="room-option available",
            id={"type": "missing-class-option", "index": idx, "course": display_course, "faculty": display_faculty},
            n_clicks=0,
            style={"width": "100%", "textAlign": "left", "background": "none", "border": "none", "padding": "12px 16px", "cursor": "pointer"})
        )
    
    return class_options, {"display": "block"}, {"display": "block"}

# Callback to handle room option selection
@app.callback(
    Output("room-change-data", "data", allow_duplicate=True),
    [Input({"type": "room-option", "room_id": ALL, "room_name": ALL}, "n_clicks")],
    [State({"type": "room-option", "room_id": ALL, "room_name": ALL}, "id"),
     State("room-change-data", "data"),
     State("all-timetables-store", "data")],
    prevent_initial_call=True
)
def handle_room_selection(n_clicks_list, room_ids, current_room_data, all_timetables_data):
    if not any(n_clicks_list) or not current_room_data:
        return dash.no_update
    
    # Find which room was clicked
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update
    
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    try:
        triggered_room = json.loads(triggered_id)
        selected_room_name = triggered_room['room_name'];
    except:
        return dash.no_update
    
    # Update the room change data
    return {
        **current_room_data,
        'action': 'room_selected',
        'selected_room': selected_room_name,
        'timestamp': current_room_data.get('timestamp', 0) + 1
    }

def find_lecturer_for_course(course_identifier, group_name):
    """Find the lecturer assigned to teach a specific course for a specific group using code, ID, or name."""
    try:
        # Look through the input data to find the lecturer for this course and group
        for student_group in input_data.student_groups:
            if student_group.name == group_name:
                for i, course_id_from_group in enumerate(student_group.courseIDs):
                    course = input_data.getCourse(course_id_from_group)
                    # MODIFIED: Check if the identifier matches the course code, ID, or name (case-insensitive)
                    if course and (
                        str(course.code).strip().lower() == str(course_identifier).strip().lower() or
                        str(course.id).strip().lower() == str(course_identifier).strip().lower() or
                        str(course.name).strip().lower() == str(course_identifier).strip().lower()
                    ):
                        # Found the course, get the lecturer
                        faculty_id = student_group.teacherIDS[i]
                        faculty = input_data.getFaculty(faculty_id)
                        if faculty:
                            return faculty.name if faculty.name else faculty.faculty_id
                        break  # Found the course, no need to check other courses for this group
        return "Unknown"
    except Exception as e:
        print(f"Error finding lecturer for course {course_identifier}: {e}")
        return "Unknown"

# Callback to handle room confirmation and update timetable
@app.callback(
    [Output("all-timetables-store", "data", allow_duplicate=True),
     Output("manual-cells-store", "data", allow_duplicate=True),
     Output("conflict-warning", "style"),
     Output("conflict-warning-text", "children")],
    [Input("room-confirm-btn", "n_clicks"),
     Input("room-delete-btn", "n_clicks")],
    [State("room-change-data", "data"),
     State("all-timetables-store", "data"),
     State("student-group-dropdown", "value"),
     State("rooms-data-store", "data"),
     State("manual-cells-store", "data")],
    prevent_initial_call=True
)

def confirm_room_change(confirm_clicks, delete_clicks, room_change_data, all_timetables_data, selected_group_idx, rooms_data, manual_cells):
    ctx = dash.callback_context
    if not ctx.triggered:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
    # FIX: Initialize updated_manual_cells at the start of the function
    # This ensures it exists regardless of which button is clicked.
    updated_manual_cells = manual_cells.copy() if manual_cells else []
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Handle delete button for manually scheduled cells
    if trigger_id == "room-delete-btn" and delete_clicks:
        if not room_change_data:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update
        
        try:
            # Parse cell information
            cell_id_str = room_change_data['cell_id']
            cell_id = json.loads(cell_id_str)
            row_idx = cell_id['row']
            col_idx = cell_id['col']
            group_idx = cell_id['group']
            
            # Update timetable to FREE and remove from manual cells tracking
            updated_timetables = json.loads(json.dumps(all_timetables_data))
            updated_timetables[group_idx]['timetable'][row_idx][col_idx + 1] = "FREE"
            
            # Also remove from manual cells store
            manual_cell_key = f"{group_idx}_{row_idx}_{col_idx}"
            if manual_cell_key in updated_manual_cells:
                updated_manual_cells.remove(manual_cell_key)
            
            # Save changes
            save_timetable_to_file(updated_timetables, updated_manual_cells)
            
            return updated_timetables, updated_manual_cells, {"display": "none"}, ""
            
        except Exception as e:
            return dash.no_update, dash.no_update, {"display": "block"}, f"Error deleting schedule: {str(e)}"

    # Handle room confirmation (existing logic)
    if trigger_id == "room-confirm-btn" and confirm_clicks:
        if not room_change_data or room_change_data.get('action') != 'room_selected':
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
        global session_has_swaps
        session_has_swaps = True
        
        try:
            # Parse cell information
            cell_id_str = room_change_data['cell_id']
            cell_id = json.loads(cell_id_str)
            row_idx = cell_id['row']
            col_idx = cell_id['col']
            selected_room = room_change_data['selected_room']
            
            # Update the current group's timetable
            updated_timetables = json.loads(json.dumps(all_timetables_data))  # Deep copy
            current_group_timetable = updated_timetables[selected_group_idx]['timetable']
            
            # Get the original cell content and extract course info
            original_content = current_group_timetable[row_idx][col_idx + 1]
            
            # Update room in the cell content
            updated_content = update_room_in_cell_content(original_content, selected_room)
            current_group_timetable[row_idx][col_idx + 1] = updated_content
            
            # Find and update consecutive classes of the same course
            course_code = extract_course_code_from_cell(original_content)
            if course_code:
                update_consecutive_course_rooms(updated_timetables, selected_group_idx, course_code, selected_room, row_idx, col_idx)
            
            # Update the global all_timetables variable BEFORE saving to ensure consistency
            global all_timetables
            all_timetables = json.loads(json.dumps(updated_timetables))  # Deep copy to avoid reference issues
            
            # Check for conflicts after the update
            room_usage = get_room_usage_at_timeslot(updated_timetables, row_idx, col_idx)
            conflict_warning_style = {"display": "none"}
            conflict_warning_text = ""
            
            if selected_room in room_usage and len(room_usage[selected_room]) > 1:
                # There's a conflict
                other_groups = [group for group in room_usage[selected_room] 
                                if group != updated_timetables[selected_group_idx]['student_group']['name']]
                
                conflict_warning_style = {"display": "block"}
                conflict_warning_text = f"This classroom is already in use by: {', '.join(other_groups)}"
            
            # Auto-save the changes
            # This call will now work because updated_manual_cells was initialized earlier.
            save_success = save_timetable_to_file(updated_timetables, updated_manual_cells)
            if save_success:
                print(f"✅ Room change auto-saved successfully - Global state updated")
            else:
                print(f"❌ Failed to auto-save room change")
            
            # When just changing a room, the list of manual cells doesn't change, so return the original 'manual_cells' state
            return updated_timetables, manual_cells, conflict_warning_style, conflict_warning_text
            
        except Exception as e:
            print(f"Error in room change: {e}")
            return dash.no_update, dash.no_update, {"display": "block"}, f"Error updating room: {str(e)}"

    return dash.no_update, dash.no_update, dash.no_update, dash.no_update

def extract_course_code_from_cell(cell_content):
    """Extract course code from cell content with new format: Course Code\\nRoom Name\\nFaculty"""
    if not cell_content or cell_content in ["FREE", "BREAK"]:
        return None
    
    # Split by newlines and get the first line (course code)
    lines = cell_content.split('\n')
    if lines and lines[0].strip():
        return lines[0].strip()
    return None

def update_room_in_cell_content(cell_content, new_room):
    """Update the room name in cell content with new format: Course Code\\nRoom Name\\nFaculty"""
    if not cell_content or cell_content in ["FREE", "BREAK"]:
        return cell_content
    
    # Split by newlines and update the second line (room name)
    lines = cell_content.split('\n')
    if len(lines) >= 3:
        lines[1] = new_room  # Update the room name (second line)
        return '\n'.join(lines)
    elif len(lines) == 2:
        # If only 2 lines, add room as second line and move faculty to third
        return f"{lines[0]}\n{new_room}\n{lines[1]}"
    elif len(lines) == 1:
        # If only 1 line, add room and keep original as course code
        return f"{lines[0]}\n{new_room}\nUnknown"
    
    return cell_content

def update_consecutive_course_rooms(timetables_data, group_idx, course_code, new_room, current_row, current_col):
    """Update consecutive classes of the same course to use the same room"""
    timetable_rows = timetables_data[group_idx]['timetable']
    
    # Check same day (same column) for consecutive hours
    for row_idx in range(len(timetable_rows)):
        if row_idx != current_row:  # Skip the cell we just updated
            cell_content = timetable_rows[row_idx][current_col + 1]
            if extract_course_code_from_cell(cell_content) == course_code:
                # This is the same course, update the room
                updated_content = update_room_in_cell_content(cell_content, new_room)
                timetable_rows[row_idx][current_col + 1] = updated_content

def save_timetable_to_file(timetables_data, manual_cells_data):
    """Save timetable data AND manual cell state to file."""
    try:
        global all_timetables
        import os
        import time
        
        save_dir = os.path.join(os.path.dirname(__file__), 'data')
        os.makedirs(save_dir, exist_ok=True)
        
        session_save_path = os.path.join(save_dir, 'timetable_data.json')
        export_save_path = os.path.join(save_dir, 'fresh_timetable_data.json')
        backup_path = os.path.join(save_dir, 'timetable_data_backup.json')
        
        # MODIFIED: Create a dictionary to hold both timetable and manual cell data
        save_data = {
            'timetables': timetables_data,
            'manual_cells': manual_cells_data
        }

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] Saving timetable data...")

        if os.path.exists(session_save_path):
            shutil.copy2(session_save_path, backup_path)
        
        all_timetables = json.loads(json.dumps(timetables_data))

        # MODIFIED: Save the combined dictionary
        with open(session_save_path, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        
        # The export file should only contain timetable data for clean exports
        with open(export_save_path, 'w', encoding='utf-8') as f:
            json.dump(timetables_data, f, indent=2, ensure_ascii=False)
        
        print(f"[{timestamp}] ✅ Auto-saved changes to session file: {session_save_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error auto-saving timetable: {e}")
        import traceback
        traceback.print_exc()
        return False

def recompute_constraint_violations_simplified(timetables_data, rooms_data=None, include_consecutive=True):
    """
    Recomputes constraint violations based ONLY on the current state of the timetable data.
    """
    try:
        # This dictionary will hold only the violations currently detected.
        violations = {
            'Same Student Group Overlaps': [],
            'Different Student Group Overlaps': [],
            'Lecturer Clashes': [],
            'Lecturer Schedule Conflicts (Day/Time)': [],
            'Lecturer Workload Violations': [],
            'Consecutive Slot Violations': [],
            'Missing or Extra Classes': [],
            'Same Course in Multiple Rooms on Same Day': [],
            'Room Capacity/Type Conflicts': [],
            'Classes During Break Time': []
        }

        room_lookup = {room['name']: room for room in rooms_data} if rooms_data else {}
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

        # Check for room/lecturer conflicts and capacity issues
        for time_slot in range(8):
            for day in range(5):
                room_usage = {}
                lecturer_usage = {}
                
                for timetable in timetables_data:
                    if time_slot < len(timetable['timetable']) and day + 1 < len(timetable['timetable'][time_slot]):
                        cell_content = timetable['timetable'][time_slot][day + 1]
                        if cell_content and cell_content not in ['FREE', 'BREAK']:
                            lines = cell_content.split('\n')
                            if len(lines) >= 2:
                                course_code = lines[0].strip()
                                room = lines[1].strip()
                                lecturer = lines[2].strip() if len(lines) >= 3 else "Unknown"
                                group_name = timetable['student_group']['name']
                                
                                if room not in room_usage: room_usage[room] = []
                                room_usage[room].append(group_name)
                                
                                if lecturer not in lecturer_usage: lecturer_usage[lecturer] = []
                                lecturer_usage[lecturer].append({'group': group_name, 'course': course_code})

                                if room in room_lookup:
                                    group_size = next((g.get('no_students', 0) for g in input_data.student_groups if g.name == group_name), 0)
                                    if group_size > room_lookup[room].get('capacity', 999):
                                        violations['Room Capacity/Type Conflicts'].append({
                                            'type': 'Room Capacity Exceeded', 'room': room, 'group': group_name,
                                            'day': days_map.get(day), 'time': f"{time_slot + 9}:00",
                                            'students': group_size, 'capacity': room_lookup[room].get('capacity', 999)
                                        })
                
                for room, groups in room_usage.items():
                    if len(groups) > 1:
                        violations['Different Student Group Overlaps'].append({
                            'room': room, 'groups': groups, 'day': days_map.get(day),
                            'time': f"{time_slot + 9}:00", 'location': f"{days_map.get(day)} at {time_slot + 9}:00"
                        })

                for lecturer, sessions in lecturer_usage.items():
                    if len(sessions) > 1 and lecturer != "Unknown":
                        violations['Lecturer Clashes'].append({
                            'lecturer': lecturer, 'day': days_map.get(day), 'time': f"{time_slot + 9}:00",
                            'courses': [s['course'] for s in sessions], 'groups': [s['group'] for s in sessions],
                            'location': f"{days_map.get(day)} at {time_slot + 9}:00"
                        })
        
        # FIX: Return the newly calculated violations directly, without merging old ones.
        return violations

    except Exception as e:
        print(f"Error in simplified constraint checking: {e}")
        return None

@app.callback(
    Output("constraint-details-store", "data", allow_duplicate=True),
    [Input("all-timetables-store", "data")],
    [State("rooms-data-store", "data"),
     State("constraint-details-store", "data")],
    prevent_initial_call=True
)
def update_constraint_violations_realtime(timetables_data, rooms_data, current_constraints):
    """Update constraint violations in real-time when timetable changes."""
    if not timetables_data:
        return dash.no_update
    
    try:
        # Check if this is a user-initiated change by looking at session_has_swaps
        global session_has_swaps
        
        # ONLY update constraints if the user has made swaps/changes
        # This preserves the original algorithm constraint details on initial load
        if not session_has_swaps:
            print("🔒 No user changes detected - preserving original DE algorithm constraint details")
            return dash.no_update
        
        # For user-initiated changes, check serious violations + track original consecutive violations
        print(f"🔍 Updating constraint violations for user changes (session_has_swaps={session_has_swaps})")
        
        # Recompute constraint violations with rooms data
        # Use include_consecutive=False to use the special logic for tracking original violations
        updated_violations = recompute_constraint_violations_simplified(
            timetables_data, 
            rooms_data, 
            include_consecutive=False  # Special handling for consecutive violations
        )
        
        if updated_violations:
            print("🔄 Updated constraint violations in real-time (tracking original consecutive violations)")
            # Debug: Print violation counts for comparison
            for constraint_type, violations_list in updated_violations.items():
                if violations_list:
                    print(f"  - {constraint_type}: {len(violations_list)} violations")
            return updated_violations
        else:
            print("❌ Failed to update violations - keeping current constraints")
            return current_constraints
            
    except Exception as e:
        print(f"Error updating constraint violations: {e}")
        return current_constraints
@app.callback(
    [Output("all-timetables-store", "data", allow_duplicate=True),
     Output("manual-cells-store", "data", allow_duplicate=True)],
    Input("swap-data", "data"),
    [State("all-timetables-store", "data"),
     State("manual-cells-store", "data")],
    prevent_initial_call=True
)
def handle_swap(swap_data, current_timetables, manual_cells):
    global all_timetables, session_has_swaps
    
    print(f"🔄 Handle swap triggered with data: {swap_data}")
    
    if not swap_data or not current_timetables:
        raise dash.exceptions.PreventUpdate
    
    try:
        source = swap_data['source']
        target = swap_data['target']
        
        # Validate swap data structure
        if not source or not target or 'group' not in source or 'group' not in target:
            print("Invalid swap data structure")
            raise dash.exceptions.PreventUpdate
        
        # Make sure both swaps are in the same group
        if source['group'] != target['group']:
            print("Cannot swap between different student groups")
            raise dash.exceptions.PreventUpdate
        
        # Prevent swapping with BREAK times
        if source.get('content') == 'BREAK' or target.get('content') == 'BREAK':
            print("Cannot swap with BREAK time")
            raise dash.exceptions.PreventUpdate
        
        group_idx = source['group']
        
        # Validate group index
        if group_idx < 0 or group_idx >= len(current_timetables):
            print(f"Invalid group index: {group_idx}")
            raise dash.exceptions.PreventUpdate
        
        # Create a deep copy to avoid reference issues
        updated_timetables = json.loads(json.dumps(current_timetables))
        
        # Update the timetable data
        timetable_rows = updated_timetables[group_idx]['timetable']
        
        # Validate row and column indices
        if (source['row'] >= len(timetable_rows) or target['row'] >= len(timetable_rows) or
            source['col'] + 1 >= len(timetable_rows[0]) or target['col'] + 1 >= len(timetable_rows[0])):
            print("Invalid row or column index in swap data")
            raise dash.exceptions.PreventUpdate
        
        # Get the current content (skip time column, so add 1 to col index)
        source_content = timetable_rows[source['row']][source['col'] + 1]
        target_content = timetable_rows[target['row']][target['col'] + 1]
        
        # Perform the swap
        timetable_rows[source['row']][source['col'] + 1] = target_content
        timetable_rows[target['row']][target['col'] + 1] = source_content
        
        print(f"✅ Swap completed: '{source_content}' ↔ '{target_content}' (Group: {group_idx})")
        
        # Mark that we've made swaps in this session
        session_has_swaps = True

        # --- NEW LOGIC TO UPDATE MANUAL CELLS STATE ---
        source_is_manual = swap_data.get('sourceIsManual', False)
        target_is_manual = swap_data.get('targetIsManual', False)
        updated_manual_cells = manual_cells.copy() if manual_cells else []

        source_key = f"{source['group']}_{source['row']}_{source['col']}"
        target_key = f"{target['group']}_{target['row']}_{target['col']}"

        # Remove existing keys from their original positions
        if source_is_manual and source_key in updated_manual_cells:
            updated_manual_cells.remove(source_key)
        if target_is_manual and target_key in updated_manual_cells:
            updated_manual_cells.remove(target_key)

        # Add keys to their new positions
        if source_is_manual and target_key not in updated_manual_cells:
            updated_manual_cells.append(target_key)
        if target_is_manual and source_key not in updated_manual_cells:
            updated_manual_cells.append(source_key)
        
        # Update the global all_timetables variable BEFORE saving to ensure persistence
        all_timetables = json.loads(json.dumps(updated_timetables))  # Deep copy to avoid reference issues
        
        # Auto-save the changes using centralized function
        save_success = save_timetable_to_file(updated_timetables, updated_manual_cells)
        if save_success:
            print(f"✅ Swap auto-saved successfully - Global state updated")
        else:
            print(f"❌ Failed to auto-save swap")
        
        return updated_timetables, updated_manual_cells
        
    except Exception as e:
        print(f"❌ Error in handle_swap: {e}")
        import traceback
        traceback.print_exc()
        raise dash.exceptions.PreventUpdate

# Callback to handle saving the current timetable state
@app.callback(
    [Output("save-status", "children"),
     Output("save-error", "style")],
    Input("save-button", "n_clicks"),
    State("all-timetables-store", "data"),
    prevent_initial_call=True
)
def save_timetable(n_clicks, current_timetables):
    if n_clicks and current_timetables:
        # Check for room conflicts before saving
        if has_any_room_conflicts(current_timetables):
            # Show error popup and prevent saving
            return (
                html.Div([
                    html.Span("❌ Cannot save - resolve conflicts first", 
                             style={"color": "#d32f2f", "fontWeight": "bold"})
                ]),
                {"display": "block"}
            )
        
        try:
            # Update the global variable
            global all_timetables
            all_timetables = current_timetables
            
            # Save to JSON file for persistence
            import os
            
            # Create a data directory if it doesn't exist
            save_dir = os.path.join(os.path.dirname(__file__), 'data')
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            
            # Save the timetable data
            save_path = os.path.join(save_dir, 'timetable_data.json')
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(current_timetables, f, indent=2, default=str, ensure_ascii=False)
            
            print("Timetable state saved to file")
            print(f"Current timetables contain {len(all_timetables)} student groups")
            print(f"Saved to: {save_path}")
            
            return (
                html.Div([
                    html.Span("✅ Timetable saved successfully!", style={"color": "green", "fontWeight": "bold"}),
                    html.Br(),
                    html.Small(f"Saved to: {save_path}", style={"color": "gray"})
                ]),
                {"display": "none"}
            )
            
        except Exception as e:
            print(f"Error saving timetable: {e}")
            return (
                html.Div([
                    html.Span("❌ Error saving timetable!", style={"color": "red", "fontWeight": "bold"}),
                    html.Br(),
                        html.Small(f"Error: {str(e)}", style={"color": "red"})
                ]),
                {"display": "none"}
            )
    
    return ("", {"display": "none"})

# Callback to refresh timetable data from file on page load - DISABLED to prevent navigation conflicts
# The refresh is now handled only when actual swaps occur in handle_swap callback
# @app.callback(
#     Output("all-timetables-store", "data", allow_duplicate=True),
#     Input("student-group-dropdown", "value"),
#     prevent_initial_call='initial_duplicate'
# )
# def refresh_timetable_data(selected_group_idx):
#     # Only load saved data if we've made swaps in this session
#     global session_has_swaps, all_timetables 
#     
#     if session_has_swaps:
#         fresh_saved_data = load_saved_timetable()
#         if fresh_saved_data:
#             print(f"🔄 Session has swaps - loading saved data: {len(fresh_saved_data)} student groups")
#             return fresh_saved_data
#     
#     # Otherwise, use the current all_timetables (fresh DE results)
#     print(f"🔄 Using fresh DE results: {len(all_timetables)} student groups")
#     return all_timetables

# Callback to load saved user modifications on initial app startup only
@app.callback(
    [Output("all-timetables-store", "data", allow_duplicate=True),
     Output("manual-cells-store", "data", allow_duplicate=True)],
    Input("trigger", "children"),
    State("all-timetables-store", "data"),
    prevent_initial_call='initial_duplicate'
)
def load_user_modifications_on_startup(trigger, current_data):
    """Load saved user modifications and manual cell state on app startup."""
    global all_timetables, session_has_swaps
    
    if current_data:
        # MODIFIED: Unpack both timetables and manual_cells from the loading function
        timetables, manual_cells = load_saved_timetable()
        if timetables:
            print("🔄 Loading saved user modifications on app startup")
            all_timetables = timetables
            session_has_swaps = True
            # Return both pieces of data to their respective stores
            return timetables, manual_cells or []
    
    # Otherwise use fresh results and return empty manual cells list
    session_has_swaps = False
    return current_data or all_timetables, []

# Additional safeguard callback to prevent dropdown state issues
@app.callback(
    Output("student-group-dropdown", "value", allow_duplicate=True),
    Input("student-group-dropdown", "value"),
    State("all-timetables-store", "data"),
    prevent_initial_call=True
)
def validate_dropdown_selection(selected_value, all_timetables_data):
    """Ensure dropdown value is always valid and within bounds"""
    if not all_timetables_data or selected_value is None:
        return 0
    
    # Ensure the selected value is within valid range
    max_index = len(all_timetables_data) - 1
    if selected_value < 0 or selected_value > max_index:
        print(f"🔧 Correcting invalid dropdown value {selected_value} to 0 (max: {max_index})")
        return 0
    
    # Value is valid, no change needed
    raise dash.exceptions.PreventUpdate

# Callback to handle errors button click and show modal
@app.callback(
    [Output("errors-modal-overlay", "style"),
     Output("errors-modal", "style"),
     Output("errors-content", "children")],
    [Input("errors-btn", "n_clicks"),
     Input("errors-modal-close-btn", "n_clicks"),
     Input("errors-close-btn", "n_clicks"),
     Input("errors-modal-overlay", "n_clicks")],
    State("constraint-details-store", "data"),
    prevent_initial_call=True
)
def handle_errors_modal(errors_btn_clicks, close_btn_clicks, close_btn2_clicks, overlay_clicks, constraint_details):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if trigger_id == "errors-btn" and errors_btn_clicks:
        # Show modal and populate with constraint details
        modal_content = create_errors_modal_content(constraint_details)
        return {"display": "block"}, {"display": "block"}, modal_content
    elif trigger_id in ["errors-modal-close-btn", "errors-close-btn", "errors-modal-overlay"]:
        # Hide modal
        return {"display": "none"}, {"display": "none"}, []
    
    raise dash.exceptions.PreventUpdate

# Callback to handle missing classes modal close
@app.callback(
    [Output("missing-modal-overlay", "style", allow_duplicate=True),
     Output("missing-classes-modal", "style", allow_duplicate=True)],
    [Input("missing-modal-close-btn", "n_clicks"),
     Input("missing-cancel-btn", "n_clicks"),
     Input("missing-modal-overlay", "n_clicks")],
    prevent_initial_call=True
)
def handle_missing_modal_close(close_btn_clicks, cancel_btn_clicks, overlay_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    
    # Hide modal
    return {"display": "none"}, {"display": "none"}

# Callback to handle help button click and show help modal
@app.callback(
    [Output("help-modal-overlay", "style"),
     Output("help-modal", "style")],
    [Input("help-icon-btn", "n_clicks"),
     Input("help-modal-close-btn", "n_clicks"), 
     Input("help-close-btn", "n_clicks"),
     Input("help-modal-overlay", "n_clicks")],
    prevent_initial_call=True
)
def handle_help_modal(help_btn_clicks, close_btn_clicks, close_btn2_clicks, overlay_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if trigger_id == "help-icon-btn" and help_btn_clicks:
        # Show modal
        return {"display": "block"}, {"display": "block"}
    elif trigger_id in ["help-modal-close-btn", "help-close-btn", "help-modal-overlay"]:
        # Hide modal
        return {"display": "none"}, {"display": "none"}
    
    raise dash.exceptions.PreventUpdate

# Callback to handle download button click and show download modal
@app.callback(
    [Output("download-modal-overlay", "style"),
     Output("download-modal", "style")],
    [Input("download-button", "n_clicks"),
     Input("download-modal-close-btn", "n_clicks"),
     Input("download-close-btn", "n_clicks"),
     Input("download-modal-overlay", "n_clicks")],
    prevent_initial_call=True
)
def handle_download_modal(download_btn_clicks, close_btn_clicks, close_btn2_clicks, overlay_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if trigger_id == "download-button" and download_btn_clicks:
        # Show modal
        return {"display": "block"}, {"display": "block"}
    elif trigger_id in ["download-modal-close-btn", "download-close-btn", "download-modal-overlay"]:
        # Hide modal
        return {"display": "none"}, {"display": "none"}
    
    raise dash.exceptions.PreventUpdate

# Callback to handle constraint dropdown toggle
@app.callback(
    Output("errors-content", "children", allow_duplicate=True),
    [Input({"type": "constraint-header", "index": dash.dependencies.ALL}, "n_clicks")],
    [State("constraint-details-store", "data"),
     State("errors-content", "children")],
    prevent_initial_call=True
)
def toggle_constraint_dropdown(n_clicks_list, constraint_details, current_content):
    """Handle constraint dropdown toggle by regenerating content with updated state"""
    ctx = dash.callback_context
    if not ctx.triggered or not any(n_clicks_list):
        raise dash.exceptions.PreventUpdate
    
    # Find which header was clicked
    trigger_info = ctx.triggered[0]['prop_id']
    clicked_index = eval(trigger_info.split('.')[0])['index']
    
    # Toggle the expansion state for this constraint
    # For simplicity, we'll regenerate the entire content with the clicked item toggled
    return create_errors_modal_content(constraint_details, toggle_constraint=clicked_index)

# Callbacks to handle download actions
@app.callback(
    Output("download-status", "children"),
    [Input("download-sst-btn", "n_clicks"),
     Input("download-tyd-btn", "n_clicks"),
     Input("download-lecturer-btn", "n_clicks")],
    prevent_initial_call=True
)
def handle_download_actions(sst_clicks, tyd_clicks, lecturer_clicks):
    """Handle download button clicks"""
    ctx = dash.callback_context
    if not ctx.triggered:
        raise dash.exceptions.PreventUpdate
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    try:
        # Import output_data functions
        from output_data import export_sst_timetables, export_tyd_timetables, export_lecturer_timetables
        
        if trigger_id == "download-sst-btn" and sst_clicks:
            success, message = export_sst_timetables()
            if success:
                return html.Div(f"✅ {message}", style={"color": "green", "fontWeight": "600"})
            else:
                return html.Div(f"❌ {message}", style={"color": "red", "fontWeight": "600"})
                
        elif trigger_id == "download-tyd-btn" and tyd_clicks:
            success, message = export_tyd_timetables()
            if success:
                return html.Div(f"✅ {message}", style={"color": "green", "fontWeight": "600"})
            else:
                return html.Div(f"❌ {message}", style={"color": "red", "fontWeight": "600"})
                
        elif trigger_id == "download-lecturer-btn" and lecturer_clicks:
            success, message = export_lecturer_timetables()
            if success:
                return html.Div(f"✅ {message}", style={"color": "green", "fontWeight": "600"})
            else:
                return html.Div(f"❌ {message}", style={"color": "red", "fontWeight": "600"})
    
    except Exception as e:
        return html.Div(f"❌ Error: {str(e)}", style={"color": "red", "fontWeight": "600"})
    
    raise dash.exceptions.PreventUpdate

# Callback to handle undo all changes
@app.callback(
    [Output("all-timetables-store", "data", allow_duplicate=True),
     Output("feedback", "children", allow_duplicate=True)],
    Input("undo-all-btn", "n_clicks"),
    State("original-timetables-store", "data"),
    prevent_initial_call=True
)
def handle_undo_all_changes(n_clicks, original_timetables):
    if n_clicks and original_timetables:
        print("🔄 Undoing all changes - reverting to original timetable")
        
        # Clear the saved timetable file so fresh DE results are used on next restart
        clear_saved_timetable()
        
        return original_timetables, html.Div("✅ All changes have been undone!", 
                                           style={"color": "green", "fontWeight": "600"})
    raise dash.exceptions.PreventUpdate

def create_errors_modal_content(constraint_details, expanded_constraint=None, toggle_constraint=None):
    """Create the content for the errors modal with constraint dropdowns"""
    if not constraint_details:
        return [html.Div("No constraint violation data available.", style={"padding": "20px", "textAlign": "center"})]
    
    # Keep track of expanded states (simple approach)
    if not hasattr(create_errors_modal_content, 'expanded_states'):
        create_errors_modal_content.expanded_states = set()
    
    # Toggle the state if a constraint was clicked
    if toggle_constraint:
        if toggle_constraint in create_errors_modal_content.expanded_states:
            create_errors_modal_content.expanded_states.remove(toggle_constraint)
        else:
            create_errors_modal_content.expanded_states.add(toggle_constraint)
    
    # Set initial expanded state if specified
    if expanded_constraint:
        create_errors_modal_content.expanded_states.add(expanded_constraint)
    
    # Mapping from user-friendly names to internal names
    constraint_mapping = {
        'Same Student Group Overlaps': 'Same Student Group Overlaps',
        'Different Student Group Overlaps': 'Different Student Group Overlaps', 
        'Lecturer Clashes': 'Lecturer Clashes',
        'Lecturer Schedule Conflicts (Day/Time)': 'Lecturer Schedule Conflicts (Day/Time)',
        'Lecturer Workload Violations': 'Lecturer Workload Violations',
        'Consecutive Slot Violations': 'Consecutive Slot Violations',
        'Missing or Extra Classes': 'Missing or Extra Classes',
        'Same Course in Multiple Rooms on Same Day': 'Same Course in Multiple Rooms on Same Day',
        'Room Capacity/Type Conflicts': 'Room Capacity/Type Conflicts',
        'Classes During Break Time': 'Classes During Break Time'
    }
    
    content = []
    
    for display_name, internal_name in constraint_mapping.items():
        violations = constraint_details.get(internal_name, [])
        count = len(violations)
        
        # Determine if this dropdown should be expanded
        is_expanded = display_name in create_errors_modal_content.expanded_states
        
        # Determine count badge class
        count_class = "constraint-count zero" if count == 0 else "constraint-count non-zero"
        
        # Create constraint header
        header = html.Div([
            html.Span(display_name, style={"flex": "1"}),
            html.Span(f"{count} Occurrence{'s' if count != 1 else ''}", className=count_class),
            html.Span("^", className=f"constraint-arrow{' rotated' if is_expanded else ''}")
        ], className=f"constraint-header{' active' if is_expanded else ''}", 
           id={"type": "constraint-header", "index": display_name}, n_clicks=0)
        
        # Create constraint details
        details_content = []
        if violations:
            for i, violation in enumerate(violations):
                if internal_name == 'Same Student Group Overlaps':
                    details_content.append(html.Div(
                        f"Group '{violation['group']}' has clashing courses {', '.join(violation['courses'])} on {violation['location']}",
                        className="constraint-item"
                    ))
                elif internal_name == 'Different Student Group Overlaps':
                    # Handle both old format (events) and new format (groups)
                    if 'events' in violation:
                        details_content.append(html.Div(
                            f"Room conflict at {violation['location']}: {', '.join(violation['events'])}",
                            className="constraint-item"
                        ))
                    elif 'groups' in violation:
                        details_content.append(html.Div(
                            f"Room conflict in {violation['room']} at {violation['location']}: Groups {', '.join(violation['groups'])} both scheduled",
                            className="constraint-item"
                        ))
                    else:
                        details_content.append(html.Div(
                            f"Room conflict at {violation.get('location', 'Unknown location')}",
                            className="constraint-item"
                        ))
                elif internal_name == 'Lecturer Clashes':
                    # Show both student groups that are clashing
                    if 'groups' in violation and len(violation['groups']) >= 2:
                        details_content.append(html.Div(
                            f"Lecturer '{violation['lecturer']}' has clashing courses {violation['courses'][0]} for group {violation['groups'][0]}, and {violation['courses'][1]} for group {violation['groups'][1]} on {violation['location']}",
                            className="constraint-item"
                        ))
                    else:
                        # Fallback to original format if groups info is missing
                        details_content.append(html.Div(
                            f"Lecturer '{violation['lecturer']}' has clashing courses {', '.join(violation['courses'])} on {violation['location']}",
                            className="constraint-item"
                        ))
                elif internal_name == 'Lecturer Schedule Conflicts (Day/Time)':
                    details_content.append(html.Div(
                        f"Lecturer '{violation['lecturer']}' scheduled for {violation['course']} for group {violation['group']} on {violation['location']} but available: {violation['available_days']} at {violation['available_times']}",
                        className="constraint-item"
                    ))
                elif internal_name == 'Lecturer Workload Violations':
                    if violation['type'] == 'Excessive Daily Hours':
                        courses_text = violation.get('courses', 'Unknown courses')
                        details_content.append(html.Div(
                            f"Lecturer '{violation['lecturer']}' has {violation['hours_scheduled']} hours on {violation['day']} from courses {courses_text}, exceeding maximum of {violation['max_allowed']} hours per day",
                            className="constraint-item"
                        ))
                    elif violation['type'] == 'Excessive Consecutive Hours':
                        courses_text = violation.get('courses', 'Unknown courses')
                        details_content.append(html.Div(
                            f"Lecturer '{violation['lecturer']}' has {violation['consecutive_hours']} consecutive hours on {violation['day']} from courses {courses_text} ({', '.join(violation['hours_times'])}), exceeding maximum of {violation['max_allowed']} consecutive hours",
                            className="constraint-item"
                        ))
                    else:
                        details_content.append(html.Div(
                            f"Lecturer workload violation for {violation['lecturer']} on {violation['day']}: {violation.get('violation', 'Unknown violation')}",
                            className="constraint-item"
                        ))
                elif internal_name == 'Consecutive Slot Violations':
                    details_content.append(html.Div(
                        f"{violation['reason']}: Course '{violation['course']}' ({violation.get('course_name', '')}) for group '{violation['group']}' at times {', '.join(violation['times'])}",
                        className="constraint-item"
                    ))
                elif internal_name == 'Missing or Extra Classes':
                    details_content.append(html.Div(
                        f"{violation['issue']} classes for {violation['location']}: Expected {violation['expected']}, Got {violation['actual']}",
                        className="constraint-item"
                    ))
                elif internal_name == 'Same Course in Multiple Rooms on Same Day':
                    details_content.append(html.Div(
                        f"{violation['location']} in multiple rooms: {', '.join(violation['rooms'])}",
                        className="constraint-item"
                    ))
                elif internal_name == 'Room Capacity/Type Conflicts':
                    if violation['type'] == 'Room Type Mismatch':
                        details_content.append(html.Div(
                            f"Room type mismatch at {violation['location']}: {violation['course']} for group {violation['group']} requires {violation['required_type']} but scheduled in {violation['room']} ({violation['room_type']})",
                            className="constraint-item"
                        ))
                    else:
                        details_content.append(html.Div(
                            f"Room capacity exceeded at {violation['room']} by group {violation['group']} on {violation['day']} at {violation['time']}: {violation['students']} students in {violation['room']} (capacity: {violation['capacity']})",
                            className="constraint-item"
                        ))
                elif internal_name == 'Classes During Break Time':
                    details_content.append(html.Div(
                        f"Class during break time at {violation['location']}: {violation['course']} for {violation['group']}",
                        className="constraint-item"
                    ))
        else:
            details_content.append(html.Div("No violations found.", className="constraint-item", style={"color": "#28a745", "fontStyle": "italic"}))
        
        details = html.Div(details_content, 
                          className=f"constraint-details{' expanded' if is_expanded else ''}", 
                          id={"type": "constraint-details", "index": display_name})
        
        # Add constraint dropdown to content
        content.append(html.Div([header, details], className="constraint-dropdown"))
    
    return content

# Callback to update the error notification badge
@app.callback(
    Output("error-notification-badge", "children"),
    [Input("constraint-details-store", "data"),
     Input("all-timetables-store", "data")],
    prevent_initial_call=False
)
def update_error_notification_badge(constraint_details, timetables_data):
    if not constraint_details:
        return "0"
    
    # Define which constraints are hard constraints
    hard_constraint_names = [
        'Same Student Group Overlaps',
        'Different Student Group Overlaps', 
        'Lecturer Clashes',
        'Lecturer Schedule Conflicts (Day/Time)',
        'Lecturer Workload Violations',
        'Consecutive Slot Violations',
        'Missing or Extra Classes',
        'Same Course in Multiple Rooms on Same Day',
        'Room Capacity/Type Conflicts',
        'Classes During Break Time'
    ]
    
    # Count how many hard constraints have violations
    violated_hard_constraints = 0
    for constraint_name in hard_constraint_names:
        violations = constraint_details.get(constraint_name, [])
        if len(violations) > 0:
            violated_hard_constraints += 1
    
    return str(violated_hard_constraints)

# Run the Dash app
if __name__ == '__main__':
    app.run(debug=False)
    
    # Uncomment below to test DE algorithm performance
    # import time
    # pop_size = 30  # Reduced population size for faster testing
    # F = 0.5
    # max_generations = 10  # Reduced generations for testing
    # CR = 0.8

    # print("Starting Differential Evolution")
    # de = DifferentialEvolution(input_data, pop_size, F, CR)

    # start_time = time.time()
    # best_solution, fitness_history, generation, diversity_history = de.run(max_generations)
    # de_time = time.time() - start_time

    # print(f'Time: {de_time:.2f}s')
    # print(f'Final fitness: {fitness_history[-1] if fitness_history else "N/A"}')
    # print(f'Initial fitness: {fitness_history[0] if fitness_history else "N/A"}')
    
    # # If initial fitness is good, then run the app
    # if fitness_history and fitness_history[0] < 200:
    #     print("✅ Initial fitness is acceptable, running Dash app...")
    #     app.run(debug=False)
    # else:
    #     print("❌ Initial fitness is too high, please check constraints")