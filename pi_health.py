#!/usr/bin/python3
"""Touch dashboard and a collapsible health indicator for the local Pi desktop."""
import json
import os
from pathlib import Path
import tempfile
import gi
gi.require_version("Gtk","3.0")
gi.require_version("Gdk","3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango
from field_metrics import Sampler
from health_corner import Corner


PREFS=Path.home()/".config/orangepi-field-health/view.json"
GROUPS=("Orange Pi","Temperatures","Cooling / power","Controller","Flight sensors","Pi peripherals")


def load_view(path=PREFS):
    try:
        state=json.loads(path.read_bytes())
        return str(state.get("pinned","pi.cpu_temp"))[:120], state.get("collapsed") is True
    except (OSError,ValueError,AttributeError):
        return "pi.cpu_temp",False


def save_view(pin,collapsed,path=PREFS):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile("w",dir=path.parent,delete=False) as f:
        json.dump({"pinned":pin,"collapsed":collapsed},f);f.flush();os.fsync(f.fileno())
    os.replace(f.name,path)


def pad_label(initial="",align=0):
    widget=Gtk.Label(label=initial,xalign=align)
    widget.set_ellipsize(Pango.EllipsizeMode.END)
    return widget


def changed(widget,value):
    if widget.get_text()!=value:widget.set_text(value)


def age_label(r):
    if r.age is None:return r.status
    if r.age<1:return r.status+" · <1 s"
    if r.age<60:return r.status+f" · {int(r.age)} s"
    return r.status+" · "+(f"{int(r.age//60)} min" if r.age<86400 else ">1 day")


class Health(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.orangepi.FieldHealth",flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("overlay",0,GLib.OptionFlags.NONE,GLib.OptionArg.NONE,"Start the corner indicator",None)
        self.overlay=None;self.menu=None;self.sampler=Sampler()
        self.pin,self.collapsed=load_view()
        self.group=GROUPS[0];self.page=0;self.rows={};self.keys=[]

    def do_command_line(self,command):
        self.activate()
        if not (command.get_options_dict().contains("overlay") or "--overlay" in command.get_arguments()):self.open_menu()
        return 0

    def do_activate(self):
        if self.overlay is not None:return
        display=Gdk.Display.get_default()
        monitor=display.get_primary_monitor() or display.get_monitor(0)
        self.scale=max(1,min(4, min(monitor.get_geometry().width/480,monitor.get_geometry().height/296)))
        self.monitor=monitor
        self.css=Gtk.CssProvider()
        s=self.scale
        css=f"""
        #health-menu, #health-menu button, #health-menu combobox {{font-size:{round(13*s)}px;}}
        #health-menu #value {{font-weight:bold;}}
        #health-menu #status {{font-size:{round(11*s)}px;}}
        #health-menu button {{padding:{round(2*s)}px {round(7*s)}px; min-height:{round(23*s)}px;}}
        """
        self.css.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),self.css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.overlay=Gtk.ApplicationWindow(application=self)
        self.overlay.set_name("health-corner");self.overlay.set_title("Pi health indicator")
        self.overlay.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.overlay.set_decorated(False);self.overlay.set_resizable(False)
        self.overlay.set_skip_taskbar_hint(True);self.overlay.set_skip_pager_hint(True)
        self.overlay.set_accept_focus(False);self.overlay.set_focus_on_map(False)
        self.overlay.set_keep_above(True);self.overlay.stick()
        self.corner=Corner(self.overlay,s,self.collapse,self.open_menu)
        self.overlay.add(self.corner)
        self.overlay.connect("map-event",lambda *_:self.position())
        self.overlay.show_all();self.update_corner();self.refresh()
        self.monitor.connect("notify::geometry", lambda *_:self.position())
        self.monitor.connect("notify::workarea", lambda *_:self.position())
        GLib.timeout_add_seconds(2,self.refresh)

    def position(self):
        area=self.monitor.get_workarea()
        self.overlay.move(area.x,area.y+round(2*self.scale))
        return False

    def collapse(self,new):
        self.collapsed=new;save_view(self.pin,self.collapsed)
        self.update_corner();self.refresh()

    def update_corner(self):
        self.corner.update(self.corner.label,self.collapsed)
        self.position()

    def refresh(self):
        visible=self.menu is not None and self.menu.get_visible()
        if self.collapsed and not visible:return True
        self.rows=self.sampler.read(detailed=visible or self.pin not in ("pi.cpu_temp","pi.state"))
        r=self.rows.get(self.pin)
        state=self.rows["pi.state"]
        if self.pin=="pi.cpu_temp":
            value=r.value.split(".")[0]+"°" if r and r.status=="Live" else "—"
            label="CPU "+value+" · "+(state.value.capitalize() if state.status=="Live" else "Unknown")
        elif r:
            label=r.label.split(" · ")[-1][:13]+" "+(r.value if r.status=="Live" else "—")
        else:label="Pinned · unavailable"
        self.corner.update(label,self.collapsed)
        if visible:self.render()
        return True

    def open_menu(self):
        if self.menu is None:self.make_menu()
        self.overlay.hide()
        self.menu.show_all();self.menu.maximize();self.menu.present();self.refresh()

    def close_menu(self,*unused):
        self.menu.hide();self.overlay.show();self.update_corner();self.refresh()
        return True

    def make_menu(self):
        self.menu=Gtk.ApplicationWindow(application=self);self.menu.set_title("Pi health and sensors")
        self.menu.set_name("health-menu");self.menu.connect("delete-event",self.close_menu)
        self.menu.set_default_size(round(450*self.scale),round(245*self.scale))
        body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=round(3*self.scale))
        body.set_border_width(round(5*self.scale));self.menu.add(body)
        top=Gtk.Box(spacing=round(4*self.scale));body.pack_start(top,False,False,0)
        self.groups=Gtk.ComboBoxText()
        for group in GROUPS:self.groups.append_text(group)
        self.groups.set_active(0)
        self.groups.connect("changed",self.select_group);top.pack_start(self.groups,True,True,0)
        close=Gtk.Button.new_with_label("Back");close.connect("clicked",self.close_menu);top.pack_end(close,False,False,0)
        self.cells=[]
        for i in range(4):
            row=Gtk.Box(spacing=round(4*self.scale))
            lab=Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            name=pad_label();status=pad_label();status.set_name("status")
            lab.pack_start(name,True,True,0);lab.pack_start(status,True,True,0)
            row.pack_start(lab,True,True,0)
            value=pad_label(align=1);value.set_name("value");value.set_max_width_chars(18)
            row.pack_start(value,False,False,0)
            button=Gtk.Button.new_with_label("Pin");button.connect("clicked",self.set_pin,i)
            row.pack_end(button,False,False,0);body.pack_start(row,True,True,0)
            self.cells.append((row,name,status,value,button))
        foot=Gtk.Box(spacing=round(4*self.scale));body.pack_end(foot,False,False,0)
        self.prev=Gtk.Button.new_with_label("‹ Prev");self.next=Gtk.Button.new_with_label("Next ›")
        self.prev.connect("clicked",self.turn,-1);self.next.connect("clicked",self.turn,1)
        self.page_label=pad_label(align=.5)
        foot.pack_start(self.prev,False,False,0);foot.pack_start(self.page_label,True,True,0);foot.pack_end(self.next,False,False,0)

    def select_group(self,combo):
        self.group=combo.get_active_text() or GROUPS[0];self.page=0;self.render()

    def turn(self,button,delta):
        self.page+=delta;self.render()

    def set_pin(self,button,index):
        slot=self.page*4+index
        if slot>=len(self.keys):return
        self.pin=self.keys[slot];self.collapsed=False;save_view(self.pin,False)
        self.refresh()

    def render(self):
        self.keys=[k for k,r in self.rows.items() if r.group==self.group]
        pages=max(1,(len(self.keys)+3)//4)
        self.page=max(0,min(self.page,pages-1));changed(self.page_label,f"{self.page+1} / {pages}")
        self.prev.set_sensitive(self.page>0);self.next.set_sensitive(self.page+1<pages)
        for i,(row,name,status,value,button) in enumerate(self.cells):
            slot=self.page*4+i;valid=slot<len(self.keys)
            row.set_visible(valid)
            if valid:
                key=self.keys[slot];r=self.rows[key]
                changed(name,r.label);changed(status,age_label(r));changed(value,r.value)
                name.set_tooltip_text(r.label);value.set_tooltip_text(r.value)
                new="Pinned" if key==self.pin else "Pin"
                if button.get_label()!=new:button.set_label(new)


if __name__=="__main__":
    import sys
    raise SystemExit(Health().run(sys.argv))
