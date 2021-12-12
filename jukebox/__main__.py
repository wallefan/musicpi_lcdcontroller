from jukebox import Display, RotaryEncoder, LCD
from jukebox.screen import Screen
from jukebox.screen.directory import Directory
from jukebox.screen.mpd import NowPlaying
from jukebox.screen.clock import Clock
import pigpio
import asyncio
import my_aiompd
from jukebox.screen.text_entry import TextInputScreen


if __name__ == '__main__':
    pi = pigpio.pi('musicpi.local')
    print('pi connected')
    try:
        display = Display(
            pi,
            my_aiompd.Client('musicpi.local'),
            LCD(pi, d4=24, d5=23, d6=22, d7=27, rs=6, e=5,
                bl_red=18, bl_green=17, bl_blue=4  # PWM pins for common-anode RGB backlight
                ),
            RotaryEncoder(pi, 19, 16),
            rotary_switch=21,
            adc_spi_channel=0,
            buttons_adc_channel=2,
        )
        try:
            main_menu = Directory('Main Menu', display)
            now_playing = NowPlaying(display, main_menu)
            main_menu.children.append(('Now Playing', now_playing))
            clock = Clock(display, main_menu)
            main_menu.children.append(('Clock', clock))
            test_text_entry = TextInputScreen(display, main_menu, main_menu)
            display.lcd.set_color(0,0)
            display.switch_screen(test_text_entry)
            display.mainloop()  # run one iteration of the main loop and schedule the next one
            asyncio.get_event_loop().run_forever()
        finally:
            display.shutdown()  # the destructor calls this, but it must run before pi.stop() happens.
    finally:
        pi.stop()
