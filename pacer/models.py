# models.py

# Pacer object
class Pacer:
    def __init__(self, pace, color, rep_dist=400):

        # pace in seconds per 400m, used to calculate split times
        self.pace = pace

        # color in RGB format, used to set LED colors
        self.color = color

        # current position in meters, used to determine which LEDs to light up
        self.position = 0.0

        # bool, is the pacer currently active (running) or idle
        self.active = False

        # distance in meters for each rep, used to calculate split times
        self.rep_dist = rep_dist