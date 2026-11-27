#include <cassert>
#include <cstdint>
#include <set>
#include <vector>
#include "BackgroundStyles.h"

struct Canvas {
  int left, top, w, h;
  std::vector<uint16_t> pixels;
  unsigned writes=0;
  Canvas(int x,int y,int width,int height):left(x),top(y),w(width),h(height),pixels(w*h){}
  void drawPixel(int x,int y,uint16_t value){
    assert(x>=left&&y>=top&&x<left+w&&y<top+h);
    pixels[(y-top)*w+(x-left)]=value;++writes;
  }
  void drawFastHLine(int x,int y,int n,uint16_t v){while(n-->0)drawPixel(x++,y,v);}
  void drawFastVLine(int x,int y,int n,uint16_t v){while(n-->0)drawPixel(x,y++,v);}
};

int main(){
  assert(backdrop::name(255)==backdrop::name(0));
  for(auto dim: {std::pair<int,int>(438,58),{284,130},{5,193},{5,351},{2,2},{1,1}}){
    std::set<std::vector<uint16_t>> stills;
    for(unsigned style=0;style<backdrop::Count;++style){
      Canvas c(13,11,dim.first,dim.second);
      backdrop::motif(c,c.left,c.top,c.w,c.h,style,0x7fff);
      if(style<backdrop::DriftingStars)stills.insert(c.pixels);
      if(!backdrop::animated(style))continue;
      for(uint32_t phase: {0u,1u,0xffffffffu,0xfffffff1u}){
        Canvas m(7,16,c.w,c.h);
        backdrop::markers(m,m.left,m.top,m.w,m.h,style,65535,phase);
        const auto first=m.pixels;
        const unsigned maximum=(c.w<=6?3u:14u)*4u;
        assert(m.writes<=maximum);
        backdrop::markers(m,m.left,m.top,m.w,m.h,style,0,phase);
        for(auto p:m.pixels)assert(!p);
        backdrop::markers(m,m.left,m.top,m.w,m.h,style,65535,phase+1);
        if(dim.first>10&&dim.second>10)assert(first!=m.pixels);
      }
    }
    if(dim.first>10)assert(stills.size()==4);
  }
}
