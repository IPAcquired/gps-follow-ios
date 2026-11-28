#!/usr/bin/python3
"""Owner-local Xfce terminal from verified distribution packages. No sudo."""
import argparse
import contextlib
import ctypes
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile

NAME = "orangepi-field-terminal"
PACKAGES = ("xterm", "libutempter0")
HOME = Path.home()
SHARE = HOME/".local/share"
ROOT = SHARE/NAME
EXTERNAL = {"launcher": HOME/".local/bin"/NAME, "desktop": SHARE/"applications"/(NAME+".desktop")}
ASSETS = {"bin/xterm": 0o700, "lib/libutempter.so.0": 0o600,
          "licenses/xterm.copyright": 0o600, "licenses/libutempter0.copyright": 0o600}

def check(condition, error):
    if not condition:
        raise ValueError(error)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def run(*args, **options):
    return subprocess.run(args, check=True, capture_output=True, timeout=options.pop("timeout",120), **options)

def regular(path):
    return path.is_file() and not path.is_symlink() and path.stat().st_uid == os.getuid()

def package_plan():
    import apt
    import apt_pkg
    cache = apt.Cache()
    indices = apt_pkg.SourceList()
    indices.read_main_list()
    records = apt_pkg.PackageRecords(cache._cache)
    native = run("/usr/bin/dpkg","--print-architecture",text=True).stdout.strip()
    plan={}
    for name in PACKAGES:
        version = cache[name].candidate
        check(version and version.architecture==native,"Missing native distribution candidate for "+name)
        sums=set()
        origins=set()
        for ref in version._cand.file_list:
            pkgfile=ref[0]
            index=indices.find_index(pkgfile)
            if (not index or not index.is_trusted or pkgfile.origin not in ("Ubuntu","Debian")
                    or pkgfile.label not in ("Ubuntu","Debian","Debian-Security")):
                continue
            if records.lookup(ref) and re.fullmatch("[a-fA-F0-9]{64}",records.sha256_hash):
                sums.add(records.sha256_hash.lower())
                origins.add(pkgfile.origin)
        check(len(sums)==1 and len(origins)==1,"No unambiguous trusted official SHA-256 for "+name)
        plan[name]={"version":version.version,"arch":native,"origin":origins.pop(),"sha256":sums.pop()}
    return plan

def package_files(name, metadata, scratch):
    dest=scratch/name
    dest.mkdir(mode=0o700)
    run("/usr/bin/apt-get","-o","Acquire::Retries=1","-o","Acquire::http::Timeout=20",
        "-o","Acquire::https::Timeout=20","download",name+":"+metadata["arch"]+"="+metadata["version"],
        cwd=dest,timeout=120)
    debs=list(dest.glob("*.deb"))
    check(len(debs)==1 and regular(debs[0]) and sha(debs[0].read_bytes())==metadata["sha256"],
          "Downloaded SHA-256 differs from the trusted index for "+name)
    deb=debs[0]
    for key,expected in (("Package",name),("Version",metadata["version"]),("Architecture",metadata["arch"])):
        check(run("/usr/bin/dpkg-deb","-f",str(deb),key,text=True).stdout.strip()==expected,"Package metadata mismatch")
    raw=run("/usr/bin/dpkg-deb","--fsys-tarfile",str(deb)).stdout
    with tarfile.open(fileobj=io.BytesIO(raw),mode="r:") as archive:
        members={m.name.removeprefix("./"):m for m in archive.getmembers()}
        if name=="xterm":
            choices={"bin/xterm":"usr/bin/xterm"}
        else:
            libraries=[p for p in members if re.fullmatch(r"(?:usr/)?lib/(?:[^/]+/)?libutempter\.so\.0",p)]
            check(len(libraries)==1,"Packaged library SONAME missing or ambiguous")
            lib=libraries[0]
            link=members[lib]
            if link.issym():
                check(bool(re.fullmatch(r"libutempter\.so\.[0-9]+(?:\.[0-9]+)+",link.linkname)),"Unexpected library target")
                lib=str(Path(lib).parent/link.linkname)
            choices={"lib/libutempter.so.0":lib}
        choices["licenses/"+name+".copyright"]="usr/share/doc/"+name+"/copyright"
        files={}
        for relative,selected in choices.items():
            m=members.get(selected)
            check(m is not None and m.isfile() and 0<m.size<12*1024*1024,"Required package file missing: "+relative)
            files[relative]=archive.extractfile(m).read()
    return files

def runtime_loader(binary):
    # Read only the ELF program headers. Use the kernel interpreter recorded in the verified xterm itself.
    check(binary[:4]==b"\x7fELF" and binary[4] in (1,2) and binary[5] in (1,2),"Invalid xterm ELF")
    fmt="<" if binary[5]==1 else ">"
    is64=binary[4]==2
    offset=struct.unpack_from(fmt+("Q" if is64 else "I"),binary,32 if is64 else 28)[0]
    stride,count=struct.unpack_from(fmt+"HH",binary,54 if is64 else 42)
    for pos in range(offset,offset+count*stride,stride):
        kind=struct.unpack_from(fmt+"I",binary,pos)[0]
        if kind!=3:
            continue
        start=struct.unpack_from(fmt+("Q" if is64 else "I"),binary,pos+(8 if is64 else 4))[0]
        size=struct.unpack_from(fmt+("Q" if is64 else "I"),binary,pos+(32 if is64 else 16))[0]
        check(1<size<255,"Invalid ELF interpreter length")
        path=Path(binary[start:start+size].rstrip(b"\0").decode("ascii"))
        check(path.is_absolute() and re.fullmatch(r"/(?:usr/)?lib(?:32|64)?/(?:[^/]+/)?ld-linux[^/]*\.so\.[0-9]+",str(path)),
              "Unexpected ELF interpreter")
        target=path.resolve(strict=True)
        check(any(target.is_relative_to(p) for p in (Path("/usr/lib"),Path("/lib"),Path("/lib64"),Path("/usr/lib64")))
              and target.is_file() and target.stat().st_uid==0 and not target.stat().st_mode & 0o022,
              "Unexpected system loader ownership or mode")
        return str(path)
    raise ValueError("No system loader in xterm")

def external_files(receipt):
    payload=ROOT/receipt["payload"]
    args=[receipt["loader"],"--library-path",str(payload/"lib"),str(payload/"bin/xterm"),
          "-ut","-fa","DejaVu Sans Mono","-fs","13","-T","Field terminal"]
    command=" ".join(shlex.quote(s) for s in args)
    if receipt["schema"]==1:
        script=("#!/bin/sh\nexec "+command+' "$@"\n').encode()
    else:
        # Probe only current X geometry. Restrict arithmetic to short decimal inputs.
        script=('''#!/bin/sh
size=$(/usr/bin/xdotool getdisplaygeometry 2>/dev/null) || size=
read -r width height rest <<EOF
$size
EOF
case "$width" in ''|*[!0-9]*|0*|?????*) width=640 ;; esac
case "$height" in ''|*[!0-9]*|0*|?????*) height=480 ;; esac
cols=$(( (width - 46) / 11 ))
rows=$(( (height - 108) / 22 ))
[ "$cols" -ge 20 ] || cols=20
[ "$cols" -le 80 ] || cols=80
[ "$rows" -ge 6 ] || rows=6
[ "$rows" -le 25 ] || rows=25
exec '''+command+' -geometry "${cols}x${rows}" "$@"\n').encode()
    # Desktop Entry Exec is parsed independently of shell expansion.
    execpath=str(EXTERNAL["launcher"])
    check(not any(c in execpath for c in '\n\r"\\`$'),"Unsupported launcher path")
    entry=("[Desktop Entry]\nType=Application\nName=Field terminal\nGenericName=Terminal emulator\n"
           "Exec=\""+execpath.replace("%","%%")+"\"\nIcon=utilities-terminal\nTerminal=false\n"
           "Categories=System;TerminalEmulator;\nStartupNotify=false\n").encode()
    return {"launcher":(script,0o700),"desktop":(entry,0o600)}

def put(path,body,mode):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        tmp=Path(f.name)
        try:
            f.write(body)
            f.flush()
            os.fchmod(f.fileno(),mode)
            os.fsync(f.fileno())
            os.link(tmp,path)  # Same-directory hard link, atomic and never overwrites an existing name.
        finally:
            tmp.unlink(missing_ok=True)

def stage(base, packages, probe_gui):
    files={}
    for pkg,meta in packages.items():
        files.update(package_files(pkg,meta,base))
    check(set(files)==set(ASSETS),"Unexpected payload inventory")
    loader=runtime_loader(files["bin/xterm"])
    suffix=sha("".join(packages[p]["sha256"] for p in PACKAGES).encode())[:16]
    payload="xterm-"+suffix
    staged=base/"staged"
    staged.mkdir(mode=0o700)
    folder=staged/payload
    for name,body in files.items():
        put(folder/name,body,ASSETS[name])
    args=[loader,"--library-path",str(folder/"lib")]
    deps=run(*args,"--list",str(folder/"bin/xterm"),text=True)
    check("not found" not in deps.stdout and str(folder/"lib/libutempter.so.0") in deps.stdout,"Missing runtime dependencies")
    version=run(*args,str(folder/"bin/xterm"),"-version",text=True)
    version=(version.stdout+version.stderr).strip()
    check(bool(re.search("xterm",version,re.I)),"xterm version smoke failed")
    if probe_gui:
        marker=base/"pty-ok"
        # Prove that xterm allocated a PTY and its run-time loader option never entered the shell environment.
        envclean=os.environ.copy()
        envclean.pop("LD_LIBRARY_PATH",None)
        envclean.pop("LD_PRELOAD",None)
        run(*args,str(folder/"bin/xterm"),"-ut","-iconic","-fa","DejaVu Sans Mono","-fs","13","-e","/bin/sh","-c",
            'test -t 0 && test -t 1 && test -z "${LD_LIBRARY_PATH-}" && printf ok > "$1"',
            "probe",str(marker),env=envclean,timeout=18)
        check(marker.is_file() and marker.read_bytes()==b"ok","X11 PTY test failed")
    receipt={"schema":2,"payload":payload,"loader":loader,"packages":packages,"version":version,
             "files":{n:sha(b) for n,b in files.items()}}
    receipt["external"]={n:sha(b) for n,(b,_) in external_files(receipt).items()}
    put(staged/"receipt.json",(json.dumps(receipt,sort_keys=True,indent=2)+"\n").encode(),0o600)
    return receipt,staged

def inspect_root():
    check(ROOT.is_dir() and not ROOT.is_symlink() and ROOT.stat().st_uid==os.getuid() and
          stat.S_IMODE(ROOT.stat().st_mode)==0o700 and regular(ROOT/"receipt.json"),"Unrecognized owner terminal directory")
    check((ROOT/"receipt.json").stat().st_size<16*1024,"Oversize receipt")
    r=json.loads((ROOT/"receipt.json").read_bytes())
    check(r.get("schema") in (1,2) and re.fullmatch(r"xterm-[a-f0-9]{16}",r.get("payload",""))
          and set(r["files"])==set(ASSETS) and set(r["external"])==set(EXTERNAL),"Invalid installation receipt")
    folder=ROOT/r["payload"]
    names={str(p.relative_to(ROOT)) for p in ROOT.rglob("*")}
    wanted={"receipt.json",r["payload"]}|{str(Path(r["payload"])/n) for n in ASSETS}
    wanted.update(str(Path(r["payload"])/Path(n).parent) for n in ASSETS)
    check(names==wanted,"Payload inventory differs from the receipt")
    for p in [folder]+[folder/n for n in ("bin","lib","licenses")]:
        check(p.is_dir() and not p.is_symlink() and p.stat().st_uid==os.getuid(),"Invalid payload directory")
    for n,mode in ASSETS.items():
        p=folder/n
        check(regular(p) and stat.S_IMODE(p.stat().st_mode)==mode and sha(p.read_bytes())==r["files"][n],
              "Preserving altered payload: "+n)
    check(runtime_loader((folder/"bin/xterm").read_bytes())==r["loader"],"Loader mismatch")
    for n,(b,_) in external_files(r).items():
        check(sha(b)==r["external"][n],"Launcher receipt mismatch")
    return r

def entries(r):
    missing=[]
    for n,(b,mode) in external_files(r).items():
        p=EXTERNAL[n]
        if not os.path.lexists(p):
            missing.append(n)
            continue
        check(regular(p) and stat.S_IMODE(p.stat().st_mode)==mode and sha(p.read_bytes())==r["external"][n],
              "Preserving occupied/altered "+n)
    return missing

def commit(staged):
    libc=ctypes.CDLL(None,use_errno=True)
    move=libc.renameat2
    move.argtypes=(ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint)
    if move(-100,os.fsencode(staged),-100,os.fsencode(ROOT),1)!=0:
        raise OSError(ctypes.get_errno(),"Could not publish owner payload without overwriting")

def directory_lock():
    check(SHARE.is_dir() and SHARE.stat().st_uid==os.getuid(),"Unsafe user share directory")
    return os.open(SHARE,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)

def summary(r,state,missing=()):
    return {"state":state,"launcher_revision":r["schema"],"missing":list(missing),"xterm_version":r["version"],"source_packages":r["packages"]}

def perform(action,gui):
    check(os.getuid()!=0,"Run as the existing desktop owner")
    os.umask(0o077)
    if action=="metadata":
        return package_plan()
    if action in ("status","remove") and not os.path.lexists(ROOT) and not any(os.path.lexists(p) for p in EXTERNAL.values()):
        return {"state":"absent"}
    SHARE.mkdir(parents=True,exist_ok=True)
    fd=directory_lock()
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        if os.path.lexists(ROOT):
            r=inspect_root()
            missing=entries(r)
            if action=="status":
                return summary(r,"incomplete" if missing else "installed",missing)
            if action=="remove":
                # First validate all items, then detach the complete payload in a single rename.
                for n in EXTERNAL:
                    if n not in missing:
                        EXTERNAL[n].unlink()
                with tempfile.TemporaryDirectory(prefix=".field-terminal-remove-",dir=SHARE) as temp:
                    os.rename(ROOT,Path(temp)/"known-payload")
                return {"state":"removed"}
            if action=="install":
                check(r["schema"]==2,"Prior launcher installed; use remove, then install the new revision")
                for n in missing:
                    b,mode=external_files(r)[n]
                    put(EXTERNAL[n],b,mode)
                check(not entries(r),"Incomplete resumed installation")
                return summary(r,"installed")
        elif any(os.path.lexists(p) for p in EXTERNAL.values()):
            raise ValueError("A launcher path is already occupied")
        elif action in ("status","remove"):
            return {"state":"absent"}
        packages=package_plan()
        # Same filesystem as the payload so its final publication can be atomic.
        with tempfile.TemporaryDirectory(prefix=".field-terminal-stage-",dir=SHARE) as name:
            r,staged=stage(Path(name),packages,gui)
            if action=="probe":
                return summary(r,"staged X11 PTY verified" if gui else "staged linker and version verified")
            check(action=="install","Unsupported action")
            check(not any(os.path.lexists(p) for p in EXTERNAL.values()),"A launcher appeared during staging")
            commit(staged)
            made=[]
            try:
                for n,(body,mode) in external_files(r).items():
                    put(EXTERNAL[n],body,mode)
                    made.append(n)
                installed=inspect_root()
                check(not entries(installed),"Incomplete installation")
            except Exception:
                # Remove only verified newly-created entries, and preserve unrelated changes.
                for n in made:
                    p=EXTERNAL[n]
                    if regular(p) and sha(p.read_bytes())==r["external"][n]:
                        p.unlink()
                os.rename(ROOT,Path(name)/"failed-commit")
                raise
            return summary(r,"installed")
    finally:
        os.close(fd)

if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action",choices=("metadata","probe","install","status","remove"))
    cli.add_argument("--gui",action="store_true",help="test a temporary iconic real X11 terminal and PTY during staging")
    a=cli.parse_args()
    print(json.dumps(perform(a.action,a.gui),sort_keys=True))

