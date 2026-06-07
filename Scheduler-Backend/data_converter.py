"""
FIXED Data Converter for Timetable-to-Dash Format Compatibility
"""
import json
from datetime import datetime

class TimetableDataConverter:
    """Converts timetable data between generation format and Dash format"""
    
    @staticmethod
    def convert_for_dash(timetables_raw, input_data_dict):
        """
        FIXED: Convert raw timetable data to Dash-compatible format
        """
        print("🔄 Converting timetable data for Dash compatibility...")
        
        converted_timetables = []
        
        for i, timetable in enumerate(timetables_raw):
            try:
                # FIXED: Ensure student_group is properly formatted
                student_group = timetable.get('student_group', {})
                if not isinstance(student_group, dict):
                    # Convert object to dict if needed
                    if hasattr(student_group, '__dict__'):
                        student_group = {
                            'id': getattr(student_group, 'id', i),
                            'name': getattr(student_group, 'name', f'Group {i+1}'),
                            'size': getattr(student_group, 'size', 30),
                            'department': getattr(student_group, 'department', ''),
                            'level': getattr(student_group, 'level', '')
                        }
                    else:
                        student_group = {
                            'id': i,
                            'name': str(student_group) if student_group else f'Group {i+1}',
                            'size': 30,
                            'department': '',
                            'level': ''
                        }
                
                # FIXED: Ensure timetable grid is properly formatted
                timetable_grid = timetable.get('timetable', [])
                if not isinstance(timetable_grid, list):
                    print(f"⚠️ Timetable {i} has invalid grid format, creating default grid")
                    # Create default 10x6 grid (10 hours, 6 columns: time + 5 days)
                    timetable_grid = []
                    for hour in range(10):
                        row = [f"{8+hour:02d}:30-{9+hour:02d}:30"]  # Time column
                        for day in range(5):  # 5 days
                            row.append("FREE")
                        timetable_grid.append(row)
                
                # FIXED: Format each cell in the timetable grid
                formatted_grid = []
                for row_idx, row in enumerate(timetable_grid):
                    if isinstance(row, list):
                        formatted_row = []
                        for cell_idx, cell in enumerate(row):
                            if isinstance(cell, str):
                                formatted_row.append(cell)
                            elif cell is None:
                                formatted_row.append("FREE")
                            else:
                                formatted_row.append(str(cell))
                        formatted_grid.append(formatted_row)
                    else:
                        # Handle non-list rows - create default row
                        default_row = [f"{8+row_idx:02d}:30-{9+row_idx:02d}:30"] + ["FREE"] * 5
                        formatted_grid.append(default_row)
                
                # FIXED: Ensure minimum grid size
                while len(formatted_grid) < 10:
                    hour = len(formatted_grid)
                    default_row = [f"{8+hour:02d}:30-{9+hour:02d}:30"] + ["FREE"] * 5
                    formatted_grid.append(default_row)
                
                converted_timetable = {
                    'student_group': student_group,
                    'timetable': formatted_grid,
                    'total_courses': timetable.get('total_courses', 0),
                    'total_hours_scheduled': timetable.get('total_hours_scheduled', 0),
                    'constraint_violations': timetable.get('constraint_violations', {}),
                    'fitness_score': timetable.get('fitness_score', 0)
                }
                
                converted_timetables.append(converted_timetable)
                print(f"✅ Converted timetable {i}: {student_group['name']}")
                
            except Exception as e:
                print(f"⚠️ Error converting timetable {i}: {e}")
                # Create a fallback timetable
                fallback_timetable = {
                    'student_group': {
                        'id': i,
                        'name': f'Group {i+1}',
                        'size': 30,
                        'department': '',
                        'level': ''
                    },
                    'timetable': [[f"{8+h:02d}:30-{9+h:02d}:30"] + ["FREE"] * 5 for h in range(10)],
                    'total_courses': 0,
                    'total_hours_scheduled': 0,
                    'constraint_violations': {},
                    'fitness_score': 0
                }
                converted_timetables.append(fallback_timetable)
                print(f"✅ Created fallback timetable for index {i}")
        
        print(f"✅ Converted {len(converted_timetables)} timetables for Dash")
        return converted_timetables
    
    @staticmethod
    def validate_session_data(session_data):
        """
        FIXED: Enhanced validation with better error messages
        """
        print("🔍 Validating session data structure...")
        
        if not isinstance(session_data, dict):
            return False, "Session data must be a dictionary"
        
        # Check required top-level keys
        required_top_keys = ['timetables', 'input_data', 'upload_id']
        missing_top_keys = [key for key in required_top_keys if key not in session_data]
        
        if missing_top_keys:
            print(f"❌ Missing top-level keys: {missing_top_keys}")
            return False, f"Missing required keys: {missing_top_keys}"
        
        # Validate timetables structure
        timetables = session_data['timetables']
        if not isinstance(timetables, list) or len(timetables) == 0:
            return False, "Timetables must be a non-empty list"
        
        # Validate input_data structure
        input_data = session_data['input_data']
        if not isinstance(input_data, dict):
            return False, "Input data must be a dictionary"
        
        required_input_keys = ['courses', 'rooms', 'faculties']
        missing_input_keys = [key for key in required_input_keys if key not in input_data]
        
        if missing_input_keys:
            print(f"❌ Missing input data keys: {missing_input_keys}")
            return False, f"Missing input data keys: {missing_input_keys}"
        
        # FIXED: Enhanced course validation with better error handling
        courses = input_data['courses']
        if courses and len(courses) > 0:
            sample_course = courses[0]
            required_course_keys = ['student_groupsID', 'facultyId']
            missing_course_keys = [key for key in required_course_keys if key not in sample_course]
            
            if missing_course_keys:
                print(f"❌ Missing course keys: {missing_course_keys}")
                print(f"🔍 Available course keys: {list(sample_course.keys())}")
                return False, f"Missing course keys: {missing_course_keys}"
        
        print("✅ Session data validation passed")
        return True, "Valid"
    
    @staticmethod
    def create_session_file(timetables, input_data, upload_id,constraint_details=None):
        """
        FIXED: Create a properly formatted session file for Dash
        """
        print(f"📄 Creating session file for upload {upload_id}...")
        
        # Convert timetables to Dash format
        converted_timetables = TimetableDataConverter.convert_for_dash(timetables, input_data)
        
        # Create session data
        session_data = {
            'timetables': converted_timetables,
            'input_data': input_data,
            'upload_id': upload_id,
            'constraint_details': constraint_details or {}, # MODIFIED: Include constraint details
            'created_at': datetime.now().isoformat(),
            'version': '2.0'
        }
        
        # Validate the session data
        is_valid, message = TimetableDataConverter.validate_session_data(session_data)
        
        if not is_valid:
            print(f"❌ Session validation failed: {message}")
            # Try to fix common issues automatically
            session_data = TimetableDataConverter.fix_session_data(session_data)
            
            # Re-validate
            is_valid, message = TimetableDataConverter.validate_session_data(session_data)
            if not is_valid:
                raise ValueError(f"Session data validation failed after fixes: {message}")
        
        print(f"✅ Session file created successfully for {len(converted_timetables)} timetables")
        return session_data
    
    @staticmethod
    def fix_session_data(session_data):
        """
        FIXED: Automatically fix common session data issues
        """
        print("🔧 Attempting to fix session data issues...")
        
        # Fix input_data courses if missing required fields
        if 'input_data' in session_data and 'courses' in session_data['input_data']:
            courses = session_data['input_data']['courses']
            for i, course in enumerate(courses):
                if not isinstance(course, dict):
                    continue
                
                # Fix missing student_groupsID
                if 'student_groupsID' not in course:
                    if 'studentGroupIds' in course:
                        course['student_groupsID'] = course['studentGroupIds']
                    elif 'student_groups' in course:
                        course['student_groupsID'] = course['student_groups']
                    else:
                        course['student_groupsID'] = [i]  # Default value
                    print(f"🔧 Fixed student_groupsID for course {i}")
                
                # Fix missing facultyId
                if 'facultyId' not in course:
                    if 'faculty_id' in course:
                        course['facultyId'] = course['faculty_id']
                    elif 'faculty' in course:
                        course['facultyId'] = course['faculty']
                    else:
                        course['facultyId'] = i  # Default value
                    print(f"🔧 Fixed facultyId for course {i}")
        
        # Ensure studentgroups vs student_groups consistency
        if 'input_data' in session_data:
            input_data = session_data['input_data']
            if 'student_groups' in input_data and 'studentgroups' not in input_data:
                input_data['studentgroups'] = input_data['student_groups']
                print("🔧 Fixed studentgroups field name")
        
        print("✅ Session data fixes applied")
        return session_data