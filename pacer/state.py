# state.py
# Management for pacer
from models import Pacer

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
                p.position += dt * (400 / p.pace)
