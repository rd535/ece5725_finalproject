# controller.py
# Controls for pacing

from .state import manager

def start_pacer():
    if manager.pacers:
        manager.pacers[0].active = True

def stop_pacer():
    if manager.pacers:
        manager.pacers[0].active = False
