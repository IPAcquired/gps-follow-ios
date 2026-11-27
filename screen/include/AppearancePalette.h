#pragma once
#include <stdint.h>
constexpr uint8_t APPEARANCE_COLOR_COUNT=12;
inline const char* appearanceColorName(uint8_t color){
  const char* names[]={"GREEN","CYAN","AMBER","PURPLE","WHITE","BLUE","RED","ORANGE","YELLOW","INDIGO","VIOLET","MAGENTA"};
  return names[color%APPEARANCE_COLOR_COUNT];
}
inline uint16_t appearanceColor565(uint8_t color){
  const uint16_t colors[]={0x07E0,0x07FF,0xFD45,0xC81F,0xF7BE,0x3DFF,0xF800,0xFD20,0xFFE0,0x681F,0xA01F,0xF81F};
  return colors[color%APPEARANCE_COLOR_COUNT];
}
inline uint8_t effectiveBackgroundColor(bool follow,uint8_t theme,uint8_t custom){return (follow?theme:custom)%APPEARANCE_COLOR_COUNT;}
