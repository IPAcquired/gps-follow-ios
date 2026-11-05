"""Background-only Wi-Fi observation; never delays fresh flight telemetry."""
import copy
import threading
import time

class WifiSnapshot:
    def __init__(self, clock=time.monotonic):
        self.clock=clock
        self.lock=threading.Lock()
        self.value=None
        self.sampled=None

    def sample(self, query):
        began=self.clock()
        try:
            value=query()
            if not isinstance(value,dict):raise ValueError('Invalid Wi-Fi observation')
        except (OSError,ValueError,TypeError):
            value=None
        with self.lock:self.value,self.sampled=value,began

    def read(self):
        with self.lock:
            if self.sampled is None or self.value is None:return {}
            age=self.clock()-self.sampled
            if not 0<=age<=4:return {}
            result=copy.deepcopy(self.value)
        result['_age_ms']=int(age*1000)
        return result

    def start(self,query,stop):
        def worker():
            while not stop.is_set():
                self.sample(query)
                stop.wait(1)
        threading.Thread(target=worker,name='wifi-observation',daemon=True).start()
