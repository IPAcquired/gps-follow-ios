#include "XiaoLights.h"
#include <string>
#include <vector>
#include <cassert>
#include <cstdio>
using String=std::string;
static String operator+(String s,int i){return s+std::to_string(i);}
bool isPortrait=false;bool portrait(){return isPortrait;}
constexpr int CYAN=1,MUTED=2,PANEL=3,AMBER=4;
struct Button{int x,y,w,h,tx,ty;String label;};
std::vector<Button> routes;std::vector<String> labels;XiaoLights xiaoLights;
struct {void fillRoundRect(int x,int y,int w,int h,int,int){assert(x>=0&&x+w<=480&&y>=0&&y+h<=278);}} lcd;
void text(const String& s,int,int,int,int){labels.push_back(s);}
void portraitText(const String& s,int,int,int,int,int){labels.push_back(s);}
void portraitButton(const String& s,int x,int y,int w,int h,int tx,int ty,int=1){routes.push_back({x,y,w,h,tx,ty,s});}
#include "xiao-ui.inc"
int main(){
  renderXiaoLights(true);assert(labels.size()>12&&labels.front().find("Disconnected")!=String::npos);
  xiaoLights.valid=true;xiaoLights.confirmed.mode=4;xiaoLights.confirmed.yellow=3;labels.clear();renderXiaoLights(true);
  bool rgb=false,yellow=false;for(auto s:labels){rgb|=s=="RGB  Beacon";yellow|=s=="Yellow LED  Blink";}assert(rgb&&yellow);
  xiaoLights.confirmed.mode=3;xiaoLights.confirmed.speed=100;xiaoLights.applyError=XiaoLights::ApplyError::Driver;
  labels.clear();renderXiaoLights(true);bool fastest=false,error=false;
  for(const auto& label:labels){fastest|=label=="100 fastest";error|=label.find("driver unavailable")!=String::npos;}
  assert(fastest&&error);
  isPortrait=true;renderXiaoLights(false);assert(routes.size()==15);
  for(auto& b:routes){
    assert(b.x>=0&&b.y>=0&&b.x+b.w<=320&&b.y+b.h<=440);
    if(b.label=="BACK"){assert(b.ty>=246&&b.ty<274);continue;}
    assert(b.ty>=110&&b.ty<242);unsigned r=(b.ty-110)/22;
    if(b.label=="-10"){assert((r==2||r==4)&&b.tx<100);}
    if(b.label=="+10"){assert((r==2||r==4)&&b.tx>=390);}
  }
  puts("PASS real LED render in landscape and portrait, disconnected colors/readback labels, mapped adjustments and local Back.");
}
