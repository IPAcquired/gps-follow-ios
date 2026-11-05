from __future__ import annotations

import hashlib
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
DEPS = Path(
    r"C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s\work\mesh-deps"
)
sys.path.insert(0, str(DEPS))

import manifold3d as md  # noqa: E402
import trimesh  # noqa: E402

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402


SOURCE = OUT / "Four_Across_REINFORCED.stl"
PROJECT_SOURCE = OUT / "Four_Across_REINFORCED.3mf"
NAME = "Four_Across_HEAVY_DUTY_MOUNTS"
M = md.Manifold


def manifold_from_trimesh(mesh: trimesh.Trimesh) -> M:
    return M(
        md.Mesh(
            np.asarray(mesh.vertices, dtype=np.float32),
            np.asarray(mesh.faces, dtype=np.uint32),
        )
    )


def trimesh_from_manifold(solid: M) -> trimesh.Trimesh:
    raw = solid.to_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(raw.vert_properties[:, :3]),
        faces=np.asarray(raw.tri_verts),
        process=True,
    )


def box(x: float, y: float, z: float, dx: float, dy: float, dz: float) -> M:
    return M.cube((dx, dy, dz)).translate((x, y, z))


base_mesh = trimesh.load(SOURCE, force="mesh", process=True)
base = manifold_from_trimesh(base_mesh)
assert base.status() == md.Error.NoError

# Broad, tapered saddles directly beneath the unchanged 16 x 20 mm pad faces.
# Their lowest point is 48 mm, leaving 2 mm above the modeled 46 mm battery
# envelopes.  The upper footprint is wider than each pad to spread its load
# into both the bridge and its permanent bridge gusset.
saddles: list[M] = []
for center_y in (15.0, 125.0):
    lower_left = box(12.0, center_y - 11.0, 48.0, 24.0, 22.0, 2.0)
    upper_left = box(9.0, center_y - 13.0, 57.0, 30.0, 26.0, 3.9)
    left_saddle = M.batch_boolean([lower_left, upper_left], md.OpType.Add).hull()
    saddles.append(left_saddle)
    saddles.append(left_saddle.mirror((1, 0, 0)).translate((160.0, 0.0, 0.0)))

added = M.batch_boolean(saddles, md.OpType.Add)
solid = base + added
heavy_mesh = trimesh_from_manifold(solid)
stl_path = OUT / f"{NAME}.stl"
heavy_mesh.export(stl_path)
heavy_mesh = trimesh.load(stl_path, force="mesh", process=True)

edge_counts = np.bincount(
    heavy_mesh.edges_unique_inverse, minlength=len(heavy_mesh.edges_unique)
)
assert heavy_mesh.is_watertight
assert heavy_mesh.is_winding_consistent
assert heavy_mesh.body_count == 1
assert np.all(edge_counts == 2)
assert np.allclose(heavy_mesh.bounds, base_mesh.bounds, atol=1e-5)

# These checks make the protected mounting interface and usable modeled pack
# envelopes fail closed if the new geometry crosses them.
pad_slab = box(-50, -20, 61.0, 260, 190, 6.0)
base_pad = base ^ pad_slab
new_pad = solid ^ pad_slab
pad_delta = (base_pad - new_pad).volume() + (new_pad - base_pad).volume()
pack_x = (-17.0, 32.0, 81.0, 130.0)
pack_collisions = [
    (solid ^ box(x, -1.0, 0.0, 47.0, 142.0, 46.0)).volume()
    for x in pack_x
]
sensor_collision = (
    solid ^ box(54.6, 44.6, -10.0, 50.8, 50.8, 10.0)
).volume()
assert pad_delta < 1e-6
assert max(pack_collisions) < 1e-6
assert sensor_collision < 1e-6

# Create a fresh editable project while retaining the already verified printer,
# filament, and support settings. Four enlarged modifiers force the entire new
# saddle and upper mounting structure to print solid.
with zipfile.ZipFile(PROJECT_SOURCE) as source_zip:
    content = {name: source_zip.read(name) for name in source_zip.namelist()}

core = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
prod = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
q = "{" + core + "}"
ET.register_namespace("", core)
ET.register_namespace("p", prod)
object_path = f"3D/Objects/{NAME}.model"
model = ET.Element(q + "model", {"unit": "millimeter"})
resources = ET.SubElement(model, q + "resources")
center = np.array([80.0, 70.0, 28.5])

modifier_solids = [
    box(x, y, -6.0, 78.0, 32.0, 73.0)
    for y in (-1.0, 109.0)
    for x in (-35.0, 117.0)
]
objects = [heavy_mesh] + [trimesh_from_manifold(item) for item in modifier_solids]
for object_id, mesh in enumerate(objects, 1):
    obj = ET.SubElement(
        resources, q + "object", {"id": str(object_id), "type": "model"}
    )
    mesh_xml = ET.SubElement(obj, q + "mesh")
    vertices = ET.SubElement(mesh_xml, q + "vertices")
    triangles = ET.SubElement(mesh_xml, q + "triangles")
    for point in mesh.vertices - center:
        ET.SubElement(
            vertices,
            q + "vertex",
            dict(zip(("x", "y", "z"), (f"{value:.7f}" for value in point))),
        )
    for face in mesh.faces:
        ET.SubElement(
            triangles,
            q + "triangle",
            dict(zip(("v1", "v2", "v3"), map(str, face))),
        )
content[object_path] = ET.tostring(model, encoding="utf-8", xml_declaration=True)

main = ET.fromstring(content["3D/3dmodel.model"])
for component in main.findall(".//" + q + "component"):
    component.set("{" + prod + "}path", "/" + object_path)
content["3D/3dmodel.model"] = ET.tostring(
    main, encoding="utf-8", xml_declaration=True
)

relationships = content["3D/_rels/3dmodel.model.rels"].decode("utf-8")
old_paths = {
    relationship.split('Target="', 1)[1].split('"', 1)[0]
    for relationship in relationships.split("<Relationship")[1:]
    if 'Target="' in relationship and "/3D/Objects/" in relationship
}
for old_path in old_paths:
    relationships = relationships.replace(old_path, "/" + object_path)
content["3D/_rels/3dmodel.model.rels"] = relationships.encode("utf-8")

config = ET.fromstring(content["Metadata/model_settings.config"])
for metadata in config.findall(".//metadata"):
    key = metadata.get("key")
    if key in ("name", "source_file") and metadata.get("value", "").endswith(
        ".stl"
    ):
        metadata.set("value", NAME + ".stl")
content["Metadata/model_settings.config"] = ET.tostring(
    config, encoding="utf-8", xml_declaration=True
)

for entry in list(content):
    if entry.startswith("3D/Objects/") and entry != object_path:
        del content[entry]
    elif entry.endswith(".png") or entry in (
        "Metadata/slice_info.config",
        "Metadata/plate_1.json",
    ):
        del content[entry]

project_path = OUT / f"{NAME}.3mf"
with zipfile.ZipFile(project_path, "w", zipfile.ZIP_DEFLATED) as destination:
    for entry, data in content.items():
        destination.writestr(entry, data)

# A simple section screen shows the added saddle's load-spreading change. This
# is geometry-based only and deliberately is not labeled a load rating.
total_added = (solid - base).volume()
screen = {
    "source": str(SOURCE),
    "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "overall_mm": heavy_mesh.extents.tolist(),
    "watertight": bool(heavy_mesh.is_watertight),
    "connected_bodies": int(heavy_mesh.body_count),
    "nonmanifold_edges": int(np.count_nonzero(edge_counts != 2)),
    "mount_pattern_mm": [110.0, 110.0],
    "mount_face_symmetric_difference_mm3": pad_delta,
    "maximum_pack_envelope_intersection_mm3": max(pack_collisions),
    "sensor_opening_intersection_mm3": sensor_collision,
    "added_mount_saddle_volume_mm3": total_added,
    "minimum_modeled_vertical_pack_to_saddle_clearance_mm": 2.0,
    "saddle_bounds_each_left_mm": {
        "x": [9.0, 39.0],
        "y_about_mount_center": [-13.0, 13.0],
        "z": [48.0, 60.9],
    },
    "print_requirement": (
        "Use the supplied 3MF or sliced G-code project so the four enlarged "
        "100% infill modifiers and verified support settings are retained."
    ),
    "physical_load_tested": False,
}
(OUT / f"{NAME}_Geometry_Checks.json").write_text(
    json.dumps(screen, indent=2), encoding="utf-8"
)

figure = plt.figure(figsize=(12, 8))
axis = figure.add_subplot(111, projection="3d")
for shape, color, alpha in ((base, "#9db1c2", 0.22), (solid - base, "#e56b1f", 1.0)):
    shape_mesh = trimesh_from_manifold(shape)
    axis.add_collection3d(
        Poly3DCollection(
            shape_mesh.triangles, facecolor=color, edgecolor="none", alpha=alpha
        )
    )
axis.set(
    xlim=(-38, 198),
    ylim=(-10, 150),
    zlim=(-12, 72),
    xlabel="X (mm)",
    ylabel="Y (mm)",
    zlabel="Z (mm)",
)
axis.set_box_aspect((228, 152, 85))
axis.view_init(25, -55)
axis.set_title("Four-across heavy-duty mounts: orange = added under-pad saddles")
figure.tight_layout()
figure.savefig(OUT / f"{NAME}_Preview.png", dpi=160)
plt.close(figure)

print(json.dumps(screen, indent=2))
