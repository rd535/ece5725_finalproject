# models.py

# Pacer object
class Pacer:
    def __init__(self, pace, color, rep_dist=400):
        self.pace = pace
        self.color = color
        self.position = 0.0
        self.active = False
        self.rep_dist = rep_dist