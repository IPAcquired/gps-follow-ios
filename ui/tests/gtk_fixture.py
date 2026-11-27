"""Exercise normal GTK actions on an isolated display with synthetic owner/private state."""
from pathlib import Path
import sys
import tempfile
import time
from test_review import FixtureAPI
from field_change_review import Reviews
from field_review_gtk import GLib, Gtk, Window


def settle():
    for _ in range(15):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(.012)


def find_button(w, name):
    for child in w.get_children():
        if isinstance(child,Gtk.Button) and child.get_label()==name:
            return child
        if isinstance(child,Gtk.Container):
            nested=find_button(child,name)
            if nested:return nested


def main():
    with tempfile.TemporaryDirectory() as tmp:
        width,height=(map(int,sys.argv[2].split("x")) if len(sys.argv)>2 else (480,296))
        home=Path(tmp)
        api=FixtureAPI()
        reviews=Reviews(home,api,lambda:True)
        folder=reviews.queues["controller"];folder.mkdir(mode=0o700,parents=True)
        candidate=folder/"candidate.json";candidate.write_text('{"fixture":true}');candidate.chmod(0o600)
        item=reviews.discover()[0]
        w=Window(reviews);w.resize(width,height);w.show_all();settle()
        list_button=next(x for x in w.body.get_children() if isinstance(x,Gtk.Button))
        list_button.clicked();settle()
        assert w.item==item and reviews.receipt(item) is None
        for name in ("Approve digest","Decline","Later"):
            button=find_button(w,name)
            assert button.get_sensitive() and button.get_allocated_height()>=38
            x,y=button.translate_coordinates(w,0,0)
            assert 0<=x and y+button.get_allocated_height()<=w.get_allocated_height()
        assert w.get_allocated_width()<=width and w.get_allocated_height()<=height
        assert w.scale>=width/480-.1
        if len(sys.argv)>1:
            from gi.repository import Gdk,GdkPixbuf
            buf=Gdk.pixbuf_get_from_window(w.get_window(),0,0,w.get_allocated_width(),w.get_allocated_height())
            if width>480:
                buf=buf.scale_simple(480,round(buf.get_height()*480/buf.get_width()),GdkPixbuf.InterpType.BILINEAR)
            assert buf.savev(sys.argv[1],"png",[],[])
        find_button(w,"Later").clicked()
        assert w.item is None and reviews.receipt(item) is None
        w.open_item(item)
        GLib.idle_add(lambda: (w.decision_dialog.response(Gtk.ResponseType.CANCEL),False)[1])
        find_button(w,"Approve digest").clicked()
        assert reviews.receipt(item) is None
        def stale():
            api.state="pending"
            w.decision_dialog.response(Gtk.ResponseType.OK)
            return False
        GLib.idle_add(stale)
        find_button(w,"Approve digest").clicked()
        assert reviews.receipt(item) is None and not find_button(w,"Approve digest").get_sensitive()
        api.state="ready_for_owner";w.open_item(item)
        GLib.idle_add(lambda: (w.decision_dialog.response(Gtk.ResponseType.OK),False)[1])
        find_button(w,"Approve digest").clicked();settle()
        assert reviews.receipt(item)["decision"]=="approved"
        assert find_button(w,"Approve digest") is None
        w.destroy()
    print(f"GTK {width}x{height} verified: candidate details, reachable action buttons, Later, Cancel, stale confirmation, exact owner approval.")


if __name__=="__main__":
    main()
