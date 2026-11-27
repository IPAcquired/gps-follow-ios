"""Touch-sized review pages for the existing owner desktop."""
import shlex
import subprocess
import threading
import time
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango
from field_change_review import Held, NAMES, PROFILES, approval_current, clean, describe_error


def label(text, *, large=False, wrap=True):
    value = Gtk.Label(label=text, xalign=0)
    value.set_line_wrap(wrap)
    value.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    value.set_max_width_chars(48)
    if large:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        attrs.insert(Pango.attr_scale_new(1.15))
        value.set_attributes(attrs)
    return value


class Window(Gtk.Window):
    def __init__(self, reviews):
        super().__init__(title="Field change review")
        self.reviews = reviews
        self.model_jobs = {}
        self.set_name("field-review")
        self.scale = 1
        self.styles = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), self.styles,
                                                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.connect("size-allocate", self.size_for_field_screen)
        self.set_default_size(600, 370)
        self.set_border_width(9)
        self.main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.add(self.main)
        self.header = label("Field change review", large=True)
        self.main.pack_start(self.header, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroll.add(self.body)
        self.main.pack_start(scroll, True, True, 0)
        self.actions = Gtk.Box(spacing=5, homogeneous=True)
        self.main.pack_start(self.actions, False, False, 0)
        self.item = None
        self.decision_dialog = None
        self.list_page()

    def size_for_field_screen(self, _, area):
        # The paired panel fits the whole Pi desktop into 480 × 296.
        scale = max(1, round(max(area.width/480, area.height/296), 1))
        if self.scale == scale:
            return
        self.scale = scale
        font = Pango.FontDescription.from_string(self.get_settings().get_property("gtk-font-name"))
        points = max(9, font.get_size()/Pango.SCALE)*scale
        selector = "#field-review, #field-review-confirm"
        buttons = "#field-review button, #field-review-confirm button"
        self.styles.load_from_data((f"{selector} {{font-size:{points:.1f}pt;}} "
                                   f"{buttons} {{min-height:{round(32*scale)}px;}}").encode())
        self.set_border_width(round(9*scale))
        self.body.set_spacing(round(6*scale))
        self.actions.set_spacing(round(5*scale))

    def page(self, title):
        self.header.set_text(title)
        for container in (self.body, self.actions):
            for child in container.get_children():
                child.destroy()

    def note(self, text, bold=False):
        self.body.pack_start(label(text, large=bold), False, False, 0)

    def button(self, text, callback, area=None, active=True):
        button = Gtk.Button(label=text)
        button.set_size_request(-1, 40)
        button.set_sensitive(active)
        button.connect("clicked", lambda *_: callback())
        (area or self.actions).pack_start(button, False, False, 0)
        return button

    def list_page(self, message=None):
        self.item = None
        self.page("Field change review")
        if message:
            self.note(message, True)
        items = []
        if not self.reviews:
            self.note("Install the local model review service to open proposals.")
        else:
            try:
                items = self.reviews.discover()
                if not items:
                    self.note("No pending proposals.")
                for item in items:
                    receipt = self.reviews.receipt(item)
                    state = receipt["decision"].capitalize() if receipt else "Review"
                    self.button(f"{state}  ·  {NAMES[item.kind]}  ·  {item.digest[:10]}",
                                lambda item=item: self.open_item(item), self.body)
            except (OSError, ValueError, TypeError) as error:
                self.note(describe_error(error))
        self.button("Refresh", self.list_page)
        self.button("Close", self.close)
        self.show_all()

    def open_item(self, item, message=None):
        self.item = item
        self.page(NAMES[item.kind]+"  ·  "+item.digest[:10])
        if message:
            self.note(message, True)
        try:
            subject, review = self.reviews.details(item)
            receipt = self.reviews.receipt(item)
            self.note(clean(subject["reason"]))
            if item.kind == "controller":
                self.note("Route  "+clean(subject["route"])+"   ·   "+clean(subject["operation"]))
            for field, change in subject["changes"].items():
                self.note(f"{clean(field)}     {clean(change['from'])}   →   {clean(change['to'])}", True)
            if not subject["changes"]:
                self.note("No settings would change.")
            self.note("Model review  ·  "+clean(review["reason"]).replace("_", " "))
            votes = {v.get("profile"): v for v in review.get("votes", [])}
            for name in PROFILES:
                vote = votes.get(name)
                self.note(f"{name.capitalize()}  ·  "+(clean(vote["vote"])+"  ·  "+clean(vote["reason"]).replace("_", " ")
                                                     if vote else "Awaiting current vote"))
            deadline = review.get("expires_unix") or subject.get("expires_unix")
            if deadline:
                self.note("Review valid until "+time.strftime("%H:%M:%S %Z", time.localtime(deadline)))
            self.note("SHA-256  "+item.digest)
            if receipt and receipt["decision"]=="approved" and not approval_current(receipt,review):
                self.note("The previous approval no longer matches a current review. Review again before applying.")
                receipt = None
            if receipt:
                self.note("Owner "+receipt["decision"]+" this exact digest.", True)
                if receipt["decision"] == "approved":
                    if item.kind == "ai-policy":
                        self.button("Apply approved policy", lambda: self.apply_policy(item),
                                    active=review["status"] == "ready_for_owner")
                    else:
                        self.controller_handoff(item, subject)
                self.button("Back", self.list_page)
            else:
                can_approve = bool(subject["changes"]) and review.get("status") == "ready_for_owner"
                self.button("Approve digest", lambda: self.confirm(item, "approved"), active=can_approve)
                self.button("Decline", lambda: self.confirm(item, "declined"))
                self.button("Later", self.list_page)
                if not can_approve:
                    self.button("Recheck review", lambda: self.open_item(item), self.body)
                    if review.get("status")=="pending":
                        running = self.model_jobs.get(item.digest)
                        self.button("Model review running" if running and running.poll() is None else "Request local model review",
                                    lambda: self.request_model_review(item), self.body,
                                    active=not running or running.poll() is not None)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.note("Manual review required.", True)
            self.note(describe_error(error))
            self.button("Back", self.list_page)
        self.show_all()

    def request_model_review(self, item):
        try:
            if not self.reviews.owner():
                raise Held("Unlock the local owner desktop first.")
            self.reviews.details(item)
            previous = self.model_jobs.get(item.digest)
            if previous is None or previous.poll() is not None:
                command = [str(self.reviews.home/"bin/orangepi-ai-team"), "--review-proposal", str(item.path),
                           "--review-kind", item.kind, "--review-sha256", item.digest]
                self.model_jobs[item.digest] = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            message = "Local review requested. Recheck here for the result."
        except (OSError, ValueError, KeyError, TypeError) as error:
            message = describe_error(error)
        self.open_item(item, message)

    def controller_handoff(self, item, subject):
        self.note("Controller changes await the existing guarded maintenance tool. Begin an approved operation only while grounded.")
        if subject["operation"] != "apply" or subject["route"] != "pi-uart0":
            self.note("Manual handoff requires the original rollback journal or the separately identified USB port.")
            return
        cmd = [str(self.reviews.home/".local/bin/orangepi-field-review"), "--apply-controller", item.digest]
        self.note("Open this command in the owner's terminal to recheck the votes and use the existing maintenance tool.")
        instruction = label(shlex.join(cmd))
        instruction.set_selectable(True)
        self.body.pack_start(instruction, False, False, 0)

    def confirm(self, item, decision):
        dialog = Gtk.Dialog(title="Confirm owner decision", transient_for=self, modal=True)
        self.decision_dialog = dialog
        dialog.set_name("field-review-confirm")
        dialog.set_default_size(round(390*self.scale), round(180*self.scale))
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Approve exact digest" if decision=="approved" else "Decline exact digest", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        box = dialog.get_content_area()
        box.set_border_width(12)
        box.set_spacing(6)
        box.add(label("Record your decision for this proposal?", large=True))
        box.add(label(NAMES[item.kind]+"  ·  SHA-256"))
        box.add(label(item.digest))
        box.add(label("A separate guarded action applies an approved change."))
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        self.decision_dialog = None
        if response == Gtk.ResponseType.OK:
            try:
                self.reviews.decide(item, decision)
                message = "Decision saved."
            except (OSError, ValueError, KeyError, TypeError) as error:
                message = describe_error(error)
            self.open_item(item, message)

    def apply_policy(self, item):
        try:
            command = self.reviews.policy_command(item)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.open_item(item, describe_error(error))
            return
        self.page("Applying approved local AI policy")
        self.note("Checking the proposal and current operating conditions.")
        self.show_all()
        def apply():
            try:
                completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, timeout=120, check=False)
                message = ("Local AI policy applied." if completed.returncode == 0 else
                           "Application was refused. Check the pending proposal and current guards.")
            except (OSError, subprocess.SubprocessError):
                message = "Application could not be confirmed. Check the existing policy before trying again."
            GLib.idle_add(lambda: (self.list_page(message), False)[1])
        threading.Thread(target=apply, daemon=True).start()


def run(reviews):
    window = Window(reviews)
    window.connect("destroy", Gtk.main_quit)
    window.maximize()
    window.show_all()
    Gtk.main()


def watch(reviews):
    if not reviews:
        return
    def inspect():
        try:
            if not reviews.owner():
                return True
            root = reviews.private_store()
            for item in reviews.discover():
                mark = root/(".notified-"+item.kind+"-"+item.digest)
                if mark.exists() or reviews.receipt(item):
                    continue
                reviews.api.subject(item.kind, item.path, item.digest)
                # Notifications offer navigation only. They never record decisions.
                sent = subprocess.run(["/usr/bin/notify-send", "--app-name=Field change review",
                                       "A field change needs review", "Open Field change review in the desktop menu."],
                                      timeout=3, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if sent.returncode == 0:
                    mark.touch(mode=0o600, exist_ok=True)
        except (OSError, ValueError, TypeError, subprocess.SubprocessError):
            pass
        return True
    inspect()
    GLib.timeout_add_seconds(60, inspect)
    GLib.MainLoop().run()
