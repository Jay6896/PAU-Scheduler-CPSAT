
class Faculty:
    def __init__(
        self,
        id: str,
        name: str,
        department: str,
        courseID: str,
        avail_days: list,
        avail_times: list,
        available_hours: int = 4,
        available_consecutive_hours: int = 3,
    ):
        self.faculty_id = id
        self.name = name
        self.department = department
        self.courseID = courseID
        self.avail_days = avail_days
        self.avail_times = avail_times

        # Lecturer workload limits (per day)
        self.available_hours = int(available_hours) if available_hours is not None else 4
        self.available_consecutive_hours = (
            int(available_consecutive_hours) if available_consecutive_hours is not None else 3
        )

    def __repr__(self):
        return (
            "Faculty("
            f"id={self.faculty_id}, name={self.name}, department={self.department}, courseID={self.courseID}, "
            f"avail_days={self.avail_days}, avail_times={self.avail_times}, "
            f"available_hours={getattr(self, 'available_hours', None)}, "
            f"available_consecutive_hours={getattr(self, 'available_consecutive_hours', None)}"
            ")"
        )
