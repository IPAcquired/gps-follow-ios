"""Headless, native-size X11 desktop for the paired display. No network listener."""
import os,re,subprocess,threading,time

_lock=threading.Lock()
_size=None
_checked=0.0
_active=False
_opened=False
SIZES={(320,436),(480,276),(800,600)}

def command(args,timeout=3):
    env={**os.environ,'DISPLAY':':0','XAUTHORITY':'/home/drone/.Xauthority','DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus'}
    return subprocess.run(args,env=env,capture_output=True,text=True,timeout=timeout,check=True)

def ensure_size(width,height):
    global _size,_checked,_active,_opened
    if (width,height) not in SIZES:raise ValueError('Unsupported touch workspace')
    with _lock:
        if _size==(width,height) and time.monotonic()-_checked<10:return True
        screen=command(['xrandr','--current']).stdout
        # Never change an attached physical monitor's video mode.
        if re.search(r'^\S+ connected(?: primary)? ',screen,re.M):_active=False;return False
        if f'current {width} x {height},' not in screen:
            command(['xrandr','--fb',f'{width}x{height}'])
        monitors=command(['xrandr','--listmonitors']).stdout
        geometry=f'{width}/{round(width*25.4/96)}x{height}/{round(height*25.4/96)}+0+0'
        if 'AXL-ESP32' not in monitors or geometry not in monitors:
            if 'AXL-ESP32' in monitors:command(['xrandr','--delmonitor','AXL-ESP32'])
            command(['xrandr','--setmonitor','AXL-ESP32',geometry,'none'])
        _size=(width,height);_checked=time.monotonic();_active=True
        if not _opened:launch('apps');_opened=True
        return True

def start(stop):
    def watch():
        previous=None
        while not stop.wait(.5):
            if not _active:previous=None;continue
            try:
                window=command(['xdotool','getactivewindow']).stdout.strip()
                identity=(window,_size)
                if not window.isdigit() or identity==previous:continue
                previous=identity
                kind=command(['xprop','-id',window,'_NET_WM_WINDOW_TYPE']).stdout
                if '_NET_WM_WINDOW_TYPE_NORMAL' in kind:
                    command(['wmctrl','-i','-r',hex(int(window)),'-b','remove,maximized_vert,maximized_horz'])
                    command(['wmctrl','-i','-r',hex(int(window)),'-e',f'0,0,27,{_size[0]},{max(150,_size[1]-52)}'])
                    command(['wmctrl','-i','-r',hex(int(window)),'-b','add,maximized_vert,maximized_horz'])
            except (OSError,subprocess.SubprocessError):pass
    threading.Thread(target=watch,name='touch-window-fit',daemon=True).start()

def launch(which):
    choices={'apps':['/home/drone/bin/orangepi-touch-desktop'],
             'web':['/home/drone/bin/orangepi-touch-desktop','--web'],
             'files':['thunar','/home/drone']}
    if which not in choices:raise ValueError('Unknown desktop application')
    env={**os.environ,'DISPLAY':':0','XAUTHORITY':'/home/drone/.Xauthority','DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus'}
    subprocess.Popen(choices[which],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
