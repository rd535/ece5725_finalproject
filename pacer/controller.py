# controller.py

from .state import manager

def start_pacer():
    if manager.pacers:
        pacer = manager.pacers[0]
        pacer.active = True
        pacer.start()

def stop_pacer():
    if manager.pacers:
        pacer = manager.pacers[0]
        pacer.active = False
        pacer.stop()
