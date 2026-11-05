#include "DesktopGeometry.h"
#include <cassert>
#include <cstdio>
int main(){
 for(int i=0;i<10000;++i){int size=i%2?320:336,zoom=i%4+1,center=(i*37)%10001;
 int left=desktopCoordinate(0,size,zoom,center),right=desktopCoordinate(size-1,size,zoom,center);
 assert(left>=0&&right<=10000&&right>=left);assert(right-left==10000/zoom);
 int pixel=i%size;int value=desktopCoordinate(pixel,size,zoom,center);assert(value>=left&&value<=right);
 if(pixel)assert(value>=desktopCoordinate(pixel-1,size,zoom,center));
 if(zoom==1){assert(left==0);assert(right==10000);}
 }
 assert(desktopCoordinate(-1,320,1,5000)==-1);assert(desktopCoordinate(320,320,1,5000)==-1);
 printf("PASS: 10000 native desktop mapping cases\n");
}
