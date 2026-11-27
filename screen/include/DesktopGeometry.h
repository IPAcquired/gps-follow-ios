#pragma once
inline int desktopCoordinate(int pixel,int size,int zoom,int center){
 if(size<2||zoom<1||zoom>4)return -1;
 if(pixel<0||pixel>=size||center<0||center>10000)return -1;
 int span=10000/zoom,origin=center-span/2;
 if(origin<0)origin=0;
 if(origin>10000-span)origin=10000-span;
 return origin+pixel*span/(size-1);
}

inline int desktopViewportCoordinate(int pixel,int size,int first,int last){
 if(size<2||pixel<0||pixel>=size||first<0||last>10000||first>last)return -1;
 return first+pixel*(last-first)/(size-1);
}
