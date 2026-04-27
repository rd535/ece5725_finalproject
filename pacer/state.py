# state.py
# Management for pacer
# from models import Pacer
from pacer.pacer_pattern import ConstantPacerWithPacer

# this is very outdated
# I think we need to change so this is only object sending data line to led strip
# so needs to queue all pace updates from active pacers and determine which has priority
# I was thinking have an array that gets updated by each pacer with last pacers having higher priority
# and then this pacer manager just looks at the array and executes the highest priority pacer (probably just the last one in the array that is active)

class PacerManager:
    def __init__(self):
        # ALWAYS keep the LED pacer as the active pacer
        self.pacers = [ConstantPacerWithPacer()]

    def create_single_pacer(self, pace, color):
        # This should NOT replace the LED pacer
        # Instead, update its parameters
        p = self.pacers[0]   # keep the same LED pacer object
        p.pace = pace
        p.color = color
        return p

    def update(self, dt):
        for p in self.pacers:
            if p.active:
                p.position += dt * (p.rep_dist / p.pace)

manager = PacerManager()

# Update the existing LED pacer instead of replacing it
current_pacer = manager.create_single_pacer(pace=60, color=(0,255,0))
