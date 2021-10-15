import typing

import mpdloop
import sys

from asyncio import CancelledError
from types import coroutine

LOOP = sys.intern('loop')
TIME = sys.intern('time')
SUBSYS = sys.intern('subsys')
MESSAGE = sys.intern('message')
FUTURE = sys.intern('future')
CANCEL = sys.intern('cancel')


class TaskNotDone(Exception):
    pass


class _FutureMixIn:
    def __init__(self, loop: mpdloop.MPDLoop = None):
        self._loop = loop
        self._done = False
        self._result = None
        self._exception = None
        self._done_callbacks = []

    def _mark_done(self):
        # there are probably HUGE downsides to doing it this way but I am not entirely sure that I care
        if not self._done:
            self._done = True
            for callback in self._done_callbacks:
                if self._loop:
                    # schedule the callback if possible.
                    self._loop.call_soon(0, callback, self)
                else:
                    callback(self)

    def add_done_callback(self, callback):
        self._done_callbacks.append(callback)

    def remove_done_callback(self, callback):
        self._done_callbacks.remove(callback)

    def result(self):
        if not self._done:
            raise TaskNotDone
        if self._exception:
            raise self._exception
        return self._result

    def __await__(self):
        if not self._done:
            yield FUTURE, self
        if self._exception:
            raise self._exception
        return self._result

    @property
    def is_complete(self):
        return self._done


class Task(_FutureMixIn):
    def __init__(self, coro, loop: mpdloop.MPDLoop):
        super().__init__(loop)
        self._coro = type(coro).__await__(coro)
        self._waiter = loop.call_soon(0, self._callback)
        self._waiting_on_future = None

    def _callback(self, arg=None, is_exception=False):
        # When called by subsystem_waiter or channel_waiter, arg is the list of subsystems that were modified.
        # We pass it directly to the coroutine in case it wants to do something with it.
        # When called by a Future's done_callback, arg will be the future, which it is safe to assume that the coroutine
        # will ignore.
        # In all other cases, we accept an arbitrary object or exception to throw into the coroutine.
        self._waiter = None
        self._waiting_on_future = None
        try:
            if is_exception:
                type_, arg = self._coro.throw(arg)
            else:
                type_, arg = self._coro.send(arg)
            # imo this is how getting the current event loop *should* be handled.
            # i know it has its problems, e.g. you can't get the running event loop from a non coroutine, but this way
            # you're always guaranteed to get the loop that's running you
            while type_ == LOOP:
                type_, arg = self._coro.send(self._loop)
        except StopIteration as e:
            self._result = e.value
            self._mark_done()
            return
        except BaseException as e:
            self._exception = e
            self._mark_done()
            return

        if type_ == TIME:
            self._waiter = self._loop.call_soon(arg, self._callback)
        elif type_ == SUBSYS:
            self._waiter = self._loop.add_subsystem_waiter(arg, self._callback)
        elif type_ == MESSAGE:
            self._waiter = self._loop.add_channel_waiter(arg, self._callback)
        elif type_ == FUTURE:
            arg: _FutureMixIn
            self._waiting_on_future = arg
            arg.add_done_callback(self._callback)

    def cancel(self):
        if self._done:
            return
        if self._waiter:
            self._loop.cancel(self._waiter)
            self._waiter = None
        if self._waiting_on_future:
            self._waiting_on_future.remove_done_callback(self._callback)
            self._waiting_on_future = None
        self._loop.call_soon(0, self._callback, CancelledError, True)


class Future(_FutureMixIn):
    def set_result(self, result):
        if self._done:
            raise ValueError("Can't set the result of a future that's already done")
        self._result = result
        self._mark_done()

    def set_exception(self, exc):
        if isinstance(exc, type):
            if not issubclass(exc, BaseException):
                raise TypeError("set_exception() requires an exception, not %r" % exc.__name__)
            exc = exc()
        elif not isinstance(exc, BaseException):
            raise TypeError("set_exception() requires an exception, not %r" % type(exc).__name__)
        if self._done:
            raise ValueError("Can't set an exception on a future that's already done")
        self._exception = exc
        self._mark_done()

#
# class sleep:
#     __slots__ = ['delay']
#
#     def __init__(self, delay):
#         self.delay = delay
#
#     def __await__(self):
#         yield TIME, self.delay

@coroutine
def sleep(seconds):
    yield TIME, seconds


@coroutine
def get_event_loop() -> typing.Awaitable[mpdloop.MPDLoop]:
    return (yield LOOP, None)

@coroutine
def _await_channel_messages(channel):
    yield MESSAGE, channel


async def iter_channel_messages(channel):
    loop = await get_event_loop()
    while True:
        m = loop.client.pending_messages.get(channel)
        while m:
            yield m.pop(0)
        await _await_channel_messages(channel)


@coroutine
def wait_for_events(events) -> typing.Awaitable[typing.List[str]]:
    return (yield SUBSYS, events)


class ChannelMessages:
    def __init__(self, channel):
        self.channel = channel
    def __aiter__(self):
        return self
    @coroutine
    def __anext__(self):
        loop: mpdloop.MPDLoop = yield LOOP, None
        while True:
            m = loop.client.pending_messages.get(self.channel)
            if m:
                return m.pop(0)
            yield MESSAGE, self.channel


