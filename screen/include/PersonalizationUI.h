#pragma once
void renderDashboardQr(bool full){
  auto code=codeSnapshot();bool ready=remoteReady&&code.fresh(millis());
  const int x=portrait()?70:16,y=portrait()?108:82;
  String identity=ready?String(code.url):String(remoteReady?"loading":"offline");
  // Repaint only this square when the code changes, never on telemetry ticks.
  if(widgetChanged(21,x,y,180,180,identity)){
    lcd.fillRect(x,y,180,180,TFT_WHITE);
    if(ready){QRCode qr;uint8_t bytes[512];
      if(qrcode_initText(&qr,bytes,5,ECC_LOW,code.url)==0){
        for(int row=0;row<qr.size;++row)for(int col=0;col<qr.size;++col)
          if(qrcode_getModule(&qr,col,row))lcd.fillRect(x+16+col*4,y+16+row*4,4,4,TFT_BLACK);
      }else {lcd.fillRect(x,y,180,180,BG);text("QR unavailable",x+8,y+75,AMBER,2);}
    }else {lcd.fillRect(x,y,180,180,BG);text(remoteReady?"Getting fresh QR":"Connect to Pi",x+8,y+75,AMBER,2);}
  }
  if(portrait()){
    portraitText("PRIVATE DASHBOARD",12,80,296,CYAN);
    portraitText("1. Phone on same network as Pi",12,298,296,INK,2);
    portraitText("2. Scan QR with iPhone Camera",12,321,296,INK,2);
    portraitText("Single use / expires in 2 minutes",12,345,296,MUTED,1);
    portraitButton("NEW QR",12,369,296,31,300,195);
    portraitButton("HIDE / BACK",12,408,296,27,300,251);
  }else if(full){
    text("PRIVATE DASHBOARD",18,60,CYAN,2);
    text("Phone on Pi's network",210,85,INK,2);
    text("Scan with iPhone Camera",210,111,INK,2);
    text("Opens your private dashboard",210,140,MUTED,1);
    text("One use / expires in 2 minutes",210,159,AMBER,1);
    lcd.fillRoundRect(218,182,246,32,5,PANEL);text("NEW QR",300,191,CYAN,2);
    text("Keep the QR private",218,223,MUTED,1);
    lcd.fillRoundRect(218,244,246,25,5,PANEL);text("HIDE / BACK",283,250,CYAN,1);
  }
}

void renderAppearance(bool full){
  const char* themes[]={"CLASSIC DARK","ARCTIC","OCEAN","MATRIX LIVE"};
  const char* modes[]={"OFF","SOLID","BREATHE","RAINBOW","BEACON","FLASHLIGHT"};
  const char* colors[]={"WHITE","RED","GREEN","BLUE","CYAN","MAGENTA","AMBER","ORANGE","YELLOW","INDIGO","VIOLET"};
  const char* beacons[]={"SINGLE COLOR","RAINBOW STEPS","WARM / COOL","COLOR / WHITE"};
  String labels[]={String("THEME: ")+themes[uiTheme],String("THEME INK: ")+appearanceColorName(themeColors[uiTheme]),String("REAR LED: ")+modes[lightMode],String("LED COLOR: ")+colors[lightColor],String("LED ")+((int(lightBrightness)*100+127)/255)+"%",String("BEACON: ")+beacons[beaconPattern],lightSpeed==100?String("100 / ON"):String("SPEED ")+lightSpeed};
  if(portrait()){
    portraitButton("XIAO LIGHTS",12,78,140,29,215,88);portraitButton("BACKGROUNDS",158,78,150,29,380,88);
    for(int i=0;i<7;++i){
      if(i==4||i==6){const int xs[]={12,64,108,216,260},ws[]={48,40,104,40,48},hits[]={40,135,240,340,430};const String values[]={"-10","-1",labels[i],"+1","+10"};for(int k=0;k<5;++k)portraitButton(values[k],xs[k],112+i*39,ws[k],34,hits[k],121+i*19);}
      else portraitButton(labels[i],12,112+i*39,296,34,100,121+i*19);
    }
    portraitText("Speed 1 slow | 80 fast | 100 steady",12,389,296,MUTED,1);
    portraitButton(lightMode==5?"LIGHT OFF":"FLASHLIGHT",12,401,143,31,100,257);
    portraitButton("BACK",165,401,143,31,350,257);
  }else if(full){
    text("SCREEN LIGHTS",18,86,CYAN,1);lcd.fillRoundRect(145,78,149,28,4,PANEL);text("XIAO LIGHTS",163,88,CYAN,1);lcd.fillRoundRect(300,78,164,28,4,PANEL);text("BACKGROUNDS",336,88,CYAN,1);
    for(int i=0;i<7;++i){
      if(i==4||i==6){const int xs[]={16,88,152,328,392},ws[]={68,60,172,60,72};const String values[]={"-10","-1",labels[i],"+1","+10"};for(int k=0;k<5;++k){lcd.fillRoundRect(xs[k],112+i*19,ws[k],18,4,PANEL);text(values[k],xs[k]+7,114+i*19,CYAN,1);}}
      else{lcd.fillRoundRect(16,112+i*19,448,18,4,PANEL);text(labels[i],27,113+i*19,CYAN,2);}
    }
    lcd.fillRoundRect(16,247,220,27,5,PANEL);lcd.fillRoundRect(245,247,219,27,5,PANEL);
    text(lightMode==5?"LIGHT OFF":"FLASHLIGHT",55,253,CYAN,1);text("BACK",330,253,CYAN,1);
  }
}

void renderXiaoLights(bool full){
  if(!full&&!portrait())return;
  const bool ready=xiaoLights.ready();const auto& c=xiaoLights.confirmed;
  const char* modes[]={"Off","Solid","Breathe","Rainbow","Beacon","Flashlight"};
  const char* colors[]={"White","Red","Green","Blue","Cyan","Magenta","Amber","Orange","Yellow","Indigo","Violet"};
  const char* patterns[]={"Single color","Rainbow steps","Warm / cool","Color / white"};
  const char* yellow[]={"Off","On","Follow RGB","Blink"};
  String labels[]={String("RGB  ")+modes[c.mode],String("Color  ")+colors[c.color],String("Brightness  ")+((int(c.brightness)*100+127)/255)+"%",
      String("Beacon  ")+patterns[c.pattern],(c.mode==3&&c.speed==100)?String("100 fastest"):String("Speed  ")+c.speed,String("Yellow LED  ")+yellow[c.yellow]};
  const String title=ready?"XIAO RP2350 lights":"XIAO lights  |  Disconnected";
  if(portrait())portraitText(title,12,80,296,ready?CYAN:MUTED,2);else text(title,18,82,ready?CYAN:MUTED,2);
    if(portrait())portraitText(xiaoLights.applyNote(),12,99,296,AMBER,1);
    else text(xiaoLights.applyNote(),18,101,AMBER,1);
  for(int r=0;r<6;r++){
    int y=110+22*r;bool adjust=r==2||r==4;
    const char* step[]={"-10","-1","","+1","+10"};
    const int px[]={12,64,108,216,260},pw[]={48,40,104,40,48},hit[]={40,135,240,340,430};
    for(int k=0;k<(adjust?5:1);k++){
      String label=ready?(adjust&&k!=2?String(step[k]):labels[r]):(adjust&&k!=2?String(step[k]):String("--"));
      if(portrait())portraitButton(label,adjust?px[k]:12,112+r*45,adjust?pw[k]:296,39,adjust?hit[k]:100,y+10,ready?CYAN:MUTED);
      else {const int xs[]={16,84,148,325,392},ws[]={62,58,171,61,72};int x=adjust?xs[k]:16;
        lcd.fillRoundRect(x,y,adjust?ws[k]:448,20,4,PANEL);text(label,x+6,y+2,ready?CYAN:MUTED,1);}
    }
  }
  if(portrait())portraitButton("BACK",12,400,296,32,200,256);
  else{lcd.fillRoundRect(16,247,448,27,4,PANEL);text("BACK",211,253,CYAN,1);}
}

uint16_t backgroundInk(){
  return appearanceColor565(effectiveBackgroundColor(backgroundFollowsTheme,themeColors[uiTheme],backgroundColor));
}

bool backgroundAllowed(){
  return !wiredViewer.active()&&!desktopActive&&!wiredPriorityCard&&!calibrating&&!powerMenu&&!sleepPending&&
         !quickJoin&&!securityMenu&&!setupEntry&&!keyboardVisible&&!maintenanceMenu&&telemetryPage<0;
}

void drawPageBackdrop(){
  if(!backgroundAllowed()||backgroundEffect==backdrop::Plain)return;
  const int width=lcd.width(),top=portrait()?74:75,bottom=portrait()?434:274;
  backdrop::motif(lcd,8,top,width-16,bottom-top,backgroundEffect,backgroundInk());
}

void serviceAppearance(){
  static uint32_t ledAt=0,animationAt=0;
  uint32_t now=millis();
  lightDriveConfig=sleepPending?0:uint32_t(lightMode)|(uint32_t(lightColor)<<3)|(uint32_t(lightBrightness)<<7)|(uint32_t(beaconPattern)<<15)|(uint32_t(lightSpeed)<<17);
  if(!lightTimer&&uint32_t(now-ledAt)>=5){ledAt=now;driveRearLight(nullptr);}
  if(!backdrop::animated(backgroundEffect)||!backgroundAllowed()||brightness==0||dirty||
     digitalRead(36)==LOW||touchGesture.active||uint32_t(now-animationAt)<175)return;
  animationAt=now;
  const uint32_t oldPhase=matrixFrames++;
  const uint16_t moving=backdrop::tint(backgroundInk(),10);
  const int top=79,bottom=portrait()?430:272;
  auto update=[&](int x,int y,int w,int h){
    backdrop::markers(lcd,x,y,w,h,backgroundEffect,BG,oldPhase);
    backdrop::markers(lcd,x,y,w,h,backgroundEffect,moving,matrixFrames);
  };
  lcd.startWrite();
  update(1,top,5,bottom-top);update(lcd.width()-6,top,5,bottom-top);
  if(backgroundMenu){
    if(portrait())update(18,119,284,130);
    else update(21,116,438,58);
  }
  lcd.endWrite();
}

void renderBackground(bool full){
  const String effect=String("Style: ")+backdrop::name(backgroundEffect);
  uint8_t selected=effectiveBackgroundColor(backgroundFollowsTheme,themeColors[uiTheme],backgroundColor);
  String color=String("Ink: ")+appearanceColorName(selected);
  String follow=backgroundFollowsTheme?"Use theme color: on":"Use theme color: off";
  const char* heading=backdrop::animated(backgroundEffect)?"ANIMATED BACKGROUND":"STATIC BACKGROUND";
  if(portrait()){
    portraitText(heading,12,82,296,CYAN);
    if(full){
      lcd.fillRoundRect(12,112,296,145,7,BG);lcd.drawRoundRect(12,112,296,145,7,BORDER);
      if(backdrop::animated(backgroundEffect))backdrop::markers(lcd,18,119,284,130,backgroundEffect,backdrop::tint(backgroundInk(),10),matrixFrames);
      else backdrop::motif(lcd,18,119,284,130,backgroundEffect,backgroundInk());
    }
    portraitButton(effect,12,273,296,39,100,200);portraitButton(color,12,323,296,39,350,200);
    portraitButton(follow,12,370,296,29,350,230);portraitButton("BACK",12,410,296,25,350,257);
  }else if(full){
    text(heading,18,80,CYAN,2);lcd.fillRect(16,112,448,67,BG);lcd.drawRoundRect(16,112,448,67,6,BORDER);
    if(backdrop::animated(backgroundEffect))backdrop::markers(lcd,21,116,438,58,backgroundEffect,backdrop::tint(backgroundInk(),10),matrixFrames);
    else backdrop::motif(lcd,21,116,438,58,backgroundEffect,backgroundInk());
    lcd.fillRoundRect(16,184,220,32,5,PANEL);lcd.fillRoundRect(245,184,219,32,5,PANEL);
    text(effect,25,194,CYAN,2);text(color,258,194,CYAN,2);
    lcd.fillRoundRect(16,220,448,23,4,PANEL);text(follow,145,226,CYAN,1);
    lcd.fillRoundRect(16,247,448,27,5,PANEL);text("BACK",220,254,CYAN,1);
  }
}
