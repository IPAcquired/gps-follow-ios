"""Read local Linux health counters and the installed flight monitor's published data."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import time


@dataclass(frozen=True)
class Reading:
    group: str
    label: str
    value: str
    status: str = "Live"
    age: float | None = None


def text(path):
    try:
        return path.read_text().strip()[:512]
    except (OSError, UnicodeError):
        return ""


def number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def age(stamp, now):
    stamp = number(stamp)
    return now-stamp if stamp is not None and 0 < stamp <= now else None


def age_ok(seconds, maximum):
    return seconds is not None and 0 <= seconds <= maximum


def data(path):
    try:
        with path.open("rb") as f:
            raw = f.read(1048577)
        obj = json.loads(raw) if len(raw) <= 1048576 else None
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


def fmt(v):
    if type(v) is bool:
        return "Yes" if v else "No"
    if type(v) is float:
        return f"{v:.6f}".rstrip("0").rstrip(".") if math.isfinite(v) else "—"
    return str(v)[:55]

def mapping(v):
    return v if isinstance(v,dict) else {}


def controller(rows, fc, now):
    expected, source = fc.get("expected_source"), fc.get("h743_source")
    matched = (isinstance(expected, dict) and isinstance(source, dict)
               and all(type(expected.get(k)) is int and 1 <= expected[k] <= 255
                       and expected[k] == source.get(k) for k in ("system_id","component_id")))
    hb = age(fc.get("heartbeat_updated_unix"), now)
    current = (matched and fc.get("connected") is True and age_ok(hb,3)
               and age_ok(age(fc.get("updated_unix"),now),3))
    rows["fc.link"] = Reading("Controller","Heartbeat","Connected" if current else "Unavailable",
                              "Live" if current else "Stale / unknown",hb)
    for k,label in (("armed","Armed"),("mode","Flight mode"),("system_status","Controller state")):
        rows["fc."+k] = Reading("Controller",label,fmt(fc[k]) if current and fc.get(k) is not None else "—",
                                "Live" if current and fc.get(k) is not None else "Unavailable",hb)
    for ident,record in mapping(fc.get("sensors")).items():
        if not isinstance(record,dict):
            continue
        group = str(ident).removesuffix(":0").replace("_"," ")
        peer = matched and all(record.get("source_"+k) == expected[k] for k in ("system_id","component_id"))
        ttl = number(record.get("stale_after_ms"))
        for k,v in mapping(record.get("values")).items():
            sec = age(mapping(record.get("field_updated_unix")).get(k),now)
            valid = (current and peer and record.get("fresh") is True and ttl is not None
                     and age_ok(sec,ttl/1000) and mapping(record.get("field_fresh")).get(k) is True
                     and type(v) in (float,int,str,bool) and fmt(v)!="—")
            u = str(mapping(record.get("units")).get(k) or "")
            unit = {"raw_unscaled_no_physical_unit":"raw","dimensionless":"","count":"","degC":"°C",
                    "GPS_FIX_TYPE_enum":"", "m_from_h_acc":"m","MAV_POWER_STATUS":"flags"}.get(u,u)
            value = (fmt(v)+" "+unit).strip() if valid else "—"
            rows["fc."+str(ident)+"."+k] = Reading("Flight sensors",group+" · "+k.replace("_"," "),value,
                                                  "Live" if valid else "Stale / unavailable",sec)
    # Additional battery instances carry their own identity and observation time.
    for ident,r in mapping(fc.get("batteries")).items():
        if not isinstance(r,dict):
            continue
        sec=age(r.get("updated_unix"),now)
        valid=(current and age_ok(sec,5) and r.get("source_system_id")==source.get("system_id")
               and r.get("source_component_id")==source.get("component_id"))
        for k in ("voltage_v","current_a","remaining_percent","consumed_mah","temperature_c"):
            if k in r:
                rows["battery."+str(ident)+"."+k]=Reading("Flight sensors","Battery "+str(r.get("battery_id",""))+" · "+k.replace("_"," "),
                    fmt(r[k]) if valid and r[k] is not None else "—","Live" if valid and r[k] is not None else "Unavailable",sec)


class Sampler:
    def __init__(self):
        self.last_cpu = None

    def read(self, detailed=True):
        now=time.time()
        rows={}
        def put(key,group,label,value):
            rows[key]=Reading(group,label,value if value is not None else "—","Live" if value is not None else "Unavailable")
        root=Path("/sys/class/thermal"); cpu=[]
        for p in sorted(root.glob("thermal_zone*")):
            kind=text(p/"type")
            val=number(text(p/"temp"))
            valid=val is not None and -40000<=val<=150000
            if valid and kind.lower().startswith(("cpu","soc")) and "idle" not in kind.lower():
                cpu.append(val/1000)
            if detailed:
                put("zone."+p.name,"Temperatures",kind.replace("_"," ") or p.name,f"{val/1000:.1f} °C" if valid else None)
        put("pi.cpu_temp","Orange Pi","CPU temperature",f"{max(cpu):.1f} °C" if cpu else None)
        perf=Path("/run/orangepi-performance-state.json"); d=data(perf)
        try: pa=age(perf.stat().st_mtime,now)
        except OSError: pa=None
        state=d.get("state")
        good=isinstance(state,str) and bool(state.strip()) and age_ok(pa,15)
        rows["pi.state"]=Reading("Orange Pi","Operating state",state.replace("_"," ").strip()[:28] if good else "—",
                                 "Live" if good else "Unavailable",pa)
        if not detailed:
            return rows
        try:
            fields=[int(i) for i in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
            total,idle=sum(fields),fields[3]+fields[4]
            busy=None
            if self.last_cpu and total>self.last_cpu[0] and idle>=self.last_cpu[1]:
                busy=max(0,min(100,100*(1-(idle-self.last_cpu[1])/(total-self.last_cpu[0]))))
            self.last_cpu=(total,idle)
            put("pi.busy","Orange Pi","CPU busy",f"{busy:.0f} %" if busy is not None else None)
            mem={l.split(':')[0]:int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines() if ':' in l}
            for k,label in (("MemAvailable","Memory available"),("MemTotal","Memory total"),("SwapFree","Swap free")):
                put("pi."+k,"Orange Pi",label,f"{mem[k]/1024:.0f} MiB" if k in mem else None)
            disk=shutil.disk_usage("/")
            put("pi.free","Orange Pi","System disk free",f"{disk.free/2**30:.1f} GiB")
            put("pi.load","Orange Pi","Load · 1 minute",f"{os.getloadavg()[0]:.2f}")
            uptime=number(text(Path("/proc/uptime")).split(" ")[0])
            put("pi.uptime","Orange Pi","Uptime",f"{int(uptime)//3600} h {int(uptime)%3600//60} min" if uptime else None)
        except (OSError,ValueError,KeyError,IndexError): pass
        for p in sorted(Path("/sys/devices/system/cpu/cpufreq").glob("policy*")):
            clock=number(text(p/"scaling_cur_freq"))
            put(p.name,"Orange Pi","CPU "+p.name.removeprefix("policy")+" cluster",f"{clock/1000:.0f} MHz" if clock else None)
        for p in sorted(root.glob("cooling_device*")):
            kind=text(p/"type"); v=text(p/"cur_state"); mx=text(p/"max_state")
            if v and mx:put("cool."+p.name,"Cooling / power",kind+" · "+p.name.removeprefix("cooling_device"),v+" / "+mx)
        for p in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            for f in sorted(p.glob("*_input")):
                base=f.name.removesuffix("_input")
                spec=next(((scale,unit) for prefix,scale,unit in (("temp",1000,"°C"),("fan",1,"RPM"),("in",1000,"V"),("curr",1000,"A"),("power",1e6,"W"),("humidity",1000,"%")) if base.startswith(prefix)),None)
                val=number(text(f))
                if spec and val is not None:put("hw."+p.name+"."+base,"Cooling / power",text(f.with_name(base+"_label")) or (text(p/"name")+" "+base),fmt(round(val/spec[0],2))+" "+spec[1])
        controller(rows,data(Path("/run/orangepi-mavlink/status.json")),now)
        v=data(Path.home()/".local/state/orangepi-vision/latest.json")
        a=age(v.get("captured_unix"),now)
        good=v.get("status")=="active" and age_ok(a,2) and age_ok(age(v.get("updated_unix"),now),2)
        rows["ext.camera"]=Reading("Pi peripherals","USB camera","Fresh capture" if good else "No fresh capture","Live" if good else "Unavailable",a)
        for k,label,paths in (("c1","C1 lidar · UART2",("/dev/rplidar","/dev/rplidar-c1-usb")),
                              ("matrix","8×8 matrix · UART7",("/dev/matrix-lidar","/dev/dfrobot-matrix-lidar","/dev/dfrobot-matrix-uart7"))):
            node=any(Path(p).exists() for p in paths)
            rows["ext."+k]=Reading("Pi peripherals",label,"Port present" if node else "No data","No verified sample")
        return rows
