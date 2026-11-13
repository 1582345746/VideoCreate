"""Keep Tk variables and completion callbacks on their owning UI thread."""
import queue
import sys
import threading
import tkinter as tk


_interpreters = {}
_ui_thread = None


def reap_interpreters():
    """Release unused Tcl interpreters on the UI thread, including after worker GC.

    Destroyed widgets retained by Python cycles still reference their tkapp. A
    later worker may collect those cycles. Keep one interpreter reference until
    no widget/variable owns it; dropping that last reference here avoids Tcl's
    fatal wrong-thread interpreter deletion. CPython/Tk is the manager runtime.
    """
    if _ui_thread is not None and threading.get_ident() != _ui_thread:
        raise RuntimeError('Tcl interpreters must be released on their UI thread')
    for identity in tuple(_interpreters):
        interpreter = _interpreters[identity]
        # Registry, this local and getrefcount's temporary argument only.
        if sys.getrefcount(interpreter) == 3:
            del _interpreters[identity]


class _Variables:
    def __init__(self, owner):
        self.owner = owner
        self.values = []
        owner.bind('<Destroy>', self.destroyed, add='+')

    def destroyed(self, event):
        if event.widget is not self.owner:
            return
        for value in self.values:
            # Traces own Python callbacks and can retain entire closed forms.
            # Remove them before unsetting, so teardown cannot invoke UI code.
            for mode, command in value.trace_info():
                value.trace_remove(mode, command)
            value.__del__()
            # The real Tcl cleanup above has finished on the UI thread. Later
            # Python collection must neither call nor retain this interpreter.
            value._tk = None
            value._root = None
        self.values.clear()
        self.owner = None


def _retain_interpreter(master):
    global _ui_thread
    if _ui_thread is None:
        _ui_thread = threading.get_ident()
    reap_interpreters()
    if not isinstance(master, tk.Misc) or not master.winfo_exists():
        raise ValueError('A live, explicit Tk widget must own each UI variable')
    _interpreters[id(master.tk)] = master.tk


def _variable(kind, master, value):
    _retain_interpreter(master)
    scope = getattr(master, '_videocreate_variables', None)
    if scope is None:
        scope = master._videocreate_variables = _Variables(master)
    result = kind(master, value=value)
    scope.values.append(result)
    return result


def StringVar(master, value=None):
    return _variable(tk.StringVar, master, value)


def BooleanVar(master, value=None):
    return _variable(tk.BooleanVar, master, value)


def _work(channel, function, arguments, options):
    """Worker receives data and a service function, never a UI callback."""
    try:
        channel.put((True, function(*arguments, **options)))
    except Exception as exc:
        channel.put((False, exc))


class BackgroundCall:
    """One in-flight service call; destroying its widget detaches the UI only."""
    def __init__(self, owner, *, interval=100):
        _retain_interpreter(owner)
        self.owner, self.interval = owner, interval
        self.channel = queue.Queue()
        self.busy = False
        self.closed = False
        self.scheduled = None
        self.completed = self.failed = None
        owner.bind('<Destroy>', self.destroyed, add='+')

    def start(self, function, *arguments, completed, failed, **options):
        if self.closed or self.busy:
            return False
        self.busy = True
        self.completed, self.failed = completed, failed
        threading.Thread(target=_work, args=(self.channel, function, arguments, options),
                         daemon=False).start()
        self.scheduled = self.owner.after(self.interval, self.receive)
        return True

    def receive(self):
        reap_interpreters()
        self.scheduled = None
        try:
            ok, result = self.channel.get_nowait()
        except queue.Empty:
            self.scheduled = self.owner.after(self.interval, self.receive)
            return
        self.busy = False
        callback = self.completed if ok else self.failed
        self.completed = self.failed = None
        callback(result)

    def destroyed(self, event):
        if event.widget is not self.owner:
            return
        self.closed = True
        if self.scheduled is not None:
            self.owner.after_cancel(self.scheduled)
            self.scheduled = None
        self.completed = self.failed = None
        self.owner = None
