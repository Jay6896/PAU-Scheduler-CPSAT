from enum import Enum

# class PhysicalSpaceTypes(Enum):
#     REGULAR_CLASSROOM = "regular classroom"
#     COMPUTER_LAB = "computer lab"
#     PHYSICS_LAB = "physics lab"
#     CHEMISTRY_LAB = "chemistry lab"
#     THERMOFLUIDS_LAB = "thermofluids lab"
#     AUDIO_VISUAL_LAB = "audio visual lab"

class Size(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"

class RoomType(Enum):
    REGULAR = "regular"
    LAB = "lab"