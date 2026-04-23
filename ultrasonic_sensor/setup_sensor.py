"""
Ultrasonic sensor setup, referring to following docs: 
https://www.woolseyworkshop.com/2020/05/01/interfacing-ultrasonic-distance-sensors-with-a-raspberry-pi/
Ultrasonic sensor type: RCWL-1601, range: 450cm
"""

from time import sleep
from gpiozero import DistanceSensor #use class DistanceSensor
from signal import pause

#
sensor = DistanceSensor(echo = 23, trigger = 24, max_distance = 4, threshold_distance = 0.25)


def object_in_range():
    print("Object detected in range (%.1f cm)." % (sensor.distance * 100))

def object_out_of_range():
    print("Object detected out of range (%.1f cm)." % (sensor.distance * 100))


#main
sensor.when_in_range = object_in_range()
sensor.when_out_of_range = object_out_of_range()

while True: 
    print("Distance: %.1f cm" % (sensor.distance * 100))
    sleep(0.5)