from pathlib import Path
import sys,json,hashlib,zipfile,xml.etree.ElementTree as E
import numpy as np
sys.path.insert(0,r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s\work\mesh-deps')
import trimesh,manifold3d as md
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
OUT=Path('outputs'); NAME='Four_Across_REINFORCED'; SRC=Path(r'C:\Users\Daddy Nate\Desktop\A_Four_Across_REFINED.stl')
M=md.Manifold
old=trimesh.load(SRC,force='mesh',process=True)
base=M(md.Mesh(np.asarray(old.vertices,dtype=np.float32),np.asarray(old.faces,dtype=np.uint32)))
assert base.status()==md.Error.NoError

def box(x,y,z,dx,dy,dz): return M.cube((dx,dy,dz)).translate((x,y,z))
def prism(points,y,depth):
 return md.CrossSection([np.array(points)]).extrude(depth).rotate((90,0,0)).translate((0,y+depth,0))
adds=[]
for y in [15,125]:
 # Full-depth tower-to-bridge overlap and tapered lower bridge gusset.
 left=prism([(-33,46.5),(-28,46.5),(25,50.9),(25,51.2),(-28,60.9),(-33,60.9)],y-10,20)
 adds.extend([left,left.mirror((1,0,0)).translate((160,0,0))])
# Long external deck-to-tower root fillets, outside battery and guide envelopes.
leftroot=prism([(-28.1,-1),(-21.9,-1),(-21.9,0.2),(-28.1,10)],-6,152)
adds.extend([leftroot,leftroot.mirror((1,0,0)).translate((160,0,0))])
solid=base+M.batch_boolean(adds,md.OpType.Add)
def mesh(s):
 raw=s.to_mesh();return trimesh.Trimesh(np.asarray(raw.vert_properties[:,:3]),np.asarray(raw.tri_verts),process=True)
new=mesh(solid); new.export(OUT/(NAME+'.stl')); new=trimesh.load(OUT/(NAME+'.stl'),process=True)
slab=box(-40,-10,61,240,170,6)
pack_collisions=[(solid^box(x,-1,0,47,142,46)).volume() for x in [-17,32,81,130]]
removed=(base-solid).volume(); pad_delta=((solid^slab)-(base^slab)).volume()+((base^slab)-(solid^slab)).volume()
assert new.is_watertight and new.is_winding_consistent and new.body_count==1
assert np.allclose(new.bounds,old.bounds,atol=1e-5)
assert max(pack_collisions)<1e-4 and removed<1e-4 and pad_delta<1e-4
assert (solid^box(54.6,44.6,-10,50.8,50.8,10)).volume()<1e-4
report={'source':str(SRC),'source_sha256':hashlib.sha256(SRC.read_bytes()).hexdigest(),'bounds_mm':new.bounds.tolist(),'overall_mm':new.extents.tolist(),'watertight':bool(new.is_watertight),'bodies':new.body_count,'source_material_removed_mm3':removed,'mount_pad_symmetric_difference_mm3':pad_delta,'pack_envelopes_mm':[47,142,46],'pack_intersections_mm3':pack_collisions,'mount_pattern_mm':[110,110],'sensor_aperture_mm':[50.8,50.8],'added_volume_mm3':(solid-base).volume(),'preserved':'Source bounds, all four pad faces, floor top, strap slots, battery cuboids, sensor opening. Added gussets reduce unused space above packs and along outboard tower roots.','physical_load_tested':False}
(OUT/(NAME+'_Checks.json')).write_text(json.dumps(report,indent=2))
fig=plt.figure(figsize=(12,8));ax=fig.add_subplot(111,projection='3d')
for shape,color,alpha in [(base,'#93aabd',0.25),(solid-base,'#f28c28',1)]:
 tm=mesh(shape); ax.add_collection3d(Poly3DCollection(tm.triangles,facecolor=color,edgecolor='none',alpha=alpha))
ax.set(xlim=(-38,198),ylim=(-10,150),zlim=(-12,72),xlabel='X (mm)',ylabel='Y (mm)',zlabel='Z (mm)');ax.set_box_aspect((228,152,85));ax.view_init(25,-55);ax.set_title('Four across: orange = permanent bridge and tower-root reinforcement')
fig.tight_layout();fig.savefig(OUT/(NAME+'_Preview.png'),dpi=160);plt.close(fig)
# Replace actual meshes and keep verified printer/process/filament settings.
CORE='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'; PROD='http://schemas.microsoft.com/3dmanufacturing/production/2015/06'; Q='{'+CORE+'}'
E.register_namespace('',CORE);E.register_namespace('p',PROD)
z=zipfile.ZipFile(OUT/'Wide_Tray_REINFORCED_SOLID_MOUNTS.3mf'); content={n:z.read(n) for n in z.namelist()}
objpath='3D/Objects/Four_Across_REINFORCED.model'
model=E.Element(Q+'model',{'unit':'millimeter'});res=E.SubElement(model,Q+'resources')
# Object coordinates centered about source bounds. Build translation restores bed Z=0.
center=np.array([80,70,28.5])
mods=[box(x,y,-6,69,24,73) for y in [3,113] for x in [-35,126]]
for i,tm in enumerate([new]+[mesh(m) for m in mods],1):
 obj=E.SubElement(res,Q+'object',{'id':str(i),'type':'model'});me=E.SubElement(obj,Q+'mesh');vs=E.SubElement(me,Q+'vertices');ts=E.SubElement(me,Q+'triangles')
 for p in tm.vertices-center:E.SubElement(vs,Q+'vertex',dict(zip(['x','y','z'],[f'{v:.7f}' for v in p])))
 for f in tm.faces:E.SubElement(ts,Q+'triangle',dict(zip(['v1','v2','v3'],map(str,f))))
content[objpath]=E.tostring(model,encoding='utf-8',xml_declaration=True)
main=E.fromstring(content['3D/3dmodel.model'])
for c in main.findall('.//'+Q+'component'): c.set('{'+PROD+'}path','/'+objpath)
main.find('.//'+Q+'item').set('transform','1 0 0 0 1 0 0 0 1 128 128 38.5')
content['3D/3dmodel.model']=E.tostring(main,encoding='utf-8',xml_declaration=True)
rels=content['3D/_rels/3dmodel.model.rels'].decode().replace('Wide_160x140_REPAIRED_SUPPORTS_REQUIRED.stl_3.model','Four_Across_REINFORCED.model');content['3D/_rels/3dmodel.model.rels']=rels.encode()
config=E.fromstring(content['Metadata/model_settings.config'])
for met in config.findall('.//metadata'):
 k=met.get('key');v=met.get('value','')
 if k in ['name','source_file'] and 'Wide_Tray' in v: met.set('value',NAME+'.stl')
 if k=='source_offset_x':met.set('value','80')
 if k=='source_offset_y':met.set('value','70')
 if k=='source_offset_z':met.set('value','28.5')
config.find('.//assemble_item').set('transform','1 0 0 0 1 0 0 0 1 0 0 38.5')
content['Metadata/model_settings.config']=E.tostring(config,encoding='utf-8',xml_declaration=True)
settings=json.loads(content['Metadata/project_settings.config']);settings['support_threshold_angle']='60';settings['support_on_build_plate_only']='0'
content['Metadata/project_settings.config']=json.dumps(settings,indent=2).encode()
# Remove stale previews/slice metadata; native slicing creates fresh previews.
for n in list(content):
 if n.startswith('3D/Objects/') and n!=objpath: del content[n]
 elif n.endswith('.png') or n in ['Metadata/slice_info.config','Metadata/plate_1.json']: del content[n]
with zipfile.ZipFile(OUT/(NAME+'.3mf'),'w',zipfile.ZIP_DEFLATED) as dest:
 for n,data in content.items():dest.writestr(n,data)
print(json.dumps(report,indent=2))
