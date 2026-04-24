
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


NOTE (4/22): 
From Rhea- I have pushed and changed around code in the pacer folder (to almost all the files), however they are untested because of the hardware issue we were having. Once I can run it on the pi, I can test it. Thanks!

(4/23):
Strip notes
SK6812 RGBW 5m LED Strip 60L/m
Total LED count: 300

How often to update LEDS? based on pace? Driven at 800kHz not sure 
Interesting note: Data is daisy chained togther
LED1 stores first 32 bits and then passes rest
to send stuff to LED50 have to send 49 32 bit packets first and then hold data line low
Hardware shift register chain with memory
