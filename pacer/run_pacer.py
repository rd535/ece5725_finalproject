#!/usr/bin/env python3

import sys
import time
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pacer.event_log import log_event
from pacer.pacer_pattern import Color, NewConstantPacer
from pacer.state import NewPacerManager


def main():
    manager = NewPacerManager()
    pacer1 = NewConstantPacer(pace=10, rep_distance=400, lap_count=4, color=Color(255, 0, 0))
    pacer2 = NewConstantPacer(pace=5, rep_distance=400, lap_count=4, color=Color(0, 255, 0))

    log_event("Adding pacers to manager", category="run_pacer")
    manager.add_pacer(pacer1)
    manager.add_pacer(pacer2)

    manager.flash_startup()

    log_event("Starting pacer manager", category="run_pacer")
    manager.start()

    time.sleep(3)

    log_event("Starting first pacer", category="run_pacer")
    pacer1.start()
    log_event("First pacer active state", category="run_pacer", active=pacer1.active, position=pacer1.pos)

    time.sleep(3)

    log_event("Starting second pacer", category="run_pacer")
    pacer2.start()
    log_event("Second pacer active state", category="run_pacer", active=pacer2.active, position=pacer2.pos)

    try:
        while manager.active:
            if not any(p.active for p in manager.pacers):
                log_event("All pacers finished", category="run_pacer")
                manager.stop()
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        log_event("Keyboard interrupt received; stopping pacer manager", category="run_pacer", level="WARNING")
        manager.stop()

    if manager.thread and manager.thread.is_alive():
        manager.thread.join(timeout=1.0)

    log_event("run_pacer complete", category="run_pacer")


if __name__ == "__main__":
    main()
