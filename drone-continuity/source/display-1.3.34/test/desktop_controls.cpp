#include "DesktopControls.h"
#include <cassert>
#include <iostream>
int main(){
 for(int width:{320,480}){int height=(width==320?480:320)-DESKTOP_TOOLBAR_HEIGHT;
  for(int i=0;i<8;++i){auto r=desktopMenuRect(width,height,i);assert(r.w>=140&&r.h>=40&&r.y+r.h<height);assert(desktopMenuHit(width,height,r.x+r.w/2,r.y+r.h/2)==i);}
  assert(desktopMenuHit(width,height,0,0)==-1);assert(desktopMenuHit(width,height,5,height+1)==-1);
 }
 std::cout<<"Portrait and landscape controls fit native canvas with >=40px touch height\n";
}
