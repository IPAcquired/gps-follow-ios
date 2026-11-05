#include "KeyboardLayout.h"
#include <assert.h>
#include <stdio.h>
int main(){bool seen[128]={};seen[' ']=true;unsigned checks=0;
  for(int mode=0;mode<3;++mode)for(int caps=0;caps<2;++caps)for(int row=0;row<4;++row){
    assert(strlen(keyboardRow(mode,row))<=10);++checks;
    for(int col=0;col<10;++col){char c=keyboardCharacter(mode,row,col,caps);if(c)seen[unsigned(c)]=true;}
  }
  for(int c=32;c<=126;++c){assert(seen[c]);++checks;}
  for(int c=0;c<10;++c){assert(keyboardCharacter(1,0,c,false)=="1234567890"[c]);++checks;}
  assert(keyboardCharacter(0,1,0,true)=='Q');++checks;
  assert(!keyboardCharacter(3,0,0,false));++checks;assert(!keyboardCharacter(0,1,99,false));++checks;
  printf("PASS: %u keyboard assertions; all 95 printable ASCII characters available\n",checks);
}
