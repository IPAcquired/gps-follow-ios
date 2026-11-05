import sys,json,math,itertools,zipfile
from pathlib import Path
import numpy as np
ROOT=Path(r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s')
sys.path[:0]=[str(ROOT/'work'/'mesh-deps'),str(ROOT/'work')]
import build_prop_guard_multimaterial as old
import manifold3d as md
import trimesh
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
M=md.Manifold
OUT=Path(__file__).resolve().parent/'outputs'/'prop-guard-v10-light-flex-petg'
OUT.mkdir(parents=True,exist_ok=True)
ASSEMBLED=OUT/'assembled_coordinates';PRINT=OUT/'print_ready_parts'
ASSEMBLED.mkdir(exist_ok=True);PRINT.mkdir(exist_ok=True)
RI,RO,BRI,BRO=152.6,165.,165.35,167.75
def box(x,y,z,dx,dy,dz):return M.cube((dx,dy,dz)).translate((x,y,z))
def cylinder(x,y,z,h,r):return M.cylinder(h,r,circular_segments=64).translate((x,y,z))
def sector(ri,ro,z,h,a,b):return old.base.annular_sector(ri,ro,z,h,a,b)
def union(p):return M.batch_boolean(p,md.OpType.Add)
def xy(r,a):return r*math.cos(math.radians(a)),r*math.sin(math.radians(a))
def mesh(s):
 s=s.simplify(.001)
 raw=s.to_mesh();t=trimesh.Trimesh(vertices=np.asarray(raw.vert_properties[:,:3]),faces=np.asarray(raw.tri_verts),process=True)
 t.merge_vertices(digits_vertex=5);t.update_faces(t.nondegenerate_faces(height=1e-6));t.remove_unreferenced_vertices()
 return t
def bolt_cut(s,x,y,bottom=-1):
 return s-cylinder(x,y,bottom,30,1.7)-cylinder(x,y,16.8,2.3,3.2)
mount=cylinder(-44.4,0,-9,6,19.4)
mount_xy=[(-36.4,8),(-52.4,8),(-52.4,-8),(-36.4,-8)]
for x,y in mount_xy:mount=mount-cylinder(x,y,-26,29,1.7)-cylinder(x,y,-5.2,2.3,3.2)
def spoke(start,a):
 end=np.array(xy(157,a));start=np.array(start);mid=start+(end-start)*.5
 # Rounded planform I-section: narrow web with small top/bottom flanges.
 # Independent hulls preserve the open channels instead of filling the beam solid.
 nodes=[(start,-18.5,10.,6.)]
 if a in (16,344):nodes.append(((-20,36 if a==16 else -36),-7.,6.,2.4))
 nodes.extend([(mid,-7.,6.,2.4),(end,-3.,8.,3.2)])
 pieces=[]
 for (p,z,w,web),(q,zz,ww,webb) in zip(nodes,nodes[1:]):
  for width,width2,offset,height in [(web,webb,0,22),(w,ww,0,1.5),(w,ww,20.5,1.5)]:
   u=cylinder(*p,z+offset,height,width/2);v=cylinder(*q,zz+offset,height,width2/2)
   pieces.append(union([u,v]).hull())
 # Local rounded gusset spreads load at the compact mounting-foot transition.
 target=start+(np.asarray(nodes[1][0])-start)*(.55 if a in (16,344) else .24)
 gusset=union([cylinder(*start,-18.5,9.5,5),cylinder(*target,-15.,13.5,4.5)]).hull()
 pieces.append(gusset)
 return union(pieces)
parts={'PETG_Round_Mount_38p80mm':mount};hardware=[]
for i,(a0,a1,sy) in enumerate([(.12,89.85,1),(270.15,359.88,-1)],1):
 tab=cylinder(-44.4,0,-19,10,19.4)^box(-64,.2 if sy>0 else -20,-19,40,19.8,10)
 angles_spoke=[16,72] if sy>0 else [344,288]
 rim=sector(RI,RO,11,8,a0,a1)-sector(.1,163.,12.8,4.4,a0-.3,a1+.3)
 core=union([tab,spoke((-34,8*sy),angles_spoke[0]),spoke((-54,10*sy),angles_spoke[1]),rim])
 core=core-cylinder(-44.4,0,-9,30,19.4)-box(-203.55,-14.1,-3.35,178.9,28.2,3.7)
 for bx,by in mount_xy:
  if by*sy>0:core=core-cylinder(bx,by,-26,30,1.7)
 # One seam fastener per rigid half; four TPU screws per half.
 angles=[3.5,9.5,33.75,56.25,78.75] if sy>0 else [356.5,281.25,303.75,326.25,350.5]
 # Keep solid material behind every recess and washer bearing area.
 core=core+union([cylinder(*xy(159.5,ang),11,8,4.4) for ang in angles])
 for ang in angles:core=bolt_cut(core,*xy(159.5,ang))
 parts[f'PETG_Core_Half_{i}']=core
 for j,(lo,hi) in enumerate([(a0,(a0+a1)/2-.15),((a0+a1)/2+.15,a1)],1):
  tpu=sector(BRI,BRO,7.65,11.35,lo,hi)
  # Local screw lugs replace the heavy continuous lower flange.
  for ang in angles[1:]:
   if lo<ang<hi:
    bridge=box(159.5,-3.5,7.65,8.15,7.,3.35).rotate((0,0,ang))
    tpu=tpu+cylinder(*xy(159.5,ang),7.65,3.35,4.3)+bridge
  for ang in angles[1:]:
   if lo<ang<hi:tpu=tpu-cylinder(*xy(159.5,ang),0,22,1.7)
  parts[f'TPU_Screw_On_Strip_{i}_{j}']=tpu
for i,a in enumerate([0],1):
 splice=sector(RI,RO,5.35,5.65,a-6,a+6)
 for ang in [a-3.5,a+3.5]:splice=splice-cylinder(*xy(159.5,ang),0,22,1.7)
 parts[f'PETG_Rim_Splice_{i}']=splice
report={'revision':'V10 lightweight PETG open semicircle with screw-on TPU strips','printer_bed_mm':[256,256],
 'rim_inner_diameter_mm':2*RI,'outer_diameter_with_TPU_mm':2*BRO,'parts':{},'part_intersections':[],
 'arm_intersections':[],'motor_keepout_intersections':[],'hardware_intersections':[],
 'nominal_blade_underside_z_mm':27,'highest_part_z_mm':19,'static_vertical_clearance_mm':8,
 'mount_diameter_mm':38.8,'aircraft_holes':'User drills; mounting rigidity remains unverified'}
actual={}
for n,s in parts.items():
 t=mesh(s);p=ASSEMBLED/(n+'.stl');t.export(p);t=trimesh.load(p,force='mesh',process=True)
 assert t.is_watertight and t.is_winding_consistent and t.body_count==1,(n,t.body_count,t.is_watertight)
 actual[n]=M(md.Mesh(np.asarray(t.vertices,dtype=np.float32),np.asarray(t.faces,dtype=np.uint32)))
 assert np.all(t.extents<=246),(n,t.extents)
 report['parts'][n]={'bounds_mm':t.bounds.tolist(),'size_mm':t.extents.tolist(),'volume_mm3':float(t.volume),'watertight':True,'bodies':1}
 # Put each core rim-top-down for a broad curved contact footprint.
 # Supports remain required under the raised mounting feet and selected rib regions.
 if n.startswith('PETG_Core'):t.vertices[:,1:]*=-1
 t.apply_translation(-t.bounds[0]);t.export(PRINT/(n+'.stl'))
for a,b in itertools.combinations(actual,2):
 vol=(actual[a]^actual[b]).volume()
 if vol>.001:report['part_intersections'].append({'parts':[a,b],'volume_mm3':vol})
arm=box(-203.2,-13.75,-3,178.2,27.5,3);motor=cylinder(0,0,-3,30,25)
for n,s in actual.items():
 for label,env in [('arm_intersections',arm),('motor_keepout_intersections',motor)]:
  vol=(s^env).volume()
  if vol>.001:report[label].append({'part':n,'volume_mm3':vol})
def add_hardware(label,x,y,headbase,length,washer_top):
 # Explicit clearance envelopes: button head <=6 diameter and <=2 high;
 # washer OD7, ID3.4, thickness0.6; nut circumscribed diameter6.4, height2.4.
 bolt=cylinder(x,y,headbase-length,length,1.5)+cylinder(x,y,headbase,2,3)
 washer=cylinder(x,y,washer_top-.6,.6,3.5)-cylinder(x,y,washer_top-.7,.8,1.7)
 nut=cylinder(x,y,washer_top-3,2.4,3.2)-cylinder(x,y,washer_top-3.1,2.6,1.7)
 hardware.extend([(label+' bolt',bolt),(label+' washer',washer),(label+' nut',nut)])
for i,(x,y) in enumerate(mount_xy):add_hardware(f'mount {i+1}',x,y,-5.2,18,-19)
for a in [0]:
 for ang in [a-3.5,a+3.5]:add_hardware(f'rim splice {ang}',*xy(159.5,ang),16.8,16,5.35)
for a in [9.5,33.75,56.25,78.75,281.25,303.75,326.25,350.5]:add_hardware(f'TPU {a}',*xy(159.5,a),16.8,14,7.65)
for label,h in hardware:
 for n,s in actual.items():
  vol=(h^s).volume()
  if vol>.001:report['hardware_intersections'].append({'hardware':label,'part':n,'volume_mm3':vol})
 assert (h^arm).volume()<.001,(label,'arm')
 assert (h^motor).volume()<.001,(label,'motor')
# Layer-connectedness screen in the delivered print orientation.
for n,s in actual.items():
 low,high=report['parts'][n]['bounds_mm'][0][2],report['parts'][n]['bounds_mm'][1][2]
 slices=[]
 for z in np.arange(low+.1,high,.5):
  slab=s^box(-250,-250,float(z),500,500,.2)
  if slab.volume()>0:slices.append(len(slab.decompose()))
 report['parts'][n]['maximum_disconnected_layer_regions']=max(slices,default=0)
 report['parts'][n]['supports_required']=n.startswith('PETG_Core')
 report['parts'][n]['print_orientation']='rim top on bed; supports required' if n.startswith('PETG_Core') else 'flat bottom on bed'
# Directional beam screen; the actual routed assembly is checked separately.
E=1500.;L=230.;h=22.;b=6.;web=2.4;flange=1.5
I=(b*h**3-(b-web)*(h-2*flange)**3)/12
Iz=2*flange*b**3/12+(h-2*flange)*web**3/12
report['structural_screen']={'type':'idealized constant I-section cantilever; not a load rating',
 'assumed_modulus_MPa':E,'span_mm':L,'section_mm':{'width':b,'height':h,'web':web,'flange':flange},
 'vertical_second_moment_mm4':I,'lateral_second_moment_mm4':Iz,'vertical_to_lateral_stiffness_ratio':I/Iz,
 'reference':'https://prusament.com/materials/prusament-petg/',
 'load_cases':[{'tip_force_N':F,'nominal_vertical_bending_stress_MPa':F*L*h/(2*I),'ideal_single_beam_tip_deflection_mm':F*L**3/(3*E*I)} for F in [2,5,10]],
 'unresolved':['mount/drilled-hole strength','layer adhesion at tab-to-spoke neck','joint slip and PETG creep','TPU screw pull-through','impact and fatigue','printed settings and actual filament properties']}
report['neighbor_spacing_screen']='Inner semicircle remains open. Actual neighboring guard placement is unverified; conflicting old motor spacing values were not used.'
report['estimated_solid_mass_g']={m:sum(v['volume_mm3'] for n,v in report['parts'].items() if n.startswith(m))*rho/1000 for m,rho in [('PETG',1.27),('TPU',1.20)]}
previous=json.loads((OUT.parent/'prop-guard-v9-semicircle-screw-tpu'/'geometry_and_structure_audit.json').read_text())
report['mass_reduction_from_v9_percent']=100*(1-sum(report['estimated_solid_mass_g'].values())/sum(previous['estimated_solid_mass_g'].values()))
# Projected area is a geometry comparison only; it is not a drag or thrust estimate.
def plan_area(paths):
 polygons=[]
 for p in paths:
  tm=trimesh.load(p,force='mesh')
  for tri in tm.triangles[:,:,:2]:
   if abs(np.cross(tri[1]-tri[0],tri[2]-tri[0]))>1e-8:
    polygons.append(md.CrossSection([tri]))
 silhouette=md.CrossSection.batch_boolean(polygons,md.OpType.Add)
 return (silhouette^md.CrossSection.circle(139.7,1024)).area()
newarea=plan_area(ASSEMBLED.glob('PETG_Core*.stl'))
oldarea=plan_area((OUT.parent/'prop-guard-v9-semicircle-screw-tpu'/'assembled_coordinates').glob('PLA_Core*.stl'))
report['downwash_projection_screen']={'v9_inside_prop_disk_mm2':oldarea,'v10_inside_prop_disk_mm2':newarea,'area_reduction_percent':100*(1-newarea/oldarea),'limitation':'Plan-view blockage; no CFD, drag coefficient or propeller performance validation.'}
(OUT/'geometry_and_structure_audit.json').write_text(json.dumps(report,indent=2))
assert all(not report[k] for k in ['part_intersections','arm_intersections','motor_keepout_intersections','hardware_intersections']),json.dumps({k:report[k] for k in ['part_intersections','arm_intersections','motor_keepout_intersections','hardware_intersections']})
fig=plt.figure(figsize=(14,8));ax=fig.add_subplot(121,projection='3d');plan=fig.add_subplot(122)
from matplotlib.collections import PolyCollection
for n,s in parts.items():
 t=mesh(s);col='#ec8b43' if n.startswith('TPU') else '#467b97'
 ax.add_collection3d(Poly3DCollection(t.triangles,facecolor=col,edgecolor=col,linewidth=.1))
 plan.add_collection(PolyCollection(t.triangles[:,:,:2],facecolor=col,edgecolor=col,linewidth=.1))
for x,y in mount_xy:plan.plot(x,y,'o',color='white',markersize=3)
for a in [0]:
 for ang in [a-3.5,a+3.5]:plan.plot(*xy(159.5,ang),'o',color='#26333a',markersize=3)
for a in [9.5,33.75,56.25,78.75,281.25,303.75,326.25,350.5]:plan.plot(*xy(159.5,a),'o',color='#26333a',markersize=3)
ax.set_xlim(-80,185);ax.set_ylim(-185,185);ax.set_zlim(-35,65);ax.set_box_aspect((.75,1,.27));ax.view_init(32,-50);ax.set_axis_off();ax.set_title('V10 open semicircle — PETG rim + screw-on TPU strips')
plan.set_xlim(-80,185);plan.set_ylim(-185,185);plan.set_aspect('equal');plan.grid(alpha=.2);plan.set_xlabel('X (mm)');plan.set_ylabel('Y (mm)');plan.set_title('2 rigid halves; 4 TPU strips; 38.80 mm mount')
fig.tight_layout();fig.savefig(OUT/'V10_assembly_preview.png',dpi=170);plt.close(fig)
print(json.dumps({'parts':len(parts),'maximum_part_extents':np.max([v['size_mm'] for v in report['parts'].values()],axis=0).tolist(),'collisions':{k:len(report[k]) for k in ['part_intersections','arm_intersections','motor_keepout_intersections','hardware_intersections']},'structure':report['structural_screen'],'mass':report['estimated_solid_mass_g'],'neighbors':report['neighbor_spacing_screen']},indent=2))

