# V10 lightweight PETG semicircle with screw-on TPU

Geometry-checked prototype. The design is lighter and uses more ductile rigid material, but spring-back, impact strength and aerodynamic performance are not validated.

## What changed
- Original open semicircle retained; 38.80 mm round mounting plate retained; aircraft holes are still for the user to drill.
- PETG replaces PLA, as requested. Four rounded-planform, tapered I-section spokes replace the broad solid beams. Nominal central section: 6 mm width, 22 mm height, 2.4 mm web and 1.5 mm top/bottom flanges. Roots and tips are wider; local rounded gussets spread loads at mounting feet.
- Rim is an open C-channel with 1.8 mm upper/lower flanges and 2 mm outer web. Screw recesses retain solid bearing bosses rather than being drilled through hollow sections.
- Four screw-on TPU strips retain two screws each. The continuous heavy underside flange has been replaced by local washer-supported lugs. Outer TPU band is 2.4 mm thick; nominal radial gap to the PETG is 0.35 mm.
- Mount remains 6 mm thick; mounting feet remain 10 mm thick. The two rigid halves attach with four screws, and a curved splice joins the outer seam.

## Measured comparison with V9
- Solid-geometry material estimate: **160.0 g per guard**, comprising 141.0 g PETG and 19.0 g TPU. This is **58.3% lighter** than the roughly 384 g V9 estimate. Hardware, supports and actual infill are excluded. Reference PETG density is 1.27 g/cm³; TPU uses an assumed 1.20 g/cm³.
- Projected core area inside the nominal propeller disk decreases **48.5%**, from 10913 to 5620 mm². This is an obstruction comparison, not CFD, a drag coefficient or a measured thrust improvement. Existing-arm shadow was not subtracted.
- The ideal straight beam section is about 43 times stiffer in vertical bending than lateral bending. This explains the section choice; the routed, ring-connected assembly does not have that same stiffness ratio.

## Geometry and printer checks
- Eight exported, reloaded, watertight, consistently wound, single-body STL files.
- No inter-part, modeled-arm, motor-keepout or specified-hardware collisions above 0.001 cubic mm. Contact surfaces at mounting feet, screw lugs and splice are intentional.
- Largest individual part approximately 228.8 × 164.8 × 38.0 mm. A centered footprint with a 5 mm brim fits within the previously supplied 256 × 256 mm tray.
- Rim/TPU top remains 19 mm above arm top, 8 mm below the previously supplied 27 mm blade underside. Nominal rigid-rim radial blade clearance remains approximately 12.9 mm.
- Modeled arm is 27.5 mm wide and 3 mm thick. Motor keepout is a 50 mm diameter cylinder from 3 mm below arm top to 27 mm above it. Real aircraft dimensions and neighboring guards still require a physical fit check.

## How it flexes and returns
The PETG core is intended to allow small elastic movements while resisting vertical bending. The slimmer TPU outer strips provide the softer contact surface and can deform locally. PETG is less brittle and more flexible than PLA according to the manufacturer material guide; that does not make this guard a proven spring. No printed rebound, permanent-set, damping or fatigue test has been performed. Avoid repeated large flexing, and do not assume it survives propeller strikes.
Material guide: https://prusament.com/materials/prusament-petg/
Technical reference: https://storage.googleapis.com/prusa3d-content-prod-14e8-wordpress-prusament-prod/2023/10/9f8d2165-tds_prusament-petg_n_en.pdf

## Structural screening
A tetrahedral linear-static screen was run on the front rigid half, with its two mounting washer areas ideally fixed. The rear half, splice coupling, TPU and actual aircraft attachment were excluded. Material was assumed homogeneous, isotropic, fully dense PETG with E=1.5 GPa and Poisson ratio 0.35. The final mesh has 5,252 nodes and 19,737 tetrahedra, no rejected elements, and volume matching the STL within numerical precision. Mesh convergence has not been established.

| Static force applied over outer crown patch | Mean crown movement | Maximum movement | Interior stress, volume-weighted 99th percentile | Peak stress, mesh dependent |
| --- | ---: | ---: | ---: | ---: |
| 5 N inward | 0.083 mm | 0.094 mm | 0.35 MPa | 7.3 MPa |
| 5 N outward | 0.083 mm | 0.094 mm | 0.35 MPa | 7.3 MPa |
| 5 N upward | 0.637 mm | 0.679 mm | 0.90 MPa | 42.4 MPa |

The screened small loads did not move the modeled rigid rim into the nominal blade radius, and the estimated underside gap over the blade disk remained about 10 mm. These deformed-geometry checks use a linear displacement field and exclude actual blade deflection, joint slip, print anisotropy and aircraft movement.
**The upward-load case still has a localized stress peak of about 42 MPa near a routed-spoke transition. It is not a verified safety margin.** Peak stress is sensitive to tetrahedral quality, local corners and restraints, and needs mesh refinement/physical testing. The reference material datasheet reports printed tensile yield around 47 MPa and interlayer adhesion around 18 MPa under its own test conditions. Those values cannot be used to declare this printed part safe, especially with different layer orientation. A linear model also assumes elastic return, so it cannot prove actual rebound.
The idealized beam estimate in the geometry report is a separate sensitivity calculation: a constant straight I-section at a 230 mm span. It predicts larger deflections than this routed/ring-supported FEA model. Neither is a rated load capacity. Aircraft fastening, buckling, impact, fatigue, creep and thermal effects remain unresolved.

## Printing
Use `print_ready_parts/` for the eight individual STLs, in millimetres. The core halves are oriented rim-top-down for bed contact. Supports are required below the raised mounting feet and selected spoke/channel areas; open I and C channels allow access for support removal. Confirm support access and hole openings in the slicer. This package does not contain verified G-code or a printer-specific sliced project.
Print PETG structural parts separately from TPU. Use filament-vendor/printer profiles. A 0.6 mm nozzle is compatible with the nominal 2.4 mm web and 1.8 mm rim flanges, but inspect the generated wall paths. Structural thin sections, screw bosses, mounting feet and splice need continuous solid walls; sparse infill does not reproduce the fully dense simulation. A 0.20–0.24 mm layer height and sufficient perimeter coverage are a starting point, not a validated print recipe.

## Hardware and assembly
| Use | Quantity | Hardware |
| --- | ---: | --- |
| Halves to round mount | 4 | M3 × 18 mm button-head screw |
| TPU lugs to rim | 8 | M3 × 14 mm button-head screw |
| Rim splice | 2 | M3 × 16 mm button-head screw |
| Washers | 14 | M3, OD 7 mm, ID 3.4 mm, thickness 0.6 mm |
| Nuts | 14 | M3, height 2.4 mm, maximum circumscribed diameter 6.4 mm |
Heads must be at most 6.0 mm diameter × 2.0 mm high; recesses are 6.4 mm diameter × 2.2 mm deep. Holes are 3.4 mm. Different hardware needs a new clearance check. Aircraft bolts are additional and depend on your drilled pattern.
Fit the core halves beneath the round pad and install the four recessed mount screws before fastening to the arm. Bolt the small curved splice beneath the outer seam. Fit each TPU strip to its matching rim holes, inserting two screws through the PETG bosses and TPU lugs; washers and nuts sit below the TPU. Through-bolts avoid relying on cut threads in either plastic. Tightening torque and printed lug pull-through strength have not been established; avoid crushing the TPU.
Mark aircraft holes on the actual arm while avoiding the assembly recesses and preserving material around holes. Check the attachment cannot rotate, slip or tilt into the blades. The actual drilled pattern has not been modeled.

## Delivery status
Lighter geometry, reduced projected obstruction, printer-bed fit, mesh validity and nominal assembly clearance are verified. Aerodynamic performance, impact strength, fatigue life and reliable spring-back are not verified. The localized stress hotspot remains an explicit limitation. Treat this as a prototype for a measured fit, retention, deflection and return test with propellers removed before considering motor operation.