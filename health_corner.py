"""A shaped X11 readout. Only the narrow edge handle can receive input."""
import cairo
import gi
gi.require_version("Gtk","3.0")
gi.require_version("PangoCairo","1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo


class Corner(Gtk.DrawingArea):
    def __init__(self,window,scale,toggle,open_menu):
        super().__init__()
        self.window=window;self.scale=scale;self.toggle=toggle;self.open_menu=open_menu
        self.label="";self.collapsed=False;self.surface=None;self.pressed=None
        self.tab=max(22,round(22*scale));self.height=max(22,round(22*scale))
        window.set_app_paintable(True)
        screen=window.get_screen()
        visual=screen.get_rgba_visual()
        if visual:window.set_visual(visual)
        window.add_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK)
        window.connect("button-press-event",self.press)
        window.connect("button-release-event",self.release)
        window.connect("realize",lambda *_:self.apply_shape())
        window.connect("size-allocate",lambda *_:self.apply_shape())
        screen.connect("composited-changed",lambda *_:self.paint())
        # Paint the complete toplevel, including alpha, before GTK paints decorations.
        window.connect("draw",self.draw_corner)
        self.paint()

    def update(self,label,collapsed):
        if (label,collapsed)!=(self.label,self.collapsed):
            self.label=label;self.collapsed=collapsed;self.paint()

    def paint(self):
        s=self.scale
        layout=self.create_pango_layout(self.label)
        font=Pango.FontDescription.from_string("Sans Bold")
        font.set_absolute_size(13*s*Pango.SCALE);layout.set_font_description(font)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        natural=layout.get_pixel_size()[0]
        width=min(natural,round(150*s));layout.set_width(max(1,width)*Pango.SCALE)
        box_w=self.tab if self.collapsed else self.tab+width+round(7*s)
        self.surface=cairo.ImageSurface(cairo.FORMAT_ARGB32,box_w,self.height)
        ctx=cairo.Context(self.surface)
        # Only the tab has a solid fill. Its full area always remains a usable touch target.
        ctx.set_source_rgb(.09,.17,.2);ctx.rectangle(0,0,self.tab,self.height);ctx.fill()
        x=self.tab*.5;y=self.height*.5;direction=1 if self.collapsed else -1
        ctx.set_source_rgb(.92,.97,.98);ctx.set_line_width(max(1,2*s));ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(x-direction*2*s,y-4*s);ctx.line_to(x+direction*2*s,y);ctx.line_to(x-direction*2*s,y+4*s);ctx.stroke()
        if not self.collapsed:
            ctx.move_to(self.tab+3*s,(self.height-layout.get_pixel_size()[1])/2)
            PangoCairo.layout_path(ctx,layout)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND);ctx.set_line_width(2.25*s)
            ctx.set_source_rgba(.025,.045,.055,.98);ctx.stroke_preserve()
            ctx.set_source_rgb(1,1,1);ctx.fill()
        self.set_size_request(box_w,self.height)
        self.window.resize(box_w,self.height)
        self.apply_shape();self.window.queue_draw()

    def apply_shape(self):
        win=self.window.get_window()
        if not win or self.surface is None:return
        # The same glyph mask also works on X11 desktops without a compositor.
        bounding=Gdk.cairo_region_create_from_surface(self.surface)
        win.shape_combine_region(bounding,0,0)
        win.input_shape_combine_region(cairo.Region(cairo.RectangleInt(0,0,self.tab,self.height)),0,0)

    def draw_corner(self,win,ctx):
        if self.surface is None:return False
        ctx.set_operator(cairo.OPERATOR_SOURCE);ctx.set_source_surface(self.surface,0,0);ctx.paint()
        return True

    def press(self,win,event):
        if event.button not in (1,3) or event.x>self.tab:return False
        self.pressed=(event.x_root,event.time,event.button)
        return True

    def release(self,win,event):
        if self.pressed is None:return False
        start,stamp,button=self.pressed;self.pressed=None
        if button==3 or (event.time-stamp)%2**32>=650:self.open_menu()
        elif event.x_root<start-8*self.scale:self.toggle(True)
        elif event.x_root>start+8*self.scale:self.toggle(False)
        else:self.toggle(not self.collapsed)
        return True
