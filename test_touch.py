"""Run under a disposable X11 display and a private D-Bus session."""
import os
from pathlib import Path
import sys
import tempfile
import time
import ctypes
from types import SimpleNamespace
from field_metrics import Reading
import pi_health as ui
from gi.repository import Gdk,Gtk,GdkPixbuf

def settle():
    for _ in range(12):
        while Gtk.events_pending():Gtk.main_iteration_do(False)
        time.sleep(.01)

class Example:
    def read(self,detailed=True):
        rows={"pi.cpu_temp":Reading("Orange Pi","CPU temperature","63.2 °C"),
              "pi.state":Reading("Orange Pi","Operating state","normal",age=.5)}
        for k in range(9):
            rows["probe"+str(k)]=Reading("Flight sensors","IMU · axis "+str(k),str(10+k)+" mG",age=.2)
        return rows

def image(widget,out,maxwidth=480):
    w,h=widget.get_size()
    pix=Gdk.pixbuf_get_from_window(widget.get_window(),0,0,w,h)
    if pix.get_width()>maxwidth:pix=pix.scale_simple(maxwidth,round(h*maxwidth/w),GdkPixbuf.InterpType.BILINEAR)
    pix.savev(str(out),"png",[],[])

def main():
    a=ui.Health();assert a.register(None)
    a.sampler=Example();a.activate();settle()
    assert a.corner.label=="CPU 63° · Normal"
    w1=a.overlay.get_size()[0]
    a.corner.press(None,SimpleNamespace(x=3,x_root=12*a.scale,time=100,button=1))
    a.corner.release(None,SimpleNamespace(x_root=0,time=180));settle()
    w2=a.overlay.get_size()[0]
    assert a.collapsed and w2<w1 and a.corner.get_visible(),(w1,w2)
    a.corner.press(None,SimpleNamespace(x=3,x_root=3,time=200,button=1))
    a.corner.release(None,SimpleNamespace(x_root=3,time=218));settle();assert not a.collapsed
    # A real XTest mouse click over the readout must reach an independent window.
    base=Gtk.Window();base.set_decorated(False);base.set_default_size(w1+20,a.corner.height+20)
    clicks=[];ev=Gtk.EventBox();ev.connect("button-press-event",lambda *_:clicks.append(1));base.add(ev)
    base.move(0,0);base.show_all();settle();a.overlay.get_window().raise_();settle()
    lib=ctypes.CDLL("libX11.so.6");xt=ctypes.CDLL("libXtst.so.6")
    lib.XOpenDisplay.argtypes=[ctypes.c_char_p];lib.XOpenDisplay.restype=ctypes.c_void_p
    dpy=ctypes.c_void_p(lib.XOpenDisplay(None))
    rootx,rooty=a.overlay.get_position();xt.XTestFakeMotionEvent(dpy,-1,rootx+a.corner.tab+int(10*a.scale),rooty+a.corner.height//2,0)
    xt.XTestFakeButtonEvent(dpy,1,1,0);xt.XTestFakeButtonEvent(dpy,1,0,0);lib.XSync(dpy,0);settle()
    assert clicks==[1] and not a.menu,"The overlay intercepted the test click"
    # Both transparent areas and painted text must remain in the actual backing surface.
    buf=memoryview(a.corner.surface.get_data());stride=a.corner.surface.get_stride()
    alpha=[buf[y*stride+x*4+3] for y in range(a.corner.height) for x in range(a.corner.tab,w1) if x<a.corner.surface.get_width()]
    assert alpha.count(0)>len(alpha)//3 and alpha.count(255)>20
    lib.XCloseDisplay(dpy);base.destroy()
    a.open_menu();settle()
    width,height=Gdk.Screen.get_default().get_width(),Gdk.Screen.get_default().get_height()
    a.menu.resize(width,height);settle()
    assert a.menu.get_size()[0]<=width and a.menu.get_size()[1]<=height
    if len(sys.argv)>1:image(a.menu,Path(sys.argv[1]))
    a.groups.set_active(ui.GROUPS.index("Flight sensors"));a.next.clicked();assert a.page==1
    a.cells[1][-1].clicked();assert a.pin=="probe5"
    a.close_menu();settle()
    assert "15 mG" in a.corner.label and a.overlay.get_visible()
    assert ui.load_view()==("probe5",False)
    print("Open, slide, restore, repin on next page, persisted choice; corner expanded/collapsed:",w1,w2,"desktop",width,height)

if __name__=="__main__":main()
