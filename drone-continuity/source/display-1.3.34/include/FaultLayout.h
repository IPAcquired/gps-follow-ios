#pragma once
#include <stddef.h>
template<class Width> size_t faultLineEnd(const char* value,size_t length,size_t start,int width,Width glyphWidth){
 size_t end=start,lastSpace=start;int used=0;
 while(end<length){int next=glyphWidth(value[end]);if(used+next>width)break;used+=next;if(value[end]==' ')lastSpace=end;++end;}
 if(end<length&&lastSpace>start)end=lastSpace;
 return end==start&&start<length?start+1:end;
}
