# state.py
# Management for pacer
from .models import Pacer

class PacerManager:
    def __init__(self):
        self.pacers = []

    def create_single_pacer(self, pace, color):
        self.pacers = []  # wipe any old ones
        p = Pacer(pace, color)
        self.pacers.append(p)
        return p

    def update(self, dt):
        for p in self.pacers:
            if p.active:
                p.position += dt * (p.rep_dist / p.pace)

manager = PacerManager()

# Instantiate your ONE pacer for now
current_pacer = manager.create_single_pacer(pace=60, color=(0,255,0))