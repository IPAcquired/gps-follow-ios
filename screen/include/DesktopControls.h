#pragma once
constexpr int DESKTOP_TOOLBAR_HEIGHT=44;
struct DesktopButtonRect{int x,y,w,h;};
inline DesktopButtonRect desktopMenuRect(int width,int canvasHeight,int index){
 int cell=(canvasHeight-60)/4;
 return {10+(index%2)*(width/2),52+(index/2)*cell,width/2-20,cell-8};
}
inline int desktopMenuHit(int width,int canvasHeight,int x,int y){
 for(int i=0;i<8;++i){auto r=desktopMenuRect(width,canvasHeight,i);if(x>=r.x&&x<r.x+r.w&&y>=r.y&&y<r.y+r.h)return i;}
 return -1;
}
