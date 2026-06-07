class TimeSlot:
    def __init__(self, id:int, day: str, start_time: str, available: bool):
        self.id = id  
        self.day = day  
        self.start_time = start_time 
        self.available = True  

    def __repr__(self):
        return f"TimeSlot(id={self.id}, day={self.day}, start_time={self.start_time}, available={self.available})"
    
