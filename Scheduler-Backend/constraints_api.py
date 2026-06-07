# constraints.py
"""
Updated constraints module that works with API-compatible input_data instances
instead of static imports.
"""

import random
import re

class Constraints:
    def __init__(self, input_data):
        self.input_data = input_data
        self.validate_faculty_data()  # Validate data on initialization
        self.rooms = input_data.rooms
        self.timeslots = input_data.create_time_slots(no_hours_per_day=input_data.hours, no_days_per_week=input_data.days, day_start_time=9)
        self.student_groups = input_data.student_groups
        self.courses = input_data.courses
        self.events_list, self.events_map = self.create_events()

    def validate_faculty_data(self):
        """
        Validates the format of avail_days and avail_times for all faculty members.
        Raises a ValueError if any format is incorrect.
        """
        time_format_regex = re.compile(r'^\d{2}:\d{2}-\d{2}:\d{2}$')
        valid_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "All"]

        for faculty in self.input_data.faculties:
            # Validate avail_times
            if isinstance(faculty.avail_times, str) and faculty.avail_times.upper() != 'ALL':
                if not time_format_regex.match(faculty.avail_times):
                    raise ValueError(
                        f"FATAL: Invalid 'avail_times' format for faculty '{faculty.name}' (ID: {faculty.faculty_id}). "
                        f"Expected 'HH:MM-HH:MM' or 'ALL', but got '{faculty.avail_times}'. Please correct the input data."
                    )
            
            # Validate avail_days
            days_to_check = []
            if isinstance(faculty.avail_days, str):
                if faculty.avail_days.upper() == 'ALL':
                    days_to_check = ["All"]
                else:
                    days_to_check = [d.strip() for d in faculty.avail_days.split(',')]
            elif isinstance(faculty.avail_days, list):
                days_to_check = faculty.avail_days

            for day in days_to_check:
                if day.capitalize() not in valid_days:
                    raise ValueError(
                        f"FATAL: Invalid 'avail_days' value for faculty '{faculty.name}' (ID: {faculty.faculty_id}). "
                        f"Found invalid day '{day}'. Valid days are {valid_days}. Please correct the input data."
                    )
    
    def create_events(self):
        """Create events list and mapping similar to genetic algorithm"""
        events_list = []
        event_map = {}
        
        from entitities.Class import Class
        
        idx = 0
        for student_group in self.student_groups:
            for i in range(student_group.no_courses):
                # Get the course to check its credits
                course = self.input_data.getCourse(student_group.courseIDs[i])
                
                # SPECIAL HANDLING FOR 1-CREDIT COURSES:
                # If course has 1 credit, it must have 3 hours (with 2 consecutive rule)
                if course and course.credits == 1:
                    required_hours = 3  # Force 1-credit courses to have 3 hours
                else:
                    # Use original hours required for other courses
                    required_hours = student_group.hours_required[i]
                
                hourcount = 1 
                while hourcount <= required_hours:
                    event = Class(student_group, student_group.teacherIDS[i], student_group.courseIDs[i])
                    events_list.append(event)
                    
                    # Add the event to the index map with the current index
                    event_map[idx] = event
                    idx += 1
                    hourcount += 1
                    
        return events_list, event_map    

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
                    course = self.input_data.getCourse(class_event.course_id)
                    # H1a: Room type constraints
                    if room.room_type != course.required_room_type:
                        point += 1
                    # H1b: Room capacity constraints - student group must fit in room
                    if class_event.student_group.no_students > room.capacity:
                        point += 1

        return point
       
    
    def check_student_group_constraints(self, chromosome):
        """
        No student group can have overlapping classes at the same time
        """
        penalty = 0
        for i in range(len(self.timeslots)):
            simultaneous_class_events = chromosome[:, i]
            student_group_watch = set()
            for class_event_idx in simultaneous_class_events:
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None:  # Added safety check
                        student_group = class_event.student_group
                        if student_group.id in student_group_watch:
                            penalty += 1  # Student group has overlapping classes
                        else:
                            student_group_watch.add(student_group.id)

        return penalty
    
    def check_lecturer_availability(self, chromosome):
        """
        No lecturer can have overlapping classes at the same time
        """
        penalty = 0
        for i in range(len(self.timeslots)):
            simultaneous_class_events = chromosome[:, i]
            lecturer_watch = set()
            for class_event_idx in simultaneous_class_events:
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None:  # Added safety check
                        faculty_id = class_event.faculty_id
                        if faculty_id is not None:  # Check if faculty_id exists
                            if faculty_id in lecturer_watch:
                                penalty += 1  # Lecturer has overlapping classes
                            else:
                                lecturer_watch.add(faculty_id)

        return penalty

    def check_lecturer_schedule_constraints(self, chromosome):
        """
        Checks if courses are scheduled according to the lecturer's available days and times.
        """
        penalty = 0
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    class_event = self.events_map.get(event_id)
                    if class_event and class_event.faculty_id is not None:
                        faculty = self.input_data.getFaculty(class_event.faculty_id)
                        if not faculty:
                            continue

                        timeslot = self.timeslots[timeslot_idx]
                        day_idx = timeslot_idx // self.input_data.hours
                        day_abbr = days_map.get(day_idx)

                        # 1. Check available days
                        is_available_day = False
                        if isinstance(faculty.avail_days, str):
                            if faculty.avail_days.upper() == "ALL":
                                is_available_day = True
                            else:
                                avail_days = [d.strip().capitalize() for d in faculty.avail_days.split(',')]
                                if day_abbr in avail_days:
                                    is_available_day = True
                        elif isinstance(faculty.avail_days, list):
                            avail_days = [d.strip().capitalize() for d in faculty.avail_days]
                            if "All" in avail_days or day_abbr in avail_days:
                                is_available_day = True

                        if not is_available_day:
                            penalty += 10
                            continue

                        # 2. Check available times
                        if isinstance(faculty.avail_times, str) and faculty.avail_times.upper() != "ALL":
                            try:
                                start_avail_str, end_avail_str = faculty.avail_times.split('-')
                                start_avail_h = int(start_avail_str.split(':')[0])
                                end_avail_h = int(end_avail_str.split(':')[0])

                                # TimeSlot.start_time is stored as an integer hour index (0-based) in this project.
                                # Convert it to the real clock hour using the day start time (9).
                                slot_start_h = int(timeslot.start_time) + 9

                                # The end hour is exclusive. e.g., 09:00-12:00 means 9, 10, 11 are valid.
                                if not (start_avail_h <= slot_start_h < end_avail_h):
                                    penalty += 10
                            except (ValueError, IndexError):
                                # This should not be reached if validation is done correctly, but as a safeguard:
                                penalty += 10 # Penalize malformed strings that slip through
        return penalty

    def check_room_time_conflict(self, chromosome):
        """
        Ensure only one event is scheduled per room per timeslot
        """
        penalty = 0
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event = chromosome[room_idx][timeslot_idx]
                if event is not None:
                    # Check if event is somehow a list (multiple events in same slot)
                    if isinstance(event, list) and len(event) > 1:
                        penalty += 10  # Reduced from 100 to 10
                    
                    # Additional check: count non-None values to ensure only one event per slot
                    # This constraint is inherently satisfied by the chromosome structure,
                    # but we check for any data corruption
                    
        return penalty

    def check_break_time_constraint(self, chromosome):
        """
        Ensure no classes are scheduled during break time (13:00 - 14:00) on Mon, Wed, Fri.
        Break time corresponds to timeslot index 4 on each day (9:00, 10:00, 11:00, 12:00, 13:00)
        """
        penalty = 0
        break_hour = 4  # 13:00 is the 5th hour (index 4) starting from 9:00
        
        for day in range(self.input_data.days):  # For each day
            # Apply break constraint only on Monday (0), Wednesday (2), and Friday (4)
            if day in [0, 2, 4]:
                break_timeslot = day * self.input_data.hours + break_hour  # Calculate break timeslot index
                
                for room_idx in range(len(self.rooms)):
                    if chromosome[room_idx][break_timeslot] is not None:
                        penalty += 100
                        
        return penalty

    def check_building_assignments(self, chromosome):
        """
        STRICT building assignment rules:
        - Engineering/Computer Science/Software Engineering groups MUST be in SST building
        - All other groups MUST be in TYD building  
        - Exception: Computer lab courses can use any computer lab regardless of building
          (since there are only 2 computer labs in SST but more courses may need them)
        """
        penalty = 0
        
        # Identify engineering groups more comprehensively
        engineering_groups = []
        for student_group in self.student_groups:
            group_name = student_group.name.lower()
            # Check for engineering, computer science, software engineering keywords
            if any(keyword in group_name for keyword in [
                'engineering', 'eng', 'computer science', 'software engineering',
                'mechatronics', 'electrical', 'mechanical', 'csc', 'sen'
            ]):
                engineering_groups.append(student_group.id)
        
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    class_event = self.events_map.get(event_id)
                    room = self.rooms[room_idx]
                    course = self.input_data.getCourse(class_event.course_id)
                    
                    if class_event and course:
                        # Computer lab exception: Check if this needs a computer lab
                        needs_computer_lab = (
                            course.required_room_type.lower() in ['comp lab', 'computer_lab'] or
                            room.room_type.lower() in ['comp lab', 'computer_lab'] or
                            'lab' in course.name.lower() and ('computer' in course.name.lower() or 
                                                             'programming' in course.name.lower() or
                                                             'software' in course.name.lower())
                        )
                        
                        # Get room's building
                        room_building = None
                        if hasattr(room, 'building'):
                            room_building = room.building.upper()
                        elif hasattr(room, 'name') and room.name:
                            room_name = room.name.upper()
                            if 'SST' in room_name:
                                room_building = 'SST'
                            elif 'TYD' in room_name:
                                room_building = 'TYD'
                        elif hasattr(room, 'room_id'):
                            room_id = str(room.room_id).upper()
                            if 'SST' in room_id:
                                room_building = 'SST'
                            elif 'TYD' in room_id:
                                room_building = 'TYD'
                        
                        # Apply LENIENT building assignment rules (reduced penalties)
                        if class_event.student_group.id in engineering_groups:
                            # Engineering groups prefer SST but small penalty for TYD
                            if not needs_computer_lab and room_building != 'SST':
                                penalty += 0.5  # Very small penalty (reduced from 2)
                        else:
                            # Non-engineering groups prefer TYD but small penalty for SST
                            if not needs_computer_lab and room_building == 'SST':
                                penalty += 0.5  # Very small penalty (reduced from 20)
                        
        return penalty

    def check_same_course_same_room_per_day(self, chromosome):
        """
        Same course appearing multiple times on same day must be in same room.
        """
        penalty = 0
        course_day_rooms = {}  # {(course_id, day): set_of_rooms}
        
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    class_event = self.events_map.get(event_id)
                    if class_event:
                        day_idx = timeslot_idx // self.input_data.hours
                        # Use the correct course identifier
                        course = self.input_data.getCourse(class_event.course_id)
                        course_id = getattr(course, 'course_id', None) or getattr(course, 'id', None) or getattr(course, 'code', None) if course else class_event.course_id
                        # The key now includes the student group to correctly handle multiple groups taking the same course
                        course_day_key = (course_id, day_idx, class_event.student_group.id)
                        
                        if course_day_key not in course_day_rooms:
                            course_day_rooms[course_day_key] = set()
                        course_day_rooms[course_day_key].add(room_idx)
        
        # Penalize courses that appear in multiple rooms on same day
        for course_day_key, rooms_used in course_day_rooms.items():
            if len(rooms_used) > 1:
                penalty += 5 * (len(rooms_used) - 1)  # Reduced penalty for room inconsistency
        
        return penalty


    def check_single_event_per_day(self, chromosome):
        penalty = 0
        
        # Create a dictionary to track events per day for each student group
        events_per_day = {group.id: [0] * self.input_data.days for group in self.student_groups}

        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                class_event_idx = chromosome[room_idx][timeslot_idx]
                if class_event_idx is not None:  # Event scheduled
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None:
                        student_group = class_event.student_group
                        day_idx = timeslot_idx // self.input_data.hours  # Calculate which day this timeslot falls on
                        
                        # S1: Try to avoid scheduling more than one event per day for each student group
                        events_per_day[student_group.id][day_idx] += 1
                        if events_per_day[student_group.id][day_idx] > 1:
                            penalty += 0.05  # Soft penalty for multiple events on the same day for a group

        return penalty

    def check_consecutive_timeslots(self, chromosome):
        """
        - 2-credit courses MUST be in 2 consecutive slots.
        - 3-credit courses MUST have at least a 2-hour block.
        - Penalizes the single hour of a 3-credit course if it's not consecutive with the block.
        """
        penalty = 0
        
        # Group events by course and student group to analyze their schedule
        course_schedule = {} # {(course_id, student_group_id): [timeslot_indices]}
        
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    event = self.events_map.get(event_id)
                    if event:
                        course = self.input_data.getCourse(event.course_id)
                        if course:
                            key = (course.code, event.student_group.id)
                            if key not in course_schedule:
                                course_schedule[key] = []
                            course_schedule[key].append(timeslot_idx)

        for (course_id, student_group_id), timeslots in course_schedule.items():
            course = self.input_data.getCourse(course_id)
            if not course or course.credits <= 1:
                continue

            # Sort timeslots to check for consecutiveness
            timeslots.sort()
            
            if course.credits == 2:
                # H: 2-credit courses MUST be consecutive
                if len(timeslots) == 2 and (timeslots[1] - timeslots[0] != 1):
                    penalty += 50 # Severe penalty for breaking a 2-hour block
            
            elif course.credits == 3:
                # H: 3-credit courses MUST have at least a 2-hour block
                if len(timeslots) == 3:
                    is_block_of_2 = (timeslots[1] - timeslots[0] == 1) or \
                                    (timeslots[2] - timeslots[1] == 1)
                    if not is_block_of_2:
                        penalty += 50 # Severe penalty if no 2-hour block exists
                    
                    # S: Prefer all 3 hours to be consecutive
                    is_block_of_3 = (timeslots[1] - timeslots[0] == 1) and \
                                    (timeslots[2] - timeslots[1] == 1)
                    if not is_block_of_3:
                        penalty += 0.1 # Small penalty for the separated hour

        return penalty

    # Optional: Spread events over the week
    def check_spread_events(self, chromosome):
        penalty = 0
        group_event_days = {group.id: set() for group in self.student_groups}
        total_events = {group.id: 0 for group in self.student_groups}
        events_per_day = {group.id: [0] * self.input_data.days for group in self.student_groups}
        
        # S3: Try to spread the events throughout the week
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                class_event_idx = chromosome[room_idx][timeslot_idx]
                if class_event_idx is not None:  # Event scheduled
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None:
                        student_group = class_event.student_group
                        day_idx = timeslot_idx // self.input_data.hours
                        
                        # Track which days each student group has events
                        group_event_days[student_group.id].add(day_idx)
                        total_events[student_group.id] += 1
                        events_per_day[student_group.id][day_idx] += 1

        # Penalize student groups that have events tightly clustered in the week
        for group_id, event_days in group_event_days.items():
            total = int(total_events.get(group_id, 0) or 0)
            if total <= 1:
                continue
            days_total = int(self.input_data.days)
            hours_per_day = int(self.input_data.hours)

            target_days = min(days_total, total)
            missing = max(0, target_days - len(event_days))
            if missing:
                penalty += 50.0 * missing  # Extremely strong penalty to spread across days

            min_days_target = min(3, total, days_total)
            if len(event_days) < min_days_target:
                penalty += 25.0 * (min_days_target - len(event_days))

            if hours_per_day > 0:
                for day_idx in range(days_total):
                    scheduled = events_per_day[group_id][day_idx]
                    free_hours = max(0, hours_per_day - scheduled)
                    if free_hours < 2:
                        penalty += 100.0 * (2 - free_hours)

        return penalty

    def check_course_allocation_completeness(self, chromosome):
        """
        Check that all courses appear the correct number of times for each student group
        based on their credit hours/hours_required.
        """
        penalty = 0
        
        for student_group in self.student_groups:
            # Count actual course occurrences
            course_counts = {}
            for room_idx in range(len(self.rooms)):
                for timeslot_idx in range(len(self.timeslots)):
                    event_id = chromosome[room_idx][timeslot_idx]
                    if event_id is not None:
                        class_event = self.events_map.get(event_id)
                        if class_event and class_event.student_group.id == student_group.id:
                            course_id = class_event.course_id
                            course_counts[course_id] = course_counts.get(course_id, 0) + 1
            
            # Check expected vs actual course occurrences
            for i, course_id in enumerate(student_group.courseIDs):
                # Get the course to check if it's a 1-credit course
                course = self.input_data.getCourse(course_id)
                
                # SPECIAL HANDLING FOR 1-CREDIT COURSES:
                # If course has 1 credit, it must have 3 hours
                if course and course.credits == 1:
                    expected_hours = 3  # Force 1-credit courses to have 3 hours
                else:
                    expected_hours = student_group.hours_required[i]
                
                actual_hours = course_counts.get(course_id, 0)
                
                if actual_hours != expected_hours:
                    # Apply moderate penalty for missing courses (reduced from extreme values)
                    difference = abs(expected_hours - actual_hours)
                    if actual_hours == 0:
                        penalty += difference * 5  # Reduced from 50 to 5
                    else:
                        penalty += difference * 2  # Reduced from 10 to 2
        
        return penalty

    def evaluate_fitness(self, chromosome):
        """
        Evaluate the overall fitness of a chromosome by checking all constraints.
        Lower values indicate better fitness.
        """
        # Keep API fitness priorities aligned with the core constraints.
        weights = {
            'student_group_constraints': 1000.0,
            'course_allocation_completeness': 800.0,
            'lecturer_availability': 600.0,
            'room_time_conflict': 500.0,

            # Other hard constraints
            'room_constraints': 120.0,
            'lecturer_schedule_constraints': 80.0,
            'break_time_constraint': 60.0,
            'building_assignments': 40.0,
            'same_course_same_room_per_day': 40.0,
        }

        penalty = 0.0
        cost = 0.0

        penalty += weights['room_constraints'] * self.check_room_constraints(chromosome)
        penalty += weights['student_group_constraints'] * self.check_student_group_constraints(chromosome)
        penalty += weights['lecturer_availability'] * self.check_lecturer_availability(chromosome)
        penalty += weights['room_time_conflict'] * self.check_room_time_conflict(chromosome)
        penalty += weights['building_assignments'] * self.check_building_assignments(chromosome)
        penalty += weights['same_course_same_room_per_day'] * self.check_same_course_same_room_per_day(chromosome)
        penalty += weights['break_time_constraint'] * self.check_break_time_constraint(chromosome)
        penalty += weights['course_allocation_completeness'] * self.check_course_allocation_completeness(chromosome)
        penalty += weights['lecturer_schedule_constraints'] * self.check_lecturer_schedule_constraints(chromosome)

        cost += 5.0 * self.check_single_event_per_day(chromosome)
        cost += 5.0 * self.check_consecutive_timeslots(chromosome)
        cost += 300.0 * self.check_spread_events(chromosome)

        return penalty + cost
        
    def get_all_conflicts(self, chromosome):
        """
        Identifies all conflicts in a given chromosome to guide the crossover process.
        Returns a dictionary of conflicts.
        """
        conflicts = {
            'student_group': [],
            'lecturer': [],
            'room': []
        }

        # Check for student group and lecturer clashes
        for timeslot_idx in range(len(self.timeslots)):
            student_group_watch = {}
            lecturer_watch = {}
            simultaneous_events = chromosome[:, timeslot_idx]

            for room_idx, event_id in enumerate(simultaneous_events):
                if event_id is not None:
                    event = self.events_map.get(event_id)
                    if event:
                        # Student group conflicts
                        sg_id = event.student_group.id
                        if sg_id in student_group_watch:
                            conflicts['student_group'].append({
                                'timeslot': timeslot_idx,
                                'student_group': sg_id,
                                'positions': [student_group_watch[sg_id], (room_idx, timeslot_idx)]
                            })
                        else:
                            student_group_watch[sg_id] = (room_idx, timeslot_idx)

                        # Lecturer conflicts
                        fac_id = event.faculty_id
                        if fac_id in lecturer_watch:
                            conflicts['lecturer'].append({
                                'timeslot': timeslot_idx,
                                'lecturer': fac_id,
                                'positions': [lecturer_watch[fac_id], (room_idx, timeslot_idx)]
                            })
                        else:
                            lecturer_watch[fac_id] = (room_idx, timeslot_idx)

        # Check for room capacity/type conflicts
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    event = self.events_map.get(event_id)
                    room = self.rooms[room_idx]
                    course = self.input_data.getCourse(event.course_id)
                    if event and course:
                        if room.room_type != course.required_room_type or event.student_group.no_students > room.capacity:
                            conflicts['room'].append({
                                'position': (room_idx, timeslot_idx),
                                'details': f"Room {room.name} (cap {room.capacity}, type {room.room_type}) vs Course {course.code} (students {event.student_group.no_students}, type {course.required_room_type})"
                            })

        return conflicts
        
    def get_constraint_violations(self, chromosome, debug: bool = False):
        """
        Get detailed information about constraint violations for debugging.
        """
        violations = {
            'room_constraints': self.check_room_constraints(chromosome),
            'student_group_constraints': self.check_student_group_constraints(chromosome),
            'lecturer_availability': self.check_lecturer_availability(chromosome),
            'lecturer_schedule_constraints': self.check_lecturer_schedule_constraints(chromosome),
            'room_time_conflict': self.check_room_time_conflict(chromosome),
            'building_assignments': self.check_building_assignments(chromosome),
            'same_course_same_room_per_day': self.check_same_course_same_room_per_day(chromosome),
            'break_time_constraint': self.check_break_time_constraint(chromosome),
            'course_allocation_completeness': self.check_course_allocation_completeness(chromosome),
            'single_event_per_day': self.check_single_event_per_day(chromosome),
            'consecutive_timeslots': self.check_consecutive_timeslots(chromosome),
            'spread_events': self.check_spread_events(chromosome)
        }
        violations['total'] = sum(violations.values())
        return violations

    def get_detailed_constraint_violations(self, chromosome):
        """Return detailed constraint violations for UI display.

        The API layer primarily uses the core [constraints.py](constraints.py) implementation.
        This method is provided for compatibility if any API path instantiates
        [constraints_api.py](constraints_api.py) directly.
        """
        try:
            # Local import to avoid circular dependencies.
            from constraints import Constraints as CoreConstraints

            core = CoreConstraints(self.input_data)
            return core.get_detailed_constraint_violations(chromosome)
        except Exception:
            return {}