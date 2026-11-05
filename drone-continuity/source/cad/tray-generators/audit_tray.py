from pathlib import Path
import sys,json
sys.path.insert(0,r'C:\Users\Daddy Nate\Documents\Codex\2026-09-27\locate-and-fix-the-user-s\work\mesh-deps')
import trimesh,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
p=Path(r'C:\Users\Daddy Nate\Desktop\A_Four_Across_REFINED.stl')
m=trimesh.load(p,force='mesh')
print(json.dumps({'file':str(p),'bounds':m.bounds.tolist(),'extents':m.extents.tolist(),'watertight':bool(m.is_watertight),'bodies':int(m.body_count),'volume_cm3':m.volume/1000},indent=2))
fig=plt.figure(figsize=(12,8));ax=fig.add_subplot(111,projection='3d')
ax.add_collection3d(Poly3DCollection(m.triangles,facecolor='#92b5c4',edgecolor='#284550',linewidth=.08,alpha=1))
ax.set_xlim(-40,200);ax.set_ylim(-10,150);ax.set_zlim(-15,70);ax.set_box_aspect([240,160,85]);ax.view_init(elev=24,azim=-58)
ax.set_xlabel('X (mm)');ax.set_ylabel('Y (mm)');ax.set_zlabel('Z (mm)');ax.set_title('Existing four-across tray — inspection before repair')
fig.savefig('work/existing-tray.png',dpi=150,bbox_inches='tight')
