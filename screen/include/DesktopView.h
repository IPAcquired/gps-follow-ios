#pragma once
#include "DesktopCodec.h"
// Stream::readBytes calls TLS read() once per byte on this Arduino core.
// Read whole available blocks while retaining cancellation and time bounds.
bool readDesktopBytes(WiFiClient& stream,uint8_t* buffer,size_t length,uint32_t epoch,uint32_t began,bool preempt){
  size_t received=0;
  while(received<length){
    if(!desktopActive||epoch!=desktopEpoch||uint32_t(millis()-began)>6000||(preempt&&inputQueue&&uxQueueMessagesWaiting(inputQueue)))return false;
    int count=stream.read(buffer+received,length-received);
    if(count>0)received+=size_t(count);
    else {if(!stream.connected())return false;vTaskDelay(pdMS_TO_TICKS(1));}
  }
  return true;
}
// Small row queue keeps framebuffer memory bounded while TLS is active.
void renderDesktop(){
  static uint32_t drawnEpoch=0;static bool priorMenu=false,priorPan=false;static String owner,priorMiddle;
  if(priorMenu&&!desktopOverlay){++desktopEpoch;desktopFrameAt=0;}
  int w=lcd.width(),ch=desktopHeight;
  uint32_t age=desktopFrameAt?uint32_t(millis()-desktopFrameAt):UINT32_MAX;
  String middle=!remoteReady?"OFFLINE":!desktopFrameAt?"LOADING":age>=6000?"STALE":"KEYBOARD";
  bool changed=drawnEpoch!=desktopEpoch||priorMenu!=desktopOverlay||priorPan!=desktopPanMode;
  if(changed||middle!=priorMiddle){
    lcd.fillRect(0,ch,w,DESKTOP_TOOLBAR_HEIGHT,BG);
    String bottom[]={"BACK",middle,desktopOverlay?"CLOSE":"MENU"};
    for(int i=0;i<3;++i){lcd.fillRoundRect(i*w/3+2,ch+3,w/3-4,38,5,PANEL);lcd.setTextColor(CYAN,PANEL);lcd.drawCentreString(bottom[i],(2*i+1)*w/6,ch+13,2);}
    priorMiddle=middle;
  }
  if(changed){
    drawnEpoch=desktopEpoch;owner="";
    if(desktopOverlay){
      lcd.fillRect(0,0,w,ch,BG);text("ORANGE PI DESKTOP",12,8,INK,2);
      const char* names[]={"OWNER","APPS","FILES","WEB","ESCAPE","FIT SCREEN",desktopPanMode?"ZOOM 1X":"ZOOM 2X","ROTATE"};
      for(int i=0;i<8;++i){auto r=desktopMenuRect(w,ch,i);lcd.fillRoundRect(r.x,r.y,r.w,r.h,6,PANEL);lcd.setTextColor(CYAN,PANEL);lcd.drawCentreString(names[i],r.x+r.w/2,r.y+(r.h-16)/2,2);}
    }
  }
  if(desktopOverlay){String next=ownerAccessCaption();if(next!=owner){lcd.fillRect(12,29,w-24,18,BG);text(next.substring(0,w==320?35:55),12,30,maintenanceEnabled()?GREEN:AMBER,1);owner=next;}}
  lcd.fillRect(0,ch,w,2,remoteReady&&age<6000?GREEN:AMBER);
  priorMenu=desktopOverlay;priorPan=desktopPanMode;dirty=false;
}
void serviceDesktopLines(){
  if(!desktopLines)return;DesktopLine line;
  uint32_t start=millis();
  for(int n=0;n<64&&uint32_t(millis()-start)<80&&xQueueReceive(desktopLines,&line,n?pdMS_TO_TICKS(2):0)==pdTRUE;++n){
    if(!desktopActive||line.epoch!=desktopEpoch)continue;
    if(line.row==65535){desktopFrameAt=millis();++desktopFrames;continue;}
    if(line.row>=desktopHeight)continue;
    int width=desktopWidth,height=desktopHeight;
    if(!desktopOverlay){lcd.setSwapBytes(true);lcd.pushImage(0,line.row,width,1,line.pixels);lcd.setSwapBytes(false);}
  }
}
void fetchDesktop(){
  if(!desktopActive||!desktopLines||!remoteReady||!piTrust.length()||!sessionPolicy.canRequest(millis()))return;
  IPAddress ip;if(!ip.fromString(endpoint))return;
  uint32_t epoch=desktopEpoch;int width=desktopWidth,height=desktopHeight;
  static String baseFrame;static uint32_t baseEpoch=0;
  if(baseEpoch!=epoch){baseFrame="";baseEpoch=epoch;}
  PiConnection* transport=sharedPiConnection(ip,piTrust);if(!transport)return;
  auto& client=transport->client;auto& http=transport->http;
  client.setCACert(piTrust.c_str());client.setTimeout(2);client.setHandshakeTimeout(3);
  http.setConnectTimeout(1200);http.setTimeout(2500);http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  String path=String("/api/desktop/frame?layout=")+(width==320?"portrait-touch-full":"landscape-touch-full")+"&zoom="+desktopZoom.load()+"&cx="+desktopCenterX.load()+"&cy="+desktopCenterY.load();
  if(baseFrame.length())path+="&base="+baseFrame;
  http.setReuse(true);
  if(!http.begin(client,PinnedPiClient::hostname(),8443,path,true))return;
  if(!client.connected()){http.end();return;} // Next network iteration reconnects without JSON allocations.
  client.setNoDelay(true);
  http.addHeader("Authorization","Bearer "+session);
  const char* headers[]={"X-Desktop-Viewport","X-Desktop-Encoding","X-Desktop-Frame","X-Desktop-Editable"};http.collectHeaders(headers,4);
  desktopRows=0;desktopAbort=0;
  int code=http.GET();desktopApiCode=code;
  if(code==401){session="";remoteReady=false;tlsLeaseAt=0;xQueueReset(inputQueue);}
  if(code==200)tlsLeaseAt=millis();
  if(code!=200||http.header("X-Desktop-Encoding")!="rle565-rows-v1"||http.getSize()<2||http.getSize()>(width*2+10)*height+2){desktopAbort=1;client.stop();http.end();return;}
  String nextFrame=http.header("X-Desktop-Frame");bool validId=nextFrame.length()==32;
  for(size_t i=0;i<nextFrame.length();++i)if(!((nextFrame[i]>='0'&&nextFrame[i]<='9')||(nextFrame[i]>='a'&&nextFrame[i]<='f')))validId=false;
  if(!validId){desktopAbort=2;client.stop();http.end();return;}
  int ml,mt,mr,mb;
  if(sscanf(http.header("X-Desktop-Viewport").c_str(),"%d,%d,%d,%d",&ml,&mt,&mr,&mb)!=4||ml<0||mt<0||mr>10000||mb>10000||ml>=mr||mt>=mb){desktopAbort=2;client.stop();http.end();return;}
  auto& stream=http.getStream();DesktopLine line;line.epoch=epoch;uint8_t packed[1024];
  uint32_t began=millis();
  int previousRow=-1;size_t consumed=0;bool completed=false;
  for(int count=0;count<=height;++count){
    if(!desktopActive||epoch!=desktopEpoch){desktopAbort=3;break;}
    if(uint32_t(millis()-began)>6000){desktopAbort=4;break;}
    // Touch input preempts image transfer; never execute a delayed click later.
    if(size_t(http.getSize())-consumed>8192&&inputQueue&&uxQueueMessagesWaiting(inputQueue)){desktopAbort=7;break;}
    uint8_t sizeBytes[2];
    if(!readDesktopBytes(stream,sizeBytes,2,epoch,began,size_t(http.getSize())-consumed>8192)){desktopAbort=5;break;}
    consumed+=2;int row=sizeBytes[0]|uint16_t(sizeBytes[1])<<8;
    if(row==65535){
      if(consumed!=size_t(http.getSize())){desktopAbort=5;break;}
      desktopEditableRevision=uint32_t(http.header("X-Desktop-Editable").toInt());desktopMapLeft=ml;desktopMapTop=mt;desktopMapRight=mr;desktopMapBottom=mb;line.row=65535;
      if(xQueueSend(desktopLines,&line,pdMS_TO_TICKS(400))!=pdTRUE){desktopAbort=6;break;}
      baseFrame=nextFrame;completed=true;break;
    }
    if(row<=previousRow||row>=height){desktopAbort=5;break;}
    previousRow=row;line.row=row;
    if(!readDesktopBytes(stream,sizeBytes,2,epoch,began,size_t(http.getSize())-consumed>8192)){desktopAbort=5;break;}
    consumed+=2;
    size_t size=sizeBytes[0]|uint16_t(sizeBytes[1])<<8;
    if(!size||size>sizeof(packed)||!readDesktopBytes(stream,packed,size,epoch,began,size_t(http.getSize())-consumed>8192)||!decodeDesktopRow(packed,size,line.pixels,width)){desktopAbort=5;break;}
    consumed+=size;
    if(xQueueSend(desktopLines,&line,pdMS_TO_TICKS(400))!=pdTRUE){desktopAbort=6;break;}
    desktopRows=count+1;
  }
  // A partial image may already have reached the LCD. Recover with a full frame.
  if(!completed){baseFrame="";client.stop();}
  http.end();
}
