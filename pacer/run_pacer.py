#!/usr/bin/env python3

import time
from pacer_pattern import GreenPacer, ConstantPacerWithPacer, DynamicPacer

# Create the pacer object
# pacer = GreenPacer()
# pacer = ConstantPacerWithPacer()
pace_input = input("Enter pace (comma-separated values): ")
pacer_type = input("Enter pacer type (constant/dynamic): ")
if pacer_type == "constant":
    pace = 0
    for x in pace_input.split(","):
        pace += int(x)
    pacer = ConstantPacerWithPacer(pace=pace)
else:
    pacer = DynamicPacer(pace=[int(x) for x in pace_input.split(",")])

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
