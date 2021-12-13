import types

from ..util import Buttons


def on_button_held(button:Buttons, time:float):
    def _wrapper(func):
        func.__dict__.setdefault('musicpi_trigger_events',[]).append((button, time))
        return func
    return _wrapper


def on_button_pressed(button:Buttons):
    return on_button_held(button, 0)

def on_button_released(button:Buttons):
    return on_button_held(button, -1)


class EncoderTickWatcher:
    musicpi_trigger_events = ('encoder',)
    __slots__ = ('func', 'n', 'last_encoder_value')
    def __init__(self, n, func):
        self.func = func
        self.n = n
        self.last_encoder_value = 0

    def on_update(self, encoder_value):
        val = (encoder_value - self.last_encoder_value) // self.n
        if val != 0:
            self.func(val)
            # deliberately not setting it directly to the value we were passed, in case we're set to trigger on fours
            # and the user goes 0 -> 3 -> 5 -> 8, we need to trigger twice.
            self.last_encoder_value += val * self.n

    def on_reset(self):
        self.last_encoder_value = 0

    def __call__(self, n):
        return self.func(n)

    def __get__(self, instance, owner):
        return EncoderTickWatcher(self.n, types.MethodType(self.func, instance))

class MethodWrapper:
    def __init__(self, obj, arg):
        self.obj = obj
        self.arg = arg

    def __call__(self, *args):
        return self.obj(self.arg, *args)

    def __getattr__(self, item):
        return getattr(self.obj, item)

def on_encoder_tick(n):
    def wrapper(func):
        return EncoderTickWatcher(n, func)
    return wrapper


class ScreenMeta(type):
    def __init__(cls, name, bases, ns):
        super().__init__(name, bases, ns)
        # inherit events from parent classes
        events = cls._class_events.copy() if hasattr(cls, '_class_events') else {}
        for func in ns.values():
            # not *all* of these are going to be functions, obviously, but the ones that have this attribute are
            if hasattr(func, 'musicpi_trigger_events'):
                for evt in func.musicpi_trigger_events:
                    events.setdefault(evt, []).append(func)
        cls._class_events = events


class BaseScreen(metaclass=ScreenMeta):
    disallow_popups = False

    def __init__(self):
        events = {}
        for k, v in self._class_events.items():
            events[k] = [func.__get__(self, type(self)) for func in v]
        self.events = events

    def on_switched_to(self):
        pass


class Screen(BaseScreen):
    def __init__(self, display, next_screen: BaseScreen):
        super().__init__()
        self.display = display
        self.next_screen = next_screen

    @on_button_pressed(Buttons.MODE)
    def on_mode_pressed(self):
        self.display.switch_screen(self.next_screen)