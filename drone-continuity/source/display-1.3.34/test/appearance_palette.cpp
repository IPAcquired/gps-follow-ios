#include "AppearancePalette.h"
#include <cassert>
#include <cstring>
int main(){
 for(uint8_t theme=0;theme<APPEARANCE_COLOR_COUNT;++theme){
  assert(strlen(appearanceColorName(theme))>0);
  for(uint8_t custom=0;custom<APPEARANCE_COLOR_COUNT;++custom){
   assert(effectiveBackgroundColor(true,theme,custom)==theme);
   assert(effectiveBackgroundColor(false,theme,custom)==custom);
   if(theme!=custom)assert(appearanceColor565(theme)!=appearanceColor565(custom));
  }
 }
 assert(!strcmp(appearanceColorName(6),"RED"));assert(!strcmp(appearanceColorName(7),"ORANGE"));
 assert(!strcmp(appearanceColorName(8),"YELLOW"));assert(!strcmp(appearanceColorName(9),"INDIGO"));
 assert(!strcmp(appearanceColorName(10),"VIOLET"));
}
