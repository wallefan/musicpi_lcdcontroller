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


def on_encoder_tick(n=1):
    def _wrapper(func):
        func.__dict__.setdefault('musicpi_trigger_events',[]).append(('encoder', n))
        return func
    return _wrapper


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
            events[k] = [types.MethodType(func, self) for func in v]
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