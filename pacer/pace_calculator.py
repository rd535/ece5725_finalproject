# pace_calculator.py

# Constants for Speed 
LED_PER_METER = 60
LED_STRIP_LENGTH_M = 5

# helper function to scale pace based on rep distance (convert 400m to 5m LED strip length)
def scale_pace(pace, rep_distance):
    return pace * rep_distance / 400

# speed to LEDs per second
def pace_to_speed(pace, rep_distance):
    scaled_pace = scale_pace(pace, rep_distance)
    speed = LED_PER_METER / scaled_pace
    return speed
