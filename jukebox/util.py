import enum


def mpd_quote_string(s):
    return "'" + s.replace('\\','\\\\').replace('"','\\"').replace()


class Buttons(enum.Enum):
    MODE = 'Mode'
    PAUSE = 'Pause/Play'
    REPEAT = 'Repeat'
    SHUFFLE = 'Shuffle'
    PREVIOUS = 'Previous'
    NEXT = 'Next'
    # Special value for the encoder switch.  Not read from the ADC.
    ENCODER = 'Encoder'