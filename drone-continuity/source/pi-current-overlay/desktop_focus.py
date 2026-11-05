"""Local accessibility focus only; never reads field names, contents or passwords."""
import threading
import time
import os
import secrets

_lock = threading.Lock()
_started = False
_focus = None
_revision = secrets.randbelow(999999999) + 1
_editable = False
_checked = 0.0


def snapshot():
    with _lock:
        fresh = bool(_checked and time.monotonic() - _checked < 2)
        return {'known': fresh, 'editable': fresh and _editable, 'revision': _revision}


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_run, name='desktop-focus', daemon=True).start()


def _run():
    global _focus, _revision, _editable, _checked
    try:
        os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{os.getuid()}/bus')
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi, GLib, Gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync('org.a11y.Bus', '/org/a11y/bus', 'org.freedesktop.DBus.Properties',
                      'Set', GLib.Variant('(ssv)', ('org.a11y.Status', 'IsEnabled', GLib.Variant('b', True))),
                      None, Gio.DBusCallFlags.NONE, 1000, None)
        Atspi.init()
        Atspi.set_timeout(100, 100)

        def check():
            global _editable, _checked
            try:
                with _lock:
                    target = _focus
                states = target.get_state_set() if target is not None else None
                editable = bool(states and states.contains(Atspi.StateType.FOCUSED)
                                and states.contains(Atspi.StateType.EDITABLE)
                                and states.contains(Atspi.StateType.ENABLED))
                with _lock:
                    _editable, _checked = editable, time.monotonic()
            except Exception:
                with _lock:
                    _editable, _checked = False, 0.0
            return True

        def focused(event):
            global _focus, _revision
            with _lock:
                _focus = event.source if event.detail1 else None
                _revision = (_revision + 1) % 1000000000 or 1
            check()

        listener = Atspi.EventListener.new(focused)
        listener.register('object:state-changed:focused')
        GLib.timeout_add(500, check)
        Atspi.event_main()
    except Exception:
        with _lock:
            _editable, _checked = False, 0.0
