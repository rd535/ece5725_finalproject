#!/usr/bin/env python3

import time
from pacer.pacer_pattern import NewConstantPacer, ConstantPacerWithPacer, DynamicPacer
from pacer.state import NewPacerManager
from rpi_ws281x import Color

manager = NewPacerManager()
pacer1 = NewConstantPacer(pace=10, rep_distance=400, lap_count=4, color=Color(255,0,0))
pacer2 = NewConstantPacer(pace=5, rep_distance=400, lap_count=4, color=Color(0,255,0))

print("Adding pacers to manager…")
manager.add_pacer(pacer1)
manager.add_pacer(pacer2)

print("Starting pacer manager…  Press CTRL+C to stop.")
manager.start()

time.sleep(3)

print("Starting pacers…")
pacer1.start()

time.sleep(3)

print("Starting second pacer…")
pacer2.start()

try:
    while True:
        print("Updating pacer manager…")
        time.sleep(1)
except KeyboardInterrupt:
    print("\nStopping pacer…")
    time.sleep(0.5)


# # Create the pacer object
# # pacer = GreenPacer()
# # pacer = ConstantPacerWithPacer()
# pace_input = input("Enter pace (comma-separated values): ")
# pacer_type = input("Enter pacer type (constant/dynamic): ")
# if pacer_type == "constant":
#     pace = 0
#     for x in pace_input.split(","):
#         pace += int(x)
#     pacer = ConstantPacerWithPacer(pace=pace)
# else:
#     pacer = DynamicPacer(pace=[int(x) for x in pace_input.split(",")])

# print("Starting dynamic pacer…  Press CTRL+C to stop.")

# try:
#     pacer.active = True
#     pacer.start()

#     # Keep the script alive while the pacer thread runs
#     while True:
#         time.sleep(1)

# except KeyboardInterrupt:
#     print("\nStopping pacer…")
#     pacer.active = False
#     time.sleep(0.5)
