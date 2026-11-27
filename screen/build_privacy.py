"""Keep local build paths out of SDK diagnostics compiled into release firmware."""
import os
from pathlib import Path
Import("env")

roots = [(Path.home(), "build"), (Path(env.subst("$PROJECT_DIR")), "project")]
framework = env.PioPlatform().get_package_dir("framework-arduinoespressif32")
if framework:
    roots.append((Path(framework), "framework"))
maps = []
for path, name in roots:
    spellings = {str(path), path.as_posix()}
    if os.name == "nt":
        import ctypes
        short = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(str(path), short, len(short)):
            spellings.update({short.value, short.value.replace(chr(92), "/")})
    for old in sorted(spellings):
        maps.append("-ffile-prefix-map=" + old + "=" + name)
env.Append(CCFLAGS=maps)
