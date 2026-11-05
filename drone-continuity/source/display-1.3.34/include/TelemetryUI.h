#pragma once
#include "TelemetryLayout.h"
String telemetryValue(int index){
  DisplayMetric value,heartbeat;uint32_t received=0;
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))!=pdTRUE)return String("UPDATING");
  value=displayTelemetry.fields[index];heartbeat=displayTelemetry.fields[0];received=displayTelemetry.received;xSemaphoreGive(viewMutex);
  bool link=METRICS[index].pi||index==0||(metricFresh(heartbeat,received,millis(),3000)&&heartbeat.number==1);
  return link&&metricFresh(value,received,millis(),METRICS[index].ttl)?String(value.text):String("UNAVAILABLE");
}
void drawTelemetryDetails(bool full){
  bool tall=portrait();
  if(tall){portraitHitCount=0;if(full)clearDisplay(BG);portraitText("AI FLIGHT TEAM",12,15,230,INK,4);
    portraitButton("TURN",252,12,58,33,440,25);const char* names[]={"HOME","SENSE","PI","AI","SETUP"};
    for(int i=0;i<5;++i)portraitButton(names[i],5+i*63,440,59,34,56+i*94,292,i==page?INK:CYAN);
  }else if(full)frame();
  drawDisplayBatteryHeader();
  const char* names[]={"FLIGHT DETAILS","POSITION / POWER","POWER / GPS","RADIO / PI LOAD","ORANGE PI SYSTEM","PI SENSOR STATUS","FAULTS 1 / 3","FAULTS 2 / 3","FAULTS 3 / 3","RC CHANNELS (RAW)","RANGEFINDERS (OBSERVED)","PI FAILED SERVICES 1 / 2","PI FAILED SERVICES 2 / 2","POWER MEASUREMENTS"};
  int width=tall?296:448;portraitText(names[telemetryPage],tall?12:16,80,width,CYAN,2);
  auto row=[&](int line,const String& label,const String& value,uint16_t color=INK){int y=telemetryRowY(tall,line);
    portraitText(label,tall?12:16,y,tall?165:219,MUTED,2);portraitText(value,tall?180:245,y,tall?128:219,color,2);};
  if(telemetryPage<5){int start=telemetryPage*8;for(int i=0;i<8&&start+i<int(METRIC_COUNT);++i)row(i,METRICS[start+i].label,telemetryValue(start+i));}
  else if(telemetryPage==5){const char* labels[]={"360 LIDAR","8x8 MATRIX","USB CAMERA"};
    for(int i=0;i<3;++i){bool fresh=false,node=false;uint32_t age=0;char state[28]={};
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){uint32_t elapsed=uint32_t(millis()-displayTelemetry.received);fresh=displayTelemetry.sensorFresh[i]&&elapsed<=3000&&displayTelemetry.sensorAge[i]<=3000-elapsed;node=elapsed<=6000&&displayTelemetry.sensorNode[i];age=displayTelemetry.sensorAge[i]+elapsed;strlcpy(state,elapsed<=6000?displayTelemetry.sensorState[i]:"PI OFFLINE / STALE",sizeof(state));xSemaphoreGive(viewMutex);}
      row(i*2,labels[i],fresh?"FRESH DATA":node?"PORT / NO DATA":"UNAVAILABLE",fresh?GREEN:AMBER);row(i*2+1,fresh?"Observation age":"Reported state",fresh?String(age)+" ms":String(state),MUTED);
    }
    row(6,"Phone GPS target",phoneTargetAvailable()?"AVAILABLE":"UNAVAILABLE",phoneTargetAvailable()?GREEN:AMBER);
    row(7,"Authority","ADVISORY ONLY",AMBER);
  }else if(telemetryPage==13){
    for(int i=0;i<7;++i)row(i,METRICS[40+i].label,telemetryValue(40+i));
    row(7,"Pi V/A sensors","NOT IDENTIFIED",AMBER);
  }else if(telemetryPage<9){
    // Copy both reports coherently. Sample time AFTER taking the lock: a new
    // receipt arriving during header drawing must not underflow elapsed time.
    uint8_t start=(telemetryPage-6)*2;char reports[2][121]={{0}};bool reportFresh=false,read=false;
    if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(2))==pdTRUE){
      read=true;reportFresh=uint32_t(millis()-displayTelemetry.received)<=15000;
      for(int i=0;i<2;++i)if(reportFresh&&start+i<displayTelemetry.faultCount)strlcpy(reports[i],displayTelemetry.faults[start+i],sizeof(reports[i]));
      xSemaphoreGive(viewMutex);
    }
    if(read)for(int i=0;i<2;++i){
      const char* content=reports[i][0]?reports[i]:i==0?(reportFresh?"No recent reports on this page. Not proof of hardware health.":"Fault report unavailable: Pi data is stale."):"";
      drawFaultLines(content,tall?12:16,(tall?124:105)+i*(tall?130:65),width,tall?6:3,AMBER);
    }
  }else if(telemetryPage==9){for(int i=0;i<18;++i){uint16_t raw=0;bool fresh=false;
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){uint32_t elapsed=uint32_t(millis()-displayTelemetry.received);fresh=displayTelemetry.rcFresh[i]&&elapsed<=2000&&displayTelemetry.rcAge[i]<=2000-elapsed;raw=displayTelemetry.rc[i];xSemaphoreGive(viewMutex);}
      int x=(tall?12:16)+(i%2)*(tall?154:230),y=(tall?120:99)+(i/2)*(tall?29:16);
      portraitText(String("CH")+String(i+1)+": "+(fresh?String(raw)+" us":String("--")),x,y,tall?145:220,fresh?INK:MUTED,2);}
  }else if(telemetryPage==10){for(int i=0;i<8;++i){DisplayTelemetry::Range range;uint32_t received=0;bool exists=false;
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){exists=i<displayTelemetry.rangeCount;if(exists)range=displayTelemetry.ranges[i];received=displayTelemetry.received;xSemaphoreGive(viewMutex);}
      bool fresh=exists&&range.fresh&&uint32_t(millis()-received)<=2000&&range.age<=2000-uint32_t(millis()-received);
      row(i,exists?String("Range ")+range.id+" / ori "+range.orientation:String("Range ")+String(i+1),fresh?String(range.cm,1)+" cm":"UNAVAILABLE",fresh?INK:MUTED);}}
  else{bool check=false;uint8_t count=0;
    if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){uint32_t elapsed=uint32_t(millis()-displayTelemetry.received);check=displayTelemetry.serviceCheckFresh&&elapsed<=6000&&displayTelemetry.serviceAge+elapsed<=15000;count=displayTelemetry.unitCount;xSemaphoreGive(viewMutex);}
    if(widgetChanged(8,0,0,1,1,String(check)+"|"+count)){
      lcd.fillRect(tall?12:16,tall?110:99,width,tall?260:127,BG);widgetCache.resetKind(2);
    }
    if(!check)portraitLines("Current service check unavailable. No healthy state is inferred.",tall?12:16,tall?130:110,width,4,AMBER);
    else if(!count)portraitLines("No failed services in the current bounded inventory. This is not a full hardware health test.",tall?12:16,tall?130:110,width,4,MUTED);
    else for(int i=0;i<4;++i){int index=(telemetryPage-11)*4+i;char unit[65]={};if(index<count&&xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){strlcpy(unit,displayTelemetry.failedUnits[index],sizeof(unit));xSemaphoreGive(viewMutex);}
      portraitLines(unit,tall?12:16,(tall?121:100)+i*(tall?63:31),width,2,AMBER);}
  }
  FlightView v=snapshot();if(tall||telemetryPage!=9)portraitText(v.link,tall?12:16,tall?380:230,width,v.connected?GREEN:AMBER,1);
  if(tall){portraitButton("PREV",12,403,94,30,80,255);portraitButton("NEXT",113,403,94,30,230,255);portraitButton("BACK",214,403,94,30,390,255);}
  else if(full){lcd.fillRoundRect(16,246,144,25,4,PANEL);lcd.fillRoundRect(168,246,144,25,4,PANEL);lcd.fillRoundRect(320,246,144,25,4,PANEL);
    text("PREV",65,251,CYAN,2);text("NEXT",218,251,CYAN,2);text("BACK",370,251,CYAN,2);}
}
