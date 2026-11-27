// Included after the archived R3.3 dummy TFT and UART/SPI periphery.
#include <ArduinoJson.h>
#include <cstdarg>
#include <cstdio>
#include "DirectBurst.h"
static bool powerMenu=false,sleepPending=false,touchReady=true,guard=false;
static AutoWired& wiredViewer=viewer;
static bool wiredSafetyPause(){return guard;}
static int hexNibble(char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;}
struct SyntheticUart {
  std::string input,output;
  unsigned baud=115200;
  int available(){return input.size();}
  char read(){char c=input.front();input.erase(0,1);return c;}
  void updateBaudRate(unsigned b){baud=b;}
  void flush(){}
  void flush(bool txOnly){if(!txOnly)input.clear();}
  void printf(const char* format,...){
    char out[512];
    va_list args;va_start(args,format);int n=vsnprintf(out,sizeof out,format,args);va_end(args);
    if(n>0&&n<int(sizeof out))output.append(out,n);
  }
} Serial;
#include "extracted_transport.inc"
extern "C" {
void uart_reset(){guard=false;Serial=SyntheticUart{};directBurst.clear();directBaud=115200;}
void uart_write(const char* bytes,unsigned n,unsigned baud){if(baud==Serial.baud)Serial.input.append(bytes,n);}
void uart_step(unsigned ms){fakeNow+=ms;serialInput();viewer.step(lcd,10,!guard);}
void uart_guard(bool g){guard=g;}
unsigned uart_baud(){return directBaud;}
unsigned uart_pending(){return directBurst.active();}
unsigned uart_unread(){return Serial.input.size();}
const char* uart_take(){static std::string out;out.swap(Serial.output);Serial.output.clear();return out.c_str();}
}
