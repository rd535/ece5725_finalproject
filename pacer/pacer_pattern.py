from .models import Pacer
from .state.py import PacerManager

manager = PacerManager()

# Instantiate your ONE pacer for now
current_pacer = manager.create_single_pacer(pace=60, color=(0,255,0))

def create_pacer_wave():
    return [
        manager.create_single_pacer(pace=60 + i * 10, color=(0, 255 - i * 60, 255))
        for i in range(4)
    ]


def create_pacer_spiral():
    colors = [
        (255, 0, 0),
        (255, 127, 0),
        (255, 255, 0),
        (0, 255, 0),
    ]
    return [
        manager.create_single_pacer(pace=70 + i * 5, color=colors[i])
        for i in range(len(colors))
    ]


def create_pacer_strobe():
    return [
        manager.create_single_pacer(pace=120, color=(255, 255, 255)),
        manager.create_single_pacer(pace=120, color=(0, 0, 0)),
    ]


pacer_patterns = {
    "steady_green": [current_pacer],
    "rainbow_wave": create_pacer_wave(),
    "gradient_spiral": create_pacer_spiral(),
    "strobe": create_pacer_strobe(),
}

current_pattern = pacer_patterns["steady_green"]
pattern_names = list(pacer_patterns.keys())
pattern_index = 0

while True:
    pattern_name = pattern_names[pattern_index]
    current_pattern = pacer_patterns[pattern_name]

    print("Executing pattern:", pattern_name)
    # execute the current_pattern here, e.g. manager.run_pattern(current_pattern)

    time.sleep(5)
    pattern_index = (pattern_index + 1) % len(pattern_names)