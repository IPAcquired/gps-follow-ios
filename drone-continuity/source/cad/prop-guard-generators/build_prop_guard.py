"""Build a lightweight open-inner 11-inch propeller guard with a bottom saddle.

The design is intentionally hole-free at the aircraft interface.  The user will
locate and drill their own mounting holes after a physical fit check.

Coordinate system and supplied dimensions (millimetres):
* Motor shaft / propeller centre: X=0, Y=0.
* Top of the 28 x 4 aluminium arm: Z=0; the arm extends in -X.
* Propeller plane: Z=25.
* Arm runs along the X axis; a blank mounting tongue extends inward (-X).

The low-profile saddle mounts below the arm and ends before the motor-hardware
keepout. Four thin swept supports rise to two separate outer partial arcs below
the propeller plane. The inner side stays open so adjacent guards fit in the
25.4 mm prop-tip gap. One STL is one removable guard assembly for one arm.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "prop-guard-11x7-v5-light-flex"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "work" / "mesh-deps"))

import manifold3d as md
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import trimesh


# Confirmed aircraft dimensions.
PROP_DIAMETER = 279.4  # 11.0 inches
ARM_WIDTH = 27.5
ARM_THICKNESS = 3.0
ARM_LENGTH = 203.2  # 8.0 inches
PROP_PLANE_Z = 25.0
NEIGHBOUR_TIP_GAP = 25.4
NEIGHBOUR_MOTOR_SPACING = 410.1

# Conservative concept geometry.  The 310 mm opening leaves 15.3 mm radial
# clearance around the nominal 279.4 mm propeller disc.
TIP_RADIAL_CLEARANCE = 12.7  # half an inch
FRONT_ARC_INNER_R = PROP_DIAMETER / 2.0 + TIP_RADIAL_CLEARANCE
FRONT_ARC_OUTER_R = FRONT_ARC_INNER_R + 5.0
REAR_ARC_INNER_R = FRONT_ARC_OUTER_R + 1.0
REAR_ARC_OUTER_R = REAR_ARC_INNER_R + 5.0
ARC_BOTTOM_Z = 13.0
ARC_TOP_Z = 20.0
ARC_HEIGHT = ARC_TOP_Z - ARC_BOTTOM_Z
# Slightly offset from exact cardinal axes to avoid zero-area cap triangles in
# exported STL while preserving the intended approximate 135-degree coverage.
FRONT_ARC_ANGLES = (-44.5, 89.5)
REAR_ARC_ANGLES = (-89.5, 44.5)

SADDLE_LENGTH = 148.0
SADDLE_OUTER_EDGE_X = -25.0
SADDLE_INNER_EDGE_X = SADDLE_OUTER_EDGE_X - SADDLE_LENGTH
SADDLE_CONTACT_WIDTH = 27.5
SADDLE_OUTER_WIDTH = 27.5
SADDLE_BASE_THICKNESS = 4.0
SUPPORT_ROOT_WIDTH = 7.5
SUPPORT_WAIST_WIDTH = 4.2
SUPPORT_TIP_WIDTH = 7.0
SUPPORT_DEPTH = 7.0
SUPPORT_TOP_Z = 16.0
MOTOR_HARDWARE_KEEPOUT_DIAMETER = 50.0
SLOT_WIDTH = 4.6
SLOT_LENGTH = 8.6
SLOT_CENTRE_SPACING = 127.0
SLOT_CENTRES_X = (
    SADDLE_INNER_EDGE_X + (SADDLE_LENGTH - SLOT_CENTRE_SPACING) / 2.0,
    SADDLE_OUTER_EDGE_X - (SADDLE_LENGTH - SLOT_CENTRE_SPACING) / 2.0,
)

M = md.Manifold


def union(parts: list[M]) -> M:
    return M.batch_boolean(parts, md.OpType.Add)


def mesh(solid: M) -> trimesh.Trimesh:
    raw = solid.to_mesh()
    return trimesh.Trimesh(
        vertices=np.asarray(raw.vert_properties[:, :3]),
        faces=np.asarray(raw.tri_verts),
        process=True,
    )


def cylinder(height: float, radius: float, z: float, segments: int = 192) -> M:
    return M.cylinder(height, radius, circular_segments=segments).translate((0, 0, z))


def centred_box(cx: float, cy: float, z: float, dx: float, dy: float, dz: float) -> M:
    return M.cube((dx, dy, dz)).translate((cx - dx / 2.0, cy - dy / 2.0, z))


def swept_support(start: tuple[float, float], angle_deg: float, end_r: float) -> M:
    """Two-stage tapered rib: broad at joints, narrow through the downwash."""
    angle = math.radians(angle_deg)
    end = (math.cos(angle) * end_r, math.sin(angle) * end_r)
    mid = (start[0] + (end[0] - start[0]) * 0.48,
           start[1] + (end[1] - start[1]) * 0.48)
    low = centred_box(start[0], start[1], -3.0,
                      SUPPORT_ROOT_WIDTH, SUPPORT_ROOT_WIDTH, SUPPORT_DEPTH)
    waist = centred_box(mid[0], mid[1], 3.0,
                        SUPPORT_WAIST_WIDTH, SUPPORT_WAIST_WIDTH, SUPPORT_DEPTH)
    high = centred_box(
        end[0], end[1], SUPPORT_TOP_Z - SUPPORT_DEPTH,
        SUPPORT_TIP_WIDTH, SUPPORT_TIP_WIDTH, SUPPORT_DEPTH,
    )
    return union([union([low, waist]).hull(), union([waist, high]).hull()])


def annular_sector(inner_r: float, outer_r: float, z: float, height: float,
                   angle_start: float, angle_end: float, samples: int = 96) -> M:
    angles = np.linspace(math.radians(angle_start), math.radians(angle_end), samples)
    outer = [(outer_r * math.cos(a), outer_r * math.sin(a)) for a in angles]
    inner = [(inner_r * math.cos(a), inner_r * math.sin(a)) for a in angles[::-1]]
    contour = np.asarray(outer + inner, dtype=float)
    return md.CrossSection([contour]).extrude(height).translate((0, 0, z))


def stiffened_arc(inner_r: float, outer_r: float,
                  angle_start: float, angle_end: float) -> M:
    """Thin arc rail; the swept supports serve as its tapered ribs."""
    return annular_sector(inner_r, outer_r, ARC_BOTTOM_Z, ARC_HEIGHT,
                          angle_start, angle_end)


def capsule_slot(cx: float, cy: float) -> M:
    straight = SLOT_LENGTH - SLOT_WIDTH
    centre = M.cube((straight, SLOT_WIDTH, SADDLE_BASE_THICKNESS + 2.0)).translate(
        (cx - straight / 2.0, cy - SLOT_WIDTH / 2.0, -SADDLE_BASE_THICKNESS - 1.0)
    )
    end_a = M.cylinder(SADDLE_BASE_THICKNESS + 2.0, SLOT_WIDTH / 2.0,
                       circular_segments=48).translate(
        (cx - straight / 2.0, cy, -SADDLE_BASE_THICKNESS - 1.0)
    )
    end_b = M.cylinder(SADDLE_BASE_THICKNESS + 2.0, SLOT_WIDTH / 2.0,
                       circular_segments=48).translate(
        (cx + straight / 2.0, cy, -SADDLE_BASE_THICKNESS - 1.0)
    )
    return union([centre, end_a, end_b])


def build_guard() -> M:
    front_arc = stiffened_arc(FRONT_ARC_INNER_R, FRONT_ARC_OUTER_R,
                              *FRONT_ARC_ANGLES)
    rear_arc = stiffened_arc(REAR_ARC_INNER_R, REAR_ARC_OUTER_R,
                             *REAR_ARC_ANGLES)

    # Ladder saddle: side rails distribute load along the arm; full-width pads
    # surround both bolt slots. This removes the low-stress middle material.
    rail_w = 4.0
    end_bridge_l = 10.0
    bolt_pad_l = 22.0
    saddle_parts = [
        M.cube((SADDLE_LENGTH, rail_w, SADDLE_BASE_THICKNESS)).translate(
            (SADDLE_INNER_EDGE_X, -SADDLE_OUTER_WIDTH / 2.0, -SADDLE_BASE_THICKNESS)),
        M.cube((SADDLE_LENGTH, rail_w, SADDLE_BASE_THICKNESS)).translate(
            (SADDLE_INNER_EDGE_X, SADDLE_OUTER_WIDTH / 2.0 - rail_w, -SADDLE_BASE_THICKNESS)),
        M.cube((end_bridge_l, SADDLE_OUTER_WIDTH, SADDLE_BASE_THICKNESS)).translate(
            (SADDLE_INNER_EDGE_X, -SADDLE_OUTER_WIDTH / 2.0, -SADDLE_BASE_THICKNESS)),
        M.cube((end_bridge_l, SADDLE_OUTER_WIDTH, SADDLE_BASE_THICKNESS)).translate(
            (SADDLE_OUTER_EDGE_X - end_bridge_l, -SADDLE_OUTER_WIDTH / 2.0, -SADDLE_BASE_THICKNESS)),
    ]
    for slot_x in SLOT_CENTRES_X:
        saddle_parts.append(
            M.cube((bolt_pad_l, SADDLE_OUTER_WIDTH, SADDLE_BASE_THICKNESS)).translate(
                (slot_x - bolt_pad_l / 2.0, -SADDLE_OUTER_WIDTH / 2.0,
                 -SADDLE_BASE_THICKNESS)
            )
        )
    saddle = union(saddle_parts) - union(
        [capsule_slot(x, 0.0) for x in SLOT_CENTRES_X]
    )

    starts = [
        ((SADDLE_OUTER_EDGE_X - 5.0, 0.0), 0.0,
         (FRONT_ARC_INNER_R + REAR_ARC_OUTER_R) / 2.0),
        ((-98.0, 8.0), 68.0, FRONT_ARC_INNER_R + 2.5),
        ((-98.0, -8.0), -68.0, REAR_ARC_INNER_R + 2.5),
    ]
    supports = [swept_support(start, angle, end_r) for start, angle, end_r in starts]
    # Sequential unions generate a cleaner exported boundary at the partial-arc
    # end caps than a single batch Boolean.
    solid = front_arc
    for part in [rear_arc, saddle, *supports]:
        solid = solid + part
    return solid


def export_checked(solid: M, path: Path) -> dict:
    tm = mesh(solid)
    tm.export(path)
    delivered = trimesh.load(path, force="mesh", process=True)
    edges = np.bincount(
        delivered.edges_unique_inverse, minlength=len(delivered.edges_unique)
    )
    assert delivered.is_watertight, path.name
    assert delivered.is_winding_consistent, path.name
    assert np.all(edges == 2), path.name
    return {
        "file": path.name,
        "bounds_mm": delivered.bounds.tolist(),
        "size_mm": delivered.extents.tolist(),
        "volume_cm3": float(delivered.volume / 1000.0),
        "triangles": int(len(delivered.faces)),
        "watertight": bool(delivered.is_watertight),
        "winding_consistent": bool(delivered.is_winding_consistent),
        "connected_components": int(delivered.body_count),
        "nonmanifold_edges": int(np.count_nonzero(edges != 2)),
    }


def render_dimension_sheet(path: Path) -> None:
    fig, (top, side) = plt.subplots(1, 2, figsize=(14, 7), constrained_layout=True)

    top.set_aspect("equal")
    top.add_patch(Circle((0, 0), PROP_DIAMETER / 2, fill=False, edgecolor="#d94f43", ls="--", lw=2))
    for radius, angles, colour in [
        ((FRONT_ARC_INNER_R + FRONT_ARC_OUTER_R) / 2.0, FRONT_ARC_ANGLES, "#263747"),
        ((REAR_ARC_INNER_R + REAR_ARC_OUTER_R) / 2.0, REAR_ARC_ANGLES, "#46627a"),
    ]:
        aa = np.linspace(math.radians(angles[0]), math.radians(angles[1]), 150)
        top.plot(radius * np.cos(aa), radius * np.sin(aa), color=colour, lw=8,
                 solid_capstyle="round")
    drawing_starts = [
        ((SADDLE_OUTER_EDGE_X - 5.0, 0.0), 0.0,
         (FRONT_ARC_INNER_R + REAR_ARC_OUTER_R) / 2.0),
        ((-98.0, 8.0), 68.0, FRONT_ARC_INNER_R + 2.5),
        ((-98.0, -8.0), -68.0, REAR_ARC_INNER_R + 2.5),
    ]
    for (sx, sy), a, target_r in drawing_starts:
        th = math.radians(a)
        top.plot(
            [sx, math.cos(th) * target_r],
            [sy, math.sin(th) * target_r],
            color="#557a95",
            lw=4.2,
            solid_capstyle="butt",
        )
    top.add_patch(Rectangle((SADDLE_INNER_EDGE_X, -SADDLE_OUTER_WIDTH / 2),
                            SADDLE_LENGTH, SADDLE_OUTER_WIDTH,
                            facecolor="#557a95", edgecolor="#111", alpha=0.9))
    for slot_x in SLOT_CENTRES_X:
        top.add_patch(Rectangle((slot_x - SLOT_LENGTH / 2.0, -SLOT_WIDTH / 2.0),
                                SLOT_LENGTH, SLOT_WIDTH,
                                facecolor="white", edgecolor="#111", lw=1.0))
    top.add_patch(Circle((0, 0), MOTOR_HARDWARE_KEEPOUT_DIAMETER / 2,
                         fill=False, edgecolor="#8c6f47", ls=":", lw=2))
    max_r = REAR_ARC_OUTER_R
    top.annotate("326.8 mm maximum outside", (-max_r, max_r + 18),
                 (max_r, max_r + 18),
                 arrowprops={"arrowstyle": "<->"}, ha="center", va="center")
    top.text(0, max_r + 28, "open inner half; two overlapping outer arcs", ha="center", fontsize=10)
    top.text(0, -max_r - 22, "Dashed red: nominal 279.4 mm (11 in) propeller disc",
             ha="center", color="#b3362d")
    top.set_xlim(-195, 195)
    top.set_ylim(-195, 210)
    top.set_title("Top view — inner side open toward the frame")
    top.axis("off")

    side.set_aspect("equal")
    side.add_patch(Rectangle((-105, -ARM_THICKNESS), ARM_LENGTH, ARM_THICKNESS,
                             facecolor="#a9adb1", edgecolor="#555"))
    side.add_patch(Rectangle((SADDLE_INNER_EDGE_X, -SADDLE_BASE_THICKNESS),
                             SADDLE_LENGTH, SADDLE_BASE_THICKNESS,
                             facecolor="#557a95", edgecolor="#111"))
    side.add_patch(Rectangle((FRONT_ARC_INNER_R, ARC_BOTTOM_Z),
                             REAR_ARC_OUTER_R - FRONT_ARC_INNER_R, ARC_HEIGHT,
                             facecolor="#263747", edgecolor="#111", alpha=0.9))
    side.plot([SADDLE_OUTER_EDGE_X, FRONT_ARC_INNER_R], [-1, SUPPORT_TOP_Z - 2],
              color="#557a95", lw=5)
    side.axhline(PROP_PLANE_Z, color="#d94f43", ls="--", lw=2)
    side.annotate("", xy=(180, 0), xytext=(180, PROP_PLANE_Z),
                  arrowprops={"arrowstyle": "<->", "lw": 1.4})
    side.text(185, PROP_PLANE_Z / 2, "25 mm", va="center")
    side.text(-150, PROP_PLANE_Z + 3, "propeller plane", color="#b3362d")
    side.text(-145, -12, "27.5 × 3 mm aluminium arm (shown edge-on)")
    side.text(-145, -21, "148 mm bottom saddle; two slotted bolt positions")
    side.set_xlim(-195, 205)
    side.set_ylim(-30, 55)
    side.set_title("Side view — arc top remains 5 mm below the propeller")
    side.axis("off")

    fig.suptitle("11×7 Open-Inner Propeller Guard — dimensioned concept", fontsize=16, weight="bold")
    fig.savefig(path, dpi=180, facecolor="white")
    plt.close(fig)


def render_isometric(stl_path: Path, image_path: Path) -> None:
    tm = trimesh.load(stl_path, force="mesh", process=True)
    fig = plt.figure(figsize=(10, 8), constrained_layout=True)
    ax = fig.add_subplot(111, projection="3d")
    poly = Poly3DCollection(tm.triangles, linewidths=0.08, alpha=1.0)
    poly.set_facecolor("#4f7896")
    poly.set_edgecolor("#23313d")
    ax.add_collection3d(poly)
    b = tm.bounds
    centre = b.mean(axis=0)
    radius = max(tm.extents) * 0.57
    ax.set_xlim(centre[0] - radius, centre[0] + radius)
    ax.set_ylim(centre[1] - radius, centre[1] + radius)
    ax.set_zlim(-45, 70)
    ax.set_box_aspect((1, 1, 0.36))
    ax.view_init(elev=28, azim=-48)
    ax.set_axis_off()
    ax.set_title("11×7 open-inner guard — bottom saddle with adjustment slots", fontsize=16)
    fig.savefig(image_path, dpi=180, facecolor="white")
    plt.close(fig)


def main() -> None:
    guard = build_guard()
    results = []
    full_path = OUT / "Prop_Guard_11x7_V5_Light_Flex_Open_Inner.stl"
    results.append(export_checked(guard, full_path))

    render_dimension_sheet(OUT / "Prop_Guard_11x7_dimension_sheet.png")
    render_isometric(full_path, OUT / "Prop_Guard_11x7_isometric_preview.png")

    report = {
        "units": "mm",
        "input": {
            "propeller": "11x7",
            "propeller_diameter_mm": PROP_DIAMETER,
            "arm_width_mm": ARM_WIDTH,
            "arm_thickness_mm": ARM_THICKNESS,
            "arm_length_mm": ARM_LENGTH,
            "arm_material": "7075 aluminium (user supplied)",
            "propeller_plane_above_arm_top_mm": PROP_PLANE_Z,
            "neighbour_prop_tip_gap_mm": NEIGHBOUR_TIP_GAP,
            "measured_neighbour_motor_spacing_mm": NEIGHBOUR_MOTOR_SPACING,
        },
        "design": {
            "front_arc_angles_deg": list(FRONT_ARC_ANGLES),
            "rear_arc_angles_deg": list(REAR_ARC_ANGLES),
            "arc_coverage_union_deg": max(FRONT_ARC_ANGLES[1], REAR_ARC_ANGLES[1]) - min(FRONT_ARC_ANGLES[0], REAR_ARC_ANGLES[0]),
            "arc_overlap_coverage_deg": min(FRONT_ARC_ANGLES[1], REAR_ARC_ANGLES[1]) - max(FRONT_ARC_ANGLES[0], REAR_ARC_ANGLES[0]),
            "inner_side_open": True,
            "minimum_radial_prop_clearance_mm": TIP_RADIAL_CLEARANCE,
            "arc_top_below_prop_plane_mm": PROP_PLANE_Z - ARC_TOP_Z,
            "arc_section": "thin 5 x 7 mm rail with tapered swept support ribs",
            "support_count": 3,
            "support_width_root_waist_tip_mm": [SUPPORT_ROOT_WIDTH, SUPPORT_WAIST_WIDTH, SUPPORT_TIP_WIDTH],
            "support_depth_mm": SUPPORT_DEPTH,
            "support_outer_top_z_mm": SUPPORT_TOP_Z,
            "support_clearance_below_prop_plane_mm": PROP_PLANE_Z - SUPPORT_TOP_Z,
            "saddle_contact_width_mm": SADDLE_CONTACT_WIDTH,
            "saddle_outer_width_mm": SADDLE_OUTER_WIDTH,
            "saddle_length_mm": SADDLE_LENGTH,
            "saddle_base_thickness_mm": SADDLE_BASE_THICKNESS,
            "motor_hardware_keepout_diameter_mm": MOTOR_HARDWARE_KEEPOUT_DIAMETER,
            "motor_mount_patterns_cleared_mm": [[16.0, 16.0], [19.0, 19.0]],
            "maximum_support_width_between_props_mm": SUPPORT_ROOT_WIDTH,
            "adjustment_slots_mm": [SLOT_LENGTH, SLOT_WIDTH],
            "adjustment_travel_mm": SLOT_LENGTH - SLOT_WIDTH,
            "bolt_centre_spacing_mm": SLOT_CENTRE_SPACING,
            "adjustment_slot_centres_x_mm": list(SLOT_CENTRES_X),
            "mounting": "single removable piece per arm",
        },
        "verification": results,
        "limitations": [
            "Concept geometry only; no physical fit test or impact/load certification.",
            "The 25 mm height was interpreted from the arm top surface to the propeller plane.",
            "The motor centre is the CAD origin; position the blank tongue and drill only after a physical alignment check.",
            "The 4.6 mm slots assume M4-class hardware; resize before printing if the actual bolts differ.",
            "Verify static blade and adjacent-guard clearance through full hand rotation before powering the ESC.",
        ],
    }
    (OUT / "Prop_Guard_11x7_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    notes = f"""# 11×7 propeller guard concept

This model uses the supplied 28 × 4 mm, 203.2 mm long aluminium arm and a
propeller plane 25 mm above the top of the arm.

- Nominal propeller diameter: {PROP_DIAMETER:.1f} mm
- Minimum radial blade clearance: {TIP_RADIAL_CLEARANCE:.1f} mm (0.5 in)
- Two separate 135-degree outer arcs with 90 degrees of overlapping coverage
- Inner 180 degrees stays open toward the frame and neighbouring propeller
- Arc top: {PROP_PLANE_Z-ARC_TOP_Z:.1f} mm below the propeller plane
- Three swept ribs, 7.5 mm at the roots and 4.2 mm through the downwash
- Bottom saddle 148 × 27.5 × 4 mm, matching the measured arm width
- Ladder-frame saddle removes low-stress centre material
- Two 8.6 × 4.6 mm adjustment slots for M4-class hardware
- Slot centres 127 mm apart with 4 mm adjustment travel
- 50 mm diameter motor-hardware keepout

The STL is a single removable assembly for one arm.  The front and rear arcs
remain separate and join only through their thin swept supports and common
bottom saddle.

This is a geometric prototype.  Before powering the ESC, align the guard to the
motor shaft, drill and fasten it, then rotate the propeller through a full turn
by hand and confirm clearance under gentle downward blade deflection.  A printed
guard for this aircraft should be physically load-tested before flight.
"""
    (OUT / "README.md").write_text(notes, encoding="utf-8")

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
