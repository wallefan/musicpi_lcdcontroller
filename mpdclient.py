import socket
import re


class MPDError(RuntimeError):
    # This code stolen, with slight modifications, from aiompd by TODO NAME THE AUTHOR OF AIOMPD
    RE = re.compile(r'^ACK \[(\d+)@(\d+)\] \{(.+)\} (.+)$')

    def __init__(self, line: str) -> None:
        super().__init__(line)

        parsed = self.RE.match(line)
        if parsed:
            self.code = int(parsed.group(1))
            self.lineno = int(parsed.group(2))
            self.command = parsed.group(3)
            self.message = parsed.group(4)
        else:
            self.code = None
            self.lineno = None
            self.command = None
            self.message = None


def quote_string(s):
    return '"'+s.replace('\\','\\\\').replace('"', '\\"').replace("'", "\\'")+'"'


class MPDClient:
    def __init__(self, host, port=6600):
        self.host = host
        self.port = port
        self.socket = None
        self.readfile = None
        self.protocol_version = None   # set by connect()
        self._idle_in_progress: frozenset = None  # stores the list of subsystems monitored by the running idle command.
        self._idle_cancel_callback = None
        self.partition: str = None
        self.subscriptions = set()  # list of C2C channels we're subscribed to
        self.last_cmdline = b''  # this turns into a list between a command_list_begin and a command_list_end
        self.pending_messages = {}  # mapping channel names to lists of messages that we have retrieved from the server
                                    # but that user code has not yet consumed.

    def set_idle_cancel_callback(self, callback):
        self._idle_cancel_callback = callback

    def connect(self):
        """
        Reconnect to the server, using the host and port specified in the constructor.
        The MPD reference implementation will terminate any TCP connection after 30 seconds of inactivity, so clients
        should implement reconnection logic.
        *cough* python-mpd2 *cough*
        """
        if self.socket:
            self.socket.close()
        if self.readfile:
            self.readfile.close()

        self._idle_in_progress = None
        self.last_cmdline = b''

        if self.port is None:
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.connect(self.host)
        else:
            self.socket = socket.create_connection((self.host, self.port))
        self.readfile = self.socket.makefile('rb')
        version_line = self.readfile.readline().decode('ascii')
        parts = version_line.split()
        assert parts[0] == 'OK', version_line
        if parts[1] == 'MPD':
            self.protocol_version = tuple(int(x) for x in parts[2].split('.'))
        else:
            self.protocol_version = None
        if self.partition or self.subscriptions:
            self.command_list_begin()
            if self.partition:
                self.do_command('partition', self.partition)
            for channel in self.subscriptions:
                self.do_command('subscribe', channel)
            self.command_list_end()
        return version_line

    def close(self):
        """Close the socket.  It will be automatically reopened the next time you issue a command.
        """
        if self.socket:
            self.readfile.close()
            self.socket.close()
            self.socket = None
            self.readfile = None

    def fileno(self):
        if not self.socket:
            self.connect()
        return self.socket.fileno()

    def _send_command(self, cmd, *args, forcequote=False):
        if self.socket is None and not isinstance(self.last_cmdline, list):
            # wait to reconnect until the end of a command list.
            self.connect()

        if self._idle_in_progress:
            self.cancel_idle()

        cmdline = cmd.encode('ascii') if isinstance(cmd, str) else cmd
        if args:
            cmdline += b' ' + b' '.join(
                ('"'+arg.replace('\\', '\\\\').replace('"', '\\"')+'"'
                 if forcequote or b' ' in arg or b'"' in arg or b'\\' in arg or b"'" in arg
                 else arg)
                for uarg in args
                for arg in (uarg.encode('ascii') if isinstance(uarg, str) else uarg,)
            )
        cmdline += b'\n'

        if isinstance(self.last_cmdline, list):
            if cmd != 'command_list_end':
                self.last_cmdline.append(cmdline)
        else:
            self.last_cmdline = cmdline

        if self.socket is not None:
            self.socket.sendall(cmdline)

    def _read_response(self, enable_reconnect=True):
        line = self.readfile.readline()
        if not line:
            if not enable_reconnect:
                raise RuntimeError
            # MPD will automatically drop the connection if idle for too long.
            self.connect()
            if isinstance(self.last_cmdline, list):
                self.socket.sendall(b'command_list_begin\n')
                for cmd in self.last_cmdline: self.socket.sendall(cmd)
                self.socket.sendall(b'command_list_end\n')
            else:
                self.socket.sendall(self.last_cmdline)
            line = self.readfile.readline()
        line = line.decode('utf8')
        while not line.startswith('OK') and not line.startswith('ACK'):
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            if key == 'binary':
                value = self.readfile.read(int(value))
                self.readfile.readline()
            yield (key, value)
            line = self.readfile.readline().decode('ascii')
        if line.startswith('ACK'):
            raise MPDError(line)

    def command_list_begin(self):
        if isinstance(self.last_cmdline, list):
            return
        self._send_command('command_list_begin')
        self.last_cmdline = []

    def command_list_ok_begin(self):
        raise NotImplementedError  # TODO

    def command_list_end(self):
        assert isinstance(self.last_cmdline, list)
        self._send_command('command_list_end')
        self.last_cmdline = b''
        return list(self._read_response(enable_reconnect=False))

    def do_command(self, command, *args):
        self._send_command(command, *args)
        if not isinstance(self.last_cmdline, list):
            return list(self._read_response())

    def status(self):
        """Return the status of MPD, as a dictionary containing the keys and values sent by the server.
        """
        return dict(self.do_command('status'))

    def config(self):
        """Return a segment of the config that the client would be interested in.  This is only available to clients
        connected via a local socket (MPD reference implementation defines "local socket" as only UNIX domain sockets --
        TCP sockets originating from 127.0.0.1 do not count!).  MPD reference implementation currently only returns the
        music directory.
        """
        return dict(self.do_command('config'))

    def find(self, tag, comparison, value):
        pass

    def switch_partition(self, partition):
        self.do_command('partition', partition)
        self.partition = partition

    def subscribe(self, channel):
        """Subscribe to a client-to-client (C2C) communication channel.  If the channel does not exist on the server,
        this command will create it.  Channel names must be purely alphanumeric plus hyphens and dots, but this client
        implementation leaves that up to the server to actually enforce.  If the client is already subscribed to this
        channel, do nothing.
        """
        if channel in self.subscriptions:
            # no point bothering the server
            # XXX should we bother the server anyway to avoid possible bugs, and possible slowdowns due to scanning
            # the set every time?
            return
        try:
            self.do_command('subscribe', channel)
        except MPDError as e:
            if e.code != 56:  # already subscribed
                raise
        self.subscriptions.add(channel)

    def unsubscribe(self, channel):
        """Unsubscribe from a C2C channel.
        """
        self.do_command('unsubscribe', channel)

    def send_message(self, channel, message):
        """Send a message on a C2C channel.  The server does assume anything special in the content of the message,
        merely forwards it to the other clients.  It must be 7-bit clean.
        """
        self.do_command('sendmessage', channel, message)

    def read_messages(self):
        """
        Retrieve messages from the server and populate self.pending_messages.
        """
        channel = None
        for k, v in self.do_command('readmessages'):
            if k == 'channel':
                channel = v
            elif k == 'message':
                self.pending_messages.setdefault(channel, []).append(v)

    def send_idle(self, subsystems):
        """
        Send an idle command to the server, tying up the line until it finishes.
        Running any other command before calling receive_idle() will abort the idle command.
        If this function is called and an idle command is already in progress, it will be aborted and restarted if the
        subsystem list currently being monitored is different from the list in `subsystems`; otherwise no action will
        be taken.

        :param subsystems: list of subsystems to monitor
        """
        frozenset_subsystems = frozenset(subsystems)
        assert frozenset_subsystems, "Must idle on at least one subsystem"
        if not self._idle_in_progress or self._idle_in_progress != frozenset_subsystems:
            self._send_command('idle', *subsystems)
            self._idle_in_progress = frozenset_subsystems

    def cancel_idle(self):
        """You MUST call this after manually calling send_idle before doing anything else with the connection
        if you don't intend to wait for receive_idle.
        """
        if not self._idle_in_progress: return
        self.socket.sendall(b'noidle\n')
        subsystems = self.receive_idle()
        if subsystems:
            # I have no idea under what circumstances this could happen, other than a race condition,
            # so I can't really create a unit test for it.
            if self._idle_cancel_callback:
                self._idle_cancel_callback(subsystems)
            else:
                raise ValueError("Aborted idle command returned results and no callback was registered to handle them")

    def receive_idle(self):
        subsystems = [v for k, v in self._read_response() if k == 'changed']
        self._idle_in_progress = None
        return subsystems


