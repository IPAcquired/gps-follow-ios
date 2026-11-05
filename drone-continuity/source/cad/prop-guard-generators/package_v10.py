import sys,json,zipfile,shutil
from pathlib import Path
import numpy as np
ROOT=Path(r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s')
sys.path.insert(0,str(ROOT/'work'/'mesh-deps'))
import trimesh
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.patches import Rectangle,Polygon
HERE=Path(__file__).resolve().parent
out=HERE/'outputs'/'prop-guard-v10-light-flex-petg'
r=json.loads((out/'geometry_and_structure_audit.json').read_text())
fea=json.loads((out/'linear_fea_3mm.json').read_text())
fig,axes=plt.subplots(2,4,figsize=(16,8))
for ax,p in zip(axes.flat,sorted((out/'print_ready_parts').glob('*.stl'))):
 t=trimesh.load(p,force='mesh');ext=t.extents;t.apply_translation(((256-ext[0])/2,(256-ext[1])/2,0))
 assert ext[0]+10<256 and ext[1]+10<256
 col='#ec8b43' if p.stem.startswith('TPU') else '#467b97'
 ax.add_patch(Rectangle((0,0),256,256,facecolor='#f6f7f8',edgecolor='#64717b'))
 ax.add_collection(PolyCollection(t.triangles[:,:,:2],facecolor=col,edgecolor=col,linewidth=.1))
 ax.add_patch(Rectangle((t.bounds[0][0]-5,t.bounds[0][1]-5),ext[0]+10,ext[1]+10,fill=False,edgecolor='#c16c42',linestyle='--'))
 ax.set_xlim(-5,261);ax.set_ylim(-5,261);ax.set_aspect('equal');ax.set_title(p.stem.replace('_',' '),fontsize=9)
 ax.set_xlabel(f'{ext[0]:.1f} × {ext[1]:.1f} mm; individual footprint',fontsize=9)
fig.suptitle('V10: each part fits the 256 × 256 mm tray with 5 mm brim allowance',fontsize=15)
fig.tight_layout();fig.savefig(out/'V10_tray_fit.png',dpi=150);plt.close(fig)
fig,axes=plt.subplots(1,3,figsize=(12,6))
axes[0].add_patch(Rectangle((-6,-9),12,18,facecolor='#a7b2ba'));axes[0].set_title('V9 solid spoke\n12 × 18 mm ideal section')
axes[1].add_patch(Rectangle((-1.2,-11),2.4,22,facecolor='#467b97'))
for z in [-11,9.5]:axes[1].add_patch(Rectangle((-3,z),6,1.5,facecolor='#467b97'))
axes[1].set_title('V10 I-section spoke\n6 × 22 mm; 2.4 mm web')
for z in [-4,2.2]:axes[2].add_patch(Rectangle((-6.2,z),12.4,1.8,facecolor='#467b97'))
axes[2].add_patch(Rectangle((4.2,-4),2,8,facecolor='#467b97'));axes[2].set_title('V10 open-channel rim\nSolid bosses remain at screws')
for ax in axes:ax.set_xlim(-9,9);ax.set_ylim(-14,14);ax.set_aspect('equal');ax.grid(alpha=.2);ax.set_xlabel('Plan width (mm)')
axes[0].set_ylabel('Vertical height (mm)');fig.suptitle('Less material; deep vertical sections; accessible open channels',fontsize=15)
fig.tight_layout();fig.savefig(out/'V10_lightweight_sections.png',dpi=160);plt.close(fig)
total=sum(r['estimated_solid_mass_g'].values());reduction=r['mass_reduction_from_v9_percent'];area=r['downwash_projection_screen']['area_reduction_percent']
lines=['# V10 lightweight PETG semicircle with screw-on TPU',
 '\nGeometry-checked prototype. The design is lighter and uses more ductile rigid material, but spring-back, impact strength and aerodynamic performance are not validated.',
 '\n## What changed',
 '- Original open semicircle retained; 38.80 mm round mounting plate retained; aircraft holes are still for the user to drill.',
 '- PETG replaces PLA, as requested. Four rounded-planform, tapered I-section spokes replace the broad solid beams. Nominal central section: 6 mm width, 22 mm height, 2.4 mm web and 1.5 mm top/bottom flanges. Roots and tips are wider; local rounded gussets spread loads at mounting feet.',
 '- Rim is an open C-channel with 1.8 mm upper/lower flanges and 2 mm outer web. Screw recesses retain solid bearing bosses rather than being drilled through hollow sections.',
 '- Four screw-on TPU strips retain two screws each. The continuous heavy underside flange has been replaced by local washer-supported lugs. Outer TPU band is 2.4 mm thick; nominal radial gap to the PETG is 0.35 mm.',
 '- Mount remains 6 mm thick; mounting feet remain 10 mm thick. The two rigid halves attach with four screws, and a curved splice joins the outer seam.',
 '\n## Measured comparison with V9',
 f'- Solid-geometry material estimate: **{total:.1f} g per guard**, comprising {r["estimated_solid_mass_g"]["PETG"]:.1f} g PETG and {r["estimated_solid_mass_g"]["TPU"]:.1f} g TPU. This is **{reduction:.1f}% lighter** than the roughly 384 g V9 estimate. Hardware, supports and actual infill are excluded. Reference PETG density is 1.27 g/cm³; TPU uses an assumed 1.20 g/cm³.',
 f'- Projected core area inside the nominal propeller disk decreases **{area:.1f}%**, from {r["downwash_projection_screen"]["v9_inside_prop_disk_mm2"]:.0f} to {r["downwash_projection_screen"]["v10_inside_prop_disk_mm2"]:.0f} mm². This is an obstruction comparison, not CFD, a drag coefficient or a measured thrust improvement. Existing-arm shadow was not subtracted.',
 '- The ideal straight beam section is about 43 times stiffer in vertical bending than lateral bending. This explains the section choice; the routed, ring-connected assembly does not have that same stiffness ratio.',
 '\n## Geometry and printer checks',
 '- Eight exported, reloaded, watertight, consistently wound, single-body STL files.',
 '- No inter-part, modeled-arm, motor-keepout or specified-hardware collisions above 0.001 cubic mm. Contact surfaces at mounting feet, screw lugs and splice are intentional.',
 '- Largest individual part approximately 228.8 × 164.8 × 38.0 mm. A centered footprint with a 5 mm brim fits within the previously supplied 256 × 256 mm tray.',
 '- Rim/TPU top remains 19 mm above arm top, 8 mm below the previously supplied 27 mm blade underside. Nominal rigid-rim radial blade clearance remains approximately 12.9 mm.',
 '- Modeled arm is 27.5 mm wide and 3 mm thick. Motor keepout is a 50 mm diameter cylinder from 3 mm below arm top to 27 mm above it. Real aircraft dimensions and neighboring guards still require a physical fit check.',
 '\n## How it flexes and returns',
 'The PETG core is intended to allow small elastic movements while resisting vertical bending. The slimmer TPU outer strips provide the softer contact surface and can deform locally. PETG is less brittle and more flexible than PLA according to the manufacturer material guide; that does not make this guard a proven spring. No printed rebound, permanent-set, damping or fatigue test has been performed. Avoid repeated large flexing, and do not assume it survives propeller strikes.',
 'Material guide: https://prusament.com/materials/prusament-petg/\nTechnical reference: https://storage.googleapis.com/prusa3d-content-prod-14e8-wordpress-prusament-prod/2023/10/9f8d2165-tds_prusament-petg_n_en.pdf',
 '\n## Structural screening',
 'A tetrahedral linear-static screen was run on the front rigid half, with its two mounting washer areas ideally fixed. The rear half, splice coupling, TPU and actual aircraft attachment were excluded. Material was assumed homogeneous, isotropic, fully dense PETG with E=1.5 GPa and Poisson ratio 0.35. The final mesh has 5,252 nodes and 19,737 tetrahedra, no rejected elements, and volume matching the STL within numerical precision. Mesh convergence has not been established.',
 '\n| Static force applied over outer crown patch | Mean crown movement | Maximum movement | Interior stress, volume-weighted 99th percentile | Peak stress, mesh dependent |\n| --- | ---: | ---: | ---: | ---: |']
for c in fea['cases']:
 lines.append(f'| {c["case"]} | {c["loaded_mean_displacement_mm"]:.3f} mm | {c["maximum_displacement_mm"]:.3f} mm | {c["interior_volume_weighted_von_mises_p99_MPa"]:.2f} MPa | {c["maximum_von_mises_MPa_mesh_dependent"]:.1f} MPa |')
lines.extend([
 '\nThe screened small loads did not move the modeled rigid rim into the nominal blade radius, and the estimated underside gap over the blade disk remained about 10 mm. These deformed-geometry checks use a linear displacement field and exclude actual blade deflection, joint slip, print anisotropy and aircraft movement.',
 '**The upward-load case still has a localized stress peak of about 42 MPa near a routed-spoke transition. It is not a verified safety margin.** Peak stress is sensitive to tetrahedral quality, local corners and restraints, and needs mesh refinement/physical testing. The reference material datasheet reports printed tensile yield around 47 MPa and interlayer adhesion around 18 MPa under its own test conditions. Those values cannot be used to declare this printed part safe, especially with different layer orientation. A linear model also assumes elastic return, so it cannot prove actual rebound.',
 'The idealized beam estimate in the geometry report is a separate sensitivity calculation: a constant straight I-section at a 230 mm span. It predicts larger deflections than this routed/ring-supported FEA model. Neither is a rated load capacity. Aircraft fastening, buckling, impact, fatigue, creep and thermal effects remain unresolved.',
 '\n## Printing',
 'Use `print_ready_parts/` for the eight individual STLs, in millimetres. The core halves are oriented rim-top-down for bed contact. Supports are required below the raised mounting feet and selected spoke/channel areas; open I and C channels allow access for support removal. Confirm support access and hole openings in the slicer. This package does not contain verified G-code or a printer-specific sliced project.',
 'Print PETG structural parts separately from TPU. Use filament-vendor/printer profiles. A 0.6 mm nozzle is compatible with the nominal 2.4 mm web and 1.8 mm rim flanges, but inspect the generated wall paths. Structural thin sections, screw bosses, mounting feet and splice need continuous solid walls; sparse infill does not reproduce the fully dense simulation. A 0.20–0.24 mm layer height and sufficient perimeter coverage are a starting point, not a validated print recipe.',
 '\n## Hardware and assembly',
 '| Use | Quantity | Hardware |\n| --- | ---: | --- |\n| Halves to round mount | 4 | M3 × 18 mm button-head screw |\n| TPU lugs to rim | 8 | M3 × 14 mm button-head screw |\n| Rim splice | 2 | M3 × 16 mm button-head screw |\n| Washers | 14 | M3, OD 7 mm, ID 3.4 mm, thickness 0.6 mm |\n| Nuts | 14 | M3, height 2.4 mm, maximum circumscribed diameter 6.4 mm |',
 'Heads must be at most 6.0 mm diameter × 2.0 mm high; recesses are 6.4 mm diameter × 2.2 mm deep. Holes are 3.4 mm. Different hardware needs a new clearance check. Aircraft bolts are additional and depend on your drilled pattern.',
 'Fit the core halves beneath the round pad and install the four recessed mount screws before fastening to the arm. Bolt the small curved splice beneath the outer seam. Fit each TPU strip to its matching rim holes, inserting two screws through the PETG bosses and TPU lugs; washers and nuts sit below the TPU. Through-bolts avoid relying on cut threads in either plastic. Tightening torque and printed lug pull-through strength have not been established; avoid crushing the TPU.',
 'Mark aircraft holes on the actual arm while avoiding the assembly recesses and preserving material around holes. Check the attachment cannot rotate, slip or tilt into the blades. The actual drilled pattern has not been modeled.',
 '\n## Delivery status',
 'Lighter geometry, reduced projected obstruction, printer-bed fit, mesh validity and nominal assembly clearance are verified. Aerodynamic performance, impact strength, fatigue life and reliable spring-back are not verified. The localized stress hotspot remains an explicit limitation. Treat this as a prototype for a measured fit, retention, deflection and return test with propellers removed before considering motor operation.'])
(out/'ASSEMBLY_PRINTING_AND_STRUCTURE.md').write_text('\n'.join(lines),encoding='utf-8')
for source in ['build_v10.py','analyze_v10.py']:shutil.copyfile(HERE/source,out/source)
# Include only current validated artifacts; older exploratory mesh reports are not delivered.
allowed={'ASSEMBLY_PRINTING_AND_STRUCTURE.md','geometry_and_structure_audit.json','linear_fea_3mm.json','linear_fea_3mm_fields.npz','V10_assembly_preview.png','V10_tray_fit.png','V10_lightweight_sections.png','build_v10.py','analyze_v10.py'}
dest=out.parent/'Prop_Guard_V10_Light_Flex_PETG_TPU.zip'
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted(out.rglob('*')):
  if p.is_file() and (p.name in allowed or p.parent.name in ['print_ready_parts','assembled_coordinates']):z.write(p,p.relative_to(out))
print(json.dumps({'zip':str(dest),'mass_g':total,'reduction_percent':reduction,'projected_area_reduction_percent':area},indent=2))
