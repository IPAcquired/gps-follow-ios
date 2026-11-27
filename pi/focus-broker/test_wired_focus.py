import ast
from pathlib import Path
import unittest
from browser_desktop import DesktopOwner

class FocusTests(unittest.TestCase):
    def test_focus_scope_and_replay(self):
        now=[10.];safe=[True];rev=["a"*32];commands=[]
        def focus():return dict(focus_known=True,focus_editable=False,focus_revision=rev[0])
        broker=DesktopOwner(lambda:safe[0],lambda:None,commands.append,lambda:now[0],focus_probe=focus)
        owner="8"*64
        def act(action,**values):return broker.handle(dict(action=action,owner=owner,**values))
        with self.assertRaises(PermissionError):act("focus")
        act("unlock");self.assertEqual(act("focus")["focus_revision"],rev[0])
        def key(seq,marker):return act("input",command={"type":"key","key":"left"},event_id=seq,focus_revision=marker)
        self.assertTrue(key(1,rev[0])["input_applied"]);old=rev[0];rev[0]="b"*32
        now[0]+=.1;self.assertFalse(key(2,old)["input_applied"])
        with self.assertRaises(ValueError):key(2,rev[0])
        self.assertEqual(len(commands),1)
        safe[0]=False
        with self.assertRaises(PermissionError):act("focus")
        with self.assertRaises(PermissionError):key(3,rev[0])

    def test_native_arrow_aliases(self):
        tree=ast.parse(Path(__file__).with_name("orangepi-companion").read_text())
        cls=next(c for c in tree.body if isinstance(c,ast.ClassDef) and c.name=="RemoteInput")
        mapping=next(ast.literal_eval(c.value) for c in cls.body if isinstance(c,ast.Assign) and c.targets[0].id=="SPECIAL_KEYS")
        for direction in ("left","up","right","down"):
            self.assertEqual(mapping[direction],mapping["arrow"+direction])

if __name__=="__main__":unittest.main()
