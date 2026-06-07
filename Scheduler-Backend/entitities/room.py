from enums import Size
class Room:
    def __init__(self, Id: str, name:str, capacity:int, room_type:str, building:str):
        self.Id = Id
        self.name = name
        self.capacity = capacity
        self.room_type = room_type
        self.building = building

    def __repr__(self):
        return f"Room(Id={self.Id}, name={self.name}, capacity={self.capacity}, room_type={self.room_type}, building={self.building})"

    def categorize_group_size(self):
        if self.capacity <= 20:
            return Size.SMALL
        elif 21 <= self.capacity <= 50:
            return Size.MEDIUM
        else:
            return Size.LARGE
# an inventory class, with list 
# test = Room("1", "room1", 20, "small_classroom")      