import time

import mpdclient
import sched
from collections import namedtuple
import select


def accumulate(func, iterable, *, default=None):
    try:
        current=next(iterable)
    except StopIteration:
        return default
    for item in iterable:
        current = func(current, item)
    return current


_Waiter = namedtuple('_Waiter', ['subsystems', 'channel', 'func', 'args','kw'])

_message_subsystem = frozenset(['message'])

class MPDLoop:
    def __init__(self, host='localhost', port=6600):
        self.client = mpdclient.MPDClient(host, port)
        self.client.set_idle_cancel_callback(self._handle_idle_results)
        self.scheduler = sched.scheduler(delayfunc=self._idle)
        self.waiters: list[_Waiter] = []

    def _idle(self, timeout):
        subsystems = accumulate(frozenset.union, (x.subsystems for x in self.waiters))
        if not subsystems:
            time.sleep(timeout)
            return
        self.client.send_idle(subsystems)
        if select.select([self.client], [], [], timeout)[0]:
            subsystems = self.client.receive_idle()
            self._handle_idle_results(subsystems)

    def _handle_idle_results(self, subsystems):
        #print('!', subsystems)
        if 'message' in subsystems:
            self.client.read_messages()
        i = 0
        while i < len(self.waiters):
            waiter = self.waiters[i]
            if not waiter.subsystems.isdisjoint(subsystems) and (
                    not waiter.channel or self.client.pending_messages.get(waiter.channel)):
                waiter.func(subsystems, *waiter.args, **waiter.kw)
                del self.waiters[i]
            else:
                i += 1

    def add_subsystem_waiter(self, subsystems, func, *args, **kw):
        waiter = _Waiter(frozenset(subsystems), None, func, args, kw)
        self.waiters.append(waiter)
        return waiter

    def add_channel_waiter(self, channel, func, *args, **kw):
        waiter = _Waiter(_message_subsystem, channel, func, args, kw)
        self.waiters.append(waiter)
        return waiter

    def call_soon(self, seconds, func, *args, **kwargs):
        return self.scheduler.enter(seconds, 0, func, args, kwargs)

    def cancel(self, waiter):
        if isinstance(waiter, _Waiter):
            self.waiters.remove(waiter)
        elif isinstance(waiter, sched.Event):
            self.scheduler.cancel(waiter)
        else:
            raise TypeError

    def run(self):
        self.scheduler.run()
        while self.waiters:
            self._idle(None)
            self.scheduler.run()
