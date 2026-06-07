import json
import re

def load_data():
    with open('data/faculty-data.json', 'r', encoding='utf-8') as f:
        faculty_data = json.load(f)
    try:
        with open('data/fresh_timetable_data.json', 'r', encoding='utf-8') as f:
            timetable_data = json.load(f)
    except FileNotFoundError:
        print("fresh_timetable_data.json not found.")
        return [], []
    return faculty_data, timetable_data

def parse_time(time_str):
    # expect "9:00", "10:00" etc.
    return time_str.split(':')[0]

def verify_schedule():
    faculty_list, timetable_list = load_data()
    
    # Map Name -> Faculty Object
    faculty_map = {}
    for f in faculty_list:
        faculty_map[f['name']] = f
        # Also map ID just in case
        faculty_map[f['id']] = f

    print(f"Loaded {len(faculty_list)} faculty members.")
    print(f"Loaded {len(timetable_list)} student groups.")

    days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    
    # Store schedule for workload check
    # { lecturer_name: { day_idx: [hour_int, ...] } }
    lecturer_schedule = {}

    schedule_violations = []

    for group in timetable_list:
        timetable = group['timetable']
        for row in timetable:
            time_str = row[0]
            if time_str == "Time" or time_str == "BREAK": 
                continue
                
            hour_str = time_str.split(':')[0]
            try:
                hour = int(hour_str)
            except ValueError:
                continue # Skip weird rows

            # columns 1-5 correspond to Mon-Fri
            for day_idx, cell_content in enumerate(row[1:]):
                if not cell_content or cell_content == "BREAK":
                    continue
                
                # Cell format: "Course\nRoom\nLecturer"
                parts = cell_content.split('\n')
                if len(parts) >= 3:
                    lecturer_name = parts[2].strip()
                    
                    # Sometimes lecturer name might be an email or slightly different
                    # We try to find them in faculty_map
                    faculty = faculty_map.get(lecturer_name)
                    
                    if not faculty:
                        # Try to find by partial match or assume it's valid if email format?
                        # For now, just print warning if not found
                        # print(f"Warning: Lecturer '{lecturer_name}' not found in faculty data.")
                        pass
                    
                    # Record for workload
                    if lecturer_name not in lecturer_schedule:
                        lecturer_schedule[lecturer_name] = {}
                    if day_idx not in lecturer_schedule[lecturer_name]:
                        lecturer_schedule[lecturer_name][day_idx] = []
                    
                    lecturer_schedule[lecturer_name][day_idx].append(hour)

                    if faculty:
                        # Check Availability
                        avail_days = faculty.get('avail_days')
                        if not avail_days: # None or []
                             avail_days = ['ALL']
                        
                        avail_times = faculty.get('avail_times')
                        if not avail_times: # None or []
                             avail_times = ['ALL']

                        # Check Day
                        is_day_available = False
                        if isinstance(avail_days, str):
                            if avail_days.upper() == 'ALL':
                                is_day_available = True
                            else:
                                if days[day_idx] in [d.strip() for d in avail_days.split(',')]:
                                    is_day_available = True
                        elif isinstance(avail_days, list):
                            if 'ALL' in [d.upper() for d in avail_days]:
                                is_day_available = True
                            elif days[day_idx] in avail_days:
                                is_day_available = True
                        
                        if not is_day_available:
                            schedule_violations.append(
                                f"VIOLATION: {lecturer_name} scheduled on {days[day_idx]} ({time_str}) but only available on {avail_days}"
                            )

                        # Check Time
                        # Parsing "HH:MM-HH:MM" e.g. "09:00-12:00"
                        # This is more complex if ranges are strictly checked against single hour blocks
                        # For now, let's assume if it's not ALL, we check range
                        is_time_available = False
                        if isinstance(avail_times, str) and avail_times.upper() == 'ALL':
                            is_time_available = True
                        elif isinstance(avail_times, list) and 'ALL' in [t.upper() for t in avail_times]:
                            is_time_available = True
                        else:
                            # It's a specific time range string or list of strings
                            available_ranges = []
                            if isinstance(avail_times, str):
                                available_ranges = [avail_times]
                            else:
                                available_ranges = avail_times
                            
                            current_hour = int(hour)
                            
                            # Check if current_hour matches any range
                            # Range format "09:00-12:00"
                            for rng in available_ranges:
                                try:
                                    start_s, end_s = rng.split('-')
                                    start_h = int(start_s.split(':')[0])
                                    end_h = int(end_s.split(':')[0])
                                    
                                    if start_h <= current_hour < end_h:
                                        is_time_available = True
                                        break
                                except:
                                    pass # parsing error

                        if not is_time_available and avail_times != ['ALL']: 
                             schedule_violations.append(
                                f"VIOLATION: {lecturer_name} scheduled at {time_str} but only available at {avail_times}"
                            )

    print("\n--- Schedule Availability Verification ---")
    if len(schedule_violations) == 0:
        print("✅ No lecturer schedule availability violations found.")
    else:
        print(f"❌ Found {len(schedule_violations)} schedule violations:")
        for v in schedule_violations[:20]: # Show first 20
            print(v)
        if len(schedule_violations) > 20:
            print(f"... and {len(schedule_violations) - 20} more.")

    print("\n--- Workload Verification ---")
    workload_violations = []
    
    for lecturer, days_data in lecturer_schedule.items():
        for day_idx, hours in days_data.items():
            # 1. Check Max Daily Hours > 6
            unique_hours = sorted(list(set(hours)))
            if len(unique_hours) > 6:
                workload_violations.append(
                    f"Workload (Daily): {lecturer} has {len(unique_hours)} hours on {days[day_idx]}"
                )

            # 2. Check Consecutive Hours > 3
            if len(unique_hours) >= 4:
                consecutive = 1
                max_consecutive = 1
                for i in range(1, len(unique_hours)):
                    if unique_hours[i] == unique_hours[i-1] + 1:
                        consecutive += 1
                        max_consecutive = max(max_consecutive, consecutive)
                    else:
                        consecutive = 1
                
                if max_consecutive > 3:
                     workload_violations.append(
                        f"Workload (Consecutive): {lecturer} has {max_consecutive} consecutive hours on {days[day_idx]}"
                    )

    if len(workload_violations) == 0:
         print("✅ No lecturer workload violations found.")
    else:
         print(f"❌ Found {len(workload_violations)} workload violations:")
         for v in sorted(workload_violations)[:20]:
             print(v)
         if len(workload_violations) > 20: 
             print(f"... and {len(workload_violations) - 20} more.")

if __name__ == "__main__":
    verify_schedule()
