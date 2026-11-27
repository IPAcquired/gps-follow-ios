from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from field_change_review import Held, PROFILES, Reviews
from install import install


class FixtureAPI:
    MAINTENANCE = Path("/usr/local/lib/corvon-maintenance/companion_maintenance.py")
    def __init__(self):
        self.state = "ready_for_owner"
        self.names = PROFILES
        self.expiry = time.time()+600

    @staticmethod
    def private_directory(path):
        if path.resolve()!=path or path.stat().st_mode & 0o077:
            raise ValueError("untrusted_directory")

    @staticmethod
    def read_file(path, limit, private):
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError("untrusted_file")
        return path.read_bytes()

    def subject(self, kind, path, digest):
        raw = self.read_file(path, 4096, True)
        if kind=="controller" and hashlib.sha256(raw).hexdigest()!=digest:
            raise ValueError("proposal_changed")
        if kind=="ai-policy" and json.loads(raw)["approval_sha256"]!=digest:
            raise ValueError("proposal_changed")
        return {"kind":kind,"digest":digest,"operation":"apply","route":"pi-uart0",
                "changes":{"MAV3_POSITION":{"from":2,"to":5}},
                "reason":"Match the reviewed telemetry stream profile.","expires_unix":self.expiry}

    def eligibility(self, kind, path, digest):
        return {"kind":kind,"digest":digest,"status":self.state,"reason":"unanimous_advisory_review",
                "votes":[{"profile":v,"vote":"approve","reason":"evidence_consistent"} for v in self.names],
                "expires_unix":self.expiry}

    def owner_approved(self,kind,digest,verdict):
        return verdict["status"]=="ready_for_owner" and verdict["digest"]==digest and verdict["kind"]==kind


class ReviewCase(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)
        self.api=FixtureAPI()
        self.signed_in=True
        self.reviews=Reviews(self.home,self.api,lambda:self.signed_in)
        folder=self.reviews.queues["controller"]
        folder.mkdir(parents=True,mode=0o700)
        self.proposal=folder/"candidate.json"
        self.proposal.write_text('{"fixture":true}')
        self.proposal.chmod(0o600)
        self.item=self.reviews.discover()[0]

    def test_no_writer_on_decision_and_no_approval_without_live_consent(self):
        with patch("subprocess.run", side_effect=AssertionError("Decisions do not call writers.")):
            for state in ("pending","declined"):
                self.api.state=state
                with self.assertRaises(Held):
                    self.reviews.decide(self.item,"approved")
            self.api.state="ready_for_owner"
            self.api.names=PROFILES[:3]
            with self.assertRaises(Held):
                self.reviews.decide(self.item,"approved")
            self.api.names=PROFILES
            self.api.expiry=time.time()-1
            with self.assertRaises(Held):
                self.reviews.decide(self.item,"approved")
            self.api.expiry=time.time()+100
            self.signed_in=False
            with self.assertRaises(Held):
                self.reviews.decide(self.item,"approved")
            self.assertIsNone(self.reviews.receipt(self.item))
            self.signed_in=True
            self.reviews.decide(self.item,"declined")
            with self.assertRaises(Held):
                self.reviews.decide(self.item,"approved")
            self.assertEqual(self.reviews.receipt(self.item)["decision"],"declined")
            self.assertTrue(self.proposal.exists())

    def test_racing_choices_are_exclusive_and_tamper_is_held(self):
        barrier=threading.Barrier(2)
        results=[]
        def choose(value):
            barrier.wait()
            try:results.append(self.reviews.decide(self.item,value)["decision"])
            except Held:results.append("held")
        threads=[threading.Thread(target=choose,args=(x,)) for x in ("approved","declined")]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(results.count("held"),1)
        self.assertIn(self.reviews.receipt(self.item)["decision"],results)
        self.proposal.write_text("changed")
        with self.assertRaises(ValueError):
            self.reviews.details(self.item)

    def test_handoff_revalidates_after_approval_and_policy_is_separate(self):
        with self.assertRaises(Held):
            self.reviews.maintenance_command(self.item.digest)
        self.reviews.decide(self.item,"approved")
        self.assertIn(self.item.digest,self.reviews.maintenance_command(self.item.digest))
        self.api.state="pending"
        with self.assertRaises(Held):
            self.reviews.maintenance_command(self.item.digest)
        self.api.state="ready_for_owner"
        folder=self.reviews.queues["ai-policy"]
        folder.mkdir(parents=True,mode=0o700)
        digest="4a"*32
        file=folder/(digest[:24]+".json")
        file.write_text(json.dumps({"approval_sha256":digest}));file.chmod(0o600)
        policy=next(x for x in self.reviews.discover() if x.kind=="ai-policy")
        with self.assertRaises(Held):
            self.reviews.policy_command(policy)
        self.reviews.decide(policy,"approved")
        self.assertEqual(self.reviews.policy_command(policy)[1:],["approve",digest[:24],"--confirm-sha256",digest])
        self.api.state="pending"
        with self.assertRaises(Held):
            self.reviews.policy_command(policy)

    def test_expired_owner_approval_needs_another_explicit_click(self):
        self.api.expiry=time.time()+60
        self.reviews.decide(self.item,"approved")
        with patch("field_change_review.time.time",return_value=self.api.expiry+1):
            self.api.expiry+=600
            with self.assertRaises(Held):
                self.reviews.maintenance_command(self.item.digest)
            self.reviews.decide(self.item,"approved")
            self.assertIn(self.item.digest,self.reviews.maintenance_command(self.item.digest))
        self.assertEqual(len(list(self.reviews.store.glob(".expired-*.json"))),1)

    def test_user_install_and_opt_in_notification(self):
        source=Path(__file__).resolve().parents[1]
        existing=self.home/".local/bin/orangepi-field-review"
        existing.parent.mkdir(parents=True);existing.write_bytes(b"previous launcher");existing.chmod(0o700)
        install(self.home,Path(__file__).resolve().parents[1],False)
        self.assertTrue((self.home/".local/bin/orangepi-field-review").stat().st_mode & 0o100)
        self.assertFalse((self.home/".config/autostart/orangepi-field-review-notify.desktop").exists())
        install(self.home,Path(__file__).resolve().parents[1],True)
        self.assertIn("--watch",(self.home/".config/autostart/orangepi-field-review-notify.desktop").read_text())
        self.decisions_snapshot=self.reviews.decide(self.item,"declined")
        install(self.home,source,rollback=True)
        self.assertEqual(existing.read_bytes(),b"previous launcher")
        self.assertEqual(self.reviews.receipt(self.item),self.decisions_snapshot)
        self.assertFalse((self.home/".config/autostart/orangepi-field-review-notify.desktop").exists())
        install(self.home,source)
        existing.write_bytes(b"changed independently")
        with self.assertRaises(ValueError):
            install(self.home,source,rollback=True)
        self.assertEqual(existing.read_bytes(),b"changed independently")
