
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

(4/24):
Future Me: Change UI colors to be Cornell Colors!!

(4/26):
Tasks:
Figure out how to deal with user entering dynamic paces
Make UI have live updates for every single pace thats entered
[PACE NAME (changeable)], [PACER TYPE], Current Pace, Color, Time, Status, LapCount, start/stop?

Currently:
- fix add lap pace button if not dynamic
also add way to specify total lap count for constant pacer
dynamic is just added each time "add lap pace" button is clicked

- change to make it so increasing lap number controls number of lap pace options available for dynamic!

Steps: 
X Remove button
X make .lapPace col dep on lapNum
X Make sure submit table reflects this change

Bug list:
X on change of input, if not dynamic, change .paceList to just one input
X change "addRow" logic to reflect additions
X change default pacer to constant
X when option is selected, trigger updateLapPace from LapNum
X Change so auto fill only works for new rows, user can change name of any created row 
regardless of checked

Next Feature:
- get pace configuration working similar to pace config v1
Step 1: get working with single pace
- update submitTable to reflect all changes with the dynamic table rows in JS
X?
- update Flask to reflect JS function changes!

Bugs:
- might need to change to fully using arrays for pacing? idk we will see if can handle both array and const inputs


Step 2: get manager working 
Step 3: get full table upload working for multiple paces
Step 4: get pacer status at bottom working 
- move pacer status to top of page 



Future:
Set pace to start/end at arbitrary points ex. 200m start/end (like for 1k)

