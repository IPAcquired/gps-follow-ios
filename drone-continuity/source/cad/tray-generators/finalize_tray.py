from pathlib import Path
import sys, json, hashlib, zipfile, xml.etree.ElementTree as ET
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent/'check-deps'))
sys.path.insert(0,r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s\work\mesh-deps')
import trimesh
from shapely.geometry import Polygon, box, GeometryCollection, LineString
from shapely.ops import unary_union, polygonize
from scipy.spatial import cKDTree
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs'
SRC=Path(r'C:\Users\Daddy Nate\Desktop\Drone Parts\FlipFPV_AeroCradle_Wide_160x140_55clear.stl.stl')
source_hash=hashlib.sha256(SRC.read_bytes()).hexdigest()
original=trimesh.load(SRC,force='mesh'); delta=np.array([128,128,33.5])
original.apply_translation(-delta)
fixed=trimesh.load(ROOT/'work/repaired_local.stl',force='mesh')
counts=np.bincount(fixed.edges_unique_inverse)
assert fixed.is_watertight and fixed.is_winding_consistent and fixed.body_count==1
assert np.all(counts==2)
assert np.max(abs(original.bounds-fixed.bounds))<0.0001

def section(mesh,z):
    if mesh is original:
        # Do not trust section path traversal on the original non-manifold seams.
        # Polygonize raw triangle intersections and classify each region by the
        # oriented solid-angle winding number of the original triangle soup.
        lines=trimesh.intersections.mesh_plane(mesh,[0,0,1],[0,0,z])
        points=lines[:,:,:2].reshape(-1,2).copy();parent=np.arange(len(points))
        def root(i):
            while parent[i]!=i:
                parent[i]=parent[parent[i]];i=parent[i]
            return i
        for i,j in cKDTree(points).query_pairs(1e-6):parent[root(j)]=root(i)
        points=np.array([points[root(i)] for i in range(len(points))])
        regions=list(polygonize(unary_union([LineString(v) for v in points.reshape(-1,2,2)])))
        filled=[]
        for p in regions:
            q=p.representative_point();v=mesh.triangles-np.array([q.x,q.y,z])
            a,b,c=v[:,0],v[:,1],v[:,2]
            la,lb,lc=[np.linalg.norm(w,axis=1) for w in (a,b,c)]
            numerator=np.einsum('ij,ij->i',a,np.cross(b,c))
            denominator=la*lb*lc+np.einsum('ij,ij->i',a,b)*lc+np.einsum('ij,ij->i',b,c)*la+np.einsum('ij,ij->i',c,a)*lb
            winding=np.sum(2*np.arctan2(numerator,denominator))/(4*np.pi)
            if abs(winding)>.5:filled.append(p)
        return unary_union(filled)
    s=mesh.section(plane_origin=[0,0,z],plane_normal=[0,0,1])
    result=GeometryCollection()
    seen=[]
    if s:
        for contour in s.discrete:
            p=Polygon(contour[:,:2])
            if not p.is_valid:p=p.buffer(0)
            # The source's line-only contacts can produce duplicate closed paths.
            if any(p.equals(q) for q in seen):continue
            seen.append(p)
            result=result.symmetric_difference(p)
    return result

# Check every 0.25 mm, plus immediately above/below important transitions.
# All modifications must be outside the nominal interior, below or outside walls.
checks=[]
for z in sorted(set(np.arange(.125,67,.25).tolist()+[2.001,5.999,6.001,43.999,44.001,45.999,46.001,47.999,48.001,60.999,61.001,66.999])):
    a,b=section(original,z),section(fixed,z)
    interior=box(0.0001,0.0001,159.9999,139.9999)
    added_interior=b.difference(a).intersection(interior).area
    removed=a.difference(b).area
    # Input STL rounding accounts for less than 0.01 mm2 slice difference.
    assert added_interior<.015,(z,added_interior)
    assert removed<.015,(z,removed)
    if z>20.01:assert a.symmetric_difference(b).area<.025
    checks.append({'z_mm':z,'interior_added_mm2':added_interior,'removed_mm2':removed})

name='Wide_160x140_REPAIRED_SUPPORTS_REQUIRED'
placed=fixed.copy();placed.apply_translation(delta)
placed.export(OUT/(name+'.stl'))
scad=(ROOT/'work/repaired_local.scad').read_text(encoding='utf-8-sig')
(OUT/(name+'.scad')).write_text('// Millimeters. Original selected STL coordinates preserved.\n// Print supports are REQUIRED. Prefer the accompanying 3MF project.\ntranslate([128,128,33.5]) {\n'+scad+'\n}\n',encoding='utf-8')

fig=plt.figure(figsize=(12,7));ax=fig.add_subplot(111,projection='3d')
ax.add_collection3d(Poly3DCollection(fixed.triangles,facecolor='#8fb4c7',edgecolor='#426072',linewidth=.04))
# Highlight the actual downward-facing knee and pad faces, not imaginary generated supports.
mask=(fixed.face_normals[:,2]<-.1)&(fixed.triangles_center[:,2]>40)
ax.add_collection3d(Poly3DCollection(fixed.triangles[mask],facecolor='#ef8138',edgecolor='#b95222',linewidth=.15))
for x,y in [(25,15),(135,15),(25,125),(135,125)]:
    ax.plot([x,x],[y,y],[7,44],color='#ef8138',linestyle='--',linewidth=2)
ax.set(xlim=(-6,166),ylim=(-6,146),zlim=(0,69),xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)')
ax.set_box_aspect([172,152,69]);ax.view_init(elev=24,azim=-56)
ax.set_title('Repaired wide tray — orange marks regions requiring removable supports\nDashed lines are location guides, not sliced support geometry',fontsize=12)
fig.savefig(OUT/'Wide_Tray_Support_Locations.png',dpi=160,bbox_inches='tight');plt.close(fig)

# Reuse known printer and material presets, with explicit unconfirmed material status.
template=Path(r'C:\Users\Daddy Nate\Downloads\Drone_Landing_Leg_4p75in_CLEANED_27p90_Leg.3mf')
with zipfile.ZipFile(template) as z:
    config=json.loads(z.read('Metadata/project_settings.config'))
    types=z.read('[Content_Types].xml');rels=z.read('_rels/.rels')
assert config['printer_model']=='Elegoo Centauri Carbon' and config['nozzle_diameter']==['0.6']
changes={'print_settings_id':'Wide tray - supports from tray floor - CHECK MATERIAL',
 'layer_height':'0.20','initial_layer_print_height':'0.20',
 'wall_loops':'6','top_shell_layers':'6','bottom_shell_layers':'6',
 'top_shell_thickness':'1.2','bottom_shell_thickness':'1.2',
 'sparse_infill_density':'40%','sparse_infill_pattern':'gyroid',
 'enable_support':'1','support_type':'normal(auto)','support_style':'snug',
 'support_on_build_plate_only':'0','support_threshold_angle':'55',
 'support_remove_small_overhang':'0','support_critical_regions_only':'0',
 'support_interface_not_for_body':'0','support_top_z_distance':'0.2',
 'support_bottom_z_distance':'0.2','support_interface_top_layers':'3',
 'support_interface_bottom_layers':'3','support_interface_spacing':'0.2',
 'support_bottom_interface_spacing':'0.2','support_object_xy_distance':'0.35',
 'support_speed':'60','support_interface_speed':'35',
 'outer_wall_speed':'50','inner_wall_speed':'70','sparse_infill_speed':'80',
 'internal_solid_infill_speed':'60','top_surface_speed':'45',
 'initial_layer_speed':'25','initial_layer_infill_speed':'30',
 'brim_type':'outer_only','brim_width':'6','print_sequence':'by layer','enable_prime_tower':'0'}
config.update(changes)
core='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
prod='http://schemas.microsoft.com/3dmanufacturing/production/2015/06'
relationship='http://schemas.openxmlformats.org/package/2006/relationships'
ET.register_namespace('',core);ET.register_namespace('p',prod)
def c(s):return '{'+core+'}'+s
def xml(e):return ET.tostring(e,encoding='utf-8',xml_declaration=True)
model=ET.Element(c('model'),unit='millimeter',requiredextensions='p')
for k,v in [('Application','ElegooSlicer-1.5.3.5'),('BambuStudio:3mfVersion','1'),('Title',name),('Description','Dimensions preserved. Auto supports allowed on tray floor. Printer/material inherited: confirm before slicing. Unsliced.')]:
    ET.SubElement(model,c('metadata'),name=k).text=v
resources=ET.SubElement(model,c('resources'));obj=ET.SubElement(resources,c('object'),id='2',type='model')
components=ET.SubElement(obj,c('components'));geompath='3D/Objects/Wide_Tray.model'
ET.SubElement(components,c('component'),{'objectid':'1','{'+prod+'}path':'/'+geompath,'transform':'1 0 0 0 1 0 0 0 1 0 0 0'})
transform='1 0 0 0 1 0 0 0 1 48 58 0'
build=ET.SubElement(model,c('build'));ET.SubElement(build,c('item'),objectid='2',transform=transform,printable='1')
geom=ET.Element(c('model'),unit='millimeter');res=ET.SubElement(geom,c('resources'));ob=ET.SubElement(res,c('object'),id='1',type='model')
me=ET.SubElement(ob,c('mesh'));vs=ET.SubElement(me,c('vertices'));fs=ET.SubElement(me,c('triangles'))
for v in fixed.vertices:ET.SubElement(vs,c('vertex'),{axis:format(float(q),'.10g') for axis,q in zip('xyz',v)})
for face in fixed.faces:ET.SubElement(fs,c('triangle'),{f'v{i+1}':str(int(q)) for i,q in enumerate(face)})
ET.SubElement(geom,c('build'))
ms=ET.Element('config');o=ET.SubElement(ms,'object',id='2')
ET.SubElement(o,'metadata',key='name',value=name);ET.SubElement(o,'metadata',key='extruder',value='1')
part=ET.SubElement(o,'part',id='1',subtype='normal_part')
ET.SubElement(part,'metadata',key='name',value=name);ET.SubElement(part,'metadata',key='matrix',value='1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1')
ET.SubElement(part,'mesh_stat',edges_fixed='0',degenerate_facets='0',facets_removed='0',facets_reversed='0',backwards_edges='0')
plate=ET.SubElement(ms,'plate');ET.SubElement(plate,'metadata',key='plater_id',value='1');ET.SubElement(plate,'metadata',key='plater_name',value='Wide tray - support check required')
inst=ET.SubElement(plate,'model_instance');ET.SubElement(inst,'metadata',key='object_id',value='2');ET.SubElement(inst,'metadata',key='instance_id',value='0');ET.SubElement(inst,'metadata',key='identify_id',value='1')
assembly=ET.SubElement(ms,'assemble');ET.SubElement(assembly,'assemble_item',object_id='2',instance_id='0',transform=transform,offset='0 0 0')
rr=ET.Element('Relationships',xmlns=relationship);ET.SubElement(rr,'Relationship',Target='/'+geompath,Id='rel-1',Type='http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel')
project=OUT/'Wide_Tray_SUPPORT_SETUP_CC_0p6_PLA_UNSLICED.3mf'
with zipfile.ZipFile(project,'w',zipfile.ZIP_DEFLATED) as z:
    for p,data in [('[Content_Types].xml',types),('_rels/.rels',rels),('3D/3dmodel.model',xml(model)),(geompath,xml(geom)),('3D/_rels/3dmodel.model.rels',xml(rr)),('Metadata/model_settings.config',xml(ms)),('Metadata/project_settings.config',json.dumps(config,indent=2))]:z.writestr(p,data)
    z.writestr('Metadata/plate_1.png',(OUT/'Wide_Tray_Support_Locations.png').read_bytes())
    z.writestr('Metadata/plate_1_small.png',(OUT/'Wide_Tray_Support_Locations.png').read_bytes())
with zipfile.ZipFile(project) as z:
    assert z.testzip() is None
    reread=json.loads(z.read('Metadata/project_settings.config'))
    assert all(reread[k]==v for k,v in changes.items())
    assert not any(n.endswith('.gcode') for n in z.namelist())
    gm=ET.fromstring(z.read(geompath))
    rv=np.array([[float(e.get(a)) for a in 'xyz'] for e in gm.findall('.//'+c('vertex'))])
    assert np.max(abs(rv-fixed.vertices))<1e-6
    assert np.all(rv.min(axis=0)+[48,58,0]>=[0,0,0]) and np.all(rv.max(axis=0)+[48,58,0]<=[256,256,256])
assert hashlib.sha256(SRC.read_bytes()).hexdigest()==source_hash
report={'source':str(SRC),'source_sha256':source_hash,'source_unchanged':True,
 'original_bounds_mm':(original.bounds+delta).tolist(),'repaired_bounds_mm':placed.bounds.tolist(),
 'nominal_tray_mm':[160,140],'overall_mm':fixed.extents.tolist(),'mount_spacing_mm':[110,110],
 'pad_centers_selected_coordinates_mm':[[153,143],[263,143],[153,253],[263,253]],
 'pad_underside_z_mm':94.5,'pad_top_z_mm':100.5,'floor_z_mm':39.5,'floor_to_pad_underside_mm':55,
 'watertight':True,'connected_components':1,'nonmanifold_edges':0,
 'section_checks':len(checks),'max_added_interior_section_area_mm2':max(r['interior_added_mm2'] for r in checks),
 'max_removed_section_area_mm2':max(r['removed_mm2'] for r in checks),
 'added_volume_mm3':fixed.volume-original.volume,
 'changes':'Exterior wall-floor laps and exterior wall corner seams only; all four mounting supports and pads retain their existing shape. Missing print support is handled in the 3MF settings, not by filling the battery bay.',
 'print_settings':changes,'printer_material_assumption':'Existing Centauri Carbon 0.6 mm / Elegoo PLA preset; user has not confirmed material.',
 'sliced_support_coverage_verified':False,'physical_strength_tested':False}
(OUT/'Wide_Tray_Verification.json').write_text(json.dumps(report,indent=2))
(OUT/'Wide_Tray_Read_Me.md').write_text('''# Wide tray repair and support setup

The selected double-extension STL was used as the dimensional reference. The source file is unchanged.

## What is fixed

Finite exterior laps now join the walls to the floor, and small exterior corner seams connect adjacent walls. The finished mesh is one connected, watertight body with zero non-manifold edges. These changes strengthen those connections geometrically; there is no measured load rating.

The four inward mounting transitions still require removable print supports. They shift roughly 21.5 mm over only 2 mm of height. Permanent pillars below them would occupy the existing battery space. To preserve that space, the accompanying 3MF enables normal automatic supports **on the tray floor as well as the build plate**, disables ignoring small overhangs, and enables top/bottom support interfaces. Merely importing the STL does NOT carry those settings.

## Preserved dimensions

- Nominal tray: 160 × 140 mm; overall: 168 × 148 × 67 mm.
- Floor thickness: 6 mm; original underside pockets and six strap slots retained.
- Mount pattern: 110 × 110 mm; pads: 16 × 20 × 6 mm.
- Floor to mounting-pad underside: 55 mm.
- Original STL coordinates retained in the repaired STL and SCAD. The 3MF only translates the part onto the bed, without scaling or rotation.
- Original internal support obstructions and clearances retained. The tray never had an unobstructed 160 × 140 × 55 mm cavity.

## Before printing

The project inherits an existing **Centauri Carbon / 0.6 mm nozzle / Elegoo PLA** preset. Confirm these match the actual printer and filament; this material has not been confirmed for this tray. It uses 0.20 mm layers, six walls, six top/bottom layers, and 40% gyroid infill.

**This project is unsliced. Support coverage is NOT verified.** The desktop slicer capture failed, so no G-code was generated and no print was started. In the layer preview, check support/interface beneath all four inward knees around part height 44–46 mm and all four pad undersides at 61 mm, including the front pair. Supports must start on the tray floor where needed. The orange preview image marks support locations; it is not a slicer preview.

Remove the temporary supports after printing. Printed dimensions, layer bonding, and strength under actual load still require physical verification; a watertight mesh is not proof of strength.

[OrcaSlicer support settings](https://github.com/OrcaSlicer/OrcaSlicer/wiki/support_settings_support) describes the build-plate-only restriction; it is disabled in this project.
''',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ['print_settings']},indent=2))
