from pathlib import Path
import sys,json,hashlib,zipfile,shutil
import numpy as np
sys.path.insert(0,r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s\work\mesh-deps')
import trimesh,manifold3d as md
out=Path('outputs');name='Four_Across_REINFORCED';data=np.load('work/four-toolpath-segments.npz');a=data['A'];k=data['K'];mid=(a[:,:2]+a[:,2:4])/2;length=np.linalg.norm(a[:,:2]-a[:,2:4],axis=1)
report=json.loads((out/(name+'_Toolpath_Checks.json')).read_text())
for row,(x0,x1,y) in zip(report['mount_checks'],[(21,80,73),(176,235,73),(21,80,183),(176,235,183)]):
 support=(mid[:,0]>=x0)&(mid[:,0]<=x1)&(mid[:,1]>=y-8)&(mid[:,1]<=y+8)&np.isin(k,['Support','Support interface'])
 bands=[float(length[support&(a[:,4]>=z)&(a[:,4]<z+1)].sum()) for z in range(11,56)]
 assert min(bands)>10
 row['minimum_support_length_per_1mm_height_band_z11_56']=min(bands)
 assert not row['interface_grid_missing_points']
(out/(name+'_Toolpath_Checks.json')).write_text(json.dumps(report,indent=2))
# Verify output G-code matches the toolpaths audited, then deliver package.
p=Path('work/four-native-slice/Four_Across_REINFORCED_CC_0p6_PLA.gcode.3mf')
with zipfile.ZipFile(p) as z:
 names=[n for n in z.namelist() if n.endswith('.gcode')];assert len(names)==1
 assert hashlib.sha256(z.read(names[0])).hexdigest()==report['gcode_sha256']
shutil.copy2(p,out/p.name)
# Check source bed/slot region is unchanged except the outboard fillets.
def man(path):
 t=trimesh.load(path,process=True);return md.Manifold(md.Mesh(np.asarray(t.vertices,dtype=np.float32),np.asarray(t.faces,dtype=np.uint32)))
base=man(r'C:\Users\Daddy Nate\Desktop\A_Four_Across_REFINED.stl');new=man(out/(name+'.stl'))
roi=md.Manifold.cube((203.8,152,10)).translate((-21.9,-6,-10))
difference=((new^roi)-(base^roi)).volume()+((base^roi)-(new^roi)).volume();assert difference<.001
checks=json.loads((out/(name+'_Checks.json')).read_text());checks['deck_and_slots_symmetric_difference_mm3']=difference
checks['bridge_root_thickness_mm']={'before':10,'after':14.5};checks['tower_bridge_vertical_overlap_mm']={'before':3.5,'after':9.9}
# Screening only: four equal vertical loads, cantilever root 53 mm from pad center.
f=6*4.4482216153/4;moment=f*53;sold=20*10**2/6;snew=20*14.5**2/6
checks['ideal_solid_bridge_root_screen']={'load_total_lb':6,'assumption':'Equal load on four pads; rectangular 20mm-wide cantilever section, 53mm lever. No notch, layer-bond, fatigue, deck bending or attachment analysis. Not a load rating.','old_static_stress_MPa':moment/sold,'new_static_stress_MPa':moment/snew,'new_illustrative_3g_stress_MPa':3*moment/snew,'root_section_modulus_ratio':snew/sold}
(out/(name+'_Checks.json')).write_text(json.dumps(checks,indent=2))
(out/(name+'_README.md')).write_text('''# Four batteries side by side — reinforced version

Source: Desktop/A_Four_Across_REFINED.stl. The original is unchanged.

Use **Four_Across_REINFORCED_CC_0p6_PLA.gcode.3mf** for the verified slice. Printer: Elegoo Centauri Carbon, 0.6 mm nozzle, ordinary Elegoo PLA; 0.20 mm object layers, 0.24 mm first layer, six walls, six top/bottom layers, 50% gyroid in the tray, and four 100% rectilinear mount modifiers. Estimated **16 h 36 m 44 s / 591.85 g including supports**. No print was started.

**Four_Across_REINFORCED.3mf** is the editable project. **Four_Across_REINFORCED.stl** contains only geometry; importing it alone does not carry the solid-mount modifiers or support settings.

## Permanent fixes

All four front/rear mounting bridges have tapered underside gussets. Bridge root depth grows from 10 to 14.5 mm; the tower-to-bridge vertical connection grows from 3.5 to 9.9 mm. Continuous gussets also reinforce both outboard tower-to-deck roots. The original mesh was already one watertight body; the reinforced exported STL remains one watertight body, with no original material removed.

## Measurements retained

- Overall 228 × 152 × 77 mm; nominal deck 204 × 152 mm.
- Four original pad outlines and mounting faces, 110 × 110 mm center spacing, source pad elevations Z61–67.
- Four modeled battery envelopes of 47 × 142 × 46 mm, with 2 mm gaps. These are the existing design assumptions, not newly measured battery dimensions.
- Deck top, strap slots, and 50.8 × 50.8 mm sensor opening unchanged.

The added material uses previously empty space above the battery envelopes and at the outboard tower roots. The minimum modeled clearance from 46 mm-high packs to the new bridge gussets is approximately 0.5 mm near the outer packs; pack dimensional tolerance and fit still need checking. No claim that every internal void is unchanged.

## Actual print-support checks

Sliced with native ElegooSlicer 1.5.3.5. Supports are allowed on the tray, with three top/bottom interface layers and 0.20 mm support contact gaps. Toolpath inspection confirms support continuity beneath all four bridges from above the tray through the bridge undersides, dense interface paths across all four bridge footprints, and interfaces beneath the raised floor. The full extrusion footprint stays inside the 256 × 256 mm bed. The upper mounting regions contain solid infill and no sparse-infill paths. The accompanying support image shows actual extruded support paths.

## Strength limit

The bridge-root section modulus is about 2.10 times the original rectangular section. A simple equal-share solid-beam calculation at 6 lb gives approximately 0.50 MPa nominal root bending stress, or 1.51 MPa for an illustrative 3g load. These are screening calculations, not FEA or a certified strength rating: they omit layer bonding, stress concentrations, unequal loads, deck bending, fasteners, fatigue and landing shocks. The completed PLA print has not been physically load-tested. Verify fit and test the intended load on the ground before flight.
''',encoding='utf-8')
print('Delivered verified slice; geometry and full bridge-support continuity checks passed.')
