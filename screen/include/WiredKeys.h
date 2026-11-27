#pragma once
#include <TFT_eSPI.h>
#include "KeyboardLayout.h"
#include "WiredDesktopProtocol.h"
class WiredKeys {
 public:
  static constexpr unsigned Top=152;
  bool shown=false,caps=false,full=false;
  uint8_t layout=0;
  uint32_t accepted=0;
  struct Event{uint8_t opcode=0,kind=0,len=0;uint16_t seq=0,x=0,y=0;bool move=false;char value[24]{};};
  const Event* head()const{return count_?&queue_[first_]:nullptr;}
  void reset(){memset(queue_,0,sizeof queue_);first_=count_=0;shown=caps=full=false;layout=0;}
  void discardTyping(){
    uint8_t keep=0;
    for(unsigned i=0;i<count_;++i){
      auto& e=queue_[(first_+i)%12];
      if(e.opcode!=0x24&&e.opcode!=0x28){if(keep!=i)queue_[(first_+keep)%12]=e;++keep;}
    }
    for(unsigned i=keep;i<count_;++i)memset(&queue_[(first_+i)%12],0,sizeof(Event));
    count_=keep;shown=caps=full=false;layout=0;
  }
  bool ack(uint16_t seq){
    if(!count_||queue_[first_].seq!=seq)return false;
    memset(&queue_[first_],0,sizeof(Event));first_=(first_+1)%12;--count_;++accepted;full=false;return true;
  }
  bool queue(uint8_t op,uint8_t kind,const char* s,uint16_t& event){
    if(count_>=12){full=true;return false;}
    if(++event==0)++event;
    auto& e=queue_[(first_+count_)%12];e.opcode=op;e.kind=kind;e.seq=event;
    e.len=strlen(s);memcpy(e.value,s,e.len);++count_;return true;
  }
  bool touch(uint8_t state,unsigned x,unsigned y,bool move,uint16_t& event){
    if(move&&count_>=2){
      auto& last=queue_[(first_+count_-1)%12];
      if(last.opcode==0x22&&last.move){last.x=x;last.y=y;return true;}
    }
    if(!queue(0x22,state,"",event))return false;
    auto& e=queue_[(first_+count_-1)%12];e.x=x;e.y=y;e.move=move;return true;
  }
  void draw(TFT_eSPI& lcd){
    lcd.fillRect(0,Top,480,296-Top,TFT_NAVY);
    for(int r=0;r<4;r++)for(int c=0;c<(layout==3?4:10);c++){
      char single[2]{};const char* name=label(r,c,single);
      if(name[0])button(lcd,c*(layout==3?120:48),Top+r*27,(layout==3?120:48),27,name);
    }
    const char* bottom[]={caps?"Caps on":"Caps",layout==0?"123":layout==1?"#+=":layout==2?"Nav":"ABC","Space","Bksp","Enter","Hide"};
    for(unsigned i=0;i<6;i++)button(lcd,i*80,260,80,36,bottom[i]);
  }
  // False asks the caller to close the keyboard and invalidate the covered area.
  bool press(TFT_eSPI& lcd,unsigned x,unsigned y,uint16_t& seq){
    if(y>=260){switch(x/80){
      case 0:caps=!caps;draw(lcd);break;
      case 1:layout=(layout+1)%4;draw(lcd);break;
      case 2:queue(0x24,1," ",seq);break;
      case 3:queue(0x24,2,"backspace",seq);break;
      case 4:queue(0x24,2,"enter",seq);break;
      case 5:return false;
    }return true;}
    char single[2]{};int r=(y-Top)/27,c=x/(layout==3?120:48);const char* code=label(r,c,single);
    if(*code)queue(0x24,layout==3?2:1,code,seq);return true;
  }
 private:
  Event queue_[12]{};uint8_t first_=0,count_=0;
  const char* label(int r,int c,char single[2]){
    if(layout==3){static const char* keys[][4]={{"escape","tab","delete","enter"},{"left","up","down","right"},{"ctrl+a","ctrl+c","ctrl+v","backspace"},{"","","",""}};return keys[r][c];}
    single[0]=keyboardCharacter(layout,r,c,caps);return single;
  }
  static void button(TFT_eSPI& l,unsigned x,unsigned y,unsigned w,unsigned h,const char* s){
    l.fillRect(x+1,y+1,w-2,h-2,0x2104);l.setTextColor(TFT_WHITE,0x2104);
    l.drawString(s,x+4,y+(h-16)/2,2);
  }
};
