"""Owner decisions on the signed-in Orange Pi desktop, also accessible on the paired display."""
import argparse
from dataclasses import dataclass
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time


DIGEST = re.compile(r"[a-f0-9]{64}")
NAMES = {"controller": "Controller telemetry", "ai-policy": "Local AI policy"}
PROFILES = ("fast", "balanced", "quality", "long")


class Held(ValueError):
    pass


@dataclass(frozen=True)
class Item:
    kind: str
    path: Path
    digest: str


def active_owner():
    user = str(os.getuid())
    if user == "0":
        return False
    def query(*args):
        return subprocess.check_output(["/usr/bin/loginctl", *args], timeout=2, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    try:
        session = query("show-user", user, "-p", "Display", "--value")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", session):
            return False
        names = ["User", "Remote", "Active", "LockedHint", "Type"]
        options = [arg for name in names for arg in ("-p", name)]
        values = dict(line.split("=", 1) for line in query("show-session", session, *options).splitlines())
        return (values["User"] == user and values["Remote"] == "no" and values["Active"] == "yes"
                and values["LockedHint"] == "no" and values["Type"] in ("x11", "wayland"))
    except (OSError, KeyError, ValueError, subprocess.SubprocessError):
        return False


def approval_current(receipt, review=None):
    return (receipt and receipt.get("decision") == "approved"
            and type(receipt.get("model_review_expires_unix")) in (int, float)
            and time.time() < receipt["model_review_expires_unix"]
            and (review is None or receipt["model_review_expires_unix"]==review.get("expires_unix")))


class Reviews:
    def __init__(self, home, api, owner=active_owner):
        self.api, self.owner, self.home = api, owner, home
        self.queues = {"controller": home/".local/state/corvon-maintenance/proposals",
                       "ai-policy": home/"ai-improvement/pending"}
        self.store = home/".local/state/corvon-maintenance/owner-decisions"

    def discover(self):
        items = []
        for kind, folder in self.queues.items():
            if not folder.exists():
                continue
            self.api.private_directory(folder)
            for path in sorted(folder.glob("*.json")):
                if kind == "ai-policy" and not re.fullmatch(r"[0-9a-f]{24}\.json", path.name):
                    continue
                try:
                    raw = self.api.read_file(path, 8192 if kind == "controller" else 262144, private=True)
                    digest = hashlib.sha256(raw).hexdigest() if kind == "controller" else json.loads(raw)["approval_sha256"]
                    if DIGEST.fullmatch(digest):
                        items.append(Item(kind, path, digest))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return items

    def receipt(self, item):
        if not self.store.exists():
            return None
        self.api.private_directory(self.store)
        path = self.store / (item.kind+"-"+item.digest+".json")
        try:
            receipt = json.loads(self.api.read_file(path, 4096, private=True))
        except FileNotFoundError:
            return None
        if (receipt.get("schema") != 1 or receipt.get("kind") != item.kind
                or receipt.get("digest") != item.digest or receipt.get("decision") not in ("approved", "declined")):
            raise Held("The existing decision needs manual review.")
        return receipt

    def details(self, item):
        subject = self.api.subject(item.kind, item.path, item.digest)
        review = self.api.eligibility(item.kind, item.path, item.digest)
        if any(r.get("digest") != item.digest or r.get("kind") != item.kind for r in (subject, review)):
            raise Held("The proposal changed. Reopen its current version.")
        return subject, review

    def private_store(self):
        self.store.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.api.private_directory(self.store)
        return self.store

    def decide(self, item, decision):
        if decision not in ("approved", "declined"):
            raise Held("Select an owner decision.")
        root = self.private_store()
        fd = os.open(root/".lock", os.O_RDWR|os.O_NOFOLLOW|os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if not self.owner():
                raise Held("Unlock the local owner desktop first.")
            prior = self.receipt(item)
            subject, review = self.details(item)
            if prior and (prior["decision"] == "declined" or approval_current(prior, review)):
                raise Held("An owner decision already exists for this exact proposal.")
            if decision == "approved":
                votes = review.get("votes", [])
                if (review["status"] != "ready_for_owner" or not subject["changes"]
                        or [v.get("profile") for v in votes] != list(PROFILES)
                        or any(v.get("vote") != "approve" for v in votes)
                        or not isinstance(review.get("expires_unix"), (int, float))
                        or not time.time() < review["expires_unix"]):
                    raise Held("Approval is held. Check the current review and controller connection.")
            record = {"schema": 1, "kind": item.kind, "digest": item.digest, "decision": decision,
                      "decided_unix": int(time.time()), "source": "signed-in-owner-desktop",
                      "model_review_expires_unix": review.get("expires_unix"),
                      "application": "separate-guarded-handoff"}
            tmp = None
            try:
                with tempfile.NamedTemporaryFile("w", dir=root, delete=False) as file:
                    tmp = Path(file.name)
                    json.dump(record, file, sort_keys=True)
                    file.flush()
                    os.fsync(file.fileno())
                dest = root/(item.kind+"-"+item.digest+".json")
                if prior:
                    # Only a new explicit click can renew an expired approval. Keep the previous receipt.
                    prior_hash = hashlib.sha256(self.api.read_file(dest,4096,private=True)).hexdigest()
                    archived = root/(".expired-"+prior_hash+".json")
                    if not archived.exists():
                        os.link(dest, archived)
                    os.replace(tmp, dest)
                else:
                    os.link(tmp, dest)
                parent = os.open(root, os.O_DIRECTORY)
                try:
                    os.fsync(parent)
                finally:
                    os.close(parent)
            finally:
                if tmp:
                    tmp.unlink(missing_ok=True)
            return record

    def policy_command(self, item):
        if not self.owner() or item.kind != "ai-policy" or not approval_current(self.receipt(item)):
            raise Held("An explicit owner approval is required.")
        _, review = self.details(item)
        if not self.api.owner_approved(item.kind,item.digest,review):
            raise Held("The model review or ground status changed. Application is held.")
        return [str(self.home/"bin/orangepi-ai-improvement"), "approve", item.digest[:24],
                "--confirm-sha256", item.digest]

    def maintenance_command(self, digest):
        if not self.owner() or not DIGEST.fullmatch(digest):
            raise Held("Unlock the local owner desktop and select the approved digest.")
        matches = [item for item in self.discover() if item.kind == "controller" and item.digest == digest]
        if len(matches) != 1 or not approval_current(self.receipt(matches[0])):
            raise Held("A matching explicit owner approval is required.")
        item = matches[0]
        subject, review = self.details(item)
        if (subject.get("operation") != "apply" or subject.get("route") != "pi-uart0"
                or not self.api.owner_approved(item.kind,item.digest,review)):
            raise Held("The current review or route requires manual inspection.")
        return ["/usr/bin/sudo", "-n", "/usr/bin/python3", str(self.api.MAINTENANCE), "apply",
                "--route", "pi-uart0", "--proposal", str(item.path), "--approve", digest,
                "--journal", str(item.path.parent/("recovery-"+digest[:16]+".journal"))]


def load_api(home):
    source = home/"bin/orangepi_model_review.py"
    mode = source.lstat()
    if (not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.getuid() or mode.st_mode & 0o022
            or source != source.resolve()):
        raise Held("The installed review module needs verification.")
    spec = importlib.util.spec_from_file_location("orangepi_model_review", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clean(value, limit=200):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return " ".join(str(value).split())[:limit]


def describe_error(error):
    if isinstance(error, Held):
        return str(error)
    code = str(error)
    if re.fullmatch(r"[a-z_]{3,70}", code):
        return code.replace("_", " ").capitalize()+"."
    return "Private proposal or review unavailable. Open it again after checking the local services."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="Notify once for each new pending proposal")
    parser.add_argument("--apply-controller", metavar="SHA256",
                        help="Hand off a previously approved exact native-UART plan in an owner terminal")
    args = parser.parse_args()
    os.umask(0o077)
    home = Path.home()
    try:
        reviews = Reviews(home, load_api(home))
    except (ValueError, OSError, ImportError):
        reviews = None
    if args.apply_controller:
        if not reviews or not sys.stdin.isatty() or not sys.stdout.isatty():
            raise SystemExit("Open a foreground terminal on the signed-in owner's desktop.")
        try:
            reviews.maintenance_command(args.apply_controller)
            print("Controller telemetry profile    SHA-256 "+args.apply_controller)
            if input("Type APPLY to start the guarded maintenance tool: ").strip() != "APPLY":
                return
            # Complete any interactive credential prompt before the final live eligibility check.
            if subprocess.run(["/usr/bin/sudo", "-v"], check=False).returncode != 0:
                raise Held("Administrator authorization was unavailable. The proposal remains staged.")
            command = reviews.maintenance_command(args.apply_controller)
            raise SystemExit(subprocess.run(command, check=False).returncode)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SystemExit(describe_error(error)) from None
    from field_review_gtk import run, watch
    return watch(reviews) if args.watch else run(reviews)


if __name__ == "__main__":
    sys.modules.setdefault("field_change_review", sys.modules[__name__])
    main()
