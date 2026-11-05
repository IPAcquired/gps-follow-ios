from pathlib import Path
import zipfile,xml.etree.ElementTree as ET,json,sys
import numpy as np
sys.path.insert(0,r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s\work\mesh-deps')
import trimesh
out=Path('outputs');src=out/'Wide_Tray_PERMANENT_GUSSETS.3mf';dst=out/'Wide_Tray_REINFORCED_SOLID_MOUNTS.3mf'
core='http://schemas.microsoft.com/3dmanufacturing/core/2015/02';prod='http://schemas.microsoft.com/3dmanufacturing/production/2015/06'
ET.register_namespace('',core);ET.register_namespace('p',prod)
def c(s):return '{'+core+'}'+s
with zipfile.ZipFile(src) as old:
 data={n:old.read(n) for n in old.namelist()}
 gp=next(n for n in data if n.startswith('3D/Objects/') and n.endswith('.model'))
 geometry=ET.fromstring(data[gp]);res=geometry.find(c('resources'))
 main=ET.fromstring(data['3D/3dmodel.model']);components=main.find('.//'+c('components'))
 settings=ET.fromstring(data['Metadata/model_settings.config']);obj=settings.find('object')
 for i,(x,y) in enumerate([(0,5),(127,5),(0,115),(127,115)],2):
  tm=trimesh.creation.box(extents=[33,20,61.2]);tm.apply_translation([x+16.5-80,y+10-70,5.8+30.6-33.5])
  ob=ET.SubElement(res,c('object'),id=str(i),type='model');me=ET.SubElement(ob,c('mesh'));vs=ET.SubElement(me,c('vertices'));fs=ET.SubElement(me,c('triangles'))
  for v in tm.vertices:ET.SubElement(vs,c('vertex'),{a:format(float(q),'.10g') for a,q in zip('xyz',v)})
  for f in tm.faces:ET.SubElement(fs,c('triangle'),{f'v{j+1}':str(int(q)) for j,q in enumerate(f)})
  ET.SubElement(components,c('component'),{'objectid':str(i),'{'+prod+'}path':'/'+gp,'transform':'1 0 0 0 1 0 0 0 1 0 0 0'})
  part=ET.SubElement(obj,'part',id=str(i),subtype='modifier_part')
  for k,v in [('name','Solid mount '+str(i-1)),('matrix','1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1'),('sparse_infill_density','100%'),('sparse_infill_pattern','rectilinear')]:ET.SubElement(part,'metadata',key=k,value=v)
  ET.SubElement(part,'mesh_stat',edges_fixed='0',degenerate_facets='0',facets_removed='0',facets_reversed='0',backwards_edges='0')
 for n,r in [(gp,geometry),('3D/3dmodel.model',main),('Metadata/model_settings.config',settings)]:data[n]=ET.tostring(r,encoding='utf-8',xml_declaration=True)
 cfg=json.loads(data['Metadata/project_settings.config']);cfg['print_settings_id']='Reinforced tray - four solid mounts - removable supports';data['Metadata/project_settings.config']=json.dumps(cfg,indent=2).encode()
 with zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED) as z:
  for n,b in data.items():z.writestr(n,b)
print(dst.resolve())
