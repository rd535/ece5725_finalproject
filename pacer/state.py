# state.py
# Management for pacer
# from models import Pacer
import threading
from pacer.pacer_pattern import ConstantPacerWithPacer
from rpi_ws281x import PixelStrip, Color, ws

# this is very outdated
# I think we need to change so this is only object sending data line to led strip
# so needs to queue all pace updates from active pacers and determine which has priority
# I was thinking have an array that gets updated by each pacer with last pacers having higher priority
# and then this pacer manager just looks at the array and executes the highest priority pacer (probably just the last one in the array that is active)

class NewPacerManager:
    PACER_SEG_LENGTH = 3
    SEGMENT_LENGTH = 8

    def __init__(self, num_leds=300, pin=12):
        self.pacers = []  # List to hold all active pacers
        self.LED_index = [] # index to hold shared LED position states
        self.active = False
        self.thread = None
        self.num_leds = num_leds
        self.pin = pin

        self.strip = PixelStrip(
            self.num_leds,
            self.pin,
            800000,
            10,
            False,
            128,
            0,
            ws.SK6812_STRIP_RGBW
        )
        self.strip.begin()
    
    # add pacer with priority seeding, depending on pace - faster pace gets higher priority, if same pace then newer pacer gets higher priority
    # need to figure out pacer.pace vs pacer.rep_dist relationship to determine priority - maybe just use pace for now and then add in rep_dist as a tiebreaker if same pace? or just ignore rep_dist for priority and only use pace?
    def add_pacer(self, pacer):
        for p in self.pacers:
            if p.active and p.pace == pacer.pace:
                # If same pace, the newer pacer gets higher priority, so we can just add it to the end of the list
                self.pacers.append(pacer)
            elif p.active and p.pace < pacer.pace:
                # If existing pacer has a slower pace, the new pacer gets higher priority, so we can insert it before the slower pacer
                self.pacers.insert(self.pacers.index(p), pacer)
                return
        
    
    def update(self):
        # Update all pacers and determine which one has priority
        while self.active:
            self.LED_index = [] # reset LED index for this update cycle

            # update LED index for all pacers
            for p in self.pacers:
                if p.active:
                    position = p.run()
                    print(f"Pacer with pace {p.pace} is at position {position}")
                    self.LED_index.append((position, p.color, p.TYPE))

            # clear strip
            for i in range(self.num_leds):
                self.strip.setPixelColor(i, Color(0,0,0))

            for index in self.LED_index:
                position = index[0]
                color = index[1]
                type = index[2]

                # do first so can overwrite with real pace color if they overlap
                if type == 'pacer':
                    for k in range(self.PACER_SEG_LENGTH):
                        pacer_idx = int((position + k) % self.num_leds)
                        self.strip.setPixelColor(pacer_idx, color)

                # draw moving segment
                for j in range(self.SEGMENT_LENGTH):
                    idx_init = position - j
                    # FUTURE TODO, hanlde overflow on first lap so doesnt begin at end of line
                    idx = int((idx_init) % self.num_leds)
                    self.strip.setPixelColor(idx, color)
                
            self.strip.show()
            # print("Updated LED strip with current pacer positions and colors.")
        
        # clear strip when stopping
        for i in range(self.num_leds):
            self.strip.setPixelColor(i, Color(0,0,0))
        self.strip.show()

    # have function to start/stop pacer manager depending on if there are active pacers or not, so we don't waste resources updating when there are no active pacers
    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.active = True
            self.thread = threading.Thread(target=self.update, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.active = False


class PacerManager:
    def __init__(self):
        # ALWAYS keep the LED pacer as the active pacer
        self.pacers = [ConstantPacerWithPacer()]

    def create_single_pacer(self, pace, color):
        # This should NOT replace the LED pacer
        # Instead, update its parameters
        p = self.pacers[0]   # keep the same LED pacer object
        p.pace = pace
        p.color = color
        return p

    def update(self, dt):
        for p in self.pacers:
            if p.active:
                p.position += dt * (p.rep_dist / p.pace)

manager = PacerManager()

# Update the existing LED pacer instead of replacing it
current_pacer = manager.create_single_pacer(pace=60, color=(0,255,0))
