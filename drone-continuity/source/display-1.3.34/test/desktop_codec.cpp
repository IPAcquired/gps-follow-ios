#include "DesktopCodec.h"
#include "DesktopGeometry.h"
#include <cassert>
#include <cstdio>
#include <vector>
int main(){
 for(int n=0;n<10000;++n){
  int width=n%2?320:480;std::vector<uint16_t> expected(width),out(width+1,0xdead);std::vector<uint8_t> encoded;
  for(int i=0;i<width;){int count=1+(n+i*13)%128;if(count>width-i)count=width-i;bool repeat=(n+i)%2;
   encoded.push_back((repeat?128:0)+count-1);
   if(repeat){uint16_t v=(n*37+i)&65535;encoded.push_back(v&255);encoded.push_back(v>>8);for(int j=0;j<count;++j)expected[i++]=v;}
   else for(int j=0;j<count;++j){uint16_t v=(n*11+i*17)&65535;encoded.push_back(v&255);encoded.push_back(v>>8);expected[i++]=v;}
  }
  assert(decodeDesktopRow(encoded.data(),encoded.size(),out.data(),width));
  for(int i=0;i<width;++i){assert(out[i]==expected[i]);}assert(out[width]==0xdead);
  assert(!decodeDesktopRow(encoded.data(),encoded.size()-1,out.data(),width));
  assert(!decodeDesktopRow(encoded.data(),encoded.size(),out.data(),width-1));
  int first=n%5000,last=first+5000;assert(desktopViewportCoordinate(0,width,first,last)==first);assert(desktopViewportCoordinate(width-1,width,first,last)==last);
 }
 puts("PASS: 10000 lossless desktop row, bounds and viewport cases");
}
