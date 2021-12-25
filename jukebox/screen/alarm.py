from . import Screen, on_button_pressed, on_encoder_tick
from ..util import Buttons
import time
import datetime

# THIS IS VERY MESSY AND BAD AND I WILL CLEAN IT UP LATER

class AlarmClock(Screen):
    def on_switched_to(self):
        self.state = 'hour'
        self.display.clear()
        self.display.write(0, 'Now:')
        self.display.write(64,'Alarm:')
        self.alarm_hour = time.localtime().tm_hour+1
        self.alarm_minute = 0
        self._ts_now_handle = self.display.call_later(0, self.show_time_now)
        self._ts_set_handle = self.display.call_later(0, self.flash_alarm_set_cursor)
        self._flash_screen_handle = None


    def show_time_now(self):
        t = time.time()
        index = (t % 1 > 0.5)
        format = ('%H:%M:%S', '%H %M %S')[index]
        self.display.write(7, time.strftime(format))
        self._ts_now_handle = self.display.call_later(0.5 - t % 0.5, self.show_time_now)

    def flash_alarm_set_cursor(self,on=True):
        # I could do this from the same method as (and therefore have the flashes be synchronized with)
        # the current time, but I like it better this way
        if on:
            if self.state == 'hour':
                format = '>%02d<%02d '
            else:
                format = ' %02d>%02d<'
        else:
            format = ' %02d:%02d '
        self.display.write(70, format % (self.alarm_hour, self.alarm_minute))
        self._ts_set_handle = self.display.call_later(0.2, self.flash_alarm_set_cursor, not on)

    @on_encoder_tick(4)
    def adjust(self, n):
        if self.state == 'hour':
            self.alarm_hour = (self.alarm_hour + n) % 24
            self.display.write(71, '%02d' % self.alarm_hour)
        elif self.state == 'minute':
            self.alarm_minute = (self.alarm_minute + n) % 60
            self.display.write(74, '%02d' % self.alarm_minute)
        else:
            return


    @on_button_pressed(Buttons.PREVIOUS)
    def previous(self):
        if self.state == 'minute':
            self.state = 'hour'

    @on_button_pressed(Buttons.NEXT)
    def next(self):
        if self.state == 'hour':
            self.state = 'minute'

    @on_button_pressed(Buttons.PAUSE)
    @on_button_pressed(Buttons.ENCODER)
    def move_next(self):
        if self.state == 'hour':
            self.state = 'minute'
        elif self.state == 'minute':
            now = datetime.datetime.now()
            if now.hour > self.alarm_hour:
                # if it is currently before the hour set for the alarm, assume the user meant after midnight
                # and set the alarm for tomorrow.
                now += datetime.timedelta(days=1)
            self.alarm_time = now.replace(hour=self.alarm_hour, minute=self.alarm_minute, second=0)
            self.state = 'alarm'
            self._ts_set_handle.cancel()
            self._ts_now_handle.cancel()
            self.display.clear()
            self.show_countdown()
            self.display.show_popup(66, '[Alarm Set]', 2)
        elif self.state == 'ring':
            if self._flash_screen_handle:
                self._flash_screen_handle.cancel()
                self._flash_screen_handle = None
            # turn the music off
            self.display.create_task(self.display.mpd_client.send_command('stop'), persist=True)
            self.display.pi.write(12, False)
            # turn the screen back on
            self.display.lcd.set_backlight_brightness(1)
            # and return to the previous screen
            self.display.switch_screen(self.next_screen)
            # FIXME If the user presses MODE instead of PLAY or the encoder button, the alarm will be stuck on,
            # FIXME and the only way to turn it off will be to unplug the amplifier!


    def show_countdown(self):
        now = datetime.datetime.now()
        if self.alarm_time <= now:
            self.state = 'ring'
            self.display.create_task(self.trigger_alarm())
            return

        delta = self.alarm_time - now
        self.display.call_later(delta.microseconds/1000000, self.show_countdown)

        minutes, seconds = divmod(delta.seconds, 60)
        hours, minutes = divmod(minutes, 60)
        self.display.write(4, '%02d:%02d:%02d' % (hours, minutes, seconds))

    async def trigger_alarm(self):
        self.display.write(0,'WAKE UP BITCH!!!')
        await self.display.mpd_client.send_command('clear')
        await self.display.mpd_client.send_command('add', 'Virtual Self - Virtual Self/1-06 Angel Voices.flac')
        self.display.pi.write(12, True)
        await self.display.mpd_client.send_command('play')
        self.flash_screen()

    def flash_screen(self, on=True):
        self.display.lcd.set_color(1,0)
        self.display.lcd.set_backlight_brightness(1 if on else 0)
        self._flash_screen_handle = self.display.call_later(0.25, self.flash_screen, not on)
