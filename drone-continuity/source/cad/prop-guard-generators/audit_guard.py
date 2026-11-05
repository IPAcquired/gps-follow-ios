import sys,json,itertools
from pathlib import Path
import numpy as np
root=Path(r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s')
sys.path.insert(0,str(root/'work'/'mesh-deps'))
import trimesh
import manifold3d as md
folder=root/'outputs'/'prop-guard-11x7-v6-pahtcf-tpu'
meshes={p.stem:trimesh.load(p,force='mesh',process=True) for p in folder.glob('*.stl')}
solids={n:md.Manifold(md.Mesh(np.asarray(m.vertices,dtype=np.float32),np.asarray(m.faces,dtype=np.uint32))) for n,m in meshes.items()}
report={'parts':{},'intersections':[],'arm_intersections':[]}
for n,m in meshes.items():
 report['parts'][n]={'watertight':bool(m.is_watertight),'winding_consistent':bool(m.is_winding_consistent),'bodies':int(m.body_count),'bounds':m.bounds.tolist(),'volume_mm3':float(m.volume),'boolean_status':str(solids[n].status())}
for a,b in itertools.combinations(solids,2):
 s=solids[a]^solids[b]
 if s.volume()>0.001:
  raw=s.to_mesh();v=np.asarray(raw.vert_properties[:,:3]);
  report['intersections'].append({'a':a,'b':b,'volume_mm3':s.volume(),'bounds':[v.min(axis=0).tolist(),v.max(axis=0).tolist()]})
# Arm top is z=0, arm thickness is 3, and outboard hardware keepout begins x=-25.
arm=md.Manifold.cube((178.2,27.5,3)).translate((-203.2,-13.75,-3))
for n,s in solids.items():
 hit=s^arm
 if hit.volume()>0.001:report['arm_intersections'].append({'part':n,'volume_mm3':hit.volume()})
Path('guard_audit.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
