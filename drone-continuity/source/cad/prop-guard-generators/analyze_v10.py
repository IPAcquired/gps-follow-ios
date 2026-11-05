import sys,json,time
from pathlib import Path
import numpy as np
ROOT=Path(r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s')
sys.path[:0]=[str(ROOT/'work'/'mesh-deps'),str(ROOT/'work')]
from leg_fea import stl_mesh,stiffness,tet_gradients,strain_matrices
from scipy.sparse.linalg import spsolve
OUT=Path(__file__).resolve().parent/'outputs'/'prop-guard-v10-light-flex-petg'
path=OUT/'assembled_coordinates'/'PETG_Core_Half_1.stl'
h=float(sys.argv[1]) if len(sys.argv)>1 else 3.
def direct_mesh(path,h):
 import gmsh
 gmsh.initialize();gmsh.option.setNumber('General.Terminal',0)
 try:
  gmsh.model.add('guard');gmsh.merge(str(path))
  surfaces=[tag for dim,tag in gmsh.model.getEntities(2)]
  loop=gmsh.model.geo.addSurfaceLoop(surfaces);gmsh.model.geo.addVolume([loop]);gmsh.model.geo.synchronize()
  for key,val in {'Mesh.MeshSizeMin':h,'Mesh.MeshSizeMax':h,'Mesh.MeshOnlyEmpty':1,'Mesh.ElementOrder':1}.items():gmsh.option.setNumber(key,val)
  gmsh.model.mesh.generate(3)
  gmsh.model.mesh.optimize('Netgen')
  gmsh.model.mesh.rebuildNodeCache(False)
  tags,xyz,_=gmsh.model.mesh.getNodes()
  coords={int(tag):p for tag,p in zip(tags,np.asarray(xyz).reshape(-1,3))}
  def elements(dim,kind,w):
   types,_,arrays=gmsh.model.mesh.getElements(dim)
   return np.concatenate([np.asarray(flat).reshape(-1,w) for k,flat in zip(types,arrays) if k==kind])
  tetra=elements(3,4,4);surface=elements(2,2,3)
  missing=set(map(int,np.concatenate([tetra.ravel(),surface.ravel()]))) - set(coords)
  print(f'node cache missing {len(missing)} referenced nodes',flush=True)
  if missing:
   mask=np.all(np.isin(tetra,list(coords)),axis=1)
   dropped=int((~mask).sum());tetra=tetra[mask]
   surface=surface[np.all(np.isin(surface,list(coords)),axis=1)]
   print(f'rejected {dropped} tetrahedra with missing node references',flush=True)
  else:dropped=0
  order=np.array(sorted(coords));pts=np.array([coords[int(t)] for t in order])
  return pts,np.searchsorted(order,tetra),np.searchsorted(order,surface),dropped
 finally:gmsh.finalize()
points,tets,triangles,dropped=direct_mesh(path,h)
xyz=points[tets]
tet_volume=np.abs(np.linalg.det(xyz[:,1:]-xyz[:,0,None,:]))/6
good=tet_volume>1e-8
dropped+=int((~good).sum());tets=tets[good]
used=np.unique(tets);triangles=triangles[np.all(np.isin(triangles,used),axis=1)]
points=points[used];tets=np.searchsorted(used,tets);triangles=np.searchsorted(used,triangles)
import trimesh
solid_volume=trimesh.load(path,force='mesh').volume
coverage=float(tet_volume[good].sum()/solid_volume)
assert .98<coverage<1.02,('mesh volume coverage',coverage)
print(f'mesh: {len(points)} nodes, {len(tets)} tetrahedra',flush=True)
K,volumes,D=stiffness(points,tets,1500,.35)
tri=points[triangles];centre=tri.mean(axis=1);area=np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)/2
fixed_faces=np.zeros(len(triangles),dtype=bool)
for bolt in [(-36.4,8),(-52.4,8)]:fixed_faces|=(np.linalg.norm(centre[:,:2]-bolt,axis=1)<4.5)&(centre[:,2]<-8.9)
fixed_nodes=np.unique(triangles[fixed_faces]);fixed=(fixed_nodes[:,None]*3+np.arange(3)).ravel()
loaded=(centre[:,0]>162)&(centre[:,1]>0)&(centre[:,1]<23)&(centre[:,2]>10.9)
loaded_tri=triangles[loaded];loaded_nodes=np.unique(loaded_tri);loaded_area=area[loaded].sum()
assert len(fixed_nodes)>5 and loaded_area>0
free=np.setdiff1d(np.arange(len(points)*3),fixed)
F=np.zeros((len(points)*3,3))
forces=np.array([[-5.,0,0],[5.,0,0],[0,0,5.]])
for j,force in enumerate(forces):
 for local in range(3):
  for axis in range(3):np.add.at(F[:,j],loaded_tri[:,local]*3+axis,force[axis]*area[loaded]/(3*loaded_area))
print('solve three linear static load cases',flush=True)
u=np.zeros_like(F);u[free]=spsolve(K[free][:,free],F[free])
residual=K@u-F
cases=[]
for j,name in enumerate(['5 N inward','5 N outward','5 N upward']):
 disp=u[:,j].reshape(-1,3);norm=np.linalg.norm(disp,axis=1)
 stresses=[]
 for start in range(0,len(tets),3000):
  sub=tets[start:start+3000];G,_=tet_gradients(points,sub);B=strain_matrices(G)
  stress=np.einsum('tia,ta->ti',B,disp[sub].reshape(-1,12))@D.T
  sx,sy,sz,txy,tyz,txz=stress.T
  stresses.extend(np.sqrt(((sx-sy)**2+(sy-sz)**2+(sz-sx)**2)/2+3*(txy**2+tyz**2+txz**2)))
 stress=np.asarray(stresses);tc=points[tets].mean(axis=1)
 interior=tc[:,2]>-8
 order=np.argsort(stress[interior]);weights=volumes[interior][order];cdf=np.cumsum(weights);cdf/=cdf[-1]
 p95=np.interp(.95,cdf,stress[interior][order]);p99=np.interp(.99,cdf,stress[interior][order])
 deformed=points+disp;rim=np.linalg.norm(points[:,:2],axis=1)>151.5
 prop_disk=np.linalg.norm(deformed[:,:2],axis=1)<139.7
 case={'case':name,'total_force_N':forces[j].tolist(),'loaded_mean_displacement_mm':float(norm[loaded_nodes].mean()),'maximum_displacement_mm':float(norm.max()),
 'interior_volume_weighted_von_mises_p95_MPa':float(p95),'interior_volume_weighted_von_mises_p99_MPa':float(p99),'maximum_von_mises_MPa_mesh_dependent':float(stress.max()),
 'relative_free_residual':float(np.linalg.norm(residual[free,j])/np.linalg.norm(F[free,j])),
 'maximum_stress_element_centre_mm':tc[int(np.argmax(stress))].tolist(),
 'reaction_error_N':float(np.linalg.norm(residual[:,j].reshape(-1,3)[fixed_nodes].sum(axis=0)+forces[j])),
 'minimum_deformed_rim_radius_mm':float(np.linalg.norm(deformed[rim,:2],axis=1).min()),
 'minimum_blade_underside_gap_over_prop_disk_mm':float(27-deformed[prop_disk,2].max()),
 'warning':'Deformed-geometry figures use linear displacement; large motions require nonlinear analysis.'}
 cases.append(case)
report={'type':'coarse linear static tetrahedral FEA; isolated front half, ideally fixed mounting washers',
 'rejected_invalid_tetrahedra':dropped,
 'tetra_volume_to_stl_volume_ratio':coverage,
 'material_assumption':{'E_MPa':1500,'poisson_ratio':.35,'description':'homogeneous isotropic fully dense PETG; no printed anisotropy'},
 'mesh_target_mm':h,'nodes':len(points),'tetrahedra':len(tets),'mesh_volume_cm3':float(volumes.sum()/1000),'fixed_nodes':len(fixed_nodes),'loaded_area_mm2':float(loaded_area),'cases':cases,
 'limitations':['Rear-half coupling and splice behavior excluded.','Aircraft holes and real arm fastening unknown.','No nonlinear contact, buckling, damping, impact, fatigue, creep or spring-back test.','Ideal clamps and fully dense isotropic material can overestimate stiffness.','Stress peaks depend on mesh and boundary treatment.','This is a design screen, not flight approval.']}
(OUT/f'linear_fea_{h:g}mm.json').write_text(json.dumps(report,indent=2));np.savez_compressed(OUT/f'linear_fea_{h:g}mm_fields.npz',points=points,tets=tets,triangles=triangles,displacement=u)
print(json.dumps(report,indent=2),flush=True)
