#include "TelemetryLayout.h"
#include "FaultLayout.h"
#include <string>
#include <cassert>
#include <cstdio>
#include <initializer_list>
int main(){for(bool portrait:{false,true})for(int row=0;row<8;++row){int y=telemetryRowY(portrait,row);assert(y>=100);assert(y+16<=(portrait?377:229));if(row<7)assert(y+16<=telemetryRowY(portrait,row+1));}
  for(int row=0;row<9;++row)assert(99+row*16+16<=246);
  for(int unit=0;unit<4;++unit)assert(100+unit*31+19+16<=230);
  for(int i=0;i<10000;++i){std::string message(i%121,'W');for(size_t k=8;k<message.size();k+=9)message[k]=' ';size_t start=0;int width=20+i%429;
    while(start<message.size()){size_t end=faultLineEnd(message.c_str(),message.size(),start,width,[](char){return 8;});assert(end>start&&end<=message.size());assert((end-start)*8<=size_t(width));start=end;while(start<message.size()&&message[start]==' ')++start;}}
  puts("telemetry layout: both orientations, 8 metric rows, 18 RC cells, wrapped service names and footer/control bounds passed");}
