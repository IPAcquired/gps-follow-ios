from pathlib import Path
import sys,json,zipfile,xml.etree.ElementTree as ET,hashlib
import numpy as np
sys.path.insert(0,r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s\work\mesh-deps')
sys.path.insert(0,str(Path(__file__).resolve().parent/'check-deps'))
import trimesh,manifold3d as md
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs'
base=trimesh.load(ROOT/'work/repaired_local.stl',force='mesh')
M=md.Manifold
def solid(tm):return M(md.Mesh(np.asarray(tm.vertices,dtype=np.float32),np.asarray(tm.faces,dtype=np.uint32)))
def mesh(s):
 r=s.to_mesh();return trimesh.Trimesh(np.asarray(r.vert_properties[:,:3]),np.asarray(r.tri_verts),process=True)
original=solid(base);assert original.status()==md.Error.NoError
profile=[(1,45.8),(20,47.8),(29.5,47.8),(29.5,60.9),(20,60.9),(1,54)]
gussets=[]
for yy in [15,125]:
 left=md.CrossSection([profile]).extrude(15).rotate((90,0,0)).translate((0,yy+7.5,0))
 gussets += [left,left.mirror((1,0,0)).translate((160,0,0))]
reinforced=M.batch_boolean([original,*gussets],md.OpType.Add)
added=reinforced-original
fixed=mesh(reinforced);assert fixed.is_watertight and fixed.is_winding_consistent and fixed.body_count==1
assert np.max(abs(fixed.bounds-base.bounds))<.0001
def box(x,y,z,dx,dy,dz):return M.cube((dx,dy,dz)).translate((x,y,z))
assert (original-reinforced).volume()<.001
# Exact pad volume and all geometry up to the existing transition start protected.
padslab=box(-10,-10,61,180,160,10)
assert ((reinforced^padslab)-(original^padslab)).volume()<.001
assert (added^box(-10,-10,0,180,160,44)).volume()<.001
# Central space between support rows is untouched at every height.
assert (added^box(-10,24,0,180,92,67)).volume()<.001
# Inner faces of the upper support bands remain x=30 and x=130.
assert (added^box(30,0,0,100,140,61)).volume()<.001
name='Wide_Tray_PERMANENT_GUSSETS'
placed=fixed.copy();placed.apply_translation([128,128,33.5]);placed.export(OUT/(name+'.stl'))
code=(ROOT/'work/repaired_local.scad').read_text(encoding='utf-8-sig')
gusset_scad='''
// Permanent upper gussets. Existing underside and z<44 mm clearance retained.
module upper_gusset(y){
 translate([0,y+7.5,0]) rotate([90,0,0]) linear_extrude(height=15)
 polygon(points=[[1,45.8],[20,47.8],[29.5,47.8],[29.5,60.9],[20,60.9],[1,54]]);
}
for(y=[15,125]) {
 upper_gusset(y);
 translate([160,0,0]) mirror([1,0,0]) upper_gusset(y);
}
'''
(OUT/(name+'.scad')).write_text('// mm; original selected STL coordinates. Print supports still required.\ntranslate([128,128,33.5]) {\n'+code+gusset_scad+'\n}\n')

# Preserve active printer/material/process and replace only geometry in project.
src=OUT/'Wide_Tray_SUPPORTS_FIXED.3mf';dest=OUT/(name+'.3mf')
core='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
def c(s):return '{'+core+'}'+s
local=fixed.copy();local.apply_translation([-80,-70,-33.5])
with zipfile.ZipFile(src) as old,zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
 paths=[n for n in old.namelist() if n.startswith('3D/Objects/') and n.endswith('.model')];assert len(paths)==1
 for item in old.infolist():
  data=old.read(item.filename)
  if item.filename==paths[0]:
   root=ET.fromstring(data);obj=root.find('.//'+c('object'));oldmesh=obj.find(c('mesh'));obj.remove(oldmesh)
   me=ET.SubElement(obj,c('mesh'));vs=ET.SubElement(me,c('vertices'));ts=ET.SubElement(me,c('triangles'))
   for v in local.vertices:ET.SubElement(vs,c('vertex'),{a:format(float(q),'.10g') for a,q in zip('xyz',v)})
   for f in local.faces:ET.SubElement(ts,c('triangle'),{f'v{i+1}':str(int(q)) for i,q in enumerate(f)})
   data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
  elif item.filename=='Metadata/model_settings.config':
   root=ET.fromstring(data)
   for e in root.iter('metadata'):
    if e.get('key') in ('name','source_file'):e.set('value',name+'.stl')
   data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
  elif item.filename=='Metadata/project_settings.config':
   cfg=json.loads(data);cfg['print_settings_id']='Wide tray reinforced - supports on tray floor'
   data=json.dumps(cfg,indent=2).encode()
  z.writestr(item,data)
scene=trimesh.load(dest);check=scene.to_geometry()
assert np.max(abs(check.extents-[168,148,67]))<.0001 and check.is_watertight
assert np.max(abs(check.bounds-np.array([[44,54,0],[212,202,67]])))<.0001

added_mesh=mesh(added)
fig=plt.figure(figsize=(12,7));ax=fig.add_subplot(111,projection='3d')
ax.add_collection3d(Poly3DCollection(base.triangles,facecolor='#c4d4de',edgecolor='#6d8796',linewidth=.025,alpha=.5))
ax.add_collection3d(Poly3DCollection(added_mesh.triangles,facecolor='#e9752a',edgecolor='#88421b',linewidth=.15))
ax.set(xlim=(-5,165),ylim=(-5,145),zlim=(0,68),xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)');ax.set_box_aspect([170,150,68]);ax.view_init(23,-56)
ax.set_title('Permanent gussets in orange — added ABOVE all four thin mounting bends')
fig.tight_layout();fig.savefig(OUT/'Wide_Tray_PERMANENT_GUSSETS_preview.png',dpi=160);plt.close(fig)
report={'watertight':True,'connected_bodies':1,'overall_mm':fixed.extents.tolist(),'mount_pattern_mm':[110,110],
 'pads_exactly_preserved':True,'geometry_below_z44_unchanged':True,'central_y24_to116_space_unchanged':True,
 'upper_inner_x30_to130_clearance_unchanged':True,'added_volume_mm3':added.volume(),
 'added_material_region_bounds_local_mm':added_mesh.bounds.tolist(),
 'change_in_clearance':'Previously empty upper outboard corner space above the bends is occupied by gussets. No claim that every local void remains unchanged.',
 'strength_status':'Permanent reinforcement added; section screening and slicing pending; not physically load-tested.'}
(OUT/'Wide_Tray_PERMANENT_GUSSETS_checks.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
