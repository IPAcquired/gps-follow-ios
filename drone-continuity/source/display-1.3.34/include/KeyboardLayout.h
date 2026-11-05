#pragma once
#include <stdint.h>
#include <string.h>
inline const char* keyboardRow(uint8_t mode,int row) {
  static const char* alpha[]={"1234567890","qwertyuiop","asdfghjkl","zxcvbnm.,?"};
  static const char* numbers[]={"1234567890","-/:;()$&@\"",".,?!'_=+%*","[]{}<>\\|`~"};
  static const char* symbols[]={"!@#$%^&*()","-_+=[]{}\\|",";:'\",.<>/?","`~01234567"};
  if(row<0||row>3||mode>2)return "";
  return mode==1?numbers[row]:mode==2?symbols[row]:alpha[row];
}
inline char keyboardCharacter(uint8_t mode,int row,int column,bool caps) {
  const char* values=keyboardRow(mode,row);
  if(column<0||column>=int(strlen(values)))return 0;
  char c=values[column];if(caps&&c>='a'&&c<='z')c-=32;return c;
}
