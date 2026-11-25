#pragma once
// Native 320x480 layout: text keeps its normal readable font; no framebuffer
// stretching or full-screen allocation. Buttons route to the shared action code.
void portraitRoute(int x,int y,int w,int h,int tx,int ty,int tw=0,int th=0){
  if(portraitHitCount<80)portraitHits[portraitHitCount++]={int16_t(x),int16_t(y),int16_t(w),int16_t(h),int16_t(tx),int16_t(ty),int16_t(tw),int16_t(th)};
}
String portraitFit(String value,int width,int font=2){
  if(lcd.textWidth(value,font)<=width)return value;
  while(value.length()&&lcd.textWidth(value+"...",font)>width)value.remove(value.length()-1);
  return value+"...";
}
bool widgetChanged(int kind,int x,int y,int w,int h,const String& value,uint16_t color=0){return widgetCache.changed(kind,x,y,w,h,value.c_str(),color);}
void portraitText(const String& value,int x,int y,int width=296,uint16_t color=INK,int font=2){
  String fit=portraitFit(value,width,font);int h=lcd.fontHeight(font);
  if(!widgetChanged(1,x,y,width,h,fit,color))return;
  lcd.fillRect(x,y,width,h,BG);text(fit,x,y,color,font);if(telemetryPage>=6&&telemetryPage<=8)++faultRowDraws;
}
void portraitLines(const String& value,int x,int y,int width,int rows,uint16_t color=INK){
  if(!widgetChanged(2,x,y,width,rows*19,value,color))return;
  lcd.fillRect(x,y,width,rows*19,BG);
  unsigned start=0;
  for(int row=0;row<rows&&start<value.length();++row){
    unsigned end=start;while(end<value.length()&&lcd.textWidth(value.substring(start,end+1),2)<=width)++end;
    if(end<value.length()){int space=value.lastIndexOf(' ',end);if(space>int(start))end=space;}
    if(end==start)++end;
    text(value.substring(start,end),x,y+row*19,color,2);start=end;while(start<value.length()&&value[start]==' ')++start;
  }
}
#include "FaultLayout.h"
void drawFaultLines(const char* value,int x,int y,int width,int rows,uint16_t color){
 // ASCII report text is sanitized by the Pi. Linear wrapping avoids building
 // and measuring every progressively longer substring on entry.
 static uint8_t widths[95]={};
 if(!widths[0])for(int c=32;c<=126;++c){char glyph[2]={char(c),0};widths[c-32]=lcd.textWidth(glyph,2);}
 size_t length=strlen(value),start=0;
 for(int row=0;row<rows;++row){
  size_t end=faultLineEnd(value,length,start,width,[&](char c){return c>=32&&c<=126?widths[c-32]:widths['?'-32];});
  char line[122]={};size_t count=end-start;if(count>121)count=121;memcpy(line,value+start,count);
  portraitText(line,x,y+row*19,width,color,2);
  start=end;while(start<length&&value[start]==' ')++start;
 }
}
void portraitButton(const String& label,int x,int y,int w,int h,int tx,int ty,uint16_t color=CYAN){
  portraitRoute(x,y,w,h,tx,ty);
  if(!widgetChanged(3,x,y,w,h,label,color))return;
  lcd.fillRoundRect(x,y,w,h,5,PANEL);lcd.setTextColor(color,PANEL);
  lcd.drawCentreString(portraitFit(label,w-8,2),x+w/2,y+(h-16)/2,2);
}
void portraitCard(int slot,const char* title,const String& value,const String& detail,uint16_t accent){
  int x=10+(slot%2)*155,y=105+(slot/2)*145;
  if(!widgetChanged(4,x,y,145,132,String(title)+"|"+value+"|"+detail)){
    if(cardAccents[slot]!=accent){lcd.fillRect(x+7,y+10,3,109,accent);cardAccents[slot]=accent;++sideBarDraws;}
    return;
  }
  cardAccents[slot]=accent;++cardBodyDraws;++sideBarDraws;
  lcd.fillRoundRect(x,y,145,132,7,PANEL);lcd.drawRoundRect(x,y,145,132,7,BORDER);
  lcd.fillRect(x+7,y+10,3,109,accent);
  lcd.setTextColor(MUTED,PANEL);lcd.drawString(portraitFit(title,121,2),x+16,y+9,2);
  lcd.setTextColor(INK,PANEL);lcd.drawString(portraitFit(value,121,2),x+16,y+40,2);
  // Details wrap in font 2 instead of the landscape card's small font 1.
  lcd.setTextColor(MUTED,PANEL);
  unsigned start=0;for(int r=0;r<3&&start<detail.length();++r){unsigned end=start;
    while(end<detail.length()&&lcd.textWidth(detail.substring(start,end+1),2)<=121)++end;
    if(end<detail.length()){int space=detail.lastIndexOf(' ',end);if(space>int(start))end=space;}
    if(end==start)++end;lcd.drawString(detail.substring(start,end),x+16,y+65+r*18,2);start=end;while(start<detail.length()&&detail[start]==' ')++start;
  }
}
void portraitKeyboard(){
  portraitText(setupEntry?entryLabel():"PI KEYBOARD",12,82,296,CYAN);
  String value=setupEntry?setupValues[setupField]:String("");
  if(secretEntry()&&!passwordVisible){value="";for(unsigned i=0;i<setupValues[setupField].length();++i)value+='*';}
  portraitText(value.length()>28?value.substring(value.length()-28):value,12,110,secretEntry()?222:296);
  if(setupEntry&&secretEntry())portraitButton(passwordVisible?"HIDE":"SHOW",246,105,64,27,420,101);
  for(int row=0;row<4;++row)for(size_t col=0;col<strlen(keyboardRow(keyboardMode,row));++col){
    char glyph[2]={keyboardCharacter(keyboardMode,row,col,keyboardCaps),0};
    portraitButton(glyph,10+col*30,154+row*43,27,38,36+col*45,126+row*28);
  }
  const char* modes[]={"ABC","123","SYM","SHIFT","DEL"};
  for(int i=0;i<5;++i)portraitButton(modes[i],10+i*61,333,57,35,40+i*91,238);
  const char* actions[]={"SPACE",setupEntry?"CANCEL":"TAB",setupEntry?"":"ENTER",setupEntry?(entryMode==0&&setupField==4?"SAVE":"NEXT"):"DONE"};
  for(int i=0;i<4;++i)portraitButton(actions[i],10+i*77,382,72,42,45+i*114,260);
  passwordVisible=secretEntry()?passwordVisible:false;
}
void renderPortrait(const FlightView& v,const PiSensors& observed,bool live,bool full){
  portraitHitCount=0;if(full){clearDisplay(BG);drawPageBackdrop();}
  portraitText("AI FLIGHT TEAM",12,15,230,INK,4);drawDisplayBatteryHeader();
  portraitButton("TURN",252,12,58,33,440,25);
  const char* tabs[]={"HOME","SENSE","PI","AI","SETUP"};
  for(int i=0;i<5;++i){portraitButton(tabs[i],5+i*63,440,59,34,56+i*94,292,i==page?INK:CYAN);if(i==page)lcd.drawRoundRect(5+i*63,440,59,34,5,CYAN);}
  if(setupEntry||(page==2&&keyboardVisible)){portraitKeyboard();return;}
  if(backgroundMenu){renderBackground(full);return;}
  if(xiaoLightsMenu){renderXiaoLights(full);return;}
  if(appearanceMenu){renderAppearance(full);return;}
  if(updateMenu){String notice;bool known,enabled;
    if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){notice=updateNotice;known=updatePolicyKnown;enabled=updatePolicyEnabled;xSemaphoreGive(viewMutex);}else return;
    portraitText("PI AUTOMATIC UPDATES",12,82,296,CYAN);
    portraitText(known?(enabled?"ENABLED":"DISABLED"):"POLICY NOT VERIFIED",12,119,296,AMBER);
    portraitLines("Approved home Wi-Fi, idle only. Debian security updates. No automatic reboot.",12,158,296,4);
    portraitLines("Drivers and AI artifacts need compatible reviewed releases.",12,244,296,3,MUTED);
    portraitLines(notice,12,311,296,3,AMBER);
    portraitButton(known?(enabled?"DISABLE FUTURE CHECKS":"ENABLE FUTURE CHECKS"):"WAIT FOR PI",12,376,296,29,100,250);
    portraitButton("BACK",12,411,296,24,350,250);return;}
  if(storageMenu){auto info=storageInfo();portraitText("SD STORAGE",12,83,296,CYAN,4);
    portraitLines(String(storageStateName(info.state))+" / "+String(info.capacityMiB/1024.0f,1)+" GiB",12,129,296,2,info.state==2?GREEN:AMBER);
    portraitText("Saved: "+String(info.records)+"  Dropped: "+String(info.dropped),12,177);
    portraitLines("Voice clips, logs and assets. Essential UI stays on onboard flash.",12,213,296,3,MUTED);
    portraitButton("MOUNT / RESCAN",12,297,296,41,100,230);portraitButton("SAFE UNMOUNT",12,349,296,41,350,230);
    portraitLines("No passwords or tokens on SD.",12,404,296,1,AMBER);return;}
  if(quickJoin&&configured){renderDashboardQr(full);return;}
  if(quickJoin){portraitText("PHONE QUICK CONNECT",12,80,296,CYAN);
    QRCode code;uint8_t bytes[512];String content="WIFI:T:WPA;S:"+quickWifiName+";P:"+quickWifiCode+";H:false;;";
    if(full&&qrcode_initText(&code,bytes,5,ECC_LOW,content.c_str())==0){lcd.fillRect(70,108,180,180,TFT_WHITE);
      for(int y=0;y<code.size;++y)for(int x=0;x<code.size;++x)if(qrcode_getModule(&code,x,y))lcd.fillRect(86+x*4,124+y*4,4,4,TFT_BLACK);}
    portraitText("Scan with Camera, accept Join.",12,296);portraitText("Treat QR as a password.",12,318,296,AMBER);
    portraitButton("GENERATE BLUETOOTH PIN",12,344,296,32,300,195);
    portraitText(quickBluetoothPin.length()?"PIN: "+quickBluetoothPin:"BLE client app required",12,381);
    portraitButton("HIDE QR / BACK",12,408,296,27,300,251);return;}
  if(maintenanceMenu){portraitText("OWNER MAINTENANCE",12,82,296,CYAN);
    portraitLines("Confirm aircraft is secured. Verified Pi TLS, owner login and local confirmation required.",12,118,296,5);
    portraitLines("Fresh matched disarmed controller required. Airborne blocks input.",12,223,296,3,MUTED);
    portraitLines(ownerAccessCaption(),12,290,296,3,AMBER);
    portraitButton(maintenanceAccepted?"LOCK OWNER ACCESS":"UNLOCK OWNER ACCESS",12,365,296,31,100,239);portraitButton("BACK",12,404,296,29,350,239);return;}
  if(powerMenu){portraitText("POWER / SAFE SLEEP",12,82,296,CYAN);
    portraitLines("1. Tap PREPARE SLEEP. 2. Release BOOT, hold for 3 seconds. 3. Release BOOT to sleep.",12,118,296,5);
    portraitLines(!powerGate.active?"LOCKED: prepare first":!powerGate.released?"Release BOOT first":powerGate.confirmed?"Confirmed. RELEASE BOOT":powerGate.holding?"Keep holding BOOT (3 seconds)":"Prepared: hold BOOT now",12,222,296,3,AMBER);
    portraitButton("PREPARE SLEEP",12,289,145,39,100,217);portraitButton("CANCEL",165,289,143,39,350,217);
    portraitButton(audioMuted()?"SOUND: MUTED":"SOUND: ON",12,343,145,34,100,249);portraitButton("TEST CHIME",165,343,143,34,350,249);
    portraitText(displayBatteryLabel(),12,389,296,CYAN,1);portraitLines("400 mAh. Runtime / charging state unmeasured.",12,408,296,2,MUTED);return;}
  if(page<2){portraitText(live?"LIVE TELEMETRY":v.link,12,77,202,live?GREEN:AMBER);portraitButton(page==1?"PI INFO":"DETAILS",220,75,88,25,400,65);
    if(page==0){uint16_t bars[4];overviewBarColors(v,live,bars);portraitCard(0,"FLIGHT STATUS",live&&v.armedKnown?(v.armed?"ARMED":"DISARMED"):"UNKNOWN",live?v.mode:"Waiting for heartbeat",bars[0]);
      portraitCard(1,"BATTERY",valueText(live?v.voltage:NAN," V"),"Voltage / bar = data link quality",bars[1]);
      portraitCard(2,"DRONE GPS",live&&v.satellites>=0?String(v.satellites):"--",droneGpsDetail(v,live),bars[2]);
      portraitCard(3,"SPEED",valueText(live?v.speed:NAN," m/s"),"GPS can drift at rest",bars[3]);
    }else{portraitCard(0,"CORVON 743 V2 (config)",live?"LIVE":"NO DATA",v.sourceMismatch?"Source mismatch: UART0 / UART4":live?"Heartbeat: Pi UART0 / FC UART4":"No heartbeat: Pi UART0 / FC UART4",live?GREEN:AMBER);
      const char* labels[]={"C1 360 lidar / Pi UART2","8x8 matrix / Pi UART7","Camera / Pi USB"};for(int i=0;i<3;++i){bool fresh=piSensorFresh(observed,i,millis());
        portraitCard(i+1,labels[i],fresh?"LIVE DATA":"UNVERIFIED",fresh?"Fresh measurement":observed.node[i]&&uint32_t(millis()-observed.received)<6000?"Port present / no fresh data":"No verified data",fresh?GREEN:AMBER);}}
    portraitLines(page==0?(phoneTargetLabel()):"Missing data never means clear space.",12,403,296,2,page==0&&phoneTargetAvailable()?GREEN:MUTED);return;}
  if(page==2){portraitText("PI ON YOUR PHONE",12,82,296,CYAN);
    portraitButton("PHONE QUICK CONNECT",12,133,296,75,200,160);
    portraitLines("Scan the private QR for desktop, files and Wi-Fi setup.",12,230,296,3);
    portraitButton("PI UPDATE SETTINGS",12,310,296,43,100,250);
    portraitButton("WIRED DESKTOP",12,374,296,43,340,250);return;}
  if(page==3){portraitText("CHAT WITH YOUR TEAM",12,82,296,CYAN);String answer,state;
    aiView(answer,state);
    portraitLines(state,12,112,296,2,AMBER);unsigned offset=min(aiOffset,unsigned(answer.length()));
    portraitLines(answer.substring(offset),12,161,296,9);portraitRoute(12,156,296,182,50,150);
    const char* labels[]={"STATUS","SENSORS","LEARNING","TYPE"};for(int i=0;i<4;++i)portraitButton(labels[i],12+(i%2)*153,351+(i/2)*39,143,33,45+i*114,220);
    portraitText("Tap response for next",12,424,296,MUTED,1);return;}
  if(securityMenu){portraitText("WIRELESS SECURITY",12,82,296,CYAN);
    const char* labels[]={"PHONE QUICK CONNECT / QR","CUSTOM WI-FI HOTSPOT","BLUETOOTH PIN / PAIR 60s","STOP HOTSPOT & BLUETOOTH"};
    for(int i=0;i<4;++i)portraitButton(labels[i],12,119+i*53,296,43,100,128+i*31);
    portraitLines(securityNotice,12,340,296,3,AMBER);portraitLines("Sharing off after reboot. No flight commands.",12,400,296,2,MUTED);return;}
  portraitButton("LIGHTS & APPEARANCE",12,78,296,29,100,88);
  portraitButton(configured?"EDIT / SAVE & RESTART":"CONNECT TO ORANGE PI",12,113,296,37,200,129);
  portraitText("Wi-Fi: "+(ssid.length()?ssid:String("Not configured")),12,161);
  portraitText("Pi: "+(endpoint.length()?endpoint:String("Not configured")),12,186);
  portraitButton("PI UPDATE SETTINGS",12,210,296,24,285,88);
  portraitButton("SD STORAGE",12,239,296,34,400,88);
  portraitButton(String("Touch: ")+(touchThreshold==350?"LIGHT":touchThreshold==600?"BALANCED":"FIRM"),12,283,296,34,100,195);
  portraitButton("DIM",12,327,90,36,80,222);portraitButton("BRIGHT",110,327,92,36,200,222);portraitButton("CALIBRATE",210,327,98,36,350,222);
  portraitButton("POWER MENU",12,378,145,42,100,257);portraitButton("WIRELESS",165,378,143,42,350,257);
}
