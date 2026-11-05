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
    portraitButton("BACKGROUND EFFECTS",12,78,296,29,380,88);
    for(int i=0;i<7;++i){
      if(i==4||i==6){const int xs[]={12,64,108,216,260},ws[]={48,40,104,40,48},hits[]={40,135,240,340,430};const String values[]={"-10","-1",labels[i],"+1","+10"};for(int k=0;k<5;++k)portraitButton(values[k],xs[k],112+i*39,ws[k],34,hits[k],121+i*19);}
      else portraitButton(labels[i],12,112+i*39,296,34,100,121+i*19);
    }
    portraitText("Speed 1 slow | 80 fast | 100 steady",12,389,296,MUTED,1);
    portraitButton(lightMode==5?"LIGHT OFF":"FLASHLIGHT",12,401,143,31,100,257);
    portraitButton("BACK",165,401,143,31,350,257);
  }else if(full){
    text("LIGHTS & APPEARANCE",18,80,CYAN,2);lcd.fillRoundRect(300,78,164,28,4,PANEL);text("BACKGROUNDS",336,88,CYAN,1);
    for(int i=0;i<7;++i){
      if(i==4||i==6){const int xs[]={16,88,152,328,392},ws[]={68,60,172,60,72};const String values[]={"-10","-1",labels[i],"+1","+10"};for(int k=0;k<5;++k){lcd.fillRoundRect(xs[k],112+i*19,ws[k],18,4,PANEL);text(values[k],xs[k]+7,114+i*19,CYAN,1);}}
      else{lcd.fillRoundRect(16,112+i*19,448,18,4,PANEL);text(labels[i],27,113+i*19,CYAN,2);}
    }
    lcd.fillRoundRect(16,247,220,27,5,PANEL);lcd.fillRoundRect(245,247,219,27,5,PANEL);
    text(lightMode==5?"LIGHT OFF":"FLASHLIGHT",55,253,CYAN,1);text("BACK",330,253,CYAN,1);
  }
}

void drawBackgroundArea(int x,int y,int w,int h,uint32_t frame);
void serviceAppearance(){
  static uint32_t ledAt=0,matrixAt=0;uint32_t now=millis();
  lightDriveConfig=sleepPending?0:uint32_t(lightMode)|(uint32_t(lightColor)<<3)|(uint32_t(lightBrightness)<<7)|(uint32_t(beaconPattern)<<15)|(uint32_t(lightSpeed)<<17);
  if(!lightTimer&&uint32_t(now-ledAt)>=5){ledAt=now;driveRearLight(nullptr);}
  (void)matrixAt; // Background animation disabled to prioritize touch and telemetry.
}

uint16_t backgroundInk(){return appearanceColor565(backgroundColor);}
void drawBackgroundArea(int x,int y,int w,int h,uint32_t frame){
  uint16_t ink=backgroundInk();
  if(backgroundEffect==1){
    int rows=h/10,cols=max(1,w/10);if(rows<2)return;
    for(int col=0;col<cols;++col){int step=(frame+col*7)%rows,old=(step+rows-4)%rows;
      lcd.fillRect(x+col*10,y+old*10,6,9,BG);lcd.setTextColor(ink,BG);
      lcd.drawChar((frame+col)%3==0?'0':(frame+col)%3==1?'1':'X',x+col*10,y+step*10,1);}
  }else if(backgroundEffect==2){
    int stars=max(3,w/12);
    for(int i=0;i<stars;++i){int px=(i*37+3)%w;int old=(int((frame-1)%uint32_t(h))*2+i*19)%h,py=(int(frame%uint32_t(h))*2+i*19)%h;
      lcd.drawPixel(x+px,y+old,BG);lcd.drawPixel(x+px,y+py,ink);
      if(w>10&&px+1<w){lcd.drawPixel(x+px+1,y+old,BG);lcd.drawPixel(x+px+1,y+py,ink);}}
  }else if(backgroundEffect==3){
    // Three moving traces; erase only their previous pixels.
    for(int i=0;i<w;++i)for(int lane=0;lane<3;++lane){int old=(i*3+int((frame-1)%uint32_t(2*h-2))*3+lane*h/3)%(2*h-2);int py=(i*3+int(frame%uint32_t(2*h-2))*3+lane*h/3)%(2*h-2);
      if(old>=h)old=2*h-2-old;if(py>=h)py=2*h-2-py;lcd.drawPixel(x+i,y+old,BG);lcd.drawPixel(x+i,y+py,ink);}
  }
}
void renderBackground(bool full){

  String effect="ANIMATION OFF / PERFORMANCE",color=String("INK: ")+appearanceColorName(backgroundColor);
  String follow=backgroundFollowsTheme?"FOLLOW THEME: ON":"FOLLOW THEME: OFF";
  if(portrait()){
    portraitText("STATIC BACKGROUND",12,82,296,CYAN);
    if(full){lcd.fillRoundRect(12,112,296,145,7,BG);lcd.drawRoundRect(12,112,296,145,7,BORDER);}
    portraitButton(effect,12,273,296,39,100,200);
    portraitButton(color,12,323,296,39,350,200);
    portraitButton(follow,12,370,296,29,350,230);
    portraitButton("BACK",12,410,296,25,350,257);
  }else if(full){
    text("STATIC BACKGROUND / PERFORMANCE",18,80,CYAN,2);lcd.drawRoundRect(16,112,448,67,6,BORDER);
    lcd.fillRoundRect(16,184,220,32,5,PANEL);lcd.fillRoundRect(245,184,219,32,5,PANEL);
    text(effect,25,194,CYAN,1);text(color,258,194,CYAN,1);
    lcd.fillRoundRect(16,220,448,23,4,PANEL);text(follow,145,226,CYAN,1);
    lcd.fillRoundRect(16,247,448,27,5,PANEL);text("BACK",220,254,CYAN,1);
  }
}
