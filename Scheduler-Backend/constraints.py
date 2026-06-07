import random

import re

class Constraints:
    def __init__(self, input_data):
        self.input_data = input_data
        self.validate_faculty_data() # Validate data on initialization
        self.rooms = input_data.rooms
        self.timeslots = input_data.create_time_slots(no_hours_per_day=input_data.hours, no_days_per_week=input_data.days, day_start_time=9)
        self.student_groups = input_data.student_groups
        self.courses = input_data.courses
        self.events_list, self.events_map = self.create_events()

    def format_hour(self, h):
        """Helper to format decimal hour (e.g. 8.5) to string (e.g. '8:30')"""
        hour = int(h)
        minute = int((h - hour) * 60)
        return f"{hour}:{minute:02d}"

    def validate_faculty_data(self):
        """
        Validates the format of avail_days and avail_times for all faculty members.
        Raises a ValueError if any format is incorrect.
        """
        def _clean_token(v) -> str:
            tok = str(v or '').strip()
            while tok and tok[0] in "[({'\"":
                tok = tok[1:].lstrip()
            while tok and tok[-1] in "])'}\"":
                tok = tok[:-1].rstrip()
            return tok

        # Accept both 1-digit and 2-digit hour formats, and flexible separators (e.g., '-', '–', '—', 'to').
        time_format_regex = re.compile(r'^\s*\d{1,2}:\d{2}\s*(?:-|–|—|\bto\b)\s*\d{1,2}:\d{2}\s*$', re.IGNORECASE)
        valid_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "All"]

        for faculty in self.input_data.faculties:
            # Validate avail_times
            avail_times = getattr(faculty, 'avail_times', None)
            if isinstance(avail_times, str):
                raw = _clean_token(avail_times)
                if raw and (raw.upper() != 'ALL') and ('ALL' not in raw.upper()):
                    specs = [_clean_token(t) for t in raw.split(',') if _clean_token(t)]
                    if not specs:
                        pass
                    else:
                        for spec in specs:
                            if spec.upper() == 'ALL' or 'ALL' in spec.upper():
                                continue
                            if not time_format_regex.match(spec):
                                raise ValueError(
                                    f"FATAL: Invalid 'avail_times' format for faculty '{faculty.name}' (ID: {getattr(faculty, 'faculty_id', 'UNKNOWN')}). "
                                    f"Expected 'HH:MM-HH:MM' (or comma-separated ranges) or 'ALL', but got '{avail_times}'. Please correct the input data."
                                )
            elif isinstance(avail_times, list):
                for spec in avail_times:
                    spec_s = _clean_token(spec)
                    if not spec_s:
                        continue
                    if spec_s.upper() == 'ALL' or 'ALL' in spec_s.upper():
                        break
                    # Allow comma-separated entries within list elements.
                    for part in [_clean_token(p) for p in spec_s.split(',') if _clean_token(p)]:
                        if part.upper() == 'ALL' or 'ALL' in part.upper():
                            break
                        if not time_format_regex.match(part):
                            raise ValueError(
                                f"FATAL: Invalid 'avail_times' format for faculty '{faculty.name}' (ID: {getattr(faculty, 'faculty_id', 'UNKNOWN')}). "
                                f"Expected 'HH:MM-HH:MM' (or comma-separated ranges) or 'ALL', but got '{avail_times}'. Please correct the input data."
                            )
            elif isinstance(avail_times, dict):
                for _day_key, specs in avail_times.items():
                    if specs is None:
                        continue
                    if isinstance(specs, str):
                        specs_list = [_clean_token(t) for t in _clean_token(specs).split(',') if _clean_token(t)]
                    elif isinstance(specs, list):
                        specs_list = []
                        for x in specs:
                            x_s = _clean_token(x)
                            if not x_s:
                                continue
                            specs_list.extend([_clean_token(t) for t in x_s.split(',') if _clean_token(t)])
                    else:
                        specs_list = [_clean_token(specs)]

                    if any((s.upper() == 'ALL') or ('ALL' in s.upper()) for s in specs_list if s):
                        continue
                    for spec in specs_list:
                        if spec and (not time_format_regex.match(spec)):
                            raise ValueError(
                                f"FATAL: Invalid 'avail_times' format for faculty '{faculty.name}' (ID: {getattr(faculty, 'faculty_id', 'UNKNOWN')}). "
                                f"Expected 'HH:MM-HH:MM' (or comma-separated ranges) or 'ALL', but got '{avail_times}'. Please correct the input data."
                            )
            
            # Validate avail_days
            days_to_check = []
            if isinstance(faculty.avail_days, str):
                days_raw = _clean_token(faculty.avail_days)
                if (not days_raw) or (days_raw.upper() == 'ALL') or ('ALL' in days_raw.upper()):
                    days_to_check = ["All"]
                else:
                    days_to_check = [_clean_token(d).strip() for d in days_raw.split(',') if _clean_token(d).strip()]
            elif isinstance(faculty.avail_days, list):
                cleaned_days = [_clean_token(d).strip() for d in faculty.avail_days if _clean_token(d).strip()]
                if any((d.upper() == 'ALL') or ('ALL' in d.upper()) for d in cleaned_days):
                    days_to_check = ["All"]
                else:
                    days_to_check = cleaned_days
            else:
                days_raw = _clean_token(getattr(faculty, 'avail_days', ''))
                if (not days_raw) or (days_raw.upper() == 'ALL') or ('ALL' in days_raw.upper()):
                    days_to_check = ["All"]
                else:
                    days_to_check = [_clean_token(d).strip() for d in str(days_raw).split(',') if _clean_token(d).strip()]

            for day in days_to_check:
                if day.capitalize() not in valid_days:
                    raise ValueError(
                        f"FATAL: Invalid 'avail_days' value for faculty '{faculty.name}' (ID: {getattr(faculty, 'faculty_id', 'UNKNOWN')}). "
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
                    tid = student_group.teacherIDS[i]
                    # Handle multiple lecturers: Default to the first one
                    if isinstance(tid, list) and len(tid) > 0:
                        tid = tid[0]
                    elif isinstance(tid, list) and len(tid) == 0:
                        tid = "Unknown"
                        
                    event = Class(student_group, tid, student_group.courseIDs[i])
                    events_list.append(event)
                    
                    # Add the event to the index map with the current index
                    event_map[idx] = event
                    idx += 1
                    hourcount += 1
                    
        return events_list, event_map    
    def check_room_constraints(self, chromosome, debug=False):
        """
        rooms must meet the capacity and type of the scheduled event
        """
        penalty = 0
        violations = []
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

        # Capacity/type feasibility pre-check:
        # If there is NO room of the required type (or no room of that type large enough for the group),
        # the corresponding penalty is treated as unavoidable and is not counted.
        # This keeps the system solvable when input data has unavoidable capacity/type mismatches.
        rooms_by_type = {}
        try:
            for r in self.rooms:
                rt = str(getattr(r, 'room_type', '') or '').strip()
                rooms_by_type.setdefault(rt, []).append(r)
        except Exception:
            rooms_by_type = {}

        type_exists = {rt: bool(rooms) for rt, rooms in rooms_by_type.items()}
        enforce_capacity = {}
        try:
            for sg in self.student_groups:
                gid = getattr(sg, 'id', None)
                gsize = int(getattr(sg, 'no_students', 0) or 0)
                for cid in getattr(sg, 'courseIDs', []) or []:
                    c = self.input_data.getCourse(cid)
                    if not c:
                        continue
                    req_type = str(getattr(c, 'required_room_type', '') or '').strip()
                    ckey = getattr(c, 'code', None) or getattr(c, 'course_id', None) or getattr(c, 'id', None) or cid
                    key = (str(ckey), str(gid))
                    candidates = rooms_by_type.get(req_type, [])
                    enforce_capacity[key] = bool(candidates) and any(int(getattr(r, 'capacity', 0) or 0) >= gsize for r in candidates)
        except Exception:
            enforce_capacity = {}
        
        for room_idx in range(len(self.rooms)):
            room = self.rooms[room_idx]
            for timeslot_idx in range(len(self.timeslots)):
                class_event = self.events_map.get(chromosome[room_idx][timeslot_idx])
                if class_event is not None:
                    course = self.input_data.getCourse(class_event.course_id)
                    timeslot = self.timeslots[timeslot_idx]
                    day_abbr = days_map.get(timeslot.day)
                    time = timeslot.start_time + 8.5
                    
                    # H1a: Room type constraints
                    req_type = str(getattr(course, 'required_room_type', '') or '').strip() if course else ''
                    room_type = str(getattr(room, 'room_type', '') or '').strip()
                    if req_type and type_exists.get(req_type, True) and room_type != req_type:
                        penalty += 0.5  # Reduced from 1 to 0.5
                        if debug:
                            violation_info = (
                                f"Room Type Mismatch: Course '{course.code}' requires '{course.required_room_type}' "
                                f"but is scheduled in '{room.name}' (type: '{room.room_type}') "
                                f"on {day_abbr} at {self.format_hour(time)} for group '{class_event.student_group.name}'."
                            )
                            if violation_info not in violations:
                                violations.append(violation_info)
                    
                    # H1b: Room capacity constraints - student group must fit in room
                    ckey = getattr(course, 'code', None) or getattr(course, 'course_id', None) or getattr(course, 'id', None) if course else class_event.course_id
                    gid = getattr(getattr(class_event, 'student_group', None), 'id', None)
                    cap_key = (str(ckey), str(gid))
                    if enforce_capacity.get(cap_key, True) and class_event.student_group.no_students > room.capacity:
                        penalty += 0.5  # Reduced from 1 to 0.5
                        if debug:
                            violation_info = (
                                f"Room Capacity Exceeded: Group '{class_event.student_group.name}' "
                                f"({class_event.student_group.no_students} students) cannot fit in room '{room.name}' "
                                f"(capacity: {room.capacity}) on {day_abbr} at {self.format_hour(time)} for course '{course.code}'."
                            )
                            if violation_info not in violations:
                                violations.append(violation_info)

                    # H1c: Building constraints - TYD students (MGT/SMC/etc) cannot be in SST building
                    # Use central is_sst property for scalability
                    room_building = str(room.building).upper().strip() if hasattr(room, 'building') and room.building else ""
                    
                    if not class_event.student_group.is_sst and room_building == 'SST':
                        penalty += 500  # High penalty (Hard Constraint)
                        if debug:
                            violation_info = (
                                f"Wrong Building: TYD Group '{class_event.student_group.name}' "
                                f"is scheduled in SST room '{room.name}' on {day_abbr} at {self.format_hour(time)}."
                            )
                            if violation_info not in violations:
                                violations.append(violation_info)

        if debug and violations:
            print("\n--- Room Constraint Violations Detected ---")
            for violation in sorted(violations):
                print(violation)
            print("------------------------------------------\n")

        return penalty
       
    
    def check_student_group_constraints(self, chromosome, debug=False):
        """
        No student group can have overlapping classes at the same time
        """
        penalty = 0
        clashes = []
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

        for i in range(len(self.timeslots)):
            simultaneous_class_events = chromosome[:, i]
            student_group_watch = {}  # Store the first event for a group in a timeslot
            for class_event_idx in simultaneous_class_events:
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None:
                        student_group = class_event.student_group
                        if student_group.id in student_group_watch:
                            penalty += 500  # Increased from 100 to 500 (Significant penalty)
                            if debug:
                                # A clash is detected. We have the new event and the one from the watch.
                                first_event = student_group_watch[student_group.id]
                                second_event = class_event
                                
                                first_course = self.input_data.getCourse(first_event.course_id)
                                second_course = self.input_data.getCourse(second_event.course_id)
                                
                                timeslot = self.timeslots[i]
                                day_abbr = days_map.get(timeslot.day)
                                time = timeslot.start_time + 8.5
                                
                                clash_info = (
                                    f"Student Group Clash: '{student_group.name}' on {day_abbr} at {self.format_hour(time)}. "
                                    f"Clashing Courses: '{first_course.code}' and '{second_course.code}'."
                                )
                                if clash_info not in clashes:
                                    clashes.append(clash_info)
                        else:
                            # First time seeing this group in this timeslot, store the event.
                            student_group_watch[student_group.id] = class_event
        
        if debug and clashes:
            print("\n--- Student Group Clashes Detected ---")
            for clash in sorted(clashes):
                print(clash)
            print("-------------------------------------\n")
            
        return penalty
    
    def check_lecturer_availability(self, chromosome, debug=False):
        """
        No lecturer can have overlapping classes at the same time
        """
        penalty = 0
        clashes = []
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

        for i in range(len(self.timeslots)):
            simultaneous_class_events = chromosome[:, i]
            lecturer_watch = {}  # Store the first event for a lecturer in a timeslot
            for class_event_idx in simultaneous_class_events:
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None:
                        faculty_id = class_event.faculty_id
                        if faculty_id is not None:
                            if faculty_id in lecturer_watch:
                                penalty += 500  # Increased from 100 to 500 (Significant penalty)
                                if debug:
                                    first_event = lecturer_watch[faculty_id]
                                    second_event = class_event
                                    
                                    faculty = self.input_data.getFaculty(faculty_id)
                                    first_course = self.input_data.getCourse(first_event.course_id)
                                    second_course = self.input_data.getCourse(second_event.course_id)
                                    
                                    timeslot = self.timeslots[i]
                                    day_abbr = days_map.get(timeslot.day)
                                    time = timeslot.start_time + 8.5
                                    
                                    # Use faculty name if available, otherwise use faculty_id (email)
                                    lecturer_name = faculty.name if faculty and faculty.name else faculty_id
                                    
                                    clash_info = (
                                        f"Lecturer Clash: '{lecturer_name}' on {day_abbr} at {self.format_hour(time)}. "
                                        f"Clashing Courses: '{first_course.name}' for group '{first_event.student_group.name}' and "
                                        f"'{second_course.name}' for group '{second_event.student_group.name}'."
                                    )
                                    if clash_info not in clashes:
                                        clashes.append(clash_info)
                            else:
                                lecturer_watch[faculty_id] = class_event
        
        if debug and clashes:
            print("\n--- Lecturer Clashes Detected ---")
            for clash in sorted(clashes):
                print(clash)
            print("---------------------------------\n")

        return penalty

    def check_lecturer_schedule_constraints(self, chromosome, debug=False):
        """
        Checks if courses are scheduled according to the lecturer's available days and times.
        """
        penalty = 0
        violations = []
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
                        day_idx = timeslot.day
                        day_abbr = days_map.get(day_idx)
                        
                        # The actual hour of the day (e.g., 9, 10, 11)
                        slot_hour = timeslot.start_time + 8.5

                        # 1. Check available days
                        is_available_day = False
                        avail_days = faculty.avail_days
                        if not avail_days or (isinstance(avail_days, str) and avail_days.upper() == "ALL"):
                            is_available_day = True
                        else:
                            # Normalize to a list of capitalized day abbreviations
                            if isinstance(avail_days, str):
                                avail_days_list = [d.strip().capitalize() for d in avail_days.split(',')]
                            else: # is a list
                                avail_days_list = [d.strip().capitalize() for d in avail_days]
                            
                            if "All" in avail_days_list or day_abbr in avail_days_list:
                                is_available_day = True

                        if not is_available_day:
                            penalty += 50  # Increased from 2 to 50
                            if debug:
                                # Use faculty name if available, otherwise use faculty_id (email)
                                lecturer_name = faculty.name if faculty.name else faculty.faculty_id
                                violation_info = (
                                    f"Lecturer Schedule Violation: '{lecturer_name}' is scheduled on {day_abbr}, "
                                    f"but is only available on: {faculty.avail_days}."
                                )
                                if violation_info not in violations:
                                    violations.append(violation_info)
                            continue # Skip time check if day is already wrong

                        # 2. Check available times
                        # IMPORTANT: Treat end time as inclusive for allowed start-times.
                        # This matches the UX expectation that "9:00-14:00" allows a class starting at 14:00.
                        is_available_time = self._is_faculty_available_time(faculty, slot_hour, day_abbr)
                        
                        if not is_available_time:
                            penalty += 50  # Increased from 2 to 50
                            if debug:
                                # Get specific times for message to be precise
                                allowed_times = []
                                if isinstance(faculty.avail_times, dict):
                                    allowed_times = faculty.avail_times.get(day_abbr) or faculty.avail_times.get(day_abbr.capitalize()) or faculty.avail_times.get('All') or []
                                else:
                                    allowed_times = faculty.avail_times

                                allowed_str = ", ".join(str(t) for t in allowed_times) if isinstance(allowed_times, list) else str(allowed_times)
                                
                                # Use faculty name if available, otherwise use faculty_id (email)
                                lecturer_name = faculty.name if faculty.name else faculty.faculty_id
                                violation_info = (
                                    f"Lecturer Schedule Violation: '{lecturer_name}' is scheduled at {self.format_hour(slot_hour)} on {day_abbr}, "
                                    f"but is only available during: {allowed_str} on {day_abbr}."
                                )
                                if violation_info not in violations:
                                    violations.append(violation_info)
        
        if debug and violations:
            print("\n--- Lecturer Schedule Violations Detected ---")
            for violation in sorted(violations):
                print(violation)
            print("-------------------------------------------\n")
            
        return penalty

    def check_lecturer_workload_constraints(self, chromosome, debug=False):
        """
        Checks lecturer workload constraints:
        1. No more than lecturer-specific total hours of teaching per day (default 4)
        2. No more than lecturer-specific consecutive hours of teaching per day (default 3)
        """
        penalty = 0
        violations = []
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
        
        # Track each lecturer's schedule for each day with course details
        lecturer_schedules = {}  # {faculty_id: {day: [(hour_index, course_name)]}}
        
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    class_event = self.events_map.get(event_id)
                    if class_event and class_event.faculty_id is not None:
                        faculty_id = class_event.faculty_id
                        timeslot = self.timeslots[timeslot_idx]
                        day_idx = timeslot.day
                        hour_in_day = timeslot.start_time  # 0-based hour index within the day
                        
                        # Get course details
                        course = self.input_data.getCourse(class_event.course_id)
                        course_name = course.name if course else class_event.course_id
                        
                        if faculty_id not in lecturer_schedules:
                            lecturer_schedules[faculty_id] = {}
                        if day_idx not in lecturer_schedules[faculty_id]:
                            lecturer_schedules[faculty_id][day_idx] = []
                        
                        lecturer_schedules[faculty_id][day_idx].append((hour_in_day, course_name))
        
        # Check workload constraints for each lecturer
        for faculty_id, days_schedule in lecturer_schedules.items():
            faculty = self.input_data.getFaculty(faculty_id)
            lecturer_name = faculty.name if faculty and faculty.name else faculty_id

            max_hours_per_day = 4
            max_consecutive_allowed = 3
            try:
                if faculty is not None:
                    max_hours_per_day = int(getattr(faculty, 'available_hours', 4) or 4)
                    max_consecutive_allowed = int(getattr(faculty, 'available_consecutive_hours', 3) or 3)
            except Exception:
                max_hours_per_day = 4
                max_consecutive_allowed = 3

            # Safety clamp (template enforces 2..8, but keep runtime safe)
            max_hours_per_day = max(2, min(8, max_hours_per_day))
            max_consecutive_allowed = max(2, min(8, max_consecutive_allowed))
            
            max_hours_per_day = 4
            max_consecutive_allowed = 3
            try:
                if faculty is not None:
                    max_hours_per_day = int(getattr(faculty, 'available_hours', 4) or 4)
                    max_consecutive_allowed = int(getattr(faculty, 'available_consecutive_hours', 3) or 3)
            except Exception:
                max_hours_per_day = 4
                max_consecutive_allowed = 3

            max_hours_per_day = max(2, min(8, max_hours_per_day))
            max_consecutive_allowed = max(2, min(8, max_consecutive_allowed))

            for day_idx, hour_course_pairs in days_schedule.items():
                day_abbr = days_map.get(day_idx, "Unknown")
                
                # Extract hours and courses
                hours = [pair[0] for pair in hour_course_pairs]
                courses = [pair[1] for pair in hour_course_pairs]
                
                # Remove duplicates and sort hours
                hours_sorted = sorted(set(hours))
                
                # Get unique courses for this day
                unique_courses = list(set(courses))
                courses_text = ", ".join(unique_courses)
                
                # 1. Check total hours per day (default max 4) - STRONG PENALTY
                total_hours = len(hours_sorted)
                if total_hours > max_hours_per_day:
                    penalty += 55.0 * (total_hours - max_hours_per_day)
                    if debug:
                        violation_info = (
                            f"Lecturer Workload Violation: '{lecturer_name}' has {total_hours} hours "
                            f"on {day_abbr} from courses {courses_text}, exceeding the maximum of {max_hours_per_day} hours per day."
                        )
                        if violation_info not in violations:
                            violations.append(violation_info)
                
                # 2. Check for consecutive hours (default max 3 consecutive) - VERY HIGH PENALTY
                if len(hours_sorted) >= 4:  # Only need to check if 4 or more hours
                    consecutive_count = 1
                    max_consecutive = 1
                    
                    for i in range(1, len(hours_sorted)):
                        if hours_sorted[i] == hours_sorted[i-1] + 1:
                            consecutive_count += 1
                            max_consecutive = max(max_consecutive, consecutive_count)
                        else:
                            consecutive_count = 1
                    
                    if max_consecutive > max_consecutive_allowed:
                        penalty += 550.0 * (max_consecutive - max_consecutive_allowed)
                        if debug:
                            violation_info = (
                                f"Lecturer Consecutive Hours Violation: '{lecturer_name}' has {max_consecutive} "
                                f"consecutive hours on {day_abbr} from courses {courses_text}, exceeding the maximum of {max_consecutive_allowed} consecutive hours."
                            )
                            if violation_info not in violations:
                                violations.append(violation_info)

            # 3. Encourage distributing a lecturer across other available days.
            # This helps reduce daily and consecutive overload pressure.
            weekly_hours = sum(len(set(pair[0] for pair in day_pairs)) for day_pairs in days_schedule.values())
            taught_days = len(days_schedule)

            available_days_count = self.input_data.days
            try:
                raw_days = getattr(faculty, 'available_days', None)
                if isinstance(raw_days, str):
                    parts = [p.strip() for p in raw_days.replace(';', ',').split(',') if p.strip()]
                    available_days_count = max(1, min(self.input_data.days, len(parts))) if parts else self.input_data.days
                elif isinstance(raw_days, (list, tuple, set)):
                    available_days_count = max(1, min(self.input_data.days, len([d for d in raw_days if str(d).strip()])))
            except Exception:
                available_days_count = self.input_data.days

            desired_days = min(
                max(1, available_days_count),
                max(1, (weekly_hours + max_hours_per_day - 1) // max_hours_per_day),
            )
            if weekly_hours >= 3 and available_days_count >= 2:
                desired_days = max(desired_days, 2)

            if taught_days < desired_days:
                penalty += 120.0 * (desired_days - taught_days)
        
        if debug and violations:
            print("\n--- Lecturer Workload Violations Detected ---")
            for violation in sorted(violations):
                print(violation)
            print("------------------------------------------\n")
        
        return penalty

    def check_room_time_conflict(self, chromosome, debug=False):
        """
        Ensure only one event is scheduled per room per timeslot
        """
        penalty = 0
        violations = []
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
        
        for room_idx in range(len(self.rooms)):
            room = self.rooms[room_idx]
            for timeslot_idx in range(len(self.timeslots)):
                event = chromosome[room_idx][timeslot_idx]
                if event is not None:
                    # Check if event is somehow a list (multiple events in same slot)
                    if isinstance(event, list) and len(event) > 1:
                        penalty += 10  # Reduced from 100 to 10
                        if debug:
                            timeslot = self.timeslots[timeslot_idx]
                            day_abbr = days_map.get(timeslot.day)
                            time = timeslot.start_time + 8.5
                            
                            event_details = []
                            for event_id in event:
                                class_event = self.events_map.get(event_id)
                                if class_event:
                                    course = self.input_data.getCourse(class_event.course_id)
                                    event_details.append(f"'{course.code}' (Group: '{class_event.student_group.name}')")
                            
                            violation_info = (
                                f"Room Time Conflict: Multiple events in room '{room.name}' "
                                f"on {day_abbr} at {self.format_hour(time)}. Conflicting events: {', '.join(event_details)}."
                            )
                            if violation_info not in violations:
                                violations.append(violation_info)
                    
                    # Additional check: count non-None values to ensure only one event per slot
                    # This constraint is inherently satisfied by the chromosome structure,
                    # but we check for any data corruption

        if debug and violations:
            print("\n--- Room Time Conflicts Detected ---")
            for violation in sorted(violations):
                print(violation)
            print("-----------------------------------\n")
                    
        return penalty

    def check_break_time_constraint(self, chromosome, debug=False):
        """
        Ensure no classes are scheduled during break time (13:00 - 14:00) on Mon, Wed, Fri.
        Break time corresponds to timeslot index 4 on each day (9:00, 10:00, 11:00, 12:00, 13:00)
        """
        penalty = 0
        violations = []
        break_hour = 4  # 13:00 is the 5th hour (index 4) starting from 9:00
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
        
        for day in range(self.input_data.days):  # For each day
            # Apply break constraint only on Monday (0), Wednesday (2), and Friday (4)
            if day in [0, 2, 4]:
                break_timeslot = day * self.input_data.hours + break_hour  # Calculate break timeslot index
                day_abbr = days_map.get(day)
                
                for room_idx in range(len(self.rooms)):
                    event_id = chromosome[room_idx][break_timeslot]
                    if event_id is not None:
                        penalty += 50  # Reduced from 100 to 50
                        if debug:
                            room = self.rooms[room_idx]
                            class_event = self.events_map.get(event_id)
                            if class_event:
                                course = self.input_data.getCourse(class_event.course_id)
                                violation_info = (
                                    f"Break Time Violation: Course '{course.code}' for group "
                                    f"'{class_event.student_group.name}' is scheduled during break time "
                                    f"(13:00) on {day_abbr} in room '{room.name}'."
                                )
                                if violation_info not in violations:
                                    violations.append(violation_info)

        if debug and violations:
            print("\n--- Break Time Constraint Violations Detected ---")
            for violation in sorted(violations):
                print(violation)
            print("------------------------------------------------\n")
                        
        return penalty

    def check_building_assignments(self, chromosome):
        """
        Building assignment rules:
        - Hard: TYD (non-SST) groups must never be placed in SST rooms (no exceptions)
        - Soft: SST groups are allowed in TYD rooms, but we prefer SST rooms when possible
        """
        penalty = 0
        
        # Identify SST groups using central classification (explicit building first, keywords as fallback).
        engineering_groups = [sg.id for sg in self.student_groups if getattr(sg, 'is_sst', False)]
        
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    class_event = self.events_map.get(event_id)
                    if class_event is None:
                        continue
                        
                    room = self.rooms[room_idx]
                    course = self.input_data.getCourse(class_event.course_id)
                    
                    if course:
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
                        
                        # Apply RULES based on User Request:
                        # 1. SST studentgroups can use both SST and TYD (Maybe prefer SST, but allowed in TYD)
                        # 2. TYD studentgroups CANNOT use SST classes (High Penalty)

                        is_sst_group = class_event.student_group.id in engineering_groups
                        is_sst_room = (room_building == 'SST')
                        is_tyd_room = (room_building == 'TYD')

                        if is_sst_group:
                            # Engineering groups are allowed in TYD, but we add a small penalty to reduce
                            # SST classes scheduled in TYD when SST rooms are available.
                            if is_tyd_room:
                                penalty += 4
                        else:
                            # Non-engineering (TYD) groups MUST NOT be in SST
                            if is_sst_room:
                                penalty += 100  # HIGH penalty (Strict Prohibition)
        
        return penalty


    def check_same_course_same_room_per_day(self, chromosome, debug=False):
        """
        Same course appearing multiple times on same day must be in same room.
        """
        penalty = 0
        violations = []
        course_day_rooms = {}  # {(course_id, day): set_of_rooms}
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
        
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
                # Stronger penalty: same course should stay in one room per day for a group.
                # This helps multi-hour blocks keep a consistent room.
                penalty += 450 * (len(rooms_used) - 1)
                if debug:
                    course_id, day_idx, student_group_id = course_day_key
                    day_abbr = days_map.get(day_idx)
                    
                    # Get student group and course details
                    student_group = self.input_data.getStudentGroup(student_group_id)
                    course = self.input_data.getCourse(course_id)
                    
                    # Get room names
                    room_names = [self.rooms[r_idx].name for r_idx in rooms_used]
                    
                    violation_info = (
                        f"Same Course Multiple Rooms Violation: Course '{course.code}' for group "
                        f"'{student_group.name}' appears in multiple rooms on {day_abbr}: "
                        f"{', '.join(room_names)}."
                    )
                    if violation_info not in violations:
                        violations.append(violation_info)

        if debug and violations:
            print("\n--- Same Course Multiple Rooms Violations Detected ---")
            for violation in sorted(violations):
                print(violation)
            print("-----------------------------------------------------\n")
        
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

    def check_consecutive_timeslots(self, chromosome, debug=False):
        """
        Hard consecutive placement:
        - 2-credit: both hours same day, adjacent.
        - SST 3-credit: all 3 hours same day in one 3-hour block.
        - TYD 3-credit: at least one same-day 2-hour consecutive block.
        """
        penalty = 0
        violations = []

        hours_per_day = int(self.input_data.hours)
        
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
            student_group = self.input_data.getStudentGroup(student_group_id)
            if not course or course.credits <= 1:
                continue

            # Sort timeslots to check for consecutiveness
            timeslots.sort()
            
            if course.credits == 2:
                # H: 2-credit courses MUST be consecutive
                if len(timeslots) == 2:
                    same_day = (timeslots[0] // hours_per_day) == (timeslots[1] // hours_per_day)
                    consecutive = (timeslots[1] - timeslots[0]) == 1
                    if (not same_day) or (not consecutive):
                        penalty += 20000.0
                        if debug:
                            violation_info = (
                                f"2-hour course '{course.name}' ({course.code}) for group "
                                f"'{student_group.name}' is not scheduled as a same-day consecutive block."
                            )
                            if violation_info not in violations:
                                violations.append(violation_info)
            
            elif course.credits == 3:
                if len(timeslots) >= 3:
                    ts3 = sorted(timeslots[:3])
                    is_sst = bool(getattr(student_group, 'is_sst', False))
                    if is_sst:
                        same_day = (
                            (ts3[0] // hours_per_day) == (ts3[1] // hours_per_day)
                            and (ts3[1] // hours_per_day) == (ts3[2] // hours_per_day)
                        )
                        full_block = (
                            same_day
                            and (ts3[1] - ts3[0] == 1)
                            and (ts3[2] - ts3[1] == 1)
                        )
                        if not full_block:
                            penalty += 20000.0
                            if debug:
                                violation_info = (
                                    f"SST 3-hour course '{course.name}' ({course.code}) for group "
                                    f"'{student_group.name}' is not scheduled as a single 3-hour consecutive block."
                                )
                                if violation_info not in violations:
                                    violations.append(violation_info)
                    else:
                        has_consecutive = False
                        for i in range(len(ts3) - 1):
                            if (ts3[i + 1] - ts3[i] == 1) and ((ts3[i] // hours_per_day) == (ts3[i + 1] // hours_per_day)):
                                has_consecutive = True
                                break
                        if not has_consecutive:
                            penalty += 20000.0
                            if debug:
                                violation_info = (
                                    f"TYD 3-hour course '{course.name}' ({course.code}) for group "
                                    f"'{student_group.name}' has no same-day 2-hour consecutive block."
                                )
                                if violation_info not in violations:
                                    violations.append(violation_info)

        if debug and violations:
            print("\n--- Consecutive Slot Violations Detected ---")
            for violation in sorted(violations):
                print(violation)
            print("------------------------------------------\n")

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

            # Encourage spread across days
            target_days = min(days_total, total)
            missing = max(0, target_days - len(event_days))
            if missing:
                penalty += 50.0 * missing  # Extremely strong penalty to spread across days

            # Soft target: at least 3 active days (when possible)
            min_days_target = min(3, total, days_total)
            if len(event_days) < min_days_target:
                penalty += 25.0 * (min_days_target - len(event_days))

            # Require at least 2 free hours every day (soft penalty)
            if hours_per_day > 0:
                for day_idx in range(days_total):
                    scheduled = events_per_day[group_id][day_idx]
                    free_hours = max(0, hours_per_day - scheduled)
                    if free_hours < 2:
                        penalty += 100.0 * (2 - free_hours)

        return penalty

    def check_course_allocation_completeness(self, chromosome, debug=False):
        """
        Check that all courses appear the correct number of times for each student group
        based on their credit hours/hours_required.
        """
        penalty = 0
        allocation_issues = []
        
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
                    difference = abs(expected_hours - actual_hours)
                    
                    if actual_hours < expected_hours:
                        # Apply VERY high penalty for missing courses to banish them entirely
                        penalty += difference * 5000 
                        if debug:
                            course_name = course.name if course else "Unknown Course"
                            credit_info = f" (1-credit → 3 hours)" if course and course.credits == 1 else ""
                            info = (
                                f"Missing Class: Group '{student_group.name}' is missing {difference} hour(s) "
                                f"for course '{course_name}' (Code: {course_id}){credit_info}. "
                                f"Expected {expected_hours}, but only {actual_hours} are scheduled."
                            )
                            allocation_issues.append(info)
                    else: # actual_hours > expected_hours
                        # Apply penalty for extra classes
                        penalty += difference * 500

                        if debug:
                            course_name = course.name if course else "Unknown Course"
                            credit_info = f" (1-credit → 3 hours)" if course and course.credits == 1 else ""
                            info = (
                                f"Extra Class: Group '{student_group.name}' has {difference} extra hour(s) "
                                f"for course '{course_name}' (Code: {course_id}){credit_info}. "
                                f"Expected {expected_hours}, but {actual_hours} are scheduled."
                            )
                            allocation_issues.append(info)

        if debug and allocation_issues:
            print("\n--- Course Allocation Issues Detected ---")
            for info in sorted(allocation_issues):
                print(info)
            print("---------------------------------------\n")
        
        return penalty

    def evaluate_fitness(self, chromosome):
        """
        Evaluate the overall fitness of a chromosome by checking all constraints.
        Lower values indicate better fitness.
        """
        # Priority weighting (minimal algorithm change):
        # 1) Same-student-group overlaps
        # 2) Missing/extra classes (allocation completeness)
        # 3) Lecturer clashes
        # 4) Room clashes (different student groups in same room/time)
        # 5) Lecturer workload
        # Everything else remains lower-weight.
        weights = {
            'student_group_constraints': 1.0,  # Penalties are handled internally (100 pts)
            'course_allocation_completeness': 1.0, # Penalties are handled internally (100,000 pts)
            'lecturer_availability': 1.0, # Penalties are handled internally (100 pts)
            'room_time_conflict': 1.0, 
            'lecturer_workload_constraints': 1.0, # Penalties are handled internally (30-50 pts)

            # Other hard constraints
            'room_constraints': 1.0,
            'lecturer_schedule_constraints': 1.0, # Penalties are handled internally (50 pts)
            'break_time_constraint': 1.0, # Penalties are handled internally (50 pts)
            'building_assignments': 1.0, # Penalties are handled internally (100 pts for strict, 0.5 for others)
            'same_course_same_room_per_day': 1.0,
            'no_free_day': 1.0,
            'consecutive_timeslots': 1.0,
        }

        penalty = 0.0
        cost = 0.0

        # Hard constraints (weighted)
        penalty += weights['room_constraints'] * self.check_room_constraints(chromosome)
        penalty += weights['student_group_constraints'] * self.check_student_group_constraints(chromosome)
        penalty += weights['lecturer_availability'] * self.check_lecturer_availability(chromosome)
        penalty += weights['room_time_conflict'] * self.check_room_time_conflict(chromosome)
        penalty += weights['building_assignments'] * self.check_building_assignments(chromosome)
        penalty += weights['same_course_same_room_per_day'] * self.check_same_course_same_room_per_day(chromosome)
        penalty += weights['break_time_constraint'] * self.check_break_time_constraint(chromosome)
        penalty += weights['course_allocation_completeness'] * self.check_course_allocation_completeness(chromosome)
        penalty += weights['lecturer_schedule_constraints'] * self.check_lecturer_schedule_constraints(chromosome)
        penalty += weights['lecturer_workload_constraints'] * self.check_lecturer_workload_constraints(chromosome)
        penalty += weights['no_free_day'] * self.check_no_free_day(chromosome)
        penalty += weights['consecutive_timeslots'] * self.check_consecutive_timeslots(chromosome)

        # Soft constraints (keep relatively small so they don't dominate feasibility)
        cost += 5.0 * self.check_single_event_per_day(chromosome)
        cost += 5.0 * self.check_three_unit_split_across_days(chromosome)
        cost += 300.0 * self.check_spread_events(chromosome)
        cost += 5500.0 * self.extremely_late_classes(chromosome, debug=False)

        # Fitness is a combination of penalties and costs
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
        
    def get_constraint_violations(self, chromosome, debug=False):
        """
        Get detailed information about constraint violations for debugging.
        """
        violations = {
            'room_constraints': self.check_room_constraints(chromosome, debug=debug),
            'student_group_constraints': self.check_student_group_constraints(chromosome, debug=debug),
            'lecturer_availability': self.check_lecturer_availability(chromosome, debug=debug),
            'room_time_conflict': self.check_room_time_conflict(chromosome, debug=debug),
            'building_assignments': self.check_building_assignments(chromosome),
            'same_course_same_room_per_day': self.check_same_course_same_room_per_day(chromosome, debug=debug),
            'break_time_constraint': self.check_break_time_constraint(chromosome, debug=debug),
            'course_allocation_completeness': self.check_course_allocation_completeness(chromosome, debug=debug),
            'lecturer_schedule_constraints': self.check_lecturer_schedule_constraints(chromosome, debug=debug),
            'lecturer_workload_constraints': self.check_lecturer_workload_constraints(chromosome, debug=debug),
            'no_free_day': self.check_no_free_day(chromosome, debug=debug),
            'three_unit_split_across_days_TYD': self.check_three_unit_split_across_days(chromosome, debug=debug),
            'single_event_per_day': self.check_single_event_per_day(chromosome),
            'consecutive_timeslots': self.check_consecutive_timeslots(chromosome, debug=debug),
            'spread_events': self.check_spread_events(chromosome),
            'extremely_late_classes': self.extremely_late_classes(chromosome, debug=debug)
        }
        violations['total'] = sum(violations.values())
        return violations

    def get_detailed_constraint_violations(self, chromosome):
        """
        Get detailed constraint violations with occurrence locations for UI display.
        Returns a dictionary with constraint names and their detailed violation information.
        """
        detailed_violations = {}
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
        
        # 1. Student Group Clashes (Same Student Group Overlaps)
        student_group_clashes = []
        for i in range(len(self.timeslots)):
            simultaneous_class_events = chromosome[:, i]
            student_group_watch = {}
            for room_idx, class_event_idx in enumerate(simultaneous_class_events):
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None:
                        student_group = class_event.student_group
                        if student_group.id in student_group_watch:
                            first_event = student_group_watch[student_group.id]
                            first_course = self.input_data.getCourse(first_event.course_id)
                            second_course = self.input_data.getCourse(class_event.course_id)
                            
                            timeslot = self.timeslots[i]
                            day_abbr = days_map.get(timeslot.day)
                            time = timeslot.start_time + 8.5
                            
                            student_group_clashes.append({
                                'group': student_group.name,
                                'day': day_abbr,
                                'time': self.format_hour(time),
                                'courses': [first_course.code, second_course.code],
                                'location': f"{day_abbr} at {self.format_hour(time)}"
                            })
                        else:
                            student_group_watch[student_group.id] = class_event
        
        detailed_violations['Same Student Group Overlaps'] = student_group_clashes
        
        # 2. Room Time Slot Conflicts (Different Student Group Overlaps)
        room_conflicts = []
        for room_idx in range(len(self.rooms)):
            room = self.rooms[room_idx]
            for timeslot_idx in range(len(self.timeslots)):
                event = chromosome[room_idx][timeslot_idx]
                if event is not None and isinstance(event, list) and len(event) > 1:
                    timeslot = self.timeslots[timeslot_idx]
                    day_abbr = days_map.get(timeslot.day)
                    time = timeslot.start_time + 8.5
                    
                    event_details = []
                    for event_id in event:
                        class_event = self.events_map.get(event_id)
                        if class_event:
                            course = self.input_data.getCourse(class_event.course_id)
                            event_details.append(f"'{course.code}' (Group: '{class_event.student_group.name}')")
                    
                    room_conflicts.append({
                        'room': room.name,
                        'day': day_abbr,
                        'time': self.format_hour(time),
                        'events': event_details,
                        'location': f"{room.name} on {day_abbr} at {self.format_hour(time)}"
                    })
        
        detailed_violations['Different Student Group Overlaps'] = room_conflicts
        
        # 3. Lecturer Clashes
        lecturer_clashes = []
        for i in range(len(self.timeslots)):
            simultaneous_class_events = chromosome[:, i]
            lecturer_watch = {}
            for room_idx, class_event_idx in enumerate(simultaneous_class_events):
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None and class_event.faculty_id:
                        faculty_id = class_event.faculty_id
                        if faculty_id in lecturer_watch:
                            first_event = lecturer_watch[faculty_id]
                            first_course = self.input_data.getCourse(first_event.course_id)
                            second_course = self.input_data.getCourse(class_event.course_id)
                            faculty = self.input_data.getFaculty(faculty_id)
                            
                            timeslot = self.timeslots[i]
                            day_abbr = days_map.get(timeslot.day)
                            time = timeslot.start_time + 8.5
                            
                            # Use faculty name if available, otherwise use faculty_id (email)
                            lecturer_name = faculty.name if faculty and faculty.name else faculty_id
                            
                            lecturer_clashes.append({
                                'lecturer': lecturer_name,
                                'day': day_abbr,
                                'time': self.format_hour(time),
                                'courses': [first_course.code, second_course.code],
                                'groups': [first_event.student_group.name, class_event.student_group.name],
                                'location': f"{day_abbr} at {self.format_hour(time)}"
                            })
                        else:
                            lecturer_watch[faculty_id] = class_event
        
        detailed_violations['Lecturer Clashes'] = lecturer_clashes
        
        # 4. Lecturer Schedule Conflicts (Day/Time)
        lecturer_schedule_conflicts = []
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                class_event_idx = chromosome[room_idx][timeslot_idx]
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None and class_event.faculty_id:
                        faculty = self.input_data.getFaculty(class_event.faculty_id)
                        if faculty:
                            timeslot = self.timeslots[timeslot_idx]
                            day_abbr = days_map.get(timeslot.day, "Unknown")
                            slot_hour = timeslot.start_time + 8.5
                            
                            # Check day availability
                            is_available_day = self._is_faculty_available_day(faculty, day_abbr)
                            is_available_time = self._is_faculty_available_time(faculty, slot_hour, day_abbr=day_abbr)
                            
                            if not is_available_day or not is_available_time:
                                course = self.input_data.getCourse(class_event.course_id)
                                
                                # Use faculty name if available, otherwise use faculty_id (email)
                                lecturer_name = faculty.name if faculty.name else faculty.faculty_id
                                
                                # Format available days and times properly
                                available_days_display = faculty.avail_days if faculty.avail_days else "Not specified"
                                available_times_display = faculty.avail_times if faculty.avail_times else "Not specified"
                                
                                lecturer_schedule_conflicts.append({
                                    'lecturer': lecturer_name,
                                    'day': day_abbr,
                                    'time': self.format_hour(slot_hour),
                                    'course': course.code,
                                    'group': class_event.student_group.name,
                                    'available_days': available_days_display,
                                    'available_times': available_times_display,
                                    'location': f"{day_abbr} at {self.format_hour(slot_hour)}"
                                })
        
        detailed_violations['Lecturer Schedule Conflicts (Day/Time)'] = lecturer_schedule_conflicts
        
        # 5. Lecturer Workload Violations
        lecturer_workload_violations = []
        lecturer_schedules = {}  # {faculty_id: {day: [(hour_index, course_name)]}}
        
        # Build lecturer schedules with course details
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is not None:
                    class_event = self.events_map.get(event_id)
                    if class_event and class_event.faculty_id is not None:
                        faculty_id = class_event.faculty_id
                        timeslot = self.timeslots[timeslot_idx]
                        day_idx = timeslot.day
                        hour_in_day = timeslot.start_time
                        
                        # Get course details
                        course = self.input_data.getCourse(class_event.course_id)
                        course_name = course.name if course else class_event.course_id
                        
                        if faculty_id not in lecturer_schedules:
                            lecturer_schedules[faculty_id] = {}
                        if day_idx not in lecturer_schedules[faculty_id]:
                            lecturer_schedules[faculty_id][day_idx] = []
                        
                        lecturer_schedules[faculty_id][day_idx].append((hour_in_day, course_name))
        
        # Check workload violations
        for faculty_id, days_schedule in lecturer_schedules.items():
            faculty = self.input_data.getFaculty(faculty_id)
            lecturer_name = faculty.name if faculty and faculty.name else faculty_id
            max_hours_per_day = 4
            max_consecutive_allowed = 3
            try:
                if faculty is not None:
                    max_hours_per_day = int(getattr(faculty, 'available_hours', 4) or 4)
                    max_consecutive_allowed = int(getattr(faculty, 'available_consecutive_hours', 3) or 3)
            except Exception:
                max_hours_per_day = 4
                max_consecutive_allowed = 3

            max_hours_per_day = max(2, min(8, max_hours_per_day))
            max_consecutive_allowed = max(2, min(8, max_consecutive_allowed))
            
            for day_idx, hour_course_pairs in days_schedule.items():
                day_abbr = days_map.get(day_idx, "Unknown")
                
                # Extract hours and courses
                hours = [pair[0] for pair in hour_course_pairs]
                courses = [pair[1] for pair in hour_course_pairs]
                
                # Remove duplicates and sort hours
                hours_sorted = sorted(set(hours))
                total_hours = len(hours_sorted)
                
                # Get unique courses for this day
                unique_courses = list(set(courses))
                courses_text = ", ".join(unique_courses)
                
                # Check total hours violation
                if total_hours > max_hours_per_day:
                    lecturer_workload_violations.append({
                        'type': 'Excessive Daily Hours',
                        'lecturer': lecturer_name,
                        'day': day_abbr,
                        'hours_scheduled': total_hours,
                        'max_allowed': max_hours_per_day,
                        'courses': courses_text,
                        'violation': f"{total_hours - max_hours_per_day} extra hours",
                        'location': f"{lecturer_name} on {day_abbr}"
                    })
                
                # Check consecutive hours violation
                if len(hours_sorted) >= 4:
                    consecutive_count = 1
                    max_consecutive = 1
                    
                    for i in range(1, len(hours_sorted)):
                        if hours_sorted[i] == hours_sorted[i-1] + 1:
                            consecutive_count += 1
                            max_consecutive = max(max_consecutive, consecutive_count)
                        else:
                            consecutive_count = 1
                    
                    if max_consecutive > max_consecutive_allowed:
                        hour_labels = [self.format_hour(h + 8.5) for h in hours_sorted]
                        lecturer_workload_violations.append({
                            'type': 'Excessive Consecutive Hours',
                            'lecturer': lecturer_name,
                            'day': day_abbr,
                            'consecutive_hours': max_consecutive,
                            'max_allowed': max_consecutive_allowed,
                            'courses': courses_text,
                            'hours_times': hour_labels,
                            'violation': f"{max_consecutive - max_consecutive_allowed} extra consecutive hours",
                            'location': f"{lecturer_name} on {day_abbr}"
                        })
        
        detailed_violations['Lecturer Workload Violations'] = lecturer_workload_violations
        
        # 6. Consecutive Slot Violations
        consecutive_violations = []
        hours_per_day = int(self.input_data.hours)
        events_by_course = {}
        for r_idx in range(len(self.rooms)):
            for t_idx in range(len(self.timeslots)):
                event_id = chromosome[r_idx][t_idx]
                if event_id is not None:
                    event = self.events_map.get(event_id)
                    if event:
                        course_key = (event.course_id, event.student_group.id)
                        if course_key not in events_by_course:
                            events_by_course[course_key] = []
                        events_by_course[course_key].append((r_idx, t_idx))
        
        for course_key, events in events_by_course.items():
            course_id, student_group_id = course_key
            course = self.input_data.getCourse(course_id)
            student_group = self.input_data.getStudentGroup(student_group_id)
            
            if not course or course.credits <= 1:
                continue
            
            # Group timeslots
            timeslots = [t_idx for _, t_idx in events]
            timeslots.sort()
            
            days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}

            if course.credits == 2:
                # 2-credit courses MUST be consecutive
                if len(timeslots) == 2 and (timeslots[1] - timeslots[0] != 1):
                    times = [self.format_hour(self.timeslots[t].start_time + 8.5) for t in timeslots]
                    days_list = [days_map.get(self.timeslots[t].day, "") for t in timeslots]
                    # Unique days while preserving order
                    seen = set()
                    days_str = ", ".join([x for x in days_list if not (x in seen or seen.add(x))])
                    
                    consecutive_violations.append({
                        'course': course.code,
                        'course_name': course.name,
                        'group': student_group.name,
                        'times': times,
                        'day': days_str,
                        'credits': course.credits,
                        'location': f"{course.code} for {student_group.name}",
                        'reason': f"2-hour course not scheduled consecutively"
                    })
            
            elif course.credits == 3:
                if len(timeslots) >= 3:
                    ts3 = sorted(timeslots[:3])
                    is_sst = bool(getattr(student_group, 'is_sst', False))
                    violated = False
                    reason = ""
                    if is_sst:
                        same_day = (
                            (ts3[0] // hours_per_day) == (ts3[1] // hours_per_day)
                            and (ts3[1] // hours_per_day) == (ts3[2] // hours_per_day)
                        )
                        if not (
                            same_day
                            and (ts3[1] - ts3[0] == 1)
                            and (ts3[2] - ts3[1] == 1)
                        ):
                            violated = True
                            reason = "SST 3-hour course is not one 3-hour consecutive block"
                    else:
                        has_pair = any(
                            (ts3[i + 1] - ts3[i] == 1)
                            and ((ts3[i] // hours_per_day) == (ts3[i + 1] // hours_per_day))
                            for i in range(len(ts3) - 1)
                        )
                        if not has_pair:
                            violated = True
                            reason = "TYD 3-hour course has no same-day 2-hour consecutive block"
                    if violated:
                        times = [self.format_hour(self.timeslots[t].start_time + 8.5) for t in ts3]
                        days_list = [days_map.get(self.timeslots[t].day, "") for t in ts3]
                        seen = set()
                        days_str = ", ".join([x for x in days_list if not (x in seen or seen.add(x))])
                        consecutive_violations.append({
                            'course': course.code,
                            'course_name': course.name,
                            'group': student_group.name,
                            'times': times,
                            'day': days_str,
                            'credits': course.credits,
                            'location': f"{course.code} for {student_group.name}",
                            'reason': reason,
                        })
        
        detailed_violations['Consecutive Slot Violations'] = consecutive_violations
        
        # 6b. Three Unit Split Violations
        three_unit_split_violations = []
        for course_key, events in events_by_course.items():
            course_id, student_group_id = course_key
            course = self.input_data.getCourse(course_id)
            student_group = self.input_data.getStudentGroup(student_group_id)
            
            if not course or course.credits != 3:
                continue
            
            timeslots = [t_idx for _, t_idx in events]
            if len(timeslots) < 3:
                continue
                
            timeslots.sort()
            day_counts = {}
            hours_per_day = int(self.input_data.hours)
            for t in timeslots[:3]:
                d = t // hours_per_day
                day_counts[d] = day_counts.get(d, 0) + 1
                
            is_sst = getattr(student_group, 'is_sst', False)
            
            times = [self.format_hour(self.timeslots[t].start_time + 8.5) for t in timeslots[:3]]
            days_list = [days_map.get(self.timeslots[t].day, "") for t in timeslots[:3]]
            seen = set()
            days_str = ", ".join([x for x in days_list if not (x in seen or seen.add(x))])

            if not is_sst:
                if max(day_counts.values()) == 3:
                    three_unit_split_violations.append({
                        'course': course.code,
                        'course_name': course.name,
                        'group': student_group.name,
                        'times': times,
                        'day': days_str,
                        'credits': course.credits,
                        'location': f"{course.code} for {student_group.name}",
                        'reason': "TYD 3-unit course has all 3 hours on the same day"
                    })

        detailed_violations['Three Unit Split Violations'] = three_unit_split_violations

        # 7. Missing or Extra Classes
        course_allocation_issues = []
        missing_by_group = {}
        for student_group in self.student_groups:
            course_counts = {}
            for room_idx in range(len(self.rooms)):
                for timeslot_idx in range(len(self.timeslots)):
                    event_id = chromosome[room_idx][timeslot_idx]
                    if event_id is not None:
                        event = self.events_map.get(event_id)
                        if event and event.student_group.id == student_group.id:
                            course_id = event.course_id
                            course_counts[course_id] = course_counts.get(course_id, 0) + 1
            
            for i, course_id in enumerate(student_group.courseIDs):
                # Get the course to check if it's a 1-credit course that should be 3 hours
                course = self.input_data.getCourse(course_id)
                
                # SPECIAL HANDLING FOR 1-CREDIT COURSES:
                # If course has 1 credit, it must have 3 hours (not flagged as extra)
                if course and course.credits == 1:
                    expected = 3  # 1-credit courses should have 3 hours
                else:
                    expected = student_group.hours_required[i]
                    
                actual = course_counts.get(course_id, 0)
                if actual != expected:
                    issue_type = "Missing" if actual < expected else "Extra"
                    credit_info = f" (1-credit → 3 hours)" if course and course.credits == 1 else ""
                    course_allocation_issues.append({
                        'group': student_group.name,
                        'course': course.code,
                        'expected': expected,
                        'actual': actual,
                        'issue': issue_type,
                        'location': f"{course.code} for {student_group.name}{credit_info}"
                    })

                # Also build a UI-friendly list of missing classes for scheduling.
                if actual < expected:
                    group_key = student_group.name
                    missing_by_group.setdefault(group_key, [])

                    # Lecturer options come from the input mapping for this group/course.
                    lecturers_raw = None
                    try:
                        lecturers_raw = student_group.teacherIDS[i]
                    except Exception:
                        lecturers_raw = None

                    # Add one entry per missing hour so the UI can schedule each occurrence.
                    for _ in range(max(0, expected - actual)):
                        item = {
                            'course': course.code,
                            'course_name': getattr(course, 'name', None) or course.code,
                        }
                        if isinstance(lecturers_raw, list):
                            item['lecturer_options'] = [str(x).strip() for x in lecturers_raw if str(x).strip()]
                        elif lecturers_raw is not None and str(lecturers_raw).strip():
                            item['lecturer'] = str(lecturers_raw).strip()
                        missing_by_group[group_key].append(item)
        
        detailed_violations['Missing or Extra Classes'] = course_allocation_issues
        detailed_violations['missing_classes'] = missing_by_group
        
        # 8. Same Course in Multiple Rooms on Same Day
        same_course_violations = []
        for student_group in self.student_groups:
            for course_id in student_group.courseIDs:
                events_by_day = {}
                for room_idx in range(len(self.rooms)):
                    for timeslot_idx in range(len(self.timeslots)):
                        event_id = chromosome[room_idx][timeslot_idx]
                        if event_id is not None:
                            event = self.events_map.get(event_id)
                            if (event and event.student_group.id == student_group.id 
                                and event.course_id == course_id):
                                day = self.timeslots[timeslot_idx].day
                                if day not in events_by_day:
                                    events_by_day[day] = set()
                                events_by_day[day].add(room_idx)
                
                for day, rooms_used in events_by_day.items():
                    if len(rooms_used) > 1:
                        course = self.input_data.getCourse(course_id)
                        day_abbr = days_map.get(day, "Unknown")
                        room_names = [self.rooms[r_idx].name for r_idx in rooms_used]
                        same_course_violations.append({
                            'course': course.code,
                            'group': student_group.name,
                            'day': day_abbr,
                            'rooms': room_names,
                            'location': f"{course.code} for {student_group.name} on {day_abbr}"
                        })
        
        detailed_violations['Same Course in Multiple Rooms on Same Day'] = same_course_violations

        # 8b. Spread Events Violations
        spread_violations = []
        days = int(self.input_data.days)
        hours_per_day = int(self.input_data.hours)
        events_per_day = {group.id: [0] * days for group in self.student_groups}
        days_used = {group.id: set() for group in self.student_groups}
        total_events = {group.id: 0 for group in self.student_groups}
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is None:
                    continue
                event = self.events_map.get(event_id)
                if not event or not getattr(event, 'student_group', None):
                    continue
                gid = event.student_group.id
                day_idx = self.timeslots[timeslot_idx].day
                if 0 <= day_idx < days:
                    events_per_day[gid][day_idx] += 1
                    days_used[gid].add(day_idx)
                total_events[gid] = total_events.get(gid, 0) + 1

        for group in self.student_groups:
            gid = group.id
            total = int(total_events.get(gid, 0) or 0)
            if total <= 1:
                continue
            target_days = min(days, total)
            used_count = len(days_used.get(gid, set()))
            missing = max(0, target_days - used_count)
            min_days_target = min(3, total, days)
            min_days_gap = max(0, min_days_target - used_count)

            free_hours = []
            if hours_per_day > 0:
                for d in range(days):
                    scheduled = events_per_day[gid][d]
                    free_hours.append(max(0, hours_per_day - scheduled))
            low_free = [i for i, fh in enumerate(free_hours) if fh < 2]

            if missing or min_days_gap or low_free:
                spread_violations.append({
                    'group': group.name,
                    'days_used': used_count,
                    'target_days': target_days,
                    'min_days_target': min_days_target,
                    'total_events': total,
                    'missing_days': missing,
                    'low_free_days': low_free,
                    'free_hours': free_hours,
                    'location': f"{group.name} has {used_count}/{target_days} active days",
                    'reason': "Courses are clustered or days lack free hours; spread across more days",
                })

        detailed_violations['Spread Events Violations'] = spread_violations
        
        # 9. Room Capacity/Type Conflicts
        room_capacity_conflicts = []
        for room_idx in range(len(self.rooms)):
            room = self.rooms[room_idx]
            for timeslot_idx in range(len(self.timeslots)):
                class_event_idx = chromosome[room_idx][timeslot_idx]
                if class_event_idx is not None:
                    class_event = self.events_map.get(class_event_idx)
                    if class_event is not None:
                        course = self.input_data.getCourse(class_event.course_id)
                        timeslot = self.timeslots[timeslot_idx]
                        day_abbr = days_map.get(timeslot.day)
                        time = timeslot.start_time + 8.5
                        
                        # Check room type
                        if room.room_type != course.required_room_type:
                            room_capacity_conflicts.append({
                                'type': 'Room Type Mismatch',
                                'room': room.name,
                                'room_type': room.room_type,
                                'required_type': course.required_room_type,
                                'course': course.code,
                                'group': class_event.student_group.name,
                                'day': day_abbr,
                                'time': self.format_hour(time),
                                'location': f"{room.name} on {day_abbr} at {self.format_hour(time)}"
                            })
                        
                        # Check room capacity
                        if class_event.student_group.no_students > room.capacity:
                            room_capacity_conflicts.append({
                                'type': 'Room Capacity Exceeded',
                                'room': room.name,
                                'capacity': room.capacity,
                                'students': class_event.student_group.no_students,
                                'course': course.code,
                                'group': class_event.student_group.name,
                                'day': day_abbr,
                                'time': self.format_hour(time),
                                'location': f"{room.name} on {day_abbr} at {self.format_hour(time)}"
                            })

                        # Check building for TYD students
                        room_building = str(room.building).upper().strip() if hasattr(room, 'building') and room.building else ""
                        
                        if not class_event.student_group.is_sst and room_building == 'SST':
                            room_capacity_conflicts.append({
                                'type': 'Wrong Building (TYD in SST)',
                                'room': room.name,
                                'building': room.building,
                                'group': class_event.student_group.name,
                                'day': day_abbr,
                                'time': self.format_hour(time),
                                'location': f"{room.name} on {day_abbr} at {self.format_hour(time)}"
                            })
        
        detailed_violations['Room Capacity/Type Conflicts'] = room_capacity_conflicts
        
        # 10. Classes During Break Time
        break_time_violations = []
        break_hour = 4  # 12:30 is the 5th hour (index 4) starting from 8:30
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                timeslot = self.timeslots[timeslot_idx]
                if timeslot.start_time == break_hour and timeslot.day in [0, 2, 4]:  # Mon, Wed, Fri
                    class_event_idx = chromosome[room_idx][timeslot_idx]
                    if class_event_idx is not None:
                        class_event = self.events_map.get(class_event_idx)
                        if class_event is not None:
                            course = self.input_data.getCourse(class_event.course_id)
                            day_abbr = days_map.get(timeslot.day)
                            time = timeslot.start_time + 8.5
                            room = self.rooms[room_idx]
                            break_time_violations.append({
                                'course': course.code,
                                'group': class_event.student_group.name,
                                'room': room.name,
                                'day': day_abbr,
                                'time': self.format_hour(time),
                                'location': f"{room.name} on {day_abbr} at {self.format_hour(time)}"
                            })
        
        detailed_violations['Classes During Break Time'] = break_time_violations

        # 11. Late Classes (17:00)
        late_class_violations = []
        last_hour_index = self.input_data.hours - 1

        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                # If 17:00
                if self.timeslots[timeslot_idx].start_time == last_hour_index:
                    event_id = chromosome[room_idx][timeslot_idx]
                    if event_id is not None:
                        event = self.events_map.get(event_id)
                        if event:
                            day_abbr = days_map.get(self.timeslots[timeslot_idx].day)
                            group_name = event.student_group.name
                            course = self.input_data.getCourse(event.course_id)
                            
                            warning_type = "Late Class"
                            if not event.student_group.is_sst:
                                warning_type = "Late Class (TYD Group - High Penalty)"
                            
                            late_class_violations.append({
                                'type': warning_type,
                                'course': course.code,
                                'group': group_name,
                                'location': f"{course.code} for {group_name} on {day_abbr} at 17:30"
                            })

        detailed_violations['Late Classes'] = late_class_violations
        
        return detailed_violations
    
    def _is_faculty_available_day(self, faculty, day_abbr):
        """Helper method to check if faculty is available on a specific day"""
        # If no availability is specified, assume available all days
        if not faculty.avail_days:
            return True

        def _clean_token(s: str) -> str:
            tok = str(s or '').strip()
            # Strip common wrappers found in stringified lists like "['Mon', 'Tue']".
            while tok and tok[0] in "[({'\"":
                tok = tok[1:].lstrip()
            while tok and tok[-1] in "])}'\"":
                tok = tok[:-1].rstrip()
            return tok

        if isinstance(faculty.avail_days, str):
            raw = _clean_token(faculty.avail_days)
            if raw.upper() == 'ALL' or 'ALL' in raw.upper():
                return True
            days_list = [_clean_token(d) for d in raw.split(',')]
        elif isinstance(faculty.avail_days, list):
            # Check if any element in the list is 'ALL'
            if any(_clean_token(day).upper() == 'ALL' or 'ALL' in _clean_token(day).upper() for day in faculty.avail_days):
                return True
            days_list = [_clean_token(day) for day in faculty.avail_days]
        else:
            # Handle any other case by converting to string
            avail_days_str = _clean_token(str(faculty.avail_days))
            if avail_days_str.upper() == 'ALL' or 'ALL' in avail_days_str.upper():
                return True
            days_list = [_clean_token(d) for d in avail_days_str.split(',')]
        
        norm_days = {str(d).strip().capitalize() for d in days_list if str(d).strip()}
        return day_abbr in norm_days or day_abbr.capitalize() in norm_days
    
    def _is_faculty_available_time(self, faculty, slot_hour, day_abbr=None):
        """Helper method to check if faculty is available at a specific time (optionally checking specific day)"""
        # If no availability is specified, assume available all times
        if not faculty.avail_times:
            return True

        time_specs = []

        def _clean_token(s: str) -> str:
            tok = str(s or '').strip()
            while tok and tok[0] in "[({'\"":
                tok = tok[1:].lstrip()
            while tok and tok[-1] in "])}'\"":
                tok = tok[:-1].rstrip()
            return tok

        if isinstance(faculty.avail_times, dict):
            # Dict mapping days to times (new format)
            if day_abbr:
                specs = None

                # Case-insensitive day key lookup (handles 'thu', 'THU', etc.)
                for k, v in faculty.avail_times.items():
                    try:
                        if _clean_token(k).upper() == str(day_abbr).upper():
                            specs = v
                            break
                    except Exception:
                        continue
                
                if specs:
                    time_specs = specs
                else:
                    # Fallback to 'All' or empty (meaning unavailable)
                    fallback = None
                    for k, v in faculty.avail_times.items():
                        try:
                            kk = _clean_token(k).upper()
                        except Exception:
                            continue
                        if kk in {'ALL', 'ALL DAYS', 'ALLDAY', 'ALL TIMES', 'ALLTIME', 'ALL_TIME'}:
                            fallback = v
                            break
                    if fallback is None:
                        fallback = faculty.avail_times.get('All') or faculty.avail_times.get('ALL') or []
                    time_specs = fallback
            else:
                 # Flatten if no day provided
                 for v in faculty.avail_times.values():
                     if isinstance(v, list): time_specs.extend(v)
                     elif isinstance(v, str): time_specs.append(v)

        elif isinstance(faculty.avail_times, str):
            raw = _clean_token(faculty.avail_times)
            if raw.upper() == 'ALL' or 'ALL' in raw.upper():
                return True
            time_specs = [_clean_token(t) for t in raw.split(',')]
        elif isinstance(faculty.avail_times, list):
            # Check if any element in the list is 'ALL'
            if any(_clean_token(time).upper() == 'ALL' or 'ALL' in _clean_token(time).upper() for time in faculty.avail_times):
                return True
            time_specs = [_clean_token(time) for time in faculty.avail_times]
        else:
            # Handle any other case by converting to string
            avail_times_str = _clean_token(str(faculty.avail_times))
            if avail_times_str.upper() == 'ALL' or 'ALL' in avail_times_str.upper():
                return True
            time_specs = [_clean_token(t) for t in avail_times_str.split(',')]
        
        # If any extracted spec means ALL, short-circuit.
        if isinstance(time_specs, str) and str(time_specs).strip().upper() == 'ALL':
            return True
        if isinstance(time_specs, list) and any(str(s).strip().upper() == 'ALL' or 'ALL' in str(s).upper() for s in time_specs):
            return True
        if not isinstance(time_specs, list):
            time_specs = [time_specs]

        slot_min = int(slot_hour * 60)

        def parse_time_point(value) -> int | None:
            s = _clean_token(str(value))
            if not s:
                return None

            m = re.match(r'^\s*(\d{1,2})\s*:\s*(\d{2})\s*$', s)
            if m:
                h = int(m.group(1))
                mi = int(m.group(2))
            else:
                m = re.match(r'^\s*(\d{1,2})\s*$', s)
                if m:
                    h = int(m.group(1))
                    mi = 0
                else:
                    try:
                        f = float(s)
                        h = int(f)
                        mi = int(round((f - h) * 60))
                    except Exception:
                        return None

            # Heuristic: treat ambiguous early-hours as afternoon/evening.
            if 1 <= h <= 5 or (h == 6 and mi <= 30):
                h += 12
            return h * 60 + mi

        def parse_time_range(spec: str):
            s = _clean_token(spec)
            parts = re.split(r'\s*(?:-|–|—|(?i:\\bto\\b))\s*', s, maxsplit=1)
            if len(parts) != 2:
                return None, None
            start_min = parse_time_point(parts[0])
            end_min = parse_time_point(parts[1])
            if start_min is None or end_min is None:
                return None, None
            if end_min <= start_min:
                return None, None
            return start_min, end_min

        for time_spec in time_specs:
            spec = _clean_token(str(time_spec))
            if not spec:
                continue
            if spec.upper() == 'ALL':
                return True
            if re.search(r'[-–—]|\bto\b', spec, flags=re.IGNORECASE):
                try:
                    start_min, end_min = parse_time_range(spec)
                    if start_min is None or end_min is None:
                        continue
                    # For discrete slot-start matching, treat end as inclusive.
                    if start_min <= slot_min <= end_min:
                        return True
                except Exception:
                    continue
            else:
                m = parse_time_point(spec)
                if m is not None and m == slot_min:
                    return True
        
        return False

    def check_student_group_clash_at_slot(self, chromosome, student_group_id, timeslot_idx, ignore_room_idx=-1):
        """Checks if a specific student group has a clash at a given timeslot, optionally ignoring one room."""
        for r_idx in range(len(self.rooms)):
            if r_idx == ignore_room_idx:
                continue
            event_id = chromosome[r_idx, timeslot_idx]
            if event_id is not None:
                event = self.events_map.get(event_id)
                if event and event.student_group.id == student_group_id:
                    return True  # Clash found
        return False

    def check_lecturer_clash_at_slot(self, chromosome, faculty_id, timeslot_idx, ignore_room_idx=-1):
        """Checks if a specific lecturer has a clash at a given timeslot, optionally ignoring one room."""
        if faculty_id is None:
            return False
        for r_idx in range(len(self.rooms)):
            if r_idx == ignore_room_idx:
                continue
            event_id = chromosome[r_idx, timeslot_idx]
            if event_id is not None:
                event = self.events_map.get(event_id)
                if event and event.faculty_id == faculty_id:
                    return True  # Clash found
        return False
    # def no_class_on_friday(self, chromosome, debug=False):
    #     """
    #     Constraint: No classes should be scheduled on Fridays.
    #     Friday corresponds to day index 4.
    #     """
    #     penalty = 0
    #     violations = []
        
    #     # Friday is day index 4 (0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri)
    #     friday_day_index = 4
        
    #     for room_idx in range(len(self.rooms)):
    #         for timeslot_idx in range(len(self.timeslots)):
    #             # Check if this timeslot is on a Friday
    #             if self.timeslots[timeslot_idx].day == friday_day_index:
    #                 # Check if there is an event scheduled
    #                 event_id = chromosome[room_idx][timeslot_idx]
    #                 if event_id is not None:
    #                     penalty += 10 # High penalty for Friday class
                        
    #                     if debug:
    #                         event = self.events_map.get(event_id)
    #                         if event:
    #                             course = self.input_data.getCourse(event.course_id)
    #                             room = self.rooms[room_idx]
    #                             time = self.timeslots[timeslot_idx].start_time + 9
    #                             violations.append(f"Friday Class: {course.code} in {room.name} at {time}:00")

    #     if debug and violations:
    #         print("\n--- Friday Class Violations ---")
    #         for v in violations:
    #             print(v)
    #         print("-------------------------------\n")

    #     return penalty
    
    def extremely_late_classes(self, chromosome, debug=False):
        """Soft/near-hard constraint: avoid scheduling anything at the last hour (17:30).

        User requirements:
        - At most 10 total late occurrences overall.
        - At most 10 student groups with any late occurrence.
        - If a student group has a late class, it must be only ONE occurrence.
        - Light-load groups (low total hours and no 4-credit courses) must NEVER be late.

        Note: This is still enforced via fitness (not a true hard constraint), so if the
        problem is infeasible under other hard constraints, the optimizer may still place late classes.
        """
        penalty = 0
        total_late = 0
        
        # Weights (EXTREME - intended to behave like hard constraints)
        base_penalty = 60000.0
        tyd_penalty_weight = 380000.0
        light_load_penalty = 1500000.0

        max_total_occurrences = 10
        max_groups_with_late = 10

        cap_penalty_weight = 1500000.0
        group_cap_penalty_weight = 1500000.0
        repeat_weight = 1500000.0

        late_by_group = {}
        last_hour_index = self.input_data.hours - 1
        
        # sst_keywords moved to StudentGroup.is_sst property

        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                # Check if 17:00
                if self.timeslots[timeslot_idx].start_time != last_hour_index:
                    continue

                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is None:
                    continue

                total_late += 1
                event = self.events_map.get(event_id)
                if not event:
                    continue

                group = event.student_group
                group_id = group.id
                late_by_group[group_id] = late_by_group.get(group_id, 0) + 1
                
                # 1. Base Penalty
                penalty += base_penalty

                # 2. Light-load groups should NEVER be late
                # Heuristic:
                # - total required hours for the group is low (<= 18), AND
                # - group has NO 4-credit courses
                total_required_hours = 0
                try:
                    if hasattr(group, 'hours_required') and group.hours_required:
                        total_required_hours = sum(int(x) for x in group.hours_required)
                except Exception:
                    total_required_hours = 0

                has_4_credit_course = False
                try:
                    for cid in getattr(group, 'courseIDs', []) or []:
                        c = self.input_data.getCourse(cid)
                        if c and getattr(c, 'credits', 0) >= 4:
                            has_4_credit_course = True
                            break
                except Exception:
                    has_4_credit_course = False

                is_light_load = (total_required_hours > 0 and total_required_hours <= 18) and (not has_4_credit_course)
                if is_light_load:
                    penalty += light_load_penalty

                # 3. TYD vs SST Check
                if not group.is_sst:
                    penalty += tyd_penalty_weight

        late_groups = len(late_by_group)

        # 4. Global caps (strict)
        if total_late > max_total_occurrences:
            penalty += (total_late - max_total_occurrences) * cap_penalty_weight

        if late_groups > max_groups_with_late:
            penalty += (late_groups - max_groups_with_late) * group_cap_penalty_weight

        # 5. Per-group cap (strict): max 1 late occurrence per group
        repeat_violations = sum(max(0, cnt - 1) for cnt in late_by_group.values())
        penalty += repeat_weight * repeat_violations

        if debug:
            # Single summary line as requested
            print(
                f"[Constraint] 17:00 late summary | groups={late_groups} (<= {max_groups_with_late}), "
                f"occurrences={total_late} (<= {max_total_occurrences}), repeat_violations={repeat_violations}, "
                f"penalty={penalty}"
            )

        return penalty


    def check_no_free_day(self, chromosome, debug: bool = False):
        """Penalize student groups that have a completely free day.

        Applies only when a group has enough scheduled events to plausibly cover all days.
        (If a group has fewer total events than days, having a free day is unavoidable.)
        """
        penalty = 0.0
        days = int(self.input_data.days)
        hours = int(self.input_data.hours)

        events_per_day = {group.id: [0] * days for group in self.student_groups}
        total_events = {group.id: 0 for group in self.student_groups}

        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is None:
                    continue
                ev = self.events_map.get(event_id)
                if not ev or not getattr(ev, 'student_group', None):
                    continue
                gid = ev.student_group.id
                day_idx = timeslot_idx // hours
                if gid in events_per_day and 0 <= day_idx < days:
                    events_per_day[gid][day_idx] += 1
                    total_events[gid] += 1

        for group in self.student_groups:
            gid = group.id
            if total_events.get(gid, 0) < days:
                continue
            free_days = sum(1 for c in events_per_day.get(gid, []) if c == 0)
            if free_days:
                penalty += 10000.0 * free_days

        return penalty


    def check_three_unit_split_across_days(self, chromosome, debug: bool = False):
        """TYD 3-credit courses: prefer 2 hours on one day, remaining hour on another day."""
        penalty = 0.0
        hours_per_day = int(self.input_data.hours)

        # (course_id, group_id) -> list[timeslot_idx]
        course_schedule = {}
        group_is_sst = {}
        for room_idx in range(len(self.rooms)):
            for timeslot_idx in range(len(self.timeslots)):
                event_id = chromosome[room_idx][timeslot_idx]
                if event_id is None:
                    continue
                event = self.events_map.get(event_id)
                if not event or not getattr(event, 'student_group', None):
                    continue
                course = self.input_data.getCourse(event.course_id)
                try:
                    if not course or int(getattr(course, 'credits', 0) or 0) != 3:
                        continue
                except Exception:
                    continue
                
                key = (str(getattr(course, 'code', '')), str(event.student_group.id))
                course_schedule.setdefault(key, []).append(timeslot_idx)
                if key not in group_is_sst:
                    group_is_sst[key] = bool(getattr(event.student_group, 'is_sst', False))

        for key, timeslots in course_schedule.items():
            if len(timeslots) < 3:
                continue
            timeslots = sorted(timeslots)
            is_sst = group_is_sst.get(key, False)
            if is_sst:
                continue

            # Analyze day distribution (TYD only)
            day_counts = {}
            for t in timeslots[:3]:  # Consider the first 3 hours
                d = t // hours_per_day
                day_counts[d] = day_counts.get(d, 0) + 1
            
            # For TYD: PREFER 2 hours one day, 1 hour another day
            pair_days = set()
            for i in range(len(timeslots) - 1):
                t1, t2 = timeslots[i], timeslots[i + 1]
                if (t2 - t1) == 1 and (t1 // hours_per_day) == (t2 // hours_per_day):
                    pair_days.add(t1 // hours_per_day)

            if not pair_days:
                penalty += 50.0
                continue

            ok = False
            for pd in pair_days:
                if any((t // hours_per_day) != pd for t in timeslots):
                    ok = True
                    break

            if not ok:
                penalty += 50.0

        return penalty