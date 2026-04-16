# models.py

# Pacer object
class Pacer:
    def __init__(self, pace, color):
        self.pace = pace
        self.color = color
        self.position = 0.0
        self.active = False
