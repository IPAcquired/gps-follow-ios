from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
WORK = ROOT / "work"
NAME = "Four_Across_HEAVY_DUTY_MOUNTS"

project = OUT / f"{NAME}.3mf"
stl = OUT / f"{NAME}.stl"
slice_source = WORK / "four-heavy-slice" / f"{NAME}_CC_0p6_PLA.gcode.3mf"
slice_output = OUT / slice_source.name
geometry = json.loads((OUT / f"{NAME}_Geometry_Checks.json").read_text())
toolpaths = json.loads((OUT / f"{NAME}_Toolpath_Checks.json").read_text())

with zipfile.ZipFile(project) as archive:
    assert archive.testzip() is None
    settings = json.loads(archive.read("Metadata/project_settings.config"))
    model_settings = archive.read("Metadata/model_settings.config").decode("utf-8")

assert settings["enable_support"] == "1"
assert settings["support_on_build_plate_only"] == "0"
assert settings["wall_loops"] == "6"
assert settings["sparse_infill_density"] == "50%"
assert settings["sparse_infill_pattern"] == "gyroid"
assert model_settings.count('subtype="modifier_part"') == 4
assert model_settings.count('key="sparse_infill_density" value="100%"') == 4

with zipfile.ZipFile(slice_source) as archive:
    assert archive.testzip() is None
    gcode_names = [name for name in archive.namelist() if name.endswith(".gcode")]
    assert len(gcode_names) == 1
    gcode = archive.read(gcode_names[0])

gcode_hash = hashlib.sha256(gcode).hexdigest()
assert gcode_hash == toolpaths["gcode_sha256"]
assert all(not item["interface_grid_missing_points"] for item in toolpaths["mount_checks"])
assert all(item["sparse_infill_in_upper_mount_mm"] == 0 for item in toolpaths["mount_checks"])
assert all(item["sparse_infill_mm"] == 0 for item in toolpaths["heavy_duty_saddle_checks"])
assert all(item["solid_infill_mm"] > 50_000 for item in toolpaths["heavy_duty_saddle_checks"])
assert all(item["underside_support_interface_mm"] > 2_800 for item in toolpaths["heavy_duty_saddle_checks"])

shutil.copy2(slice_source, slice_output)

upper_old_area = 16.0 * 20.0
upper_new_area = 30.0 * 26.0
report = {
    "status": "PASS",
    "geometry": geometry,
    "mount_reinforcement": {
        "permanent_under_pad_saddles": 4,
        "original_under_pad_footprint_mm": [16.0, 20.0],
        "reinforced_upper_saddle_footprint_mm": [30.0, 26.0],
        "upper_load_spreading_area_ratio": upper_new_area / upper_old_area,
        "solid_saddle_z_mm": [48.0, 60.9],
        "mount_faces_and_pattern_unchanged": True,
    },
    "actual_toolpaths": {
        "all_four_mounts_solid": True,
        "all_four_saddles_solid": True,
        "all_four_saddle_undersides_supported": True,
        "all_four_bridge_supports_complete": True,
        "raised_floor_supported": True,
        "extrusion_xy_bounds_mm": toolpaths["extruded_toolpath_xy_bounds_mm"],
        "gcode_sha256": gcode_hash,
    },
    "print": {
        "printer": "Elegoo Centauri Carbon",
        "nozzle_mm": 0.6,
        "material": "Elegoo PLA",
        "layer_height_mm": 0.2,
        "walls": 6,
        "tray_infill": "50% gyroid",
        "mount_infill": "100% rectilinear",
        "estimated_time": "17h 24m 3s",
        "estimated_filament_g": 624.08,
    },
    "files_sha256": {
        "stl": hashlib.sha256(stl.read_bytes()).hexdigest(),
        "editable_3mf": hashlib.sha256(project.read_bytes()).hexdigest(),
        "sliced_gcode_3mf": hashlib.sha256(slice_output.read_bytes()).hexdigest(),
    },
    "physical_load_tested": False,
    "verification_limit": (
        "CAD topology, protected dimensions, slicer settings, and actual extrusion "
        "paths passed. Printed PLA strength still requires a ground load test."
    ),
}
(OUT / f"{NAME}_Final_Verification.json").write_text(
    json.dumps(report, indent=2), encoding="utf-8"
)

(OUT / f"{NAME}_README.md").write_text(
    """# Four-across tray with heavy-duty mounting points

Use `Four_Across_HEAVY_DUTY_MOUNTS_CC_0p6_PLA.gcode.3mf` for the verified print. It is sliced for the Elegoo Centauri Carbon, 0.6 mm nozzle, and ordinary Elegoo PLA: 0.20 mm layers, six walls, 50% gyroid tray infill, and 100% rectilinear infill throughout all four mounting structures and their new saddles.

Each mounting point now has a permanent tapered saddle beneath the original pad. The upper load-spreading footprint grows from 16 × 20 mm to 30 × 26 mm, or 2.44 times the area, and tapers into the already reinforced bridge. The saddles add about 16.3 cm³ of solid CAD volume across the four mounting points.

The 110 × 110 mm mounting pattern, original pad faces, 228 × 152 × 77 mm overall size, deck, strap slots, sensor opening, and all four modeled 47 × 142 × 46 mm battery envelopes remain unchanged. The saddles begin at Z48, leaving 2 mm over the modeled 46 mm pack height. Confirm real pack height and swelling before printing because the battery dimensions are inherited design assumptions.

Native ElegooSlicer toolpaths verify continuous support and dense interfaces under every bridge and every saddle. All four saddle and upper-mount regions contain solid infill with zero sparse-infill paths. The raised floor is also supported. Estimated print is 17 h 24 m and 624.08 g including supports. No print was started.

These checks verify geometry and toolpaths. They cannot certify the strength of the finished PLA part. Perform a gradual ground load test with the intended hardware and six-pound payload before flight, and inspect for layer separation or permanent bending afterward.
""",
    encoding="utf-8",
)

print(json.dumps(report, indent=2))
