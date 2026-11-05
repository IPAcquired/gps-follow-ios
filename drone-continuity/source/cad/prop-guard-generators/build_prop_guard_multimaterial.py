"""Build a Centauri Carbon 2 printable PAHT-CF + TPU prop-guard package.

The assembled guard is one removable unit per aircraft arm.  It prints as:
1. PAHT-CF ladder saddle.
2. PAHT-CF front arc/rib section.
3. PAHT-CF rear arc/rib section.
4. Four small TPU snap bumper sections.

The two guard sections sit beneath the saddle and share the outboard aircraft
mounting bolt; the inboard bolt secures the saddle.  The design does not depend
on inter-material adhesion.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "prop-guard-11x7-v6-pahtcf-tpu"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "work"))
sys.path.insert(0, str(ROOT / "work" / "mesh-deps"))

import build_prop_guard as base
import manifold3d as md
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import trimesh

M = md.Manifold

# Core rails are lowered so the installed TPU caps remain 5 mm below the blade.
CORE_ARC_BOTTOM_Z = 11.0
CORE_ARC_TOP_Z = 18.0
CORE_ARC_HEIGHT = CORE_ARC_TOP_Z - CORE_ARC_BOTTOM_Z
ROOT_TONGUE_INNER_X = -58.0
ROOT_TONGUE_OUTER_X = base.SADDLE_OUTER_EDGE_X
ROOT_TONGUE_THICKNESS = 4.0
ROOT_TONGUE_BOTTOM_Z = -8.0
HALF_SADDLE_W = base.SADDLE_OUTER_WIDTH / 2.0

RIB_ROOT_W = 7.5
RIB_WAIST_W = 4.2
RIB_TIP_W = 7.0
RIB_DEPTH = 7.0
RIB_TOP_Z = 14.0

TPU_CLEARANCE = 0.35
TPU_WALL = 1.2
TPU_LIP = 1.0
TPU_OUTER_BOTTOM_Z = 10.0
TPU_OUTER_TOP_Z = 20.0
MEASURED_BLADE_UNDERSIDE_Z = 27.0

# Shorten only the inboard ends so each core lies flat on a 256 mm bed.
# Together the arcs still cover the complete outer semicircle and overlap 76 deg.
V6_FRONT_ARC_ANGLES = (-34.0, 89.0)
V6_REAR_ARC_ANGLES = (-89.0, 34.0)


def union(parts):
    solid = parts[0]
    for part in parts[1:]:
        solid = solid + part
    return solid


def centred_box(cx, cy, z, dx, dy, dz):
    return M.cube((dx, dy, dz)).translate((cx - dx / 2, cy - dy / 2, z))


def capsule_slot(cx: float, cy: float, z0: float, height: float):
    straight = base.SLOT_LENGTH - base.SLOT_WIDTH
    mid = M.cube((straight, base.SLOT_WIDTH, height)).translate(
        (cx - straight / 2, cy - base.SLOT_WIDTH / 2, z0)
    )
    a = M.cylinder(height, base.SLOT_WIDTH / 2, circular_segments=48).translate(
        (cx - straight / 2, cy, z0)
    )
    b = M.cylinder(height, base.SLOT_WIDTH / 2, circular_segments=48).translate(
        (cx + straight / 2, cy, z0)
    )
    return union([mid, a, b])


def arc(inner_r, outer_r, a0, a1):
    return base.annular_sector(inner_r, outer_r, CORE_ARC_BOTTOM_Z,
                               CORE_ARC_HEIGHT, a0, a1)


def rib(start, angle_deg, end_r):
    angle = math.radians(angle_deg)
    end = np.array([math.cos(angle) * end_r, math.sin(angle) * end_r])
    start = np.asarray(start, dtype=float)
    mid = start + (end - start) * 0.48
    root = centred_box(*start, ROOT_TONGUE_BOTTOM_Z + 0.5,
                       RIB_ROOT_W, RIB_ROOT_W, RIB_DEPTH)
    waist = centred_box(*mid, 2.0, RIB_WAIST_W, RIB_WAIST_W, RIB_DEPTH)
    tip = centred_box(*end, RIB_TOP_Z - RIB_DEPTH,
                      RIB_TIP_W, RIB_TIP_W, RIB_DEPTH)
    return union([union([root, waist]).hull(), union([waist, tip]).hull()])


def ladder_saddle():
    rail_w = 4.0
    bridge_l = 10.0
    pad_l = 22.0
    z0 = -base.SADDLE_BASE_THICKNESS
    parts = [
        M.cube((base.SADDLE_LENGTH, rail_w, base.SADDLE_BASE_THICKNESS)).translate(
            (base.SADDLE_INNER_EDGE_X, -HALF_SADDLE_W, z0)),
        M.cube((base.SADDLE_LENGTH, rail_w, base.SADDLE_BASE_THICKNESS)).translate(
            (base.SADDLE_INNER_EDGE_X, HALF_SADDLE_W - rail_w, z0)),
        M.cube((bridge_l, base.SADDLE_OUTER_WIDTH, base.SADDLE_BASE_THICKNESS)).translate(
            (base.SADDLE_INNER_EDGE_X, -HALF_SADDLE_W, z0)),
        M.cube((bridge_l, base.SADDLE_OUTER_WIDTH, base.SADDLE_BASE_THICKNESS)).translate(
            (base.SADDLE_OUTER_EDGE_X - bridge_l, -HALF_SADDLE_W, z0)),
    ]
    for x in base.SLOT_CENTRES_X:
        parts.append(M.cube((pad_l, base.SADDLE_OUTER_WIDTH,
                             base.SADDLE_BASE_THICKNESS)).translate(
            (x - pad_l / 2, -HALF_SADDLE_W, z0)))
    return union(parts) - union([
        capsule_slot(x, 0, -base.SADDLE_BASE_THICKNESS - 1,
                     base.SADDLE_BASE_THICKNESS + 2)
        for x in base.SLOT_CENTRES_X
    ])


def root_tongue(front: bool):
    y0 = 0.0 if front else -HALF_SADDLE_W
    tongue = M.cube((ROOT_TONGUE_OUTER_X - ROOT_TONGUE_INNER_X,
                     HALF_SADDLE_W, ROOT_TONGUE_THICKNESS)).translate(
        (ROOT_TONGUE_INNER_X, y0, ROOT_TONGUE_BOTTOM_Z)
    )
    return tongue - capsule_slot(base.SLOT_CENTRES_X[1], 0,
                                  ROOT_TONGUE_BOTTOM_Z - 1,
                                  ROOT_TONGUE_THICKNESS + 2)


def front_core():
    rail = arc(base.FRONT_ARC_INNER_R, base.FRONT_ARC_OUTER_R,
               *V6_FRONT_ARC_ANGLES)
    pieces = [
        rail,
        root_tongue(True),
        rib((-34.0, 3.5), 16.0, base.FRONT_ARC_INNER_R + 2.5),
        rib((-50.0, 10.0), 72.0, base.FRONT_ARC_INNER_R + 2.5),
    ]
    return union(pieces)


def rear_core():
    rail = arc(base.REAR_ARC_INNER_R, base.REAR_ARC_OUTER_R,
               *V6_REAR_ARC_ANGLES)
    pieces = [
        rail,
        root_tongue(False),
        rib((-34.0, -3.5), -16.0, base.REAR_ARC_INNER_R + 2.5),
        rib((-50.0, -10.0), -72.0, base.REAR_ARC_INNER_R + 2.5),
    ]
    return union(pieces)


def bumper(inner_r, outer_r, a0, a1):
    # C-channel cut from one envelope so the STL stays watertight.  The cavity
    # is extended past both angular ends to avoid coplanar Boolean seams.
    lip_inner = inner_r + 1.2
    envelope_outer = outer_r + TPU_CLEARANCE + TPU_WALL
    envelope = base.annular_sector(
        lip_inner, envelope_outer, TPU_OUTER_BOTTOM_Z,
        TPU_OUTER_TOP_Z - TPU_OUTER_BOTTOM_Z, a0, a1
    )
    cavity = base.annular_sector(
        0.1, outer_r + TPU_CLEARANCE,
        TPU_OUTER_BOTTOM_Z + TPU_LIP,
        TPU_OUTER_TOP_Z - TPU_OUTER_BOTTOM_Z - 2 * TPU_LIP,
        a0 - 0.4, a1 + 0.4,
    )
    return envelope - cavity


def mesh(solid):
    raw = solid.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(raw.vert_properties[:, :3]),
                           faces=np.asarray(raw.tri_verts), process=True)


def export_checked(solid, path):
    tm = mesh(solid)
    tm.export(path)
    tm = trimesh.load(path, force="mesh", process=True)
    counts = np.bincount(tm.edges_unique_inverse, minlength=len(tm.edges_unique))
    assert tm.is_watertight and tm.is_winding_consistent
    assert tm.body_count == 1 and np.all(counts == 2)
    assert np.all(tm.extents <= 256.0), (path.name, tm.extents)
    return {
        "file": path.name,
        "size_mm": tm.extents.tolist(),
        "volume_cm3": float(tm.volume / 1000),
        "triangles": int(len(tm.faces)),
        "watertight": True,
        "nonmanifold_edges": 0,
        "fits_256mm_build_volume_flat": True,
    }


def export_bumper_halves(prefix, inner_r, outer_r, angles):
    middle = (angles[0] + angles[1]) / 2.0
    overlap = 1.5
    pieces = [
        bumper(inner_r, outer_r, angles[0], middle + overlap),
        bumper(inner_r, outer_r, middle - overlap, angles[1]),
    ]
    return [
        export_checked(piece, OUT / f"TPU_{prefix}_Bumper_{i}.stl")
        for i, piece in enumerate(pieces, 1)
    ]


def render_preview(parts, path):
    colours = ["#3d5568", "#4f7896", "#4f7896", "#ef8b4c", "#ef8b4c",
               "#ef8b4c", "#ef8b4c"]
    fig = plt.figure(figsize=(11, 8), constrained_layout=True)
    ax = fig.add_subplot(111, projection="3d")
    all_vertices = []
    for solid, colour in zip(parts, colours):
        tm = mesh(solid)
        all_vertices.append(tm.vertices)
        poly = Poly3DCollection(tm.triangles, linewidths=0.05, alpha=0.95)
        poly.set_facecolor(colour)
        poly.set_edgecolor("#26313a")
        ax.add_collection3d(poly)
    verts = np.vstack(all_vertices)
    centre = (verts.min(axis=0) + verts.max(axis=0)) / 2
    radius = np.ptp(verts, axis=0).max() * 0.57
    ax.set_xlim(centre[0]-radius, centre[0]+radius)
    ax.set_ylim(centre[1]-radius, centre[1]+radius)
    ax.set_zlim(-55, 75)
    ax.set_box_aspect((1, 1, 0.38))
    ax.view_init(elev=30, azim=-48)
    ax.set_axis_off()
    ax.set_title("PAHT-CF structure with separate TPU snap bumpers", fontsize=16)
    fig.savefig(path, dpi=180, facecolor="white")
    plt.close(fig)


def main():
    saddle = ladder_saddle()
    front = front_core()
    rear = rear_core()
    front_bumpers = [
        bumper(base.FRONT_ARC_INNER_R, base.FRONT_ARC_OUTER_R,
               V6_FRONT_ARC_ANGLES[0], sum(V6_FRONT_ARC_ANGLES)/2 + 1.5),
        bumper(base.FRONT_ARC_INNER_R, base.FRONT_ARC_OUTER_R,
               sum(V6_FRONT_ARC_ANGLES)/2 - 1.5, V6_FRONT_ARC_ANGLES[1]),
    ]
    rear_bumpers = [
        bumper(base.REAR_ARC_INNER_R, base.REAR_ARC_OUTER_R,
               V6_REAR_ARC_ANGLES[0], sum(V6_REAR_ARC_ANGLES)/2 + 1.5),
        bumper(base.REAR_ARC_INNER_R, base.REAR_ARC_OUTER_R,
               sum(V6_REAR_ARC_ANGLES)/2 - 1.5, V6_REAR_ARC_ANGLES[1]),
    ]

    results = []
    results.append({"material": "PAHT-CF", **export_checked(
        saddle, OUT / "PAHTCF_Saddle_148mm.stl")})
    results.append({"material": "PAHT-CF", **export_checked(
        front, OUT / "PAHTCF_Front_Arc_and_Ribs.stl")})
    results.append({"material": "PAHT-CF", **export_checked(
        rear, OUT / "PAHTCF_Rear_Arc_and_Ribs.stl")})
    for i, part in enumerate(front_bumpers, 1):
        results.append({"material": "TPU", **export_checked(
            part, OUT / f"TPU_Front_Bumper_{i}.stl")})
    for i, part in enumerate(rear_bumpers, 1):
        results.append({"material": "TPU", **export_checked(
            part, OUT / f"TPU_Rear_Bumper_{i}.stl")})

    render_preview([saddle, front, rear, *front_bumpers, *rear_bumpers],
                   OUT / "Prop_Guard_V6_multimaterial_preview.png")

    paht_volume = sum(r["volume_cm3"] for r in results if r["material"] == "PAHT-CF")
    tpu_volume = sum(r["volume_cm3"] for r in results if r["material"] == "TPU")
    prop_disk_area = math.pi * (base.PROP_DIAMETER / 2) ** 2
    rib_lengths = []
    for start, angle, radius in [
        ((-34.0, 3.5), 16.0, base.FRONT_ARC_INNER_R + 2.5),
        ((-50.0, 10.0), 72.0, base.FRONT_ARC_INNER_R + 2.5),
        ((-34.0, -3.5), -16.0, base.REAR_ARC_INNER_R + 2.5),
        ((-50.0, -10.0), -72.0, base.REAR_ARC_INNER_R + 2.5),
    ]:
        end = np.array([math.cos(math.radians(angle))*radius,
                        math.sin(math.radians(angle))*radius])
        rib_lengths.append(float(np.linalg.norm(end - np.asarray(start))))
    average_width = ((RIB_ROOT_W + RIB_WAIST_W) * .48
                     + (RIB_WAIST_W + RIB_TIP_W) * .52) / 2
    rib_projected_area = sum(rib_lengths) * average_width

    report = {
        "units": "mm",
        "printer": {
            "model": "ELEGOO Centauri Carbon 2",
            "build_volume_mm": [256, 256, 256],
            "all_parts_fit_flat": True,
        },
        "materials": {
            "structural": "PAHT-CF",
            "impact_bumpers": "TPU, preferably 95A, printed separately",
            "PLA_or_PLA_CF": "not used in the load path",
        },
        "geometry": {
            "front_arc_angles_deg": list(V6_FRONT_ARC_ANGLES),
            "rear_arc_angles_deg": list(V6_REAR_ARC_ANGLES),
            "overlap_coverage_deg": V6_REAR_ARC_ANGLES[1] - V6_FRONT_ARC_ANGLES[0],
            "minimum_radial_blade_clearance_mm": base.TIP_RADIAL_CLEARANCE,
            "measured_blade_underside_above_arm_mm": MEASURED_BLADE_UNDERSIDE_Z,
            "installed_bumper_top_above_arm_mm": TPU_OUTER_TOP_Z,
            "static_vertical_clearance_to_blade_underside_mm": MEASURED_BLADE_UNDERSIDE_Z - TPU_OUTER_TOP_Z,
            "maximum_rib_width_mm": RIB_ROOT_W,
            "rib_waist_width_mm": RIB_WAIST_W,
            "bolt_spacing_mm": base.SLOT_CENTRE_SPACING,
            "slot_adjustment_travel_mm": base.SLOT_LENGTH - base.SLOT_WIDTH,
        },
        "aerodynamic_estimate": {
            "prop_disk_area_mm2": prop_disk_area,
            "rib_projected_area_upper_bound_mm2": rib_projected_area,
            "rib_projected_area_percent_of_prop_disk": rib_projected_area / prop_disk_area * 100,
            "note": "Arcs are outside the prop disc; saddle overlaps the existing arm shadow. This is projected-area screening, not CFD.",
        },
        "mass_estimate": {
            "PAHT_CF_volume_cm3": paht_volume,
            "TPU_volume_cm3": tpu_volume,
            "PAHT_CF_mass_g_at_1p15_g_cm3": paht_volume * 1.15,
            "TPU_mass_g_at_1p20_g_cm3": tpu_volume * 1.20,
            "estimated_total_per_guard_g": paht_volume * 1.15 + tpu_volume * 1.20,
            "note": "Use filament manufacturer density and slicer estimate for final mass.",
        },
        "files": results,
        "assembly": [
            "Print all PAHT-CF core parts and TPU bumpers separately.",
            "Place front and rear root tongues below the saddle at the outboard slot.",
            "The outboard aircraft bolt clamps both tongues and saddle; the inboard bolt clamps the saddle.",
            "Snap the two overlapping TPU bumper sections over each arc after the core is bolted together.",
        ],
        "limitations": [
            "Prototype geometry; not impact, fatigue, or flight certified.",
            "TPU must not extend above the modeled 20 mm top plane.",
            "Confirm all clearances by hand with neighboring propellers installed before powering ESCs.",
        ],
    }
    (OUT / "Prop_Guard_V6_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    notes = """# V6 PAHT-CF + TPU propeller guard

The load-bearing saddle, root tongues, ribs, and arc rails are PAHT-CF. The TPU
pieces are removable snap bumpers and are not part of the structural load path.
Do not replace the PAHT-CF core with PLA for flight use: PLA and PLA-CF are less
tolerant of heat and sharp impact, and PLA-CF is especially poor as a flexure.

The parts are split to fit a 256 mm square build plate. Assemble the front and
rear tongues below the saddle; the outboard aircraft bolt clamps all three core
layers, while the inboard bolt clamps the saddle. Install the TPU bumpers last.

The measured blade underside is 27 mm above the arm and the bumper top is
modeled 20 mm above the arm, leaving 7 mm of static vertical clearance.

The geometry is a prototype. Perform a static hand-deflection test and a
low-energy pendulum/tap test with no propellers installed, then install the
propellers and verify at least 12.7 mm radial clearance and 5 mm vertical
clearance under gentle blade deflection before powering the ESCs.
"""
    (OUT / "README.md").write_text(notes, encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
