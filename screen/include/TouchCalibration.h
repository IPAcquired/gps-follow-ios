#pragma once
#include <stdint.h>
#include <stdlib.h>
inline bool validCalibration(const uint16_t* p) {
  return p[1]>=1500&&p[3]>=1500&&p[0]+p[1]<=4095&&p[2]+p[3]<=4095&&p[4]<=7;
}
// Four deliberate, released-between corners: TL, BL, TR, BR.
inline bool calibrationFromCorners(const uint16_t v[8],uint16_t out[5]) {
  for(int i=0;i<8;++i)if(v[i]<80||v[i]>4015)return false;
  bool rotate=abs(int(v[0])-v[2])>abs(int(v[1])-v[3]);
  int x0,x1,y0,y1;
  if(rotate) {x0=(v[1]+v[3])/2;x1=(v[5]+v[7])/2;y0=(v[0]+v[4])/2;y1=(v[2]+v[6])/2;}
  else {x0=(v[0]+v[2])/2;x1=(v[4]+v[6])/2;y0=(v[1]+v[5])/2;y1=(v[3]+v[7])/2;}
  // Reject a diagonal/center tap or cross-axis noise, not just a nonzero range.
  int xi=rotate?1:0,yi=rotate?0:1;
  if(abs(int(v[xi])-v[2+xi])>450||abs(int(v[4+xi])-v[6+xi])>450||
     abs(int(v[yi])-v[4+yi])>450||abs(int(v[2+yi])-v[6+yi])>450)return false;
  bool invertX=x0>x1,invertY=y0>y1;
  out[0]=invertX?x1:x0;out[1]=abs(x1-x0);
  out[2]=invertY?y1:y0;out[3]=abs(y1-y0);
  out[4]=uint16_t(rotate)|(uint16_t(invertX)<<1)|(uint16_t(invertY)<<2);
  return validCalibration(out);
}
