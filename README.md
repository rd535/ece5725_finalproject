
FLASK WEB SERVER
Lives in:
/home/pi/Documents/webapp
app.py is Flask App

/webapp/templates
contain html templates for webpage looks and scripts to push/pull data

RP LED DRIVER:
uses rpi-ws281x library, from github
already disabled audio driver to stop PWM conflicts

!! Next step is to test github examples/strandtest.py
-- switch LED_PIN to 12 for PWM0 for out RPi4
!! Also need level shifter

1 IC controls 3 LED
LED_COUNT is number of 3 LED segments
run: sudo python strandtest.py -c

IR SENSOR:


