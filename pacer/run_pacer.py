#!/usr/bin/env python3

import time
from pacer_pattern import GreenPacer, ConstantPacerWithPacer, DynamicPacer

# Create the pacer object
# pacer = GreenPacer()
# pacer = ConstantPacerWithPacer()
pacer = DynamicPacer()

print("Starting dynamic pacer…  Press CTRL+C to stop.")

try:
    pacer.active = True
    pacer.start()

    # Keep the script alive while the pacer thread runs
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("\nStopping pacer…")
    pacer.active = False
    time.sleep(0.5)
