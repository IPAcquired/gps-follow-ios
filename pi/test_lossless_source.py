import base64
import hashlib
import io
import unittest
from unittest.mock import patch
from PIL import Image
from desktop_source import OwnerDesktop


class PairedCaptureTests(unittest.TestCase):
    def test_private_png_and_older_broker_jpeg(self):
        with patch("os.getuid",return_value=1000):
            source=OwnerDesktop()
        sample=Image.new("RGB",(40,24),(5,81,130))
        sample.putpixel((13,14),(213,176,19))
        def exchange(codec,base,wanted):
            args=[]
            def call(action,**options):
                args.append(options)
                encoded=io.BytesIO()
                sample.save(encoded,codec.upper())
                blob=encoded.getvalue()
                return {"frame_id":hashlib.sha256(blob).hexdigest(),"width":40,"height":24,
                        codec:base64.b64encode(blob).decode("ascii")}
            source.call=call
            source.base=base
            result=source.frame()
            self.assertEqual(args,[wanted])
            return result
        exchange("jpeg","",{"base":""})
        source.prefer_lossless=True
        exchange("jpeg","",{"base":"","lossless":True})  # old broker ignores the optional key
        result=exchange("png","",{"base":"","lossless":True})
        self.assertEqual(result[1].native.tobytes(),sample.tobytes())
        source.base=""
        source.call=lambda *a,**k:{"frame_id":"1"*64,"png":"AA==","width":1,"height":1}
        with self.assertRaises(ValueError):source.frame()
