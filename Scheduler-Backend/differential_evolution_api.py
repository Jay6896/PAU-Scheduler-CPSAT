# differential_evolution_api.py
"""
API-compatible differential evolution algorithm that works with input_data instances
passed from the Flask application instead of static imports.
"""

import random
from typing import List
import copy
from utils import Utility
from entitities.Class import Class
import numpy as np
from constraints import Constraints
import re

class DifferentialEvolution:
    def __init__(self, input_data, pop_size: int, F: float, CR: float):
        self.desired_fitness = 0
        self.input_data = input_data
        self.rooms = input_data.rooms
        self.timeslots = input_data.create_time_slots(
            no_hours_per_day=input_data.hours, 
            no_days_per_week=input_data.days, 
            day_start_time=8.5
        )
        self.student_groups = input_data.student_groups
        self.courses = input_data.courses
        self.events_list, self.events_map = self.create_events()
        self.pop_size = pop_size
        self.F = F
        self.CR = CR
        self.constraints = Constraints(input_data)

        # If True, treat soft constraints as hard (must be 0 to accept improvements).
        # This is used by the "strict-if-possible" probe and strict runs.
        self.strict_mode = False
        
        # Optimization: Cache fitness values to avoid recalculation
        self.fitness_cache = {}
        
        # Optimization: Pre-calculate building assignments for rooms to speed up evaluation
        self.room_building_cache = {}
        for idx, room in enumerate(self.rooms):
            self.room_building_cache[idx] = self.get_room_building(room)
        
        # Optimization: Pre-calculate SST groups (explicit building first; keywords as fallback).
        self.engineering_groups = {sg.id for sg in self.student_groups if getattr(sg, 'is_sst', False)}
        
        self.population = self.initialize_population()

    def set_strict_mode(self, enabled: bool) -> None:
        self.strict_mode = bool(enabled)

    def _hard_constraint_keys(self) -> list[str]:
        """Constraint keys that are prioritized lexicographically during selection.

        In normal mode, only true hard constraints are included.
        In strict mode, soft constraints are also treated as hard.
        """
        base = [
            'student_group_constraints',
            'lecturer_availability',
            'course_allocation_completeness',
            'room_time_conflict',
            'break_time_constraint',
            'room_constraints',
            'same_course_same_room_per_day',
            'lecturer_schedule_constraints',
            'building_assignments',
            'no_free_day',
            'consecutive_timeslots',
        ]
        if not self.strict_mode:
            return base

        # Treat soft constraints as hard when strict_mode is enabled.
        return base + [
            'single_event_per_day',
            'three_unit_split_across_days_TYD',
            'spread_events',
            'extremely_late_classes',
            'lecturer_workload_constraints',
        ]

    def _can_place_event_id(
        self,
        chromosome,
        room_idx: int,
        timeslot_idx: int,
        event_id,
        *,
        ignore_event_ids=None,
        ignore_faculty_availability: bool = False,
    ) -> bool:
        """Return True if event_id can be placed at (room_idx, timeslot_idx) without violating
        immediate feasibility checks.

        This is a local feasibility gate used by mutation/crossover so they don't introduce
        obvious hard violations (room suitability, break time, building rule, lecturer windows,
        and same-timeslot lecturer/group overlaps).
        """
        if event_id is None:
            return True

        if ignore_event_ids is None:
            ignore_event_ids = set()
        else:
            ignore_event_ids = set(ignore_event_ids)

        ev = self.events_map.get(event_id)
        if ev is None:
            return False

        # Cell occupancy check: allow overwriting only if the existing value is being ignored.
        existing = chromosome[room_idx][timeslot_idx]
        if existing is not None and existing not in ignore_event_ids:
            return False

        # Room suitability check
        try:
            course = self.input_data.getCourse(ev.course_id)
        except Exception:
            course = None
        if not self.is_room_suitable(self.rooms[room_idx], course):
            return False

        # Same-timeslot student-group / lecturer overlap checks (ignore specified event ids).
        sg_id = None
        try:
            sg_id = ev.student_group.id
        except Exception:
            sg_id = None

        for r_idx in range(len(self.rooms)):
            other_id = chromosome[r_idx][timeslot_idx]
            if other_id is None or other_id in ignore_event_ids:
                continue
            other_ev = self.events_map.get(other_id)
            if not other_ev:
                continue
            try:
                if sg_id is not None and other_ev.student_group and other_ev.student_group.id == sg_id:
                    return False
            except Exception:
                pass
            try:
                if ev.faculty_id is not None and other_ev.faculty_id == ev.faculty_id:
                    return False
            except Exception:
                pass

        # Use the canonical slot checks (break time, building rule, lecturer day/time windows).
        # Temporarily clear the destination cell so is_slot_available_for_event sees an empty slot.
        chromosome[room_idx][timeslot_idx] = None
        try:
            ok = self.is_slot_available_for_event(
                chromosome,
                room_idx,
                timeslot_idx,
                ev,
                ignore_faculty_availability=ignore_faculty_availability,
            )
            return bool(ok)
        finally:
            chromosome[room_idx][timeslot_idx] = existing

    @staticmethod
    def _parse_time_point(value):
        """Parse a time point into minutes since midnight.

        Supports:
        - 'HH:MM' (e.g., '08:30')
        - 'H' / 'HH' whole-hour strings (e.g., '8')
        - fractional hours (e.g., '8.5' -> 08:30)
        """
        def maybe_assume_pm(hour: int, minute: int) -> int:
            # Heuristic: treat ambiguous early-hours as afternoon/evening.
            # Users often enter '3:30' intending 15:30, not 03:30.
            # Apply for 1:00–6:30 inclusive; do not touch normal morning times like 08:30.
            if 1 <= hour <= 5:
                return hour + 12
            if hour == 6 and minute <= 30:
                return 18
            return hour

        if value is None:
            return None

        s = str(value).strip()
        # Strip wrappers from stringified lists like "['8:30-16:30']".
        while s and s[0] in "[({'\"":
            s = s[1:].lstrip()
        while s and s[-1] in "])}'\"":
            s = s[:-1].rstrip()
        if not s:
            return None

        m = re.match(r'^\s*(\d{1,2})\s*:\s*(\d{2})\s*$', s)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            hour = maybe_assume_pm(hour, minute)
            return hour * 60 + minute

        m = re.match(r'^\s*(\d{1,2})\s*\.\s*(\d+)\s*$', s)
        if m:
            hours = int(m.group(1))
            frac = float('0.' + m.group(2))
            minute = int(round(frac * 60))
            hours = maybe_assume_pm(hours, minute)
            return hours * 60 + minute

        m = re.match(r'^\s*(\d{1,2})\s*$', s)
        if m:
            hours = int(m.group(1))
            hours = maybe_assume_pm(hours, 0)
            return hours * 60

        try:
            f = float(s)
            hours = int(f)
            minute = int(round((f - hours) * 60))
            hours = maybe_assume_pm(hours, minute)
            return hours * 60 + minute
        except Exception:
            return None

    @staticmethod
    def parse_time_range(spec_str: str):
        """Parse a time range like '08:30-12:30' into (start_min, end_min)."""
        if not spec_str:
            return None, None

        s = str(spec_str).strip()
        if not s:
            return None, None

        parts = re.split(r'\s*(?:-|–|—|(?i:\\bto\\b))\s*', s, maxsplit=1)
        if len(parts) != 2:
            return None, None

        start_min = DifferentialEvolution._parse_time_point(parts[0])
        end_min = DifferentialEvolution._parse_time_point(parts[1])
        if start_min is None or end_min is None:
            return None, None
        if end_min <= start_min:
            return None, None
        return start_min, end_min

    def create_events(self):
        """Create events list and mapping for the timetabling problem"""
        events_list = []
        event_map = {}

        idx = 0
        for student_group in self.student_groups:
            for i in range(student_group.no_courses):
                # Match core behavior: 1-credit courses are treated as 3 hours.
                course = self.input_data.getCourse(student_group.courseIDs[i])
                if course and getattr(course, 'credits', None) == 1:
                    required_hours = 3
                else:
                    required_hours = student_group.hours_required[i]

                hourcount = 1
                while hourcount <= required_hours:
                    event = Class(student_group, student_group.teacherIDS[i], student_group.courseIDs[i])
                    events_list.append(event)
                    event_map[idx] = event
                    idx += 1
                    hourcount += 1
                    
        return events_list, event_map

    def initialize_population(self):
        """Initialize the population with valid chromosomes"""
        population = [] 
        for i in range(self.pop_size):
            chromosome = self.create_chromosome()
            population.append(chromosome)
        return np.array(population)

    def create_chromosome(self):
        """Create a single chromosome (timetable solution)"""
        chromosome = np.empty((len(self.rooms), len(self.timeslots)), dtype=object)
        
        # Group events by student group and course to handle them as blocks
        events_by_group_course = {}
        for idx, event in enumerate(self.events_list):
            key = (event.student_group.id, event.course_id)
            if key not in events_by_group_course:
                events_by_group_course[key] = []
            events_by_group_course[key].append(idx)

        # Trackers for optimized placement
        hours_per_day_for_group = {sg.id: [0] * self.input_data.days for sg in self.student_groups}
        non_sst_course_count_for_group = {sg.id: 0 for sg in self.student_groups}
        course_days_used = {}

        # Randomize course processing order for population diversity
        course_items = list(events_by_group_course.items())
        random.shuffle(course_items)

        for (student_group_id, course_id), event_indices in course_items:
            course = self.input_data.getCourse(course_id)
            student_group = self.input_data.getStudentGroup(student_group_id)
            hours_required = len(event_indices)

            if hours_required == 0:
                continue

            # Decide on a split strategy based on course credits
            if hours_required == 3:
                is_engineering = student_group.id in self.engineering_groups
                if is_engineering:
                    # SST: 3-hour courses are primarily 3 consecutive hours (fallback to 2,1 internally during repair if needed)
                    # We will randomly allow 2,1 occasionally but strongly prefer 3
                    split_strategy = (3,) if random.random() < 0.85 else (2, 1)
                else:
                    # TYD: 3-hour courses are scheduled as 2 hours on one day, 1 hour on another
                    split_strategy = (2, 1)
            elif hours_required == 2:
                split_strategy = (2,)
            else:
                split_strategy = (hours_required,)

            event_idx_counter = 0
            course_key = (student_group_id, course_id)
            course_days_used[course_key] = set()
            is_course_placed_in_non_sst = False

            for block_hours in split_strategy:
                placed = False
                block_event_indices = event_indices[event_idx_counter : event_idx_counter + block_hours]
                event_idx_counter += block_hours

                # Prioritize days with fewer hours and those not yet used by this course
                available_days = [d for d in range(self.input_data.days) if d not in course_days_used[course_key]]
                sorted_days = sorted(available_days, key=lambda d: hours_per_day_for_group[student_group_id][d])

                for day_idx in sorted_days:
                    day_start = day_idx * self.input_data.hours
                    day_end = (day_idx + 1) * self.input_data.hours
                    
                    possible_slots = []
                    for room_idx, room in enumerate(self.rooms):
                        if self.is_room_suitable(room, course):
                            room_building = self.room_building_cache[room_idx]
                            is_engineering = student_group.id in self.engineering_groups
                            
                            req_room_val = str(getattr(course, 'required_room_type', '') or '').lower()
                            room_type_val = str(getattr(room, 'room_type', '') or '').lower()
                            course_name_val = str(getattr(course, 'name', '') or '').lower()
                            
                            needs_computer_lab = (
                                req_room_val in ['comp lab', 'computer_lab'] or
                                room_type_val in ['comp lab', 'computer_lab'] or
                                ('lab' in course_name_val and any(k in course_name_val for k in ['computer', 'programming', 'software']))
                            )

                            building_allowed = True
                            if needs_computer_lab:
                                # Requirement: TYD groups must NEVER use SST rooms (even labs).
                                if (not is_engineering) and room_building == 'SST':
                                    building_allowed = False
                            elif is_engineering:
                                if room_building != 'SST' and non_sst_course_count_for_group[student_group_id] >= 2:
                                    building_allowed = False
                            elif room_building == 'SST':
                                building_allowed = False
                            
                            if building_allowed:
                                # Find consecutive slots
                                for timeslot_start in range(day_start, day_end):
                                    if timeslot_start + block_hours > day_end:
                                        continue

                                    def _ok(i: int) -> bool:
                                        ts = timeslot_start + i
                                        ev = self.events_list[block_event_indices[i]]
                                        return (
                                            self.is_slot_available_for_event(chromosome, room_idx, ts, ev)
                                            and self._is_student_group_available(chromosome, student_group_id, ts)
                                            and self._is_lecturer_available(chromosome, ev.faculty_id, ts)
                                        )

                                    if all(_ok(i) for i in range(block_hours)):
                                        possible_slots.append((room_idx, timeslot_start))
                    
                    if possible_slots:
                        # Prefer SST rooms for SST groups when available (soft preference).
                        if is_engineering:
                            sst_slots = [s for s in possible_slots if str(self.room_building_cache.get(s[0], '')).upper() == 'SST']
                            if sst_slots and random.random() < 0.85:
                                room_idx, timeslot_start = random.choice(sst_slots)
                            else:
                                room_idx, timeslot_start = random.choice(possible_slots)
                        else:
                            room_idx, timeslot_start = random.choice(possible_slots)
                        for i in range(block_hours):
                            chromosome[room_idx, timeslot_start + i] = block_event_indices[i]
                        
                        # Update trackers
                        hours_per_day_for_group[student_group_id][day_idx] += block_hours
                        course_days_used[course_key].add(day_idx)
                        
                        if not is_course_placed_in_non_sst and self.room_building_cache[room_idx] != 'SST' and not needs_computer_lab and is_engineering:
                            non_sst_course_count_for_group[student_group_id] += 1
                            is_course_placed_in_non_sst = True
                        
                        placed = True
                        break
                
                if placed:
                    break

        # Final verification to place any unassigned events
        chromosome = self.verify_and_repair_course_allocations(chromosome)
        return chromosome

    def is_slot_available(self, chromosome, room_idx, timeslot_idx):
        """Check if a timeslot is available"""
        if chromosome[room_idx][timeslot_idx] is not None:
            return False
        
        # Check if this is break time (13:00 - 14:00)
        break_hour = 4  # 13:00 is the 5th hour (index 4) starting from 9:00
        day = timeslot_idx // self.input_data.hours
        hour_in_day = timeslot_idx % self.input_data.hours
        
        # No break time on Tuesday (1) and Thursday (3)
        if hour_in_day == break_hour and day not in [1, 3]:
            return False
        
        return True

    def is_slot_available_for_event(self, chromosome, room_idx, timeslot_idx, event, ignore_faculty_availability: bool = False):
        """Check if a slot is available for a specific event.

        By default, enforces lecturer day/time availability windows.
        When repairing missing events, we may relax lecturer availability (but still keep
        lecturer clashes and student-group clashes prevented by the caller).
        """
        # Check if the slot is physically empty
        if chromosome[room_idx][timeslot_idx] is not None:
            return False

        # Check for break time
        break_hour = 4
        day = timeslot_idx // self.input_data.hours
        hour_in_day = timeslot_idx % self.input_data.hours
        if hour_in_day == break_hour and day not in [1, 3]:
            return False

        # Hard rule: TYD (non-SST) student groups must never be placed in SST rooms.
        # Enforce at the feasibility layer so crossover/mutation/repairs can't introduce it.
        try:
            if event is not None and getattr(event, 'student_group', None) is not None:
                if not getattr(event.student_group, 'is_sst', False):
                    room_building = self.room_building_cache.get(room_idx)
                    if not room_building:
                        room_building = self.get_room_building(self.rooms[room_idx])
                    if str(room_building).upper() == 'SST':
                        return False
        except Exception:
            pass

        # Check lecturer schedule constraints
        if (not ignore_faculty_availability) and event and event.faculty_id is not None:
            faculty = self.input_data.getFaculty(event.faculty_id)
            if faculty:
                days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
                day_abbr = days_map.get(day)

                def _clean_token(v) -> str:
                    s = str(v or '').strip()
                    while s and s[0] in "[({'\"":
                        s = s[1:].lstrip()
                    while s and s[-1] in "])'}\"":
                        s = s[:-1].rstrip()
                    return s

                def parse_hhmm(s):
                    # Delegate to shared parser so the PM heuristic applies consistently.
                    return DifferentialEvolution._parse_time_point(s)

                timeslot_obj = self.timeslots[timeslot_idx]
                # 08:30-based slots: index 0 -> 08:30
                if isinstance(getattr(timeslot_obj, 'start_time', None), (int, np.integer)):
                    slot_min = (8 * 60 + 30) + int(timeslot_obj.start_time) * 60
                else:
                    slot_min = parse_hhmm(getattr(timeslot_obj, 'start_time', ''))

                # Check day availability
                is_day_ok = False
                if isinstance(faculty.avail_days, str):
                    days_raw = _clean_token(faculty.avail_days)
                    if (not days_raw) or (days_raw.upper() == "ALL") or ("ALL" in days_raw.upper()):
                        is_day_ok = True
                    else:
                        avail_days = [_clean_token(d).strip().capitalize() for d in days_raw.split(',') if _clean_token(d).strip()]
                        if day_abbr in avail_days:
                            is_day_ok = True
                elif isinstance(faculty.avail_days, list):
                    if not faculty.avail_days:
                        is_day_ok = True
                    else:
                        cleaned = [_clean_token(d).strip() for d in faculty.avail_days if _clean_token(d).strip()]
                        if any((d.upper() == 'ALL') or ('ALL' in d.upper()) for d in cleaned):
                            is_day_ok = True
                        else:
                            avail_days = [d.capitalize() for d in cleaned]
                            if day_abbr in avail_days:
                                is_day_ok = True
                else:
                    days_raw = _clean_token(faculty.avail_days)
                    if (not days_raw) or (days_raw.upper() == "ALL") or ("ALL" in days_raw.upper()):
                        is_day_ok = True
                    else:
                        avail_days = [_clean_token(d).strip().capitalize() for d in str(days_raw).split(',') if _clean_token(d).strip()]
                        if day_abbr in avail_days:
                            is_day_ok = True
                
                if not is_day_ok:
                    return False

                # Check time availability (supports str/list/dict and ALL)
                avail_times = faculty.avail_times

                def iter_time_specs(av):
                    def normalize_to_list(specs):
                        if not specs:
                            return []
                        if isinstance(specs, list):
                            out = []
                            for x in specs:
                                if isinstance(x, str) and ',' in x:
                                    out.extend([_clean_token(t) for t in x.split(',') if _clean_token(t)])
                                else:
                                    out.append(_clean_token(x))
                            return out
                        if isinstance(specs, str):
                            raw = _clean_token(specs)
                            if raw.upper() == 'ALL' or 'ALL' in raw.upper():
                                return ['ALL']
                            if ',' in raw:
                                return [_clean_token(t) for t in raw.split(',') if _clean_token(t)]
                            return [raw]
                        return [_clean_token(specs)]

                    if not av:
                        return []
                    if isinstance(av, dict):
                        specs = None
                        if day_abbr:
                            specs = av.get(day_abbr) or av.get(day_abbr.capitalize())
                        if not specs:
                            specs = av.get('All') or av.get('ALL')
                        return normalize_to_list(specs)
                    if isinstance(av, list):
                        return normalize_to_list(av)
                    return normalize_to_list(av)

                specs_list = iter_time_specs(avail_times)
                if specs_list and not any((str(s).strip().upper() == 'ALL') or ('ALL' in str(s).upper()) for s in specs_list):
                    # If we cannot parse the slot time, be permissive.
                    if slot_min is None:
                        pass
                    else:
                        is_time_ok = False
                        for spec in specs_list:
                            spec_str = _clean_token(spec)
                            if not spec_str:
                                continue
                            if re.search(r'[-–—]|\bto\b', spec_str, flags=re.IGNORECASE):
                                start_min, end_min = self.parse_time_range(spec_str)
                                if start_min is not None and end_min is not None:

                                    # Inclusive end: users expect 9:30-15:30 to allow a 15:30 start.
                                    if start_min <= slot_min <= end_min:
                                        is_time_ok = True
                                        break
                            else:
                                m = parse_hhmm(spec_str)
                                if m is not None and m == slot_min:
                                    is_time_ok = True
                                    break
                        if not is_time_ok:
                            return False

        return True

    def is_room_suitable(self, room, course):
        """Check if room is suitable for course"""
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
        """Check if a student group is already scheduled at a given timeslot"""
        for r_idx in range(len(self.rooms)):
            event_id = chromosome[r_idx][timeslot_idx]
        for event_id in chromosome[:, timeslot_idx]:
            if event_id is not None:
                event = self.events_map.get(event_id)
                if event and event.student_group.id == student_group_id:
                    return False
        return True

    def _is_lecturer_available(self, chromosome, faculty_id, timeslot_idx):
        """Check if a lecturer is already scheduled at a given timeslot"""
        if faculty_id is None:
            return True
        for r_idx in range(len(self.rooms)):
            event_id = chromosome[r_idx][timeslot_idx]
            if event_id is not None:
                event = self.events_map.get(event_id)
                if event and event.faculty_id == faculty_id:
                    return False
        return True

    def find_clash(self, chromosome):
        """Find a random timeslot with a student or lecturer clash"""
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
                if not event: 
                    continue
                
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
        """Calculate Hamming distance between two chromosomes"""
        return np.sum(chromosome1.flatten() != chromosome2.flatten())

    def calculate_population_diversity(self):
        """Calculate population diversity using sampling for efficiency"""
        if self.pop_size <= 10:
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
        """Mutation operation with targeted clash resolution"""
        mutant_vector = self.population[target_idx].copy()

        # Strategy 1: Targeted Clash Resolution
        if random.random() < 0.7:
            clash_timeslot = self.find_clash(mutant_vector)
            if clash_timeslot is not None:
                events_in_clash = [mutant_vector[r][clash_timeslot] for r in range(len(self.rooms)) if mutant_vector[r][clash_timeslot] is not None]
                
                if events_in_clash:
                    event_id_to_move = random.choice(events_in_clash)
                    event_to_move = self.events_map.get(event_id_to_move)

                    if event_to_move:
                        # Find original position and remove it
                        for r_idx in range(len(self.rooms)):
                            if mutant_vector[r_idx][clash_timeslot] == event_id_to_move:
                                mutant_vector[r_idx][clash_timeslot] = None
                                break
                        
                        # Find a new, completely valid slot for this event
                        possible_slots = []
                        course = self.input_data.getCourse(event_to_move.course_id)
                        for r_idx, room in enumerate(self.rooms):
                            if self.is_room_suitable(room, course):
                                for t_idx in range(len(self.timeslots)):
                                    if (self.is_slot_available_for_event(mutant_vector, r_idx, t_idx, event_to_move) and
                                        self._is_student_group_available(mutant_vector, event_to_move.student_group.id, t_idx) and
                                        (event_to_move.faculty_id is None or self._is_lecturer_available(mutant_vector, event_to_move.faculty_id, t_idx))):
                                        possible_slots.append((r_idx, t_idx))
                        
                        if possible_slots:
                            r, t = random.choice(possible_slots)
                            mutant_vector[r][t] = event_id_to_move

        # Strategy 2: Perform a few swaps to introduce small variations
        if random.random() < 0.2:
            for _ in range(random.randint(1, 2)):
                occupied_slots = np.argwhere(mutant_vector != None)
                if len(occupied_slots) < 2:
                    continue

                # Try a few times to find a swap that remains feasible.
                for _try in range(8):
                    idx1, idx2 = random.sample(range(len(occupied_slots)), 2)
                    pos1, pos2 = tuple(occupied_slots[idx1]), tuple(occupied_slots[idx2])
                    if pos1 == pos2:
                        continue

                    e1 = mutant_vector[pos1]
                    e2 = mutant_vector[pos2]
                    if e1 is None or e2 is None:
                        continue

                    ignore_ids = {e1, e2}
                    r1, t1 = int(pos1[0]), int(pos1[1])
                    r2, t2 = int(pos2[0]), int(pos2[1])

                    # Check feasibility of swapping the two events.
                    if not self._can_place_event_id(mutant_vector, r2, t2, e1, ignore_event_ids=ignore_ids):
                        continue
                    if not self._can_place_event_id(mutant_vector, r1, t1, e2, ignore_event_ids=ignore_ids):
                        continue

                    mutant_vector[pos1], mutant_vector[pos2] = mutant_vector[pos2], mutant_vector[pos1]
                    break

        return mutant_vector

    def crossover(self, target_vector, mutant_vector):
        """Enhanced Strategic Crossover with conflict resolution"""
        trial_vector = target_vector.copy()
        conflicts = self.constraints.get_all_conflicts(trial_vector)
        
        # Combine all hard conflicts to be resolved
        all_clashes = conflicts.get('student_group', []) + conflicts.get('lecturer', [])
        
        if not all_clashes:
            # If no clashes, perform a more standard DE crossover
            for r in range(len(self.rooms)):
                for t in range(len(self.timeslots)):
                    if random.random() < self.CR:
                        gene = mutant_vector[r, t]
                        if gene is None:
                            trial_vector[r, t] = None
                            continue

                        # Only accept the gene if it is feasible in the target slot.
                        # Allow overwriting the existing target gene by ignoring it.
                        existing = trial_vector[r, t]
                        if self._can_place_event_id(trial_vector, r, t, gene, ignore_event_ids={existing} if existing is not None else None):
                            trial_vector[r, t] = gene
            return trial_vector

        # Create a set of positions that have clashes for quick lookup
        clash_positions = set()
        for clash in all_clashes:
            for pos in clash['positions']:
                clash_positions.add(tuple(pos))

        # Iterate through the mutant and bring in non-conflicting genes
        for r in range(len(self.rooms)):
            for t in range(len(self.timeslots)):
                if (r, t) in clash_positions:
                    mutant_gene = mutant_vector[r, t]
                    target_gene = trial_vector[r, t]

                    if mutant_gene != target_gene and mutant_gene is not None:
                        mutant_event = self.events_map.get(mutant_gene)
                        if not mutant_event: 
                            continue

                        is_safe_to_swap = True
                        # Check against all other events in the same timeslot in the trial vector
                        for r_check in range(len(self.rooms)):
                            if r_check != r:
                                existing_event_id = trial_vector[r_check, t]
                                if existing_event_id is not None:
                                    existing_event = self.events_map.get(existing_event_id)
                                    if existing_event:
                                        if (existing_event.student_group.id == mutant_event.student_group.id or
                                            existing_event.faculty_id == mutant_event.faculty_id):
                                            is_safe_to_swap = False
                                            break
                        
                        if is_safe_to_swap:
                            # Finally, enforce full feasibility in the destination slot.
                            if self._can_place_event_id(trial_vector, r, t, mutant_gene, ignore_event_ids={target_gene} if target_gene is not None else None):
                                trial_vector[r, t] = mutant_gene
                            
        return trial_vector

    def evaluate_fitness(self, chromosome):
        """Evaluate fitness using cached results"""
        chromosome_key = str(chromosome.tobytes())
        if chromosome_key in self.fitness_cache:
            return self.fitness_cache[chromosome_key]
        
        # Use the centralized Constraints class for consistent evaluation
        fitness = self.constraints.evaluate_fitness(chromosome)
        
        # Cache management: prevent unlimited growth
        if len(self.fitness_cache) > 1000:
            keys_to_remove = list(self.fitness_cache.keys())[:-500]
            for key in keys_to_remove:
                del self.fitness_cache[key]
        
        # Cache the result
        self.fitness_cache[chromosome_key] = fitness
        return fitness

    def select(self, target_idx, trial_vector):
        """Selection operation with hard constraint prioritization"""
        trial_violations = self.constraints.get_constraint_violations(trial_vector)
        target_violations = self.constraints.get_constraint_violations(self.population[target_idx])

        hard_constraints = self._hard_constraint_keys()

        trial_hard_violations = sum(trial_violations.get(c, 0) for c in hard_constraints)
        target_hard_violations = sum(target_violations.get(c, 0) for c in hard_constraints)

        accept = False
        if trial_hard_violations < target_hard_violations:
            accept = True
        elif trial_hard_violations == target_hard_violations:
            if trial_violations.get('total', float('inf')) <= target_violations.get('total', float('inf')):
                accept = True

        if accept:
            self.population[target_idx] = trial_vector

    def run(self, max_generations):
        """Run the differential evolution algorithm"""
        fitness_history = []
        best_solution = self.population[0]
        diversity_history = []

        hard_constraints = self._hard_constraint_keys()

        def hard_violation_sum(violations: dict) -> float:
            return float(sum(violations.get(c, 0) for c in hard_constraints))
        
        # Calculate initial fitness and find best solution
        initial_fitness = [self.evaluate_fitness(ind) for ind in self.population]
        best_idx = np.argmin(initial_fitness)
        best_solution = self.population[best_idx].copy()
        best_fitness = initial_fitness[best_idx]
        
        # Track fitness for early convergence detection
        stagnation_counter = 0

        for generation in range(max_generations):
            generation_improved = False
            
            for i in range(self.pop_size):
                old_vector = self.population[i].copy()
                old_violations = self.constraints.get_constraint_violations(old_vector)
                old_hard = hard_violation_sum(old_violations)
                old_total = old_violations.get('total', float('inf'))

                # Step 1: Mutation
                mutant_vector = self.mutate(i)
                
                # Step 2: Crossover
                target_vector = self.population[i]
                trial_vector = self.crossover(target_vector, mutant_vector)
                
                # Step 3: Evaluation and Selection
                self.select(i, trial_vector)
                
                # Ensure population member has all events after selection
                candidate = self.verify_and_repair_course_allocations(self.population[i])

                # Accept repaired candidate only if it doesn't worsen hard feasibility,
                # or if it improves total score at equal hard-feasibility.
                cand_violations = self.constraints.get_constraint_violations(candidate)
                cand_hard = hard_violation_sum(cand_violations)
                cand_total = cand_violations.get('total', float('inf'))

                keep_candidate = False
                if cand_hard < old_hard:
                    keep_candidate = True
                elif cand_hard == old_hard and cand_total <= old_total:
                    keep_candidate = True

                if keep_candidate:
                    self.population[i] = candidate
                    if cand_total < old_total:
                        generation_improved = True
                else:
                    self.population[i] = old_vector
                
            # Find best solution more efficiently
            current_fitness = [self.evaluate_fitness(ind) for ind in self.population]
            current_best_idx = np.argmin(current_fitness)
            current_best_fitness = current_fitness[current_best_idx]
            
            if current_best_fitness < best_fitness:
                best_solution = self.population[current_best_idx].copy()
                best_fitness = current_best_fitness
                stagnation_counter = 0
                
                # Ensure best solution has all courses properly allocated
                best_solution = self.verify_and_repair_course_allocations(best_solution)
            else:
                stagnation_counter += 1
            
            fitness_history.append(best_fitness)

            # Elitism: keep the global best inside the population to prevent regression.
            worst_idx = int(np.argmax(current_fitness))
            self.population[worst_idx] = best_solution.copy()

            # Calculate diversity less frequently for speed
            if generation % 20 == 0:
                population_diversity = self.calculate_population_diversity()
                diversity_history.append(population_diversity)

            print(f"Best solution for generation {generation+1}/{max_generations} has a fitness of: {best_fitness}")

            if best_fitness == self.desired_fitness:
                print(f"Solution with desired fitness of {self.desired_fitness} found at Generation {generation}!")
                break

            # NOTE: Do not early-terminate purely on stagnation.
            # Perfect fitness (0) can require long runs, especially when repairs are active.

        # Final verification and repair of the best solution
        best_solution = self.verify_and_repair_course_allocations(best_solution)

        # Post-algorithm repairs (best-effort, never drop events). Keep them only if they don't worsen fitness.
        best_before_repairs = best_solution.copy()
        best_before_repairs_fitness = self.evaluate_fitness(best_before_repairs)

        repaired = best_solution.copy()
        repaired = self.reduce_extremely_late_classes(repaired, max_total=10, max_per_group=1)
        repaired = self.reduce_lecturer_clashes(repaired, max_passes=5)
        repaired = self.reduce_full_time_lecturer_workload_violations(repaired, max_passes=6)
        repaired = self.verify_and_repair_course_allocations(repaired)

        repaired = self.repair_multi_hour_blocks(repaired, max_passes=2)
        repaired = self.reduce_full_time_lecturer_workload_violations(repaired, max_passes=4)
        repaired = self.verify_and_repair_course_allocations(repaired)

        repaired_fitness = self.evaluate_fitness(repaired)
        if repaired_fitness <= best_before_repairs_fitness:
            best_solution = repaired
        
        return best_solution, fitness_history, generation, diversity_history

    def repair_multi_hour_blocks(self, chromosome, max_passes: int = 2):
        """Best-effort repair to reduce consecutive-slot and room inconsistency violations.

        Targets:
        - 2-credit courses: MUST be scheduled as a 2-hour consecutive block (same day, same room).
        - 3-credit courses: MUST have at least one 2-hour consecutive block.

        Never introduces student-group or lecturer clashes.
        """
        hours = self.input_data.hours
        n_rooms = len(self.rooms)
        n_timeslots = len(self.timeslots)

        # Map (group_id, course_id) -> list[event_id]
        events_by_group_course = {}
        for event_id, ev in enumerate(self.events_list):
            try:
                sg_id = ev.student_group.id
            except Exception:
                continue
            events_by_group_course.setdefault((sg_id, ev.course_id), []).append(event_id)

        # Fast list of suitable rooms per room type
        rooms_by_type = {}
        for r_idx, room in enumerate(self.rooms):
            rooms_by_type.setdefault(getattr(room, 'room_type', None), []).append(r_idx)

        def find_positions(event_ids: list[int]):
            pos = {}
            for r in range(n_rooms):
                for t in range(n_timeslots):
                    eid = chromosome[r][t]
                    if eid in event_ids:
                        pos[eid] = (r, t)
            return pos

        def sg_free_excluding(sg_id, t_idx, ignore_ids: set[int]) -> bool:
            for r in range(n_rooms):
                eid = chromosome[r][t_idx]
                if eid is None or eid in ignore_ids:
                    continue
                ev = self.events_map.get(eid)
                if ev and ev.student_group and ev.student_group.id == sg_id:
                    return False
            return True

        def lec_free_excluding(faculty_id, t_idx, ignore_ids: set[int]) -> bool:
            if faculty_id is None:
                return True
            for r in range(n_rooms):
                eid = chromosome[r][t_idx]
                if eid is None or eid in ignore_ids:
                    continue
                ev = self.events_map.get(eid)
                if ev and ev.faculty_id == faculty_id:
                    return False
            return True

        def slot_ok_for_event(room_idx: int, t_idx: int, ev, ignore_ids: set[int]) -> bool:
            existing = chromosome[room_idx][t_idx]
            if existing is not None and existing not in ignore_ids:
                return False

            # Temporarily clear the cell so is_slot_available_for_event can run its own checks.
            chromosome[room_idx][t_idx] = None
            try:
                return self.is_slot_available_for_event(chromosome, room_idx, t_idx, ev)
            finally:
                chromosome[room_idx][t_idx] = existing

        for _ in range(max_passes):
            changed_any = False

            for (sg_id, course_id), event_ids in events_by_group_course.items():
                course = self.input_data.getCourse(course_id)
                if not course:
                    continue
                credits = getattr(course, 'credits', 0) or 0
                if credits not in (2, 3):
                    continue

                # Ensure all events exist; if missing, let verify_and_repair handle it.
                positions = find_positions(event_ids)
                if len(positions) < min(len(event_ids), credits):
                    continue

                # Collect currently scheduled timeslots
                placed = sorted([(eid, positions[eid][0], positions[eid][1]) for eid in positions], key=lambda x: x[2])
                placed_t = [t for _, _, t in placed]

                def has_consecutive_pair_same_room() -> bool:
                    for i in range(len(placed) - 1):
                        _, r1, t1 = placed[i]
                        _, r2, t2 = placed[i + 1]
                        if (t2 - t1) == 1 and (t1 // hours) == (t2 // hours) and r1 == r2:
                            return True
                    return False

                # 2-credit: need exactly a consecutive pair (same room)
                if credits == 2:
                    if len(placed) >= 2:
                        eid_a, _, _ = placed[0]
                        eid_b, _, _ = placed[1]
                        r_a, t_a = positions[eid_a]
                        r_b, t_b = positions[eid_b]
                        if (abs(t_b - t_a) == 1) and (t_a // hours) == (t_b // hours) and r_a == r_b:
                            continue

                        # Try to re-place as a 2-hour block
                        ignore_ids = {eid_a, eid_b}
                        ev_a = self.events_map.get(eid_a)
                        ev_b = self.events_map.get(eid_b)
                        if not ev_a or not ev_b:
                            continue

                        suitable_rooms = rooms_by_type.get(getattr(course, 'required_room_type', None), [])
                        if not suitable_rooms:
                            continue

                        found = None
                        rooms_order = suitable_rooms[:]
                        random.shuffle(rooms_order)
                        for day in range(self.input_data.days):
                            day_start = day * hours
                            for room_idx in rooms_order:
                                for h in range(0, hours - 1):
                                    t1 = day_start + h
                                    t2 = t1 + 1
                                    if t2 >= n_timeslots:
                                        continue

                                    if not sg_free_excluding(sg_id, t1, ignore_ids) or not sg_free_excluding(sg_id, t2, ignore_ids):
                                        continue
                                    if not lec_free_excluding(ev_a.faculty_id, t1, ignore_ids) or not lec_free_excluding(ev_b.faculty_id, t2, ignore_ids):
                                        continue
                                    if not slot_ok_for_event(room_idx, t1, ev_a, ignore_ids):
                                        continue
                                    if not slot_ok_for_event(room_idx, t2, ev_b, ignore_ids):
                                        continue

                                    found = (room_idx, t1)
                                    break
                                if found:
                                    break
                            if found:
                                break

                        if found:
                            # Clear old positions then place new
                            chromosome[positions[eid_a][0]][positions[eid_a][1]] = None
                            chromosome[positions[eid_b][0]][positions[eid_b][1]] = None
                            room_idx, t1 = found
                            chromosome[room_idx][t1] = eid_a
                            chromosome[room_idx][t1 + 1] = eid_b
                            changed_any = True
                    continue

                # 3-credit: ensure at least one consecutive pair exists
                if credits == 3:
                    if has_consecutive_pair_same_room():
                        continue

                    # Take any two events and make them consecutive
                    if len(placed) < 2:
                        continue
                    eid_a = placed[0][0]
                    eid_b = placed[1][0]
                    ignore_ids = {eid_a, eid_b}
                    ev_a = self.events_map.get(eid_a)
                    ev_b = self.events_map.get(eid_b)
                    if not ev_a or not ev_b:
                        continue

                    suitable_rooms = rooms_by_type.get(getattr(course, 'required_room_type', None), [])
                    if not suitable_rooms:
                        continue

                    found = None
                    rooms_order = suitable_rooms[:]
                    random.shuffle(rooms_order)
                    for day in range(self.input_data.days):
                        day_start = day * hours
                        for room_idx in rooms_order:
                            for h in range(0, hours - 1):
                                t1 = day_start + h
                                t2 = t1 + 1
                                if t2 >= n_timeslots:
                                    continue

                                if not sg_free_excluding(sg_id, t1, ignore_ids) or not sg_free_excluding(sg_id, t2, ignore_ids):
                                    continue
                                if not lec_free_excluding(ev_a.faculty_id, t1, ignore_ids) or not lec_free_excluding(ev_b.faculty_id, t2, ignore_ids):
                                    continue
                                if not slot_ok_for_event(room_idx, t1, ev_a, ignore_ids):
                                    continue
                                if not slot_ok_for_event(room_idx, t2, ev_b, ignore_ids):
                                    continue

                                found = (room_idx, t1)
                                break
                            if found:
                                break
                        if found:
                            break

                    if found:
                        chromosome[positions[eid_a][0]][positions[eid_a][1]] = None
                        chromosome[positions[eid_b][0]][positions[eid_b][1]] = None
                        room_idx, t1 = found
                        chromosome[room_idx][t1] = eid_a
                        chromosome[room_idx][t1 + 1] = eid_b
                        changed_any = True

            if not changed_any:
                break

        return chromosome

    def reduce_extremely_late_classes(self, chromosome, max_total=10, max_per_group=1):
        """Post-processing repair to reduce 17:00 allocations (best effort).

        Tries to MOVE events out of the last hour into earlier empty slots while respecting:
        - break-time rules
        - room suitability
        - lecturer availability window
        - no student-group overlap
        - no lecturer overlap

        Leaves events in place if no valid destination exists.
        """
        hours = self.input_data.hours
        last_hour_index = hours - 1
        days = self.input_data.days

        late_cells = []  # list[(room_idx, timeslot_idx, event_id, event, sg_id)]
        late_by_group = {}

        for day in range(days):
            t_idx = day * hours + last_hour_index
            if t_idx >= len(self.timeslots):
                continue
            for r_idx in range(len(self.rooms)):
                event_id = chromosome[r_idx][t_idx]
                if event_id is None:
                    continue
                event = self.events_map.get(event_id)
                if not event or not event.student_group:
                    continue
                sg_id = event.student_group.id
                late_cells.append((r_idx, t_idx, event_id, event, sg_id))
                late_by_group[sg_id] = late_by_group.get(sg_id, 0) + 1

        def should_move(sg_id: str, total_late: int) -> bool:
            if late_by_group.get(sg_id, 0) > max_per_group:
                return True
            return total_late > max_total

        total_late = len(late_cells)
        if total_late == 0:
            return chromosome

        # Always try to reduce late classes as much as possible.
        # We prioritize cap violations first, but continue trying to move remaining late classes too.
        changed = True
        while changed:
            changed = False
            total_late = len(late_cells)

            # Prioritize moving groups that exceed per-group cap or global cap, then try others.
            def _prio(cell):
                _sg = cell[4]
                return (
                    0 if should_move(_sg, total_late) else 1,
                    -late_by_group.get(_sg, 0)
                )

            late_cells.sort(key=_prio)

            for (src_r, src_t, event_id, event, sg_id) in list(late_cells):

                course = self.input_data.getCourse(event.course_id)

                # Prefer moving earlier within the same day
                day = src_t // hours
                day_start = day * hours
                candidate_t_idxs = [day_start + h for h in range(0, last_hour_index) if (day_start + h) < len(self.timeslots)]

                moved = False

                # Try same room first, then other rooms
                room_order = [src_r] + [r for r in range(len(self.rooms)) if r != src_r]
                for dst_r in room_order:
                    room_obj = self.rooms[dst_r]
                    if not self.is_room_suitable(room_obj, course):
                        continue
                    for dst_t in candidate_t_idxs:
                        if not self.is_slot_available_for_event(chromosome, dst_r, dst_t, event):
                            continue
                        if not self._is_student_group_available(chromosome, sg_id, dst_t):
                            continue
                        if event.faculty_id and not self._is_lecturer_available(chromosome, event.faculty_id, dst_t):
                            continue

                        chromosome[src_r][src_t] = None
                        chromosome[dst_r][dst_t] = event_id
                        moved = True
                        break
                    if moved:
                        break

                if moved:
                    # update tracking
                    late_by_group[sg_id] = max(0, late_by_group.get(sg_id, 0) - 1)
                    late_cells.remove((src_r, src_t, event_id, event, sg_id))
                    changed = True
                    break

        return chromosome

    def reduce_lecturer_clashes(self, chromosome, max_passes=5):
        """Post-processing repair to reduce lecturer overlaps (best effort).

        For each timeslot where the same lecturer appears more than once across rooms,
        tries to move the extra events into safe empty slots.
        """
        hours = self.input_data.hours
        last_hour_index = hours - 1

        for _pass in range(max_passes):
            moved_any = False

            for t_idx in range(len(self.timeslots)):
                faculty_to_cells = {}
                for r_idx in range(len(self.rooms)):
                    event_id = chromosome[r_idx][t_idx]
                    if event_id is None:
                        continue
                    event = self.events_map.get(event_id)
                    if not event or not event.faculty_id:
                        continue
                    faculty_to_cells.setdefault(event.faculty_id, []).append((r_idx, event_id, event))

                for faculty_id, cells in faculty_to_cells.items():
                    if len(cells) <= 1:
                        continue

                    # Keep the first; relocate the rest
                    for (src_r, event_id, event) in cells[1:]:
                        course = self.input_data.getCourse(event.course_id)
                        sg_id = event.student_group.id if event.student_group else None
                        if sg_id is None:
                            continue

                        # Prefer same room, then any other suitable room
                        room_order = [src_r] + [r for r in range(len(self.rooms)) if r != src_r]

                        found = False
                        for dst_r in room_order:
                            room_obj = self.rooms[dst_r]
                            if not self.is_room_suitable(room_obj, course):
                                continue

                            for dst_t in range(len(self.timeslots)):
                                # Avoid creating new 17:00 placements if possible
                                if (dst_t % hours) == last_hour_index:
                                    continue

                                if not self.is_slot_available_for_event(chromosome, dst_r, dst_t, event):
                                    continue
                                if not self._is_student_group_available(chromosome, sg_id, dst_t):
                                    continue
                                if not self._is_lecturer_available(chromosome, faculty_id, dst_t):
                                    continue

                                chromosome[src_r][t_idx] = None
                                chromosome[dst_r][dst_t] = event_id
                                moved_any = True
                                found = True
                                break
                            if found:
                                break

            if not moved_any:
                break

        return chromosome

    @staticmethod
    def _is_full_time_faculty(faculty) -> bool:
        try:
            status = str(getattr(faculty, 'status', '') or '').strip().lower()
        except Exception:
            status = ''
        return any(token in status for token in ('full time', 'full-time', 'fulltime', 'full'))

    def reduce_full_time_lecturer_workload_violations(self, chromosome, max_passes=6):
        """Move overloaded full-time lecturers' classes to other available days/times when possible."""
        hours = int(self.input_data.hours)
        days = int(self.input_data.days)
        last_hour_index = hours - 1

        def _day_of(t_idx: int) -> int:
            return t_idx // hours

        def _hour_of(t_idx: int) -> int:
            return t_idx % hours

        def _faculty_loads():
            loads = {}
            placements = {}
            for r_idx in range(len(self.rooms)):
                for t_idx in range(len(self.timeslots)):
                    event_id = chromosome[r_idx][t_idx]
                    if event_id is None:
                        continue
                    event = self.events_map.get(event_id)
                    if not event or not event.faculty_id:
                        continue
                    faculty = self.input_data.getFaculty(event.faculty_id)
                    if not faculty or not self._is_full_time_faculty(faculty):
                        continue
                    day_idx = _day_of(t_idx)
                    loads.setdefault(event.faculty_id, [0] * days)[day_idx] += 1
                    placements.setdefault(event.faculty_id, []).append((r_idx, t_idx, event_id, event, faculty))
            return loads, placements

        def _day_capacity(faculty, day_idx: int, event) -> bool:
            day_abbr = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'][day_idx] if day_idx < 5 else ''
            try:
                if not self._is_faculty_available_day(faculty, day_abbr):
                    return False
            except Exception:
                pass
            try:
                slot_hour = 8.5 + _hour_of(0)
            except Exception:
                slot_hour = 8.5
            return True

        for _pass in range(max_passes):
            loads, placements = _faculty_loads()
            if not loads:
                break

            moved_any = False
            for faculty_id, day_loads in loads.items():
                faculty = self.input_data.getFaculty(faculty_id)
                if not faculty or not self._is_full_time_faculty(faculty):
                    continue

                try:
                    max_hours_per_day = int(getattr(faculty, 'available_hours', 4) or 4)
                    max_consecutive_allowed = int(getattr(faculty, 'available_consecutive_hours', 3) or 3)
                except Exception:
                    max_hours_per_day = 4
                    max_consecutive_allowed = 3
                max_hours_per_day = max(2, min(8, max_hours_per_day))
                max_consecutive_allowed = max(2, min(8, max_consecutive_allowed))

                overloaded_days = [d for d, count in enumerate(day_loads) if count > max_hours_per_day]
                if not overloaded_days:
                    continue

                for src_day in overloaded_days:
                    candidate_events = [p for p in placements.get(faculty_id, []) if _day_of(p[1]) == src_day]
                    candidate_events.sort(key=lambda p: (_hour_of(p[1]) == last_hour_index, -_hour_of(p[1])))

                    for src_r, src_t, event_id, event, faculty_obj in candidate_events:
                        course = self.input_data.getCourse(event.course_id)
                        if course is None:
                            continue

                        # Choose another day with the lowest current load that is still available.
                        target_days = list(range(days))
                        target_days.sort(key=lambda d: day_loads[d])
                        moved = False
                        for dst_day in target_days:
                            if dst_day == src_day:
                                continue

                            if not self._is_faculty_available_day(faculty_obj, ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'][dst_day] if dst_day < 5 else ''):
                                continue

                            # Prefer any available slot on the target day, excluding 17:00 if possible.
                            slots = list(range(dst_day * hours, (dst_day + 1) * hours))
                            slots.sort(key=lambda t: (_hour_of(t) == last_hour_index, _hour_of(t)))

                            for dst_t in slots:
                                if dst_t == src_t:
                                    continue
                                if _hour_of(dst_t) == last_hour_index:
                                    # allow as last resort, but keep it later in the ordering
                                    pass
                                if not self._is_faculty_available_time(faculty_obj, 8.5 + _hour_of(dst_t), ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'][dst_day] if dst_day < 5 else ''):
                                    continue

                                for dst_r in range(len(self.rooms)):
                                    if not self.is_room_suitable(self.rooms[dst_r], course):
                                        continue
                                    if chromosome[dst_r][dst_t] is not None:
                                        continue

                                    chromosome[src_r][src_t] = None
                                    if self._can_place_event_id(chromosome, dst_r, dst_t, event_id):
                                        chromosome[dst_r][dst_t] = event_id
                                        moved_any = True
                                        moved = True
                                        break
                                    chromosome[src_r][src_t] = event_id
                                    chromosome[dst_r][dst_t] = None
                                if moved:
                                    break
                            if moved:
                                break
                        if moved:
                            break
                    if moved_any:
                        break
                if moved_any:
                    break

            if not moved_any:
                break

        return chromosome

    def print_timetable(self, individual, student_group, days, hours_per_day, day_start_time=8.5):
        """Print timetable for a specific student group"""
        timetable = [["" for _ in range(days)] for _ in range(hours_per_day)]
        
        # First, fill break time slots on Mon, Wed, Fri
        break_hour = 4
        if break_hour < hours_per_day:
            for day in range(days):
                if day in [0, 2, 4]:  # Monday, Wednesday, Friday
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
                        course = self.input_data.getCourse(class_event.course_id)
                        faculty = self.input_data.getFaculty(class_event.faculty_id)
                        course_code = course.code if course is not None else "Unknown"
                        faculty_name = faculty.name if faculty is not None else "Unknown"
                        room_obj = self.input_data.rooms[room_idx]
                        room_display = getattr(room_obj, "name", getattr(room_obj, "Id", str(room_idx)))
                        timetable[hour][day] = f"Course: {course_code}, Lecturer: {faculty_name}, Room: {room_display}"
        return timetable

    def print_all_timetables(self, individual, days, hours_per_day, day_start_time=8.5):
        """Generate all timetables for the solution"""
        def _format_time_label(hour_value) -> str:
            try:
                total_minutes = int(round(float(hour_value) * 60))
                hh = (total_minutes // 60) % 24
                mm = total_minutes % 60
                return f"{hh:02d}:{mm:02d}"
            except Exception:
                return str(hour_value)

        data = []
        student_groups = self.input_data.student_groups
        
        for student_group in student_groups:
            timetable = self.print_timetable(individual, student_group, days, hours_per_day, day_start_time)
            rows = []
            for hour in range(hours_per_day):
                time_label = _format_time_label(float(day_start_time) + float(hour))
                row = [time_label] + [timetable[hour][day] for day in range(days)]
                rows.append(row)
            data.append({"student_group": student_group, "timetable": rows})
        return data

    def verify_and_repair_course_allocations(self, chromosome):
        """
        Verify that all courses appear the correct number of times for each student group
        and repair any missing allocations with minimal disruption.
        """
        max_repair_passes = 6

        n_rooms = len(self.rooms)
        n_timeslots = len(self.timeslots)
        total_events = len(self.events_list)

        # Helper: build a fast lookup of suitable rooms for a given required room type.
        rooms_by_type = {}
        for r_idx, room in enumerate(self.rooms):
            rooms_by_type.setdefault(getattr(room, 'room_type', None), []).append(r_idx)

        for _ in range(max_repair_passes):
            # 1) Remove duplicate placements of the *same event*.
            # Duplicates can fully occupy the timetable, leaving no empty slots for genuinely missing events.
            scheduled_events = set()
            student_group_busy = [set() for _ in range(n_timeslots)]
            lecturer_busy = [set() for _ in range(n_timeslots)]
            course_day_room_mapping = {}  # (course_id, day_idx, student_group_id) -> room_idx

            for r_idx in range(n_rooms):
                for t_idx in range(n_timeslots):
                    event_id = chromosome[r_idx][t_idx]
                    if event_id is None:
                        continue
                    if event_id in scheduled_events:
                        chromosome[r_idx][t_idx] = None
                        continue

                    scheduled_events.add(event_id)
                    event = self.events_map.get(event_id)
                    if not event:
                        continue

                    sg_id = event.student_group.id
                    student_group_busy[t_idx].add(sg_id)
                    if event.faculty_id is not None:
                        lecturer_busy[t_idx].add(event.faculty_id)

                    day_idx = t_idx // self.input_data.hours
                    course_day_room_mapping[(event.course_id, day_idx, sg_id)] = r_idx

            missing_events = [event_id for event_id in range(total_events) if event_id not in scheduled_events]
            if not missing_events:
                break

            # 2) Index empty slots to speed up placement.
            empty_by_room_day = {}  # (room_idx, day_idx) -> list[t_idx]
            for r_idx in range(n_rooms):
                for t_idx in range(n_timeslots):
                    if chromosome[r_idx][t_idx] is None:
                        day_idx = t_idx // self.input_data.hours
                        empty_by_room_day.setdefault((r_idx, day_idx), []).append(t_idx)

            random.shuffle(missing_events)

            for missing_event_id in missing_events:
                event = self.events_list[missing_event_id]
                course = self.input_data.getCourse(event.course_id)
                if not course:
                    continue

                required_type = getattr(course, 'required_room_type', None)
                suitable_rooms = rooms_by_type.get(required_type, [])
                if not suitable_rooms:
                    continue

                sg_id = event.student_group.id
                faculty_id = event.faculty_id
                placed = False

                def slot_ok(room_idx: int, timeslot_idx: int, *, relax_faculty: bool = False) -> bool:
                    if sg_id in student_group_busy[timeslot_idx]:
                        return False
                    if faculty_id is not None and faculty_id in lecturer_busy[timeslot_idx]:
                        return False
                    return self.is_slot_available_for_event(
                        chromosome,
                        room_idx,
                        timeslot_idx,
                        event,
                        ignore_faculty_availability=relax_faculty,
                    )

                # Strategy 1: Prefer same room as the same course for this group on that day.
                days_order = list(range(self.input_data.days))
                random.shuffle(days_order)
                for day_idx in days_order:
                    preferred_room = course_day_room_mapping.get((event.course_id, day_idx, sg_id))
                    if preferred_room is None:
                        continue
                    if preferred_room not in suitable_rooms:
                        continue
                    for t_idx in list(empty_by_room_day.get((preferred_room, day_idx), [])):
                        if slot_ok(preferred_room, t_idx):
                            chromosome[preferred_room][t_idx] = missing_event_id
                            student_group_busy[t_idx].add(sg_id)
                            if faculty_id is not None:
                                lecturer_busy[t_idx].add(faculty_id)
                            scheduled_events.add(missing_event_id)
                            empty_by_room_day[(preferred_room, day_idx)].remove(t_idx)
                            course_day_room_mapping[(event.course_id, day_idx, sg_id)] = preferred_room
                            placed = True
                            break
                    if placed:
                        break

                # Strategy 2: Any suitable room/day empty slot.
                if not placed:
                    rooms_order = suitable_rooms[:]
                    random.shuffle(rooms_order)
                    for room_idx in rooms_order:
                        days_order = list(range(self.input_data.days))
                        random.shuffle(days_order)
                        for day_idx in days_order:
                            key = (room_idx, day_idx)
                            if key not in empty_by_room_day:
                                continue
                            for t_idx in list(empty_by_room_day[key]):
                                if slot_ok(room_idx, t_idx):
                                    chromosome[room_idx][t_idx] = missing_event_id
                                    student_group_busy[t_idx].add(sg_id)
                                    if faculty_id is not None:
                                        lecturer_busy[t_idx].add(faculty_id)
                                    scheduled_events.add(missing_event_id)
                                    empty_by_room_day[key].remove(t_idx)
                                    course_day_room_mapping[(event.course_id, day_idx, sg_id)] = room_idx
                                    placed = True
                                    break
                            if placed:
                                break
                        if placed:
                            break

                # If we still can't place it, leave it missing for this pass; a later pass
                # may open up additional empty slots after more duplicate removals.

                # Strategy 3 (last resort): relax lecturer availability windows so we never drop classes.
                if not placed:
                    rooms_order = suitable_rooms[:]
                    random.shuffle(rooms_order)
                    for room_idx in rooms_order:
                        days_order = list(range(self.input_data.days))
                        random.shuffle(days_order)
                        for day_idx in days_order:
                            key = (room_idx, day_idx)
                            if key not in empty_by_room_day:
                                continue
                            for t_idx in list(empty_by_room_day[key]):
                                if slot_ok(room_idx, t_idx, relax_faculty=True):
                                    chromosome[room_idx][t_idx] = missing_event_id
                                    student_group_busy[t_idx].add(sg_id)
                                    if faculty_id is not None:
                                        lecturer_busy[t_idx].add(faculty_id)
                                    scheduled_events.add(missing_event_id)
                                    empty_by_room_day[key].remove(t_idx)
                                    course_day_room_mapping[(event.course_id, day_idx, sg_id)] = room_idx
                                    placed = True
                                    break
                            if placed:
                                break
                        if placed:
                            break

        return chromosome

    def count_course_occurrences(self, chromosome, student_group):
        """Count how many times each course appears for a specific student group"""
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
        """Diagnostic method to check course allocations for debugging"""
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
            
            total_expected = sum(student_group.hours_required)
            total_actual = sum(course_counts.values())
            
            print(f"  Total hours: Expected {total_expected}, Got {total_actual}")
            
            for i, course_id in enumerate(student_group.courseIDs):
                expected = student_group.hours_required[i]
                actual = course_counts.get(course_id, 0)
                status = "✓" if actual == expected else "✗"
                print(f"  {course_id}: Expected {expected}, Got {actual} {status}")
        
        print("=== END DIAGNOSIS ===\n")