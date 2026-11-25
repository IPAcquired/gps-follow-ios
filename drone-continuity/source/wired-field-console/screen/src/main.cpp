#include <Arduino.h>
#include <TFT_eSPI.h>
#include "AutoWired.h"
#include "XiaoLights.h"
#include <esp_system.h>
#include <mbedtls/platform_util.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <mbedtls/md.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <mbedtls/x509_crt.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <esp_sleep.h>
#include <esp_heap_caps.h>
#include <esp_timer.h>
#include <driver/rtc_io.h>
#include <driver/gpio.h>
#include <time.h>
#include <qrcode.h>
#include "Truth.h"
#include "DisplayBattery.h"
#include "PowerGate.h"
#include "TouchCalibration.h"
#include "Wireless.h"
#include "ConnectionTrial.h"
#include "Audio.h"
#include "MaintenanceGate.h"
#include "OwnerLease.h"
#include "DesktopGeometry.h"
#include "DesktopControls.h"
#include "Gesture.h"
#include "WirelessPolicy.h"
#include "KeyboardLayout.h"
#include "Storage.h"
#include "DisplayOrientation.h"
#include "TimeBootstrapPolicy.h"
#include "SessionPolicy.h"
#include "DisplayTelemetry.h"
#include "PinnedPiClient.h"
#include <atomic>
#include "TlsMemoryRecovery.h"
std::atomic<bool> tlsRecoveryRequested{false};
TlsMemoryRecovery tlsMemoryRecovery;
#include "TelemetryLayout.h"
#include "LinkFaultPolicy.h"
#include "StatusBar.h"
#include "AppearancePalette.h"
#include "BackgroundStyles.h"

WiredLocalProfile displayLocalProfile;
static std::atomic<bool> identitiesReady{false};
bool localProfileReady(){return identitiesReady.load(std::memory_order_acquire);}
picturestore::Shared picturestore::shared;
TFT_eSPI lcd;
AutoWired wiredViewer;
XiaoLights xiaoLights;
bool xiaoLightsMenu=false;
wirednotice::Tracker wiredNotices;
portMUX_TYPE wiredNoticeLock=portMUX_INITIALIZER_UNLOCKED;
bool wiredPriorityCard=false,wiredCardWaitRelease=false;
uint32_t wiredLastInteraction=0;
bool wiredSafetyPause();
const char* wiredGuardReason();
bool wiredPriorityActive();
wirednotice::Notice wiredNoticeNow();
void paintWiredPriorityCard(const wirednotice::Notice&);
void startWiredViewer();
void finishWiredViewer();
Preferences prefs;
ConnectionTrial wifiTrial;
SavedConnection trialProfile{};
std::atomic<bool> trialLoginConfirmed{false};
SemaphoreHandle_t viewMutex;
FlightView current;
struct PiSensors {uint32_t received=0;uint32_t age[3]={};bool fresh[3]={};bool node[3]={};};
PiSensors piSensors;
DisplayTelemetry displayTelemetry;bool compactTelemetryEnabled=false;int telemetryPage=-1;
void drawTelemetryDetails(bool full);
bool piSensorFresh(const PiSensors& value,int i,uint32_t now){uint32_t elapsed=uint32_t(now-value.received);return value.fresh[i]&&elapsed<=3000&&value.age[i]<=3000-elapsed;}
uint8_t screenRotation=1;
auto& portraitHits=picturestore::shared.menus.hits;uint8_t portraitHitCount=0;
bool portrait(){return (screenRotation&1)==0;}
void renderPortrait(const FlightView&,const PiSensors&,bool,bool);
void updateOrientationTouch();
void rotateDisplay();
void navigateTo(int target);
#include "AiUiState.h"
AiUiState aiUi;
String aiAnswer="Choose STATUS, SENSORS, LEARNING, or TYPE. AI replies are advisory; connection alone does not verify model health.";
String aiState="";
void aiView(String& answer,String& state);
uint32_t aiRevision=0;unsigned aiOffset=0;
struct ChatRequest{char message[129];};
QueueHandle_t chatQueue=nullptr;
String ssid, wifiPass, endpoint, username, password, session;
String piTrust;
char timeDeviceId[33]={};uint8_t timeKey[32]={};bool timeKeyPresent=false,savedConnection=false;
bool bootstrapPiTime();
bool authBlocked = false, configured = false;
SessionPolicy sessionPolicy;
struct PiLinkDiagnostics {uint32_t identityAt=0,flightPolls=0,statusPolls=0,telemetryPolls=0,lastDuration=0,tlsHeap=0,tlsLargest=0;int lastCode=0,tlsError=0;char error[40]="not_connected";} piLink;
void apiDiagnostic(int code,const char* category){if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){piLink.lastCode=code;strlcpy(piLink.error,category,sizeof(piLink.error));xSemaphoreGive(viewMutex);}}
volatile bool applyConfig = false;
uint8_t page = 0, brightness = 210;
uint32_t redrawAt = 0, lastTouch = 0;
uint32_t framesDrawn = 0, screenClears = 0, faultRenderMaxUs=0, faultRowDraws=0;
String lastScene;
#include "WidgetCache.h"
auto& widgetCache=picturestore::shared.menus.widgets;
void clearDisplay(uint16_t color){++screenClears;lcd.fillScreen(color);}
bool dirty = true, touchReady = false;
bool powerMenu=false, sleepPending=false;
PowerGate powerGate;
BootMenuGesture bootMenuGesture;
TaskHandle_t networkHandle=nullptr;
volatile bool networkParked=false;
uint32_t sleepRequestedAt=0;
String renderSignature, cardSignatures[4];
uint16_t cardAccents[4]={};uint32_t cardBodyDraws=0,sideBarDraws=0;
constexpr const char* VERSION="flight-team-display-1.3.34-wired-paired-r3.2";
Gesture touchGesture;
uint32_t tapsSeen=0,swipesSeen=0;
volatile bool quickJoin=false;
#include "QuickConnect.h"
#include "LightPattern.h"
DashboardCode dashboardCode;
uint32_t dashboardRequest=1;
bool appearanceMenu=false,backgroundMenu=false;
uint8_t backgroundEffect=0,backgroundColor=0;
constexpr uint8_t BACKGROUND_COLOR_COUNT=APPEARANCE_COLOR_COUNT;
uint8_t themeColors[4]={6,1,5,0};bool backgroundFollowsTheme=true;
uint8_t beaconPattern=0;
uint8_t lightSpeed=29;
std::atomic<uint32_t> lightDriveConfig{0};
esp_timer_handle_t lightTimer=nullptr;
void driveRearLight(void*){uint32_t c=lightDriveConfig.load();RgbLight rgb=lightPattern(c&7,(c>>3)&15,(c>>7)&255,millis(),(c>>15)&3,(c>>17)&127);ledcWrite(2,255-rgb.r);ledcWrite(3,255-rgb.g);ledcWrite(4,255-rgb.b);}
uint8_t uiTheme=0,lightMode=0,lightColor=0,lightBrightness=64;
uint32_t matrixFrames=0;
void renderDashboardQr(bool full);
void renderAppearance(bool full);
void renderXiaoLights(bool full);
void renderBackground(bool full);
void drawPageBackdrop();
void serviceAppearance();
void openQuickJoin();
void askTeam(const char* prompt);
DashboardCode codeSnapshot(){DashboardCode result;if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){result=dashboardCode;xSemaphoreGive(viewMutex);}return result;}
void requestDashboardCode(){if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){++dashboardRequest;dashboardCode.clear();xSemaphoreGive(viewMutex);}}

bool storageMenu=false;
bool updateMenu=false,updatePolicyKnown=false,updatePolicyEnabled=false;
volatile int8_t updateDesired=-1;
String updateNotice="Connect to the verified Pi to read update policy.";
String quickWifiName,quickWifiCode,quickBluetoothPin;
uint32_t quickJoinAt=0;
bool keyboardVisible=false, setupEntry=false;
bool keyboardReturnToDesktop=false;
std::atomic<uint32_t> desktopEditableRevision{0};
uint32_t dismissedEditableRevision=0;
float localBatteryVoltage=NAN;uint32_t localBatteryAt=0;
bool batteryFresh(){return displayBatteryFresh(localBatteryAt,millis(),localBatteryVoltage);}
String displayBatteryLabel(){return batteryFresh()?String("DISPLAY BATTERY: ")+String(localBatteryVoltage,2)+" V (~"+String(displayBatteryEstimate(localBatteryVoltage))+"%)":"DISPLAY BATTERY: unavailable";}
void serviceDisplayBattery(){
  static uint32_t last=0;if(last&&uint32_t(millis()-last)<1000)return;last=millis();
  uint32_t total=0;for(int i=0;i<8;++i)total+=analogReadMilliVolts(34);
  float v=displayBatteryVolts((total+4)/8);
  localBatteryVoltage=isfinite(v)?(isfinite(localBatteryVoltage)?localBatteryVoltage*0.75f+v*0.25f:v):NAN;
  localBatteryAt=millis();
}
bool keyboardCaps=false;
uint8_t keyboardMode=0;
bool passwordVisible=false;
bool entryValueDirty=false;
uint32_t passwordShownAt=0;
bool securityMenu=false;
bool audioAvailable=false;
bool maintenanceMenu=false,maintenanceAccepted=false;
uint32_t maintenanceAt=0,maintenanceEpoch=0;
volatile uint32_t tlsLeaseAt=0;
char verifiedApBssid[18]={};
uint8_t entryMode=0; // 0 Pi credentials, 1 hotspot, 2 Bluetooth PIN.
String securityNotice="Sharing is OFF until you configure it here.";
uint16_t touchThreshold=600;
uint8_t setupField=0;
String setupValues[5];
volatile bool remoteReady=false;
volatile uint32_t forwardedPhoneRevision=0;
bool phoneTargetAvailable(){
  bool fresh=false;if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){uint32_t elapsed=uint32_t(millis()-displayTelemetry.received);fresh=displayTelemetry.phoneFresh&&elapsed<3000&&displayTelemetry.phoneAge<3000-elapsed;xSemaphoreGive(viewMutex);}return remoteReady&&fresh;
}
String phoneTargetLabel(){
  if(!phoneTargetAvailable())return "PHONE GPS: UNAVAILABLE / OPEN SAFARI OR COMPANION";
  bool browser=false;if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){browser=displayTelemetry.phoneBrowser;xSemaphoreGive(viewMutex);}
  return browser?"PHONE GPS: LIVE / SAFARI WI-FI":"PHONE GPS: LIVE / COMPANION BLE";
}
volatile uint32_t remoteEpoch=0;
struct InputEvent { uint32_t created,epoch; char action[12],key[16],value[4]; int dx,dy; };
std::atomic<bool> desktopActive{false};
std::atomic<uint32_t> inputAckMs{0},inputAcknowledged{0},inputQueueMs{0},inputRequestMs{0};
std::atomic<uint32_t> desktopEpoch{1},desktopFrameAt{0},desktopFrames{0};
std::atomic<uint16_t> desktopWidth{320},desktopHeight{240},desktopZoom{1},desktopCenterX{5000},desktopCenterY{5000};
std::atomic<int> desktopApiCode{0},desktopRows{0},desktopAbort{0};
std::atomic<int> desktopMapLeft{0},desktopMapTop{0},desktopMapRight{10000},desktopMapBottom{10000};
bool desktopOverlay=false,desktopPanMode=false;uint32_t desktopOverlayUntil=0;
struct DesktopLine {uint32_t epoch;uint16_t row,pixels[480];};
QueueHandle_t desktopLines=nullptr;
void handleTap(uint16_t x,uint16_t y);
void closeDesktop(){finishWiredViewer();desktopActive=false;++desktopEpoch;desktopFrameAt=0;dirty=true;lastScene="";}
QueueHandle_t inputQueue;
const char* keyRows[]={"1234567890","qwertyuiop","asdfghjkl","zxcvbnm.,?"};
const char* fieldNames[]={"Wi-Fi network name","Wi-Fi password","Pi private IP address","Companion username","Companion password"};
double lastPublication = 0, lastHeartbeat = 0;
String lastConnection;
uint16_t calibration[5];
bool calibrating=false,calRelease=true;
bool waitTouchRelease=false;
uint16_t calCorners[8]={},rawX=0,rawY=0,rawZ=0;
uint8_t calCorner=0,calSamples=0;
uint32_t calStarted=0,calSampleAt=0,calReleasedAt=0,calSumX=0,calSumY=0;
uint16_t BG=0x0000;
constexpr uint16_t INK=0xF7BE;
uint16_t PANEL=0x1082;
uint16_t BORDER=0x6000,CYAN=0xF800;
void applyThemeColors(){
  CYAN=appearanceColor565(themeColors[uiTheme]);BORDER=(CYAN>>2)&0x39E7;
  const uint16_t panels[]={0x1082,0x10A3,0x0843,0x0841};PANEL=panels[uiTheme];
  BG=backdrop::base(backgroundEffect,appearanceColor565(effectiveBackgroundColor(backgroundFollowsTheme,themeColors[uiTheme],backgroundColor)));
}
constexpr uint16_t MUTED=0xAD55, GREEN=0x5EAB, AMBER=0xFD45, RED=0xFA08;

void text(const String& value, int x, int y, uint16_t color=INK, int font=2) {
  lcd.setTextColor(color, BG); lcd.drawString(value, x, y, font);
}
void publish(const FlightView& value) {
  if (xSemaphoreTake(viewMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
    current = value; xSemaphoreGive(viewMutex);
  }
}
FlightView snapshot() {
  FlightView result;
  if (xSemaphoreTake(viewMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
    result = current;
    if(compactTelemetryEnabled){uint32_t now=millis();
      const char* fault=displayLinkFault(WiFi.status()==WL_CONNECTED,authBlocked,piLink.error,piLink.tlsError,uint32_t(now-displayTelemetry.received));
      if(fault){result.connected=false;result.armedKnown=false;strlcpy(result.link,fault,sizeof(result.link));}
      else if(uint32_t(now-displayTelemetry.received)>6000){result.connected=false;result.armedKnown=false;strlcpy(result.link,"PI OFFLINE",sizeof(result.link));}
      else if(!metricFresh(displayTelemetry.fields[0],displayTelemetry.received,now,3000)||displayTelemetry.fields[0].number!=1){result.connected=false;result.armedKnown=false;strlcpy(result.link,"PI ONLINE / FC OFFLINE",sizeof(result.link));}
      if(!metricFresh(displayTelemetry.fields[1],displayTelemetry.received,now,METRICS[1].ttl))result.armedKnown=false;
      if(!metricFresh(displayTelemetry.fields[4],displayTelemetry.received,now,METRICS[4].ttl))result.speed=NAN;
      if(!metricFresh(displayTelemetry.fields[15],displayTelemetry.received,now,5000))result.voltage=NAN;
      if(!metricFresh(displayTelemetry.fields[19],displayTelemetry.received,now,2000))result.fix=-1;
      if(!metricFresh(displayTelemetry.fields[20],displayTelemetry.received,now,2000))result.satellites=-1;
      if(!metricFresh(displayTelemetry.fields[9],displayTelemetry.received,now,METRICS[9].ttl)||!metricFresh(displayTelemetry.fields[10],displayTelemetry.received,now,METRICS[10].ttl)||result.fix<3)result.latitude=result.longitude=NAN;
    }
    xSemaphoreGive(viewMutex);
  }
  return result;
}
void linkState(const char* value) {
  FlightView v = snapshot(); v.connected = false; v.armedKnown = false;
  strlcpy(v.link, value, sizeof(v.link)); publish(v);
}
bool maintenanceReady() {
  FlightView v=snapshot();MaintenanceEvidence e;
  e.heartbeatFresh=viewFresh(v,millis());e.armedKnown=v.armedKnown;e.armed=v.armed;
  e.groundFresh=v.groundKnown&&uint32_t(millis()-v.groundReceived)<1500;e.onGround=v.onGround;
  e.tlsFresh=tlsLeaseAt&&uint32_t(millis()-tlsLeaseAt)<3500;
  e.ownerAuthenticated=remoteReady;e.wifiDbm=WiFi.status()==WL_CONNECTED?WiFi.RSSI():0;
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){
    if(compactTelemetryEnabled&&!metricFresh(displayTelemetry.fields[1],displayTelemetry.received,millis(),2000))e.armedKnown=false;
    // Silence on a UART cannot establish physical removal.
    e.controllerAbsent=false;
    if(compactTelemetryEnabled&&!displayTelemetry.sourceMatching)e.heartbeatFresh=false;
    e.directPiAp=verifiedApBssid[0]&&WiFi.BSSIDstr().equalsIgnoreCase(verifiedApBssid);xSemaphoreGive(viewMutex);
  }
  return maintenanceConditions(e);
}
bool ownerUnlockPending=false;uint32_t ownerUnlockDeadline=0;
const char* maintenanceReason(){
  if(ownerUnlockPending)return "Checking fresh Pi safety status...";
  if(WiFi.status()!=WL_CONNECTED)return "Connect to the Pi Wi-Fi";
  if(!remoteReady)return "Waiting for secure Pi login";
  if(!tlsLeaseAt||uint32_t(millis()-tlsLeaseAt)>=3500)return "Refreshing Pi safety status";
  FlightView v=snapshot();
  if(v.armedKnown&&v.armed)return "Controller ARMED - input blocked";
  if(v.groundKnown&&uint32_t(millis()-v.groundReceived)<1500&&!v.onGround)return "Controller airborne - input blocked";
  if(!verifiedApBssid[0]||!WiFi.BSSIDstr().equalsIgnoreCase(verifiedApBssid))return "Verifying paired Pi Wi-Fi";
  return "Checking controller source and disarmed state";
}
bool maintenanceEnabled(){
  FlightView v=snapshot();uint32_t now=millis();
  return ownerLeaseValid(maintenanceAccepted,maintenanceEpoch,remoteEpoch,now,maintenanceAt,remoteReady,WiFi.status()==WL_CONNECTED,tlsLeaseAt,v.armedKnown&&v.armed,v.groundKnown&&uint32_t(now-v.groundReceived)<1500&&!v.onGround);
}

String ownerAccessCaption(){
 uint32_t now=millis();
 if(!ownerLeaseHeld(maintenanceAccepted,maintenanceEpoch,remoteEpoch,now,maintenanceAt))return maintenanceReady()?String("Ready - tap UNLOCK"):String(maintenanceReason());
 uint32_t left=(OWNER_LEASE_MS-uint32_t(now-maintenanceAt)+999)/1000;
 return String(maintenanceEnabled()?"Owner enabled: ":"Owner paused: ")+String(left/60)+":"+(left%60<10?"0":"")+String(left%60)+" remaining";
}

String valueText(float value, const char* unit, int precision=1) {
  return isfinite(value) ? String(value, precision) + unit : String("--");
}
String droneGpsDetail(const FlightView& v,bool live){return live&&isfinite(v.latitude)&&isfinite(v.longitude)?String("DRONE ")+String(v.latitude,5)+", "+String(v.longitude,5):live&&v.fix>=3?String("3D fix reported"):String("Position not verified");}
void overviewBarColors(const FlightView& v,bool live,uint16_t colors[4]){
  const uint32_t now=millis();BarQuality quality[4];
  const bool valid[]={live&&v.armedKnown,live&&isfinite(v.voltage),live&&v.fix>=0&&v.satellites>=0,live&&isfinite(v.speed)};
  auto link=signalBar(remoteReady&&WiFi.status()==WL_CONNECTED,WiFi.RSSI());
  for(int i=0;i<4;++i)quality[i]=worseBar(link,freshnessBar(valid[i],uint32_t(now-v.received),3000));
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){
    if(compactTelemetryEnabled){const int indices[]={1,15,19,4};uint32_t elapsed=uint32_t(now-displayTelemetry.received);
      for(int i=0;i<4;++i){int k=indices[i];const auto& m=displayTelemetry.fields[k];quality[i]=worseBar(quality[i],freshnessBar(m.fresh,uint64_t(m.age)+elapsed,METRICS[k].ttl));}
      const auto& sats=displayTelemetry.fields[20];quality[2]=worseBar(quality[2],freshnessBar(sats.fresh,uint64_t(sats.age)+elapsed,METRICS[20].ttl));
      const auto& heartbeat=displayTelemetry.fields[0];auto heartbeatQuality=freshnessBar(heartbeat.fresh&&heartbeat.number==1,uint64_t(heartbeat.age)+elapsed,METRICS[0].ttl);
      for(auto& q:quality)q=worseBar(q,heartbeatQuality);
    }
    xSemaphoreGive(viewMutex);
  }else for(auto& q:quality)q=BarQuality::Unavailable;
  if(valid[2]&&v.fix<3)quality[2]=worseBar(quality[2],v.fix==2?BarQuality::Weak:BarQuality::Poor);
  for(int i=0;i<4;++i)colors[i]=barRgb565(quality[i],now,PANEL);
}
void card(int x, int y, int width, const char* title, const String& value,
          const char* detail, uint16_t accent) {
  int slot=(x>100?1:0)+(y>160?2:0);
  String signature=String(title)+"|"+value+"|"+detail;
  if(cardSignatures[slot]==signature){
    if(cardAccents[slot]!=accent){lcd.fillRoundRect(x+10,y+12,3,51,1,accent);cardAccents[slot]=accent;++sideBarDraws;}
    return;
  }
  cardSignatures[slot]=signature;
  cardAccents[slot]=accent;++cardBodyDraws;++sideBarDraws;
  // Preserve the card layout while reserving the former sprite's 17 KiB for
  // certificate verification. Repaint only cards whose contents changed.
  lcd.fillRect(x,y,width,77,BG);
  lcd.fillRoundRect(x,y,width,77,9,PANEL); lcd.drawRoundRect(x,y,width,77,9,BORDER);
  lcd.fillRoundRect(x+10,y+12,3,51,1,accent);
  lcd.setTextColor(MUTED,PANEL); lcd.drawString(title,x+22,y+8,2);
  lcd.setTextColor(INK,PANEL); lcd.drawString(value,x+22,y+28,4);
  lcd.setTextColor(MUTED,PANEL); lcd.drawString(detail,x+22,y+57,1);
}
void frame() {
  if(portrait())return;
  clearDisplay(BG);drawPageBackdrop();
  lcd.fillRoundRect(14,12,31,31,8,CYAN);
  lcd.drawLine(20,33,29,20,BG); lcd.drawLine(29,20,39,33,BG);
  lcd.drawLine(24,29,35,29,BG);
  text("AI FLIGHT TEAM",56,13,INK,4);
  text("YOUR DRONE. ONE CLEAR VIEW.",57,39,MUTED,1);
  lcd.fillRoundRect(417,14,49,30,4,PANEL);text("ROTATE",421,24,CYAN,1);
  lcd.drawFastHLine(14,51,452,BORDER);
  const char* names[] = {"OVERVIEW","SENSORS","PI CONTROL","AI TEAM","SETUP"};
  for (int i=0;i<5;++i) {
    int x=12+i*94;
    lcd.fillRoundRect(x,278,88,33,6,i==page?CYAN:PANEL);
    lcd.setTextColor(i==page?BG:MUTED,i==page?CYAN:PANEL);
    lcd.drawCentreString(names[i],x+44,289,1);
  }
}
void drawDisplayBatteryHeader(){
  bool fresh=batteryFresh();int pct=fresh?displayBatteryEstimate(localBatteryVoltage):-1;
  uint16_t color=!fresh?MUTED:pct<=10?TFT_RED:pct<=25?AMBER:GREEN;
  int x=portrait()?12:294,y=portrait()?47:13,w=portrait()?296:118,h=portrait()?18:34;
  String label=fresh?String("ESP ~")+pct+"%  "+String(localBatteryVoltage,2)+" V":"ESP BATTERY: --";
  if(!widgetCache.changed(9,x,y,w,h,label.c_str(),color))return;
  lcd.fillRect(x,y,w,h,BG);
  if(portrait())text(label,x,y,color,2);
  else{ text(fresh?String("ESP ~")+pct+"%":"ESP BAT --",x,y,color,2);text(fresh?String(localBatteryVoltage,2)+" V":"Unavailable",x,y+21,color,1); }
}
void keyboard() {
  for (int row=0;row<4;++row) for(size_t column=0;column<strlen(keyboardRow(keyboardMode,row));++column) {
    int x=16+column*45,y=114+row*28;
    lcd.fillRoundRect(x,y,41,24,4,PANEL); lcd.setTextColor(INK,PANEL);
    char glyph[2]={keyboardCharacter(keyboardMode,row,column,keyboardCaps),0};lcd.drawCentreString(glyph,x+20,y+3,2);
  }
  const char* keys[]={"ABC","123","SYMBOLS","SHIFT","DELETE"};
  for(int i=0;i<5;++i) {
    bool selected=(i<3&&keyboardMode==i)||(i==3&&keyboardCaps);
    lcd.fillRoundRect(16+i*91,230,86,18,3,selected?CYAN:PANEL);
    lcd.setTextColor(selected?BG:INK,selected?CYAN:PANEL);lcd.drawCentreString(keys[i],59+i*91,235,1);
  }
  const char* actions[]={"SPACE",setupEntry?"CANCEL":"TAB","ENTER",setupEntry?(entryMode==0&&setupField==4?"SAVE":"NEXT"):"CLOSE"};
  for(int i=0;i<4;++i){lcd.fillRoundRect(16+i*114,252,108,19,3,i==3?CYAN:PANEL);lcd.setTextColor(i==3?BG:INK,i==3?CYAN:PANEL);lcd.drawCentreString(actions[i],70+i*114,258,1);}
}
const char* entryLabel() {
  if(entryMode==3)return "Ask your AI flight team";
  if(entryMode==1)return setupField==0?"Display hotspot name":"Hotspot password (12-63 characters)";
  if(entryMode==2)return "Bluetooth PIN (6 digits, not a common PIN)";
  if(configured&&setupField==1&&setupValues[0]==ssid)return "Wi-Fi password (blank keeps saved)";
  if(configured&&setupField==4&&setupValues[2]==endpoint&&setupValues[3]==username)return "Pi password (blank keeps saved)";
  return fieldNames[setupField];
}
bool secretEntry(){return (entryMode==0&&(setupField==1||setupField==4))||(entryMode==1&&setupField==1)||entryMode==2;}
void drawEntryValue() {
  lcd.fillRect(16,94,450,19,BG);
  String value=setupValues[setupField];
  if(secretEntry()&&!passwordVisible){value="";for(size_t i=0;i<setupValues[setupField].length();++i)value+='*';}
  text(value.substring(value.length()>48?value.length()-48:0),16,98,INK,1);
  if(secretEntry()){lcd.fillRoundRect(390,94,74,18,3,PANEL);text(passwordVisible?"HIDE":"SHOW",410,99,CYAN,1);}
  entryValueDirty=false;
}
void render() {
  if(wiredViewer.active())return;

  FlightView v = snapshot(); bool live = viewFresh(v,millis());
  String signature=String(page)+"|"+String(live)+"|"+String(remoteReady)+"|"+v.link+"|"+v.mode+"|"+
    valueText(live?v.voltage:NAN," V")+"|"+valueText(live?v.speed:NAN," m/s")+"|"+
    String(v.satellites)+"|"+String(v.fix)+"|"+String(v.armedKnown)+"|"+String(v.armed)+"|"+v.notice+"|"+String(v.latitude,6)+"|"+String(v.longitude,6)+"|"+String(phoneTargetAvailable());
  if(powerMenu)signature=String("power|")+powerGate.active+"|"+powerGate.released+"|"+powerGate.confirmed+"|"+
    String(powerGate.holding?uint32_t(millis()-powerGate.heldAt)/250:0);
  if(maintenanceMenu)signature=String("maintenance|")+maintenanceReady()+"|"+String(WiFi.status()==WL_CONNECTED?WiFi.RSSI():0)+"|"+String(maintenanceEnabled())+"|"+String(millis()/1000);
  if(storageMenu){auto info=storageInfo();signature=String("storage|")+info.state+"|"+info.records+"|"+info.dropped;}
  if(updateMenu){if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){signature=String("updates|")+updateNotice+String(updatePolicyKnown)+String(updatePolicyEnabled);xSemaphoreGive(viewMutex);}}
  if(telemetryPage>=0)signature+="|"+String(displayTelemetry.revision)+"|"+String(millis()/500);
  PiSensors observed;
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){observed=piSensors;xSemaphoreGive(viewMutex);}
  if(page==1&&!powerMenu&&!storageMenu)for(int i=0;i<3;++i)signature+="|"+String(piSensorFresh(observed,i,millis()));
  if(page==3&&!powerMenu&&!setupEntry)signature+="|"+String(aiRevision)+"|"+String(aiOffset);
  if(page==3&&!setupEntry&&!powerMenu&&!storageMenu&&!maintenanceMenu&&!updateMenu)
    signature=String("ai|")+aiRevision+"|"+aiOffset+"|"+remoteReady;
  if(quickJoin&&configured){auto code=codeSnapshot();signature=String("qr|")+code.revision+"|"+code.fresh(millis())+"|"+remoteReady;}
  if(xiaoLightsMenu)signature=String("xiao lights|")+xiaoLights.revision+"|"+xiaoLights.ready();
  else if(backgroundMenu)signature=String("background|")+backgroundEffect+"|"+backgroundColor+"|"+backgroundFollowsTheme;
  else if(appearanceMenu)signature=String("appearance|")+uiTheme+"|"+themeColors[uiTheme]+"|"+lightMode+"|"+lightColor+"|"+lightBrightness+"|"+beaconPattern+"|"+lightSpeed;
  if(page==0&&!powerMenu&&!storageMenu&&!maintenanceMenu&&!updateMenu&&!quickJoin&&!setupEntry&&telemetryPage<0)signature+="|"+String(millis()/500);
  signature+="|"+displayBatteryLabel();
  if(!dirty&&signature==renderSignature)return;
  String scene=String(screenRotation)+"|"+page+"|"+telemetryPage+"|"+powerMenu+"|"+maintenanceMenu+"|"+storageMenu+"|"+updateMenu+"|"+quickJoin+"|"+securityMenu+"|"+setupEntry+"|"+keyboardVisible+"|"+(setupEntry?setupField:0)+"|"+appearanceMenu+"|"+backgroundMenu+"|"+uiTheme+"|"+backgroundEffect+"|"+backgroundColor;
  scene+="|"+String(themeColors[uiTheme])+"|"+xiaoLightsMenu;
  bool sceneChanged=scene!=lastScene;
  bool full=dirty||sceneChanged; renderSignature=signature; ++framesDrawn;
  if(sceneChanged){lastScene=scene;widgetCache.reset();for(auto& s:cardSignatures)s="";}
  if(telemetryPage>=0){dirty=false;uint32_t began=micros();drawTelemetryDetails(sceneChanged);if(telemetryPage>=6&&telemetryPage<=8)faultRenderMaxUs=max(faultRenderMaxUs,uint32_t(micros()-began));return;}
  if(portrait()){dirty=false;entryValueDirty=false;renderPortrait(v,observed,live,sceneChanged);return;}
  if(sceneChanged)frame();
  // A button edit may invalidate the body, but never clears the whole screen.
  else if(full){lcd.fillRect(12,76,456,196,BG);for(auto& s:cardSignatures)s="";}
  drawDisplayBatteryHeader();
  dirty=false;
  if(xiaoLightsMenu){renderXiaoLights(full);return;}
  if(backgroundMenu){renderBackground(full);return;}
  if(appearanceMenu){renderAppearance(full);return;}
  if(updateMenu){
    String notice;bool known,enabled;if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){notice=updateNotice;known=updatePolicyKnown;enabled=updatePolicyEnabled;xSemaphoreGive(viewMutex);}else return;
    lcd.fillRect(12,76,456,196,BG);text("PI AUTOMATIC UPDATES",18,80,CYAN,4);
    text(known?(enabled?"ENABLED":"DISABLED"):"POLICY NOT VERIFIED",18,118,known?GREEN:AMBER,2);
    text("Approved home Wi-Fi / idle only / future checks",18,147,INK,2);
    text("Debian userspace security updates. No automatic reboot.",18,176,MUTED,1);
    text("Drivers and AI artifacts require compatible reviewed releases.",18,195,MUTED,1);
    text(notice.substring(0,65),18,211,AMBER,1);
    lcd.fillRoundRect(18,235,220,33,5,PANEL);lcd.fillRoundRect(250,235,210,33,5,PANEL);
    text(known?(enabled?"DISABLE FUTURE CHECKS":"ENABLE FUTURE CHECKS"):"WAIT FOR PI",24,247,CYAN,1);text("BACK",320,244,INK,2);return;
  }
  if(storageMenu) {
    auto info=storageInfo();
    if(full){
      text("SD STORAGE",18,80,CYAN,4);
      text("Voice clips / logs / assets / profiles",18,155,INK,2);
      text("Boot and essential UI stay on onboard flash.",18,180,MUTED,2);
      lcd.fillRoundRect(18,215,220,33,5,PANEL);lcd.fillRoundRect(250,215,210,33,5,PANEL);
      text("MOUNT / RESCAN",42,224,CYAN,2);text("SAFE UNMOUNT",274,224,CYAN,2);
      text("No passwords or tokens are written to the card.",18,260,AMBER,1);
    }
    lcd.fillRect(18,114,444,36,BG);
    text(String(storageStateName(info.state))+" / "+String(info.capacityMiB/1024.0f,1)+" GiB",18,115,info.state==2?GREEN:AMBER,2);
    text("Saved "+String(info.records)+"  Dropped "+String(info.dropped)+"  Errors "+String(info.errors),18,137,MUTED,1);return;
  }
  if(quickJoin) {
    if(configured){renderDashboardQr(full);return;}
    if(full) {
      QRCode code;uint8_t bytes[512];
      String content="WIFI:T:WPA;S:"+quickWifiName+";P:"+quickWifiCode+";H:false;;";
      int result=qrcode_initText(&code,bytes,5,ECC_LOW,content.c_str());
      text("PHONE QUICK CONNECT",18,60,CYAN,2);
      if(result==0) {
        lcd.fillRect(16,82,180,180,TFT_WHITE);
        for(int y=0;y<code.size;++y)for(int x=0;x<code.size;++x)
          if(qrcode_getModule(&code,x,y))lcd.fillRect(32+x*4,98+y*4,4,4,TFT_BLACK);
      } else text("QR generation failed",18,126,AMBER,2);
      text("1. Scan with phone Camera",218,87,INK,2);
      text("2. Accept Join Wi-Fi",218,113,INK,2);
      text(quickWifiName,218,140,MUTED,1);
      text("Treat this QR as a password.",218,160,AMBER,1);
      lcd.fillRoundRect(218,182,246,32,5,PANEL);
      text("GENERATE BLUETOOTH PIN",228,194,CYAN,1);
      text(quickBluetoothPin.length()?"PIN: "+quickBluetoothPin:"Optional: BLE-capable app needed",218,222,INK,2);
      lcd.fillRoundRect(218,244,246,25,5,PANEL);text("HIDE QR / BACK",270,251,CYAN,1);
    }
    return;
  }
  if(maintenanceMenu) {
    if(full) {
      text("OWNER MAINTENANCE",18,80,CYAN,4);
      int dbm=WiFi.status()==WL_CONNECTED?WiFi.RSSI():0;
      text("AP RSSI: "+String(dbm)+" dBm / estimate "+String(wifiSignalEstimate(dbm))+"% (not distance)",18,110,MUTED,1);
      text("Confirm aircraft is secured for owner access",18,122,INK,2);
      text("Verified Pi TLS + owner login + local confirmation",18,150,INK,2);
      text("Fresh matched disarmed controller required",18,178,MUTED,2);
      lcd.fillRoundRect(18,226,220,33,5,PANEL);lcd.fillRoundRect(250,226,210,33,5,PANEL);
      text(maintenanceAccepted?"LOCK OWNER ACCESS":"UNLOCK OWNER ACCESS",24,235,CYAN,1);text("BACK",320,235,INK,2);
    }
    lcd.fillRect(18,201,444,21,BG);
    text(ownerAccessCaption(),18,202,maintenanceEnabled()?GREEN:AMBER,2);return;
  }
  if(powerMenu) {
    if(full) {
      text("POWER / SAFE SLEEP",18,80,CYAN,4);
      text("1. Tap PREPARE SLEEP below.",18,120,INK,2);
      text("2. Release BOOT, then hold it for 3 seconds.",18,145,INK,2);
      text("3. Release BOOT to enter low-power sleep.",18,168,INK,2);
      lcd.fillRoundRect(18,205,220,33,5,PANEL);
      lcd.fillRoundRect(250,205,210,33,5,PANEL);
      text("PREPARE SLEEP",50,214,CYAN,2); text("CANCEL",320,214,INK,2);
      text("400 mAh / charge estimate only; runtime unknown",18,259,AMBER,1);
      lcd.fillRoundRect(18,241,220,16,3,PANEL);lcd.fillRoundRect(250,241,210,16,3,PANEL);
      text(audioMuted()?"SOUND: MUTED (tap)":"SOUND: ON (tap)",30,245,CYAN,1);text("TEST STARTUP CHIME",269,245,CYAN,1);
    }
    lcd.fillRect(18,98,444,18,BG);text(displayBatteryLabel(),18,99,CYAN,1);
    lcd.fillRect(18,184,444,18,BG);
    String instruction=!powerGate.active?"LOCKED - holding BOOT does nothing":
      !powerGate.released?"Release BOOT first":powerGate.confirmed?"Confirmed - RELEASE BOOT now":
      powerGate.holding?"Hold: "+String(min(3.0f,float(uint32_t(millis()-powerGate.heldAt))/1000),1)+" / 3 seconds":
      "Prepared for 15 seconds - hold BOOT now";
    text(instruction,18,185,powerGate.active?GREEN:AMBER,2);return;
  }
  lcd.fillRect(12,57,456,16,BG);
  lcd.fillCircle(19,65,4,live?GREEN:AMBER);
  text(live?"LIVE TELEMETRY":v.link,30,57,live?GREEN:AMBER,1);
  if(page<2){lcd.fillRoundRect(335,55,130,22,4,PANEL);text(page==1?"ORANGE PI / DETAILS":"FLIGHT DETAILS",343,63,CYAN,1);}
  else text("ADVISORY DISPLAY",355,57,MUTED,1);
  if (page==0) {
    uint16_t bars[4];overviewBarColors(v,live,bars);
    card(12,80,221,"FLIGHT STATUS",live&&v.armedKnown?(v.armed?"ARMED":"DISARMED"):"UNKNOWN",
         live?v.mode:"Waiting for fresh heartbeat",bars[0]);
    card(245,80,223,"FLIGHT BATTERY",valueText(live?v.voltage:NAN," V"),
         "Voltage / bar = data link quality",bars[1]);
    String gps=droneGpsDetail(v,live);
    card(12,168,221,"DRONE GPS / SATELLITES",live&&v.satellites>=0?String(v.satellites):"--",gps.c_str(),bars[2]);
    card(245,168,223,"GROUND SPEED",valueText(live?v.speed:NAN," m/s"),
         "GPS speed can drift at rest",bars[3]);
    lcd.fillRect(12,250,456,18,BG);
    text(!touchReady?"Touch calibration required.":phoneTargetLabel(),15,253,phoneTargetAvailable()?GREEN:MUTED,1);
  } else if (page==1) {
    card(12,80,221,"CORVON 743 V2 (CONFIG)",live?"LIVE":"NO DATA",v.sourceMismatch?"Source mismatch: UART0 / UART4":live?"Heartbeat: Pi UART0 / FC UART4":"No heartbeat: Pi UART0 / FC UART4",live?GREEN:AMBER);
    const char* labels[]={"C1 360 LIDAR / UART2","8x8 MATRIX / UART7","CAMERA / PI USB"};
    for(int i=0;i<3;++i){bool fresh=piSensorFresh(observed,i,millis());
      card(i==1?12:245,i==0?80:168,i==1?221:223,labels[i],fresh?"LIVE DATA":"UNVERIFIED",
        fresh?"Fresh measurement":observed.node[i]&&uint32_t(millis()-observed.received)<6000?"Port present / no fresh data":"No verified data",fresh?GREEN:AMBER);
    }
    text("Missing or stale sensor data never means clear space.",17,258,AMBER,1);
  } else if (page==2) {
    if(!full)return;
    text("PI ON YOUR PHONE",16,82,CYAN,2);
    lcd.fillRoundRect(16,113,448,111,8,PANEL);
    lcd.setTextColor(CYAN,PANEL);lcd.drawCentreString("PHONE QUICK CONNECT",240,143,4);
    lcd.setTextColor(INK,PANEL);lcd.drawCentreString("Private desktop / files / Wi-Fi setup",240,185,2);
    lcd.fillRoundRect(16,235,220,32,4,PANEL);text("PI UPDATE SETTINGS",35,246,CYAN,1);
    lcd.fillRoundRect(246,235,218,32,4,PANEL);text("WIRED DESKTOP",265,246,CYAN,1);
  } else if (page==3) {
    if(setupEntry){if(full){text("ASK YOUR AI FLIGHT TEAM (128 characters)",16,78,CYAN,2);drawEntryValue();keyboard();}return;}
    lcd.fillRect(12,77,456,195,BG);
    text("CHAT WITH YOUR AI FLIGHT TEAM",16,80,CYAN,2);
    String answer,state;
    aiView(answer,state);
    text(state.substring(0,65),16,105,AMBER,1);
    unsigned index=min(aiOffset,unsigned(answer.length()));
    for(int row=0;row<5&&index<answer.length();++row){unsigned end=min(index+64,unsigned(answer.length()));
      if(end<answer.length()){int space=answer.lastIndexOf(' ',end);if(space>int(index)+20)end=space;}
      text(answer.substring(index,end),16,125+row*15,INK,1);index=end;while(index<answer.length()&&answer[index]==' ')++index;
    }
    const char* labels[]={"STATUS","SENSORS","LEARNING","TYPE"};
    for(int i=0;i<4;++i){lcd.fillRoundRect(16+i*114,207,108,30,4,PANEL);text(labels[i],31+i*114,218,CYAN,1);}
    text("Tap response for next / controller retains flight authority.",16,253,MUTED,1);
  } else {
    if(!full)return;
    if (setupEntry) {
      text(String(setupField+1)+"/"+(entryMode==1?"2":entryMode==2?"1":"5")+"  "+entryLabel(),16,78,CYAN,2);
      drawEntryValue();
      keyboard(); return;
    }
    if(securityMenu) {
      text("WIRELESS SECURITY",16,82,CYAN,4);
      const char* labels[]={"PHONE QUICK CONNECT / PRIVATE DASHBOARD","CUSTOM WI-FI HOTSPOT NAME / PASSWORD","CUSTOM BLUETOOTH PIN / PAIR FOR 60s","STOP HOTSPOT & BLUETOOTH"};
      for(int i=0;i<4;++i){lcd.fillRoundRect(16,115+i*31,448,27,5,PANEL);text(labels[i],27,124+i*31,CYAN,1);}
      text(securityNotice.substring(0,67),16,243,AMBER,1);
      text(String("Hotspot: ")+(hotspotEnabled()?"ON (WPA2 / CCMP)":"OFF")+"  BLE: "+(bluetoothAuthenticated()?"PAIRED":bluetoothPairingOpen()?"PAIRING":"CLOSED"),16,253,MUTED,1);
      text("Secrets are RAM-only. No flight-command service.",16,263,MUTED,1);return;
    }
    lcd.fillRoundRect(16,78,214,28,4,PANEL);text("LIGHTS & APPEARANCE",29,88,CYAN,1);
    lcd.fillRoundRect(238,78,105,28,4,PANEL);text("UPDATES",267,88,CYAN,1);
    lcd.fillRoundRect(352,78,112,28,4,PANEL);text("SD STORAGE",375,88,CYAN,1);
    lcd.fillRoundRect(16,115,448,29,5,PANEL);
    lcd.setTextColor(CYAN,PANEL); lcd.drawCentreString(configured?"EDIT CONNECTION / SAVE & RESTART":"CONNECT TO ORANGE PI",240,121,2);
    text("Wi-Fi: "+(ssid.length()?ssid:String("Not configured")),16,146,MUTED,2);
    text("Pi: "+(endpoint.length()?endpoint:String("Not configured"))+(piTrust.length()?" / TLS ready":" / TLS setup pending"),16,170,MUTED,2);
    text(String("Touch: ")+(touchThreshold==350?"LIGHT":touchThreshold==600?"BALANCED":"FIRM")+"  (tap to change)",16,191,CYAN,1);
    lcd.fillRoundRect(16,207,133,30,6,PANEL);
    lcd.fillRoundRect(159,207,133,30,6,PANEL);
    lcd.fillRoundRect(302,207,165,30,6,PANEL);
    text("DIM",65,212,CYAN,2); text("BRIGHT",195,212,CYAN,2);
    text("CALIBRATE TOUCH",316,217,CYAN,1);
    lcd.fillRoundRect(16,244,220,27,5,PANEL);lcd.fillRoundRect(245,244,220,27,5,PANEL);
    text("POWER MENU",65,249,CYAN,2);text("WIRELESS SECURITY",266,253,CYAN,1);
  }
}

void calibrate() {
  powerGate.cancel();powerMenu=false;calibrating=true;touchReady=false;
  // Collect and store the same physical landscape calibration in every mode.
  lcd.setRotation(1);
  calCorner=calSamples=0;calRelease=true;calStarted=millis();calReleasedAt=0;
  clearDisplay(BG);
  text("TOUCH CALIBRATION",35,25,CYAN,4);
  text("Tap each corner target; release between taps.",35,65,INK,2);
  lcd.drawCircle(4,4,13,CYAN);
}
void serviceCalibration() {
  if(!calibrating)return;
  if(uint32_t(millis()-calStarted)>180000) {
    calibrating=false;lcd.setRotation(screenRotation);updateOrientationTouch();dirty=true;
    Serial.println("{\"event\":\"touch_calibration_timeout_no_values_saved\"}");return;
  }
  if(uint32_t(millis()-calSampleAt)<15)return;
  calSampleAt=millis();rawZ=lcd.getTouchRawZ();
  bool down=digitalRead(36)==LOW&&rawZ>touchThreshold&&rawZ<4090;
  if(!down) {
    calSamples=0;
    if(!calReleasedAt)calReleasedAt=millis();
    if(uint32_t(millis()-calReleasedAt)>80)calRelease=false;
    return;
  }
  calReleasedAt=0;if(calRelease)return;
  lcd.getTouchRaw(&rawX,&rawY);
  if(rawX<80||rawX>4015||rawY<80||rawY>4015){calSamples=0;return;}
  if(calSamples&&(abs(int(rawX)-int(calSumX/calSamples))>80||abs(int(rawY)-int(calSumY/calSamples))>80))calSamples=0;
  if(!calSamples){calSumX=calSumY=0;}
  calSumX+=rawX;calSumY+=rawY;
  if(++calSamples<8)return;
  calCorners[calCorner*2]=calSumX/8;calCorners[calCorner*2+1]=calSumY/8;
  ++calCorner;calSamples=0;calRelease=true;
  clearDisplay(BG);text("TOUCH CALIBRATION",35,25,CYAN,4);
  text("Tap the target; release between taps.",35,65,INK,2);
  Serial.printf("{\"event\":\"touch_corner\",\"corners\":%u}\n",calCorner);
  if(calCorner==4) {
    if(!calibrationFromCorners(calCorners,calibration)) {
      text("Corners inconsistent. Try again carefully.",35,115,AMBER,2);
      calCorner=0;calStarted=millis();lcd.drawCircle(4,4,13,CYAN);return;
    }
    lcd.setTouch(calibration);prefs.putBytes("touch",calibration,sizeof(calibration));prefs.putUChar("touchver",2);
    touchReady=true;calibrating=false;lcd.setRotation(screenRotation);updateOrientationTouch();dirty=true;lastTouch=millis();waitTouchRelease=true;
    Serial.println("{\"event\":\"touch_calibrated_validated\"}");return;
  }
  int cx=calCorner>=2?475:4,cy=(calCorner==1||calCorner==3)?315:4;
  lcd.drawCircle(cx,cy,13,CYAN);
}

bool truthNumber(JsonVariantConst value, float& output, double low, double high) {
  if (value.isNull() || value.is<bool>() || !(value.is<double>() || value.is<long>())) { output=NAN; return false; }
  output=boundedNumber(value.as<double>(),low,high); return isfinite(output);
}
double messageUtc(const char* value) {
  if(!value||strlen(value)<20||strlen(value)>35)return NAN;
  int y,m,d,h,n,s,used=0;
  if(sscanf(value,"%d-%d-%dT%d:%d:%d%n",&y,&m,&d,&h,&n,&s,&used)!=6||used!=19||
    y<2020||y>2099||m<1||m>12||d<1||d>31||h<0||h>23||n<0||n>59||s<0||s>59)return NAN;
  const char* tail=value+used;double fraction=0;
  if(*tail=='.'){char* end=nullptr;fraction=strtod(tail,&end);if(!end||end==tail||fraction<0||fraction>=1)return NAN;tail=end;}
  if(strcmp(tail,"Z")&&strcmp(tail,"+00:00"))return NAN;
  struct tm t={};t.tm_year=y-1900;t.tm_mon=m-1;t.tm_mday=d;t.tm_hour=h;t.tm_min=n;t.tm_sec=s;
  time_t result=mktime(&t);
  if(t.tm_mon!=m-1||t.tm_mday!=d)return NAN;
  return double(result)+fraction;
}
void warningAudio(JsonVariantConst object) {
  double publication=object["updated_unix"]|0.0;
  if(!isfinite(publication)||publication<1577836800)return;
  static double lastSeen[6]={};static uint32_t lastSpoken[6]={};static bool spoken[6]={};
  for(auto message:object["messages"].as<JsonArrayConst>()) {
    const char* level=message["severity"]|"";
    if(strcmp(level,"warning")&&strcmp(level,"error")&&strcmp(level,"critical")&&strcmp(level,"alert")&&strcmp(level,"emergency"))continue;
    double timestamp=messageUtc(message["time_utc"]|"");
    if(!isfinite(timestamp)||timestamp>publication||publication-timestamp>8)continue;
    String content=message["text"]|"";if(!content.length()||content.length()>180)continue;
    portENTER_CRITICAL(&wiredNoticeLock);
    wiredNotices.observe(wirednotice::levelOf(level),timestamp,content.c_str(),millis());
    portEXIT_CRITICAL(&wiredNoticeLock);
    if(!audioAvailable||audioMuted())continue;
    content.toLowerCase();
    uint8_t category=content.indexOf("compass")>=0?0:content.indexOf("ekf")>=0||content.indexOf("estimat")>=0?1:
      content.indexOf("battery")>=0||content.indexOf("batt ")>=0?2:content.indexOf("radio")>=0||content.indexOf("rc failsafe")>=0?3:
      content.indexOf("gps")>=0?4:5;
    if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))!=pdTRUE)continue;
    bool fresh=timestamp>lastSeen[category];if(fresh)lastSeen[category]=timestamp;
    bool speak=fresh&&(!spoken[category]||uint32_t(millis()-lastSpoken[category])>=30000);
    if(speak){spoken[category]=true;lastSpoken[category]=millis();}
    xSemaphoreGive(viewMutex);
    if(speak)queueAudio(category+1);
  }
}
void flightJson(JsonVariantConst object, const char* transport) {
  FlightView v; v.packets=snapshot().packets+1;
  bool valid = object["schema"].is<int>() && object["schema"].as<int>()==1 &&
    object["connected"].is<bool>() && object["connected"].as<bool>() &&
    object["fresh"].is<bool>() && object["fresh"].as<bool>() &&
    object["authority"] == "read_only_no_mavlink_transmit";
  float age;
  valid = truthNumber(object["data_age_ms"],age,0,2000) && valid;
  if (!valid) { strlcpy(v.link,"NO FRESH FC HEARTBEAT",sizeof(v.link)); publish(v); return; }
  v.received=millis(); v.connected=true;
  v.armedKnown=object["armed"].is<bool>(); v.armed=v.armedKnown&&object["armed"].as<bool>();
  const char* mode=object["mode"]|"UNKNOWN"; strlcpy(v.mode,mode,sizeof(v.mode));
  strlcpy(v.link,transport,sizeof(v.link));
  strlcpy(v.notice,"Fresh status received. Sensor qualification is separate.",sizeof(v.notice));
  if (object["battery"]["fresh"].is<bool>() && object["battery"]["fresh"].as<bool>())
    truthNumber(object["battery"]["voltage_v"],v.voltage,1,80);
  float temporary;
  auto gps=object["sensors"]["GPS_RAW_INT:0"];
  auto motion=object["sensors"]["VFR_HUD:0"];
  if (gps["field_fresh"]["satellites"] == true && truthNumber(gps["values"]["satellites"],temporary,0,254)) v.satellites=int(temporary);
  if (gps["field_fresh"]["fix_type"] == true && truthNumber(gps["values"]["fix_type"],temporary,0,8)) v.fix=int(temporary);
  auto position=object["sensors"]["GLOBAL_POSITION_INT:0"];
  auto latitude=position["values"]["latitude"],longitude=position["values"]["longitude"];
  bool numeric=latitude.is<double>()&&!latitude.is<bool>()&&longitude.is<double>()&&!longitude.is<bool>();
  if(numeric&&verifiedDronePosition(v.fix,position["field_fresh"]["latitude"]==true,position["field_fresh"]["longitude"]==true,latitude.as<double>(),longitude.as<double>())){v.latitude=latitude.as<double>();v.longitude=longitude.as<double>();}
  if (motion["field_fresh"]["groundspeed_mps"] == true)
    truthNumber(motion["values"]["groundspeed_mps"],v.speed,0,150);
  auto ground=object["ground_state"];
  float groundAge;
  if(ground["message_type"]=="EXTENDED_SYS_STATE"&&ground["fresh"].is<bool>()&&ground["fresh"].as<bool>()&&
     truthNumber(ground["age_ms"],groundAge,0,1000)&&ground["landed_state"].is<int>()) {
    int state=ground["landed_state"];v.groundKnown=state>=1&&state<=4;v.onGround=state==1;v.groundReceived=millis()-uint32_t(groundAge);
  }
  publish(v);
  warningAudio(object);
}

struct TelemetryDiagnostics {
  std::atomic<uint32_t> attempts{0},responses{0},parsed{0},bodyBytes{0},capacity{0},used{0};
  std::atomic<const char*> state{"idle"};
} telemetryDiag;
void publishCompactTelemetry(JsonVariantConst doc,uint32_t transportAge){
  uint32_t now=millis();struct timeval utc;gettimeofday(&utc,nullptr);
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(100))!=pdTRUE){telemetryDiag.state="view_busy";return;}
  bool accepted=displayTelemetry.accept(doc,now,transportAge,uint64_t(utc.tv_sec)*1000+utc.tv_usec/1000);
  compactTelemetryEnabled=true;
  if(!accepted){telemetryDiag.state=displayTelemetry.rejection;current.connected=false;current.armedKnown=false;strlcpy(current.link,"PI DATA INVALID / STALE",sizeof(current.link));strlcpy(piLink.error,"invalid_display_schema",sizeof(piLink.error));xSemaphoreGive(viewMutex);return;}
  telemetryDiag.state="accepted";
  ++piLink.telemetryPolls;FlightView v;v.packets=current.packets;v.sourceMismatch=displayTelemetry.sourceMismatch;
  auto fresh=[&](int i){return metricFresh(displayTelemetry.fields[i],now,now,METRICS[i].ttl);};
  auto number=[&](int i){return fresh(i)?displayTelemetry.fields[i].number:NAN;};
  bool live=fresh(0)&&number(0)==1;v.connected=live;v.received=live?now:0;v.packets+=live?1:0;
  v.armedKnown=live&&fresh(1);v.armed=v.armedKnown&&number(1)==1;
  if(live&&fresh(2))strlcpy(v.mode,displayTelemetry.fields[2].text,sizeof(v.mode));
  v.speed=number(4);v.voltage=number(15);v.fix=fresh(19)?int(number(19)):-1;v.satellites=fresh(20)?int(number(20)):-1;
  if(verifiedDronePosition(v.fix,fresh(9),fresh(10),number(9),number(10))){v.latitude=number(9);v.longitude=number(10);}
  v.groundKnown=live&&fresh(26);v.onGround=v.groundKnown&&number(26)==1;v.groundReceived=v.groundKnown?now-displayTelemetry.fields[26].age:0;
  strlcpy(v.link,live?"PI ONLINE / FC LIVE":"PI ONLINE / FC OFFLINE",sizeof(v.link));
  if(displayTelemetry.faultCount)strlcpy(v.notice,displayTelemetry.faults[0],sizeof(v.notice));
  current=v;PiSensors sensors;sensors.received=now;
  for(int i=0;i<3;++i){sensors.fresh[i]=displayTelemetry.sensorFresh[i];sensors.age[i]=displayTelemetry.sensorAge[i];sensors.node[i]=displayTelemetry.sensorNode[i];}
  FieldSample sample;sample.uptime=now;sample.publication=displayTelemetry.generated;
  if(displayTelemetry.sourceMatching&&displayTelemetry.sourceHeartbeat&&fresh(0)){
    sample.connected=live?1:0;sample.heartbeatAge=displayTelemetry.fields[0].age;
    if(v.armedKnown)sample.armed=v.armed?1:0;
    if(live&&fresh(15)&&isfinite(v.voltage))sample.batteryMv=int32_t(lround(v.voltage*1000));
    if(live&&fresh(4)&&isfinite(v.speed))sample.groundspeedMmps=int32_t(lround(v.speed*1000));
  }
  const char* sensorNames[]={"rplidar","matrix_lidar","camera"};
  for(int i=0;i<3;++i){
    auto raw=doc["sensor_health"][sensorNames[i]];
    if(raw["data_age_ms"].is<uint32_t>()&&!raw["data_age_ms"].is<bool>())
      sample.sensors[i].age=fieldAge(raw["data_age_ms"].as<uint32_t>(),transportAge);
    if(sensors.fresh[i])sample.sensors[i].health=FieldHealth::Fresh;
    else if(raw["device_node_present"].is<bool>()&&raw["device_node_present"]==false)
      sample.sensors[i].health=FieldHealth::Missing;
    else if(sensors.node[i]&&sample.sensors[i].age!=UINT32_MAX&&sample.sensors[i].age>3000)
      sample.sensors[i].health=FieldHealth::Stale;
  }
  piSensors=sensors;xSemaphoreGive(viewMutex);recordFieldSample(sample);warningAudio(doc);
}
#include "PiConnection.h"
#include "BufferedJsonReader.h"
// Called before any response/filter JSON documents are allocated. Desktop
// cancellation closes a partial HTTP response; its next handshake needs the
// full transient heap, not the heap left after a 16 KiB telemetry allocation.
bool preparePiConnection() {
  if(!piTrust.length()||!bootstrapEpoch(uint32_t(time(nullptr))))return false;
  IPAddress ip;if(!ip.fromString(endpoint)||!privateAddress(endpoint.c_str()))return false;
  PiConnection* transport=sharedPiConnection(ip,piTrust);if(!transport)return false;
  auto& client=transport->client;auto& http=transport->http;
  if(client.connected())return true;
  client.setCACert(piTrust.c_str());client.setTimeout(2);client.setHandshakeTimeout(3);
  http.setReuse(true);http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  if(!http.begin(client,PinnedPiClient::hostname(),8443,"/api/identity",true))return false;
  if(!client.connectPrepared()) {
    char message[80];int error=client.lastError(message,sizeof(message));
    if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){piLink.tlsError=error;piLink.tlsHeap=ESP.getFreeHeap();piLink.tlsLargest=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);xSemaphoreGive(viewMutex);}
    if(tlsMemoryRecovery.failure(error,millis(),uint32_t(time(nullptr)),prefs.getULong("tls-restart",0)))tlsRecoveryRequested=true;
    apiDiagnostic(0,"tls_connect_failed");remoteReady=false;return false;
  }
  client.setNoDelay(true);tlsMemoryRecovery.success();return true;
}
bool httpJson(const char* path, DynamicJsonDocument& doc, const String* body=nullptr,const PhoneLocation* phone=nullptr,const JsonDocument* filter=nullptr) {
  uint32_t requestAt=millis();
  if(!sessionPolicy.canRequest(millis())){apiDiagnostic(429,"api_rate_cooldown");return false;}
  // Trust is installed only over the physically local USB provisioning channel.
  // No plain HTTP fallback, TOFU-over-Wi-Fi, setInsecure(), redirects or public hosts.
  if(!piTrust.length()){apiDiagnostic(0,"ca_missing");linkState("PI TLS TRUST SETUP REQUIRED");remoteReady=false;return false;}
  if(!bootstrapEpoch(uint32_t(time(nullptr)))){apiDiagnostic(0,"clock_not_trusted");linkState("AUTHENTICATED CLOCK REQUIRED");remoteReady=false;return false;}
  IPAddress ip;if(!ip.fromString(endpoint)||!privateAddress(endpoint.c_str()))return false;
  PiConnection* transport=sharedPiConnection(ip,piTrust);if(!transport)return false;
  auto& client=transport->client;auto& http=transport->http;
  client.setCACert(piTrust.c_str());client.setTimeout(2);client.setHandshakeTimeout(3);
  http.setConnectTimeout(1200);http.setTimeout(1500);http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
  // HTTPClient.begin() disconnects an existing socket when initializing _host.
  // Initialize it first, then establish the socket with the pinned DNS name.
  // GET/POST reuses that verified socket instead of reconnecting with numeric-IP
  // hostname verification. A failed reconnect still fails closed.
  http.setReuse(true);
  if(!http.begin(client,PinnedPiClient::hostname(),8443,path,true))return false;
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){piLink.tlsHeap=ESP.getFreeHeap();piLink.tlsLargest=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);xSemaphoreGive(viewMutex);}
  if(!client.connected()) {
    apiDiagnostic(0,"tls_reconnect_pending");remoteReady=false;return false;
  }
  // The server cannot sample this response until the HTTP request is sent.
  // Count all request/response time, but exclude the preceding TLS handshake.
  requestAt=millis();
  client.setNoDelay(true);
  tlsMemoryRecovery.success();
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){piLink.tlsError=0;xSemaphoreGive(viewMutex);}
  if (session.length()) http.addHeader("Authorization","Bearer "+session);
  int code;
  if (body) {
    http.addHeader("Content-Type","application/json");
    if(phone){
      // A TLS handshake may take seconds. Recheck the newest BLE sample and
      // compute its age after that handshake, immediately before sending.
      PhoneLocation latest=phoneLocationSnapshot();uint32_t age=phoneLocationAge(*phone,millis());
      if(!bluetoothAuthenticated()||latest.revision!=phone->revision||!phoneLocationFresh(*phone,millis())||age>2500){http.end();return false;}
      StaticJsonDocument<384> freshBody;if(deserializeJson(freshBody,*body)){http.end();return false;}
      freshBody["age_ms"]=age;String encoded;serializeJson(freshBody,encoded);code=http.POST(encoded);
    }else code=http.POST(*body);
  }
  else code=http.GET();
  AuthResponse decision=sessionPolicy.response(strcmp(path,"/api/login")==0,code,millis());
  if(decision==AuthResponse::Reauthenticate){session="";remoteReady=false;tlsLeaseAt=0;xQueueReset(inputQueue);apiDiagnostic(code,"session_expired_reauth_pending");linkState("PI SESSION EXPIRED / RECONNECTING");}
  else if(decision==AuthResponse::CredentialsBlocked){session="";authBlocked=true;remoteReady=false;tlsLeaseAt=0;xQueueReset(inputQueue);apiDiagnostic(code,"login_refused_owner_setup_required");linkState("SIGN-IN REQUIRED / CHECK SETUP");}
  else if(decision==AuthResponse::PermissionDenied)apiDiagnostic(code,"endpoint_permission_denied");
  else if(decision==AuthResponse::Cooldown){xQueueReset(inputQueue);apiDiagnostic(code,"api_rate_cooldown");linkState("PI API COOLDOWN");}
  else apiDiagnostic(code,code==200?"ok":code<0?"transport_failed":"http_error");
  const bool displayRequest=!strcmp(path,"/api/display");
  const int bodySize=http.getSize();
  if(displayRequest){
    ++telemetryDiag.responses;telemetryDiag.bodyBytes=bodySize>0?uint32_t(bodySize):0;
    if(code!=200)telemetryDiag.state="http_error";
    else if(bodySize<0||bodySize>32768)telemetryDiag.state="body_size";
    else telemetryDiag.state="parsing";
  }
  if (code!=200 || bodySize<0 || bodySize>32768) { client.stop();http.end(); return false; }
  BufferedJsonReader<WiFiClient> reader(http.getStream(),size_t(http.getSize()));
  auto error=filter?deserializeJson(doc,reader,DeserializationOption::Filter(*filter),DeserializationOption::NestingLimit(12)):deserializeJson(doc,reader,DeserializationOption::NestingLimit(12));
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){piLink.lastDuration=uint32_t(millis()-requestAt);xSemaphoreGive(viewMutex);}
  if(displayRequest){
    telemetryDiag.used=doc.memoryUsage();
    if(error)telemetryDiag.state=error==DeserializationError::NoMemory?"json_capacity":"invalid_json";
    else ++telemetryDiag.parsed;
  }
  if(error)apiDiagnostic(code,error==DeserializationError::NoMemory?"json_capacity_exceeded":"invalid_json");
  if(error)client.stop();
  http.end(); return !error;
}
// Build the filter on the network task's stack after TLS preparation and release
// it before publishing the large parsed view. No second heap block is needed.
bool fetchDisplayTelemetry(DynamicJsonDocument& doc) {
  StaticJsonDocument<JSON_OBJECT_SIZE(80)> filter;
  displayTelemetryFilter(filter);
  if(filter.overflowed()){telemetryDiag.state="filter_capacity";return false;}
  telemetryDiag.state="request";
  return httpJson("/api/display",doc,nullptr,nullptr,&filter);
}
#include "WifiRecovery.h"
void networkTask(void*) {
  WifiRecovery recovery;
  uint32_t nextConnect=0, nextPoll=0, inputSequence=0,lastIdentity=0;
  uint32_t lastUpdates=0,handledDashboardRequest=0,nextDashboardTry=0;
  uint32_t attemptedPhoneRevision=0;
  bool bootstrapped=false;
  for (;;) {
    if(sleepPending) { remoteReady=false; xQueueReset(inputQueue); session=""; networkParked=true; vTaskSuspend(nullptr); }
    if (applyConfig) { applyConfig=false; session=""; authBlocked=false;sessionPolicy=SessionPolicy(); WiFi.disconnect(); nextConnect=0; }
    if (!configured) { vTaskDelay(pdMS_TO_TICKS(200)); continue; }
    // Some AP restarts leave the ESP driver reporting WL_CONNECTED with no
    // associated radio (RSSI 0). Clear that state without weakening TLS/auth.
    if(recovery.observe(millis(),WiFi.status()==WL_CONNECTED,WiFi.RSSI())) {
      remoteReady=false;session="";bootstrapped=false;lastIdentity=0;
      xQueueReset(inputQueue);WiFi.disconnect(false,false);nextConnect=millis()+250;
      linkState("RECONNECTING TO PI WI-FI");
      vTaskDelay(pdMS_TO_TICKS(300));continue;
    }
    if (WiFi.status()!=WL_CONNECTED) {
      bootstrapped=false;
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){updatePolicyKnown=false;xSemaphoreGive(viewMutex);}updateDesired=-1;
      session="";
      if(chatQueue)xQueueReset(chatQueue);
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){aiUi.disconnected();xSemaphoreGive(viewMutex);}
      remoteReady=false; xQueueReset(inputQueue);
      linkState("CONNECTING TO PI WI-FI");
      if (int32_t(millis()-nextConnect)>=0) { WiFi.begin(ssid.c_str(),wifiPass.c_str()); nextConnect=millis()+5000; }
      vTaskDelay(pdMS_TO_TICKS(500)); continue;
    }
    if (authBlocked) { vTaskDelay(pdMS_TO_TICKS(500)); continue; }
    if(!sessionPolicy.canRequest(millis())){vTaskDelay(pdMS_TO_TICKS(250));continue;}
    if(!bootstrapped){
      if(timeKeyPresent){if(!bootstrapPiTime()){linkState("WAITING FOR TRUSTED PI CLOCK");vTaskDelay(pdMS_TO_TICKS(5000));continue;}}
      else if(!bootstrapEpoch(uint32_t(time(nullptr)))){linkState("USB CLOCK OR TIME KEY REQUIRED");vTaskDelay(pdMS_TO_TICKS(1000));continue;}
      bootstrapped=true;
    }
    if(!preparePiConnection()){vTaskDelay(pdMS_TO_TICKS(500));continue;}
    if(!session.length()&&!sessionPolicy.canLogin(millis())){vTaskDelay(pdMS_TO_TICKS(250));continue;}
    if (!session.length()||uint32_t(millis()-lastIdentity)>=30000) {
      DynamicJsonDocument identity(1024);
      if (!httpJson("/api/identity",identity) || identity["identity"]!="orange-pi-drone-companion-v1" || identity["authority"]!="companion_advisory_only") {
        linkState("PI IDENTITY NOT VERIFIED"); vTaskDelay(pdMS_TO_TICKS(5000)); continue;
      }
      lastIdentity=millis();
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){piLink.identityAt=lastIdentity;xSemaphoreGive(viewMutex);}
      const char* apBssid=identity["access_point"]["bssid"]|"";
      bool direct=identity["access_point"]["active"]==true&&identity["access_point"]["ip"]==endpoint&&
        strlen(apBssid)==17&&WiFi.BSSIDstr().equalsIgnoreCase(apBssid);
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(50))==pdTRUE){strlcpy(verifiedApBssid,direct?apBssid:"",sizeof(verifiedApBssid));xSemaphoreGive(viewMutex);}
    }
    if(!session.length()) {
      if(!sessionPolicy.canLogin(millis())){vTaskDelay(pdMS_TO_TICKS(250));continue;}
      StaticJsonDocument<512> login;
      login["username"]=username; login["password"]=password; login["client_kind"]="unknown";
      String body; serializeJson(login,body); DynamicJsonDocument reply(2048);
      if (!httpJson("/api/login",reply,&body)) { vTaskDelay(pdMS_TO_TICKS(5000)); continue; }
      const char* token=reply["session"]|"";
      if (strlen(token)<32 || strlen(token)>128) { authBlocked=true; linkState("INVALID SIGN-IN RESPONSE"); continue; }
      session=token;trialLoginConfirmed=true;
      xQueueReset(inputQueue); ++remoteEpoch; inputSequence=0; remoteReady=true;
      lastUpdates=0;requestDashboardCode();
    }
    auto currentCode=codeSnapshot();uint32_t desiredCode=0;
    if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){desiredCode=dashboardRequest;xSemaphoreGive(viewMutex);}
    bool refreshCode=desiredCode!=handledDashboardRequest||(quickJoin&&(!currentCode.fresh(millis())||uint32_t(millis()-currentCode.received)>90000));
    if(!desktopActive&&!maintenanceMenu&&refreshCode&&int32_t(millis()-nextDashboardTry)>=0){
      nextDashboardTry=millis()+5000;String body="{}";DynamicJsonDocument result(768);
      if(httpJson("/api/phone-quick-connect",result,&body)&&result["single_use"]==true&&result["scope"]=="private_field_dashboard"){
        if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){
          if(desiredCode==dashboardRequest&&dashboardCode.set(result["url"]|"",result["expires_seconds"]|0,millis()))handledDashboardRequest=desiredCode;
          xSemaphoreGive(viewMutex);
        }
      }
    }
    PhoneLocation phone=phoneLocationSnapshot();
    if(phone.revision!=attemptedPhoneRevision&&phone.seq>0&&phone.epoch[0]){
      attemptedPhoneRevision=phone.revision;
      bool fresh=bluetoothAuthenticated()&&phoneLocationFresh(phone,millis());
      if(fresh||!phone.active){
        StaticJsonDocument<384> payload;payload["source"]="phone_gps";payload["source_epoch"]=phone.epoch;payload["seq"]=phone.seq;
        if(fresh){payload["age_ms"]=phoneLocationAge(phone,millis());payload["lat"]=phone.latitude;payload["lon"]=phone.longitude;payload["accuracy_m"]=phone.accuracy;}
        else payload["stop"]=true;
        String body;serializeJson(payload,body);DynamicJsonDocument result(1536);
        bool ok=httpJson("/api/follow-location",result,&body,fresh?&phone:nullptr);
        if(ok&&fresh&&result["follow_location"]["status"]=="fresh"&&result["follow_location"]["authority"]=="advisory_only"&&result["follow_location"]["mavlink_transmit"]==false)forwardedPhoneRevision=phone.revision;
        else forwardedPhoneRevision=0;
      }
    }
    if(!desktopActive&&!maintenanceMenu&&(updateDesired>=0||!lastUpdates||uint32_t(millis()-lastUpdates)>15000)){
      int8_t desired=updateDesired;updateDesired=-1;lastUpdates=millis();DynamicJsonDocument reply(768);StaticJsonDocument<256> policyFilter;policyFilter["auto_update_policy"]["enabled"]=true;policyFilter["auto_update_policy"]["home_ssid"]=true;String body=desired>=0?String("{\"enabled\":")+(desired?"true}":"false}"):String("");
      bool ok=desired>=0?httpJson("/api/update-policy",reply,&body,nullptr,&policyFilter):httpJson("/api/updates",reply,nullptr,nullptr,&policyFilter);
      JsonVariantConst policy=reply["auto_update_policy"];bool known=ok&&policy["enabled"].is<bool>()&&localProfileReady()&&policy["home_ssid"]==displayLocalProfile.home;
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(50))==pdTRUE){updatePolicyKnown=known;if(known)updatePolicyEnabled=policy["enabled"].as<bool>();
        updateNotice=known?(desired>=0?"Policy saved for future checks.":"Policy read from verified Pi."):"Policy unavailable or change refused by Pi guards.";xSemaphoreGive(viewMutex);}
    }
    if (int32_t(millis()-nextPoll)<0) { vTaskDelay(pdMS_TO_TICKS(20));continue; }
    nextPoll=millis()+500;
    {
      ++telemetryDiag.attempts;
      const size_t largest=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
      const size_t budget=std::min<size_t>(12288,largest&~size_t(15));
      DynamicJsonDocument doc(budget>=6144?budget:0);
      telemetryDiag.capacity=doc.capacity();
      if(!doc.capacity())telemetryDiag.state="document_allocation";
      if(doc.capacity()&&fetchDisplayTelemetry(doc)){remoteReady=session.length()>0;tlsLeaseAt=millis();uint32_t duration=0;
        if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){duration=piLink.lastDuration;xSemaphoreGive(viewMutex);}
        publishCompactTelemetry(doc.as<JsonVariantConst>(),duration);
      }else linkState("PI CONNECTION INTERRUPTED");
    }

    ChatRequest chat;
    if(remoteReady&&chatQueue&&xQueueReceive(chatQueue,&chat,0)==pdTRUE){
      StaticJsonDocument<384> query;query["message"]=chat.message;String body;serializeJson(query,body);
      DynamicJsonDocument reply(8192);bool ok=httpJson("/api/chat",reply,&body);
      const char* answer=reply["answer"]|"";
      ok=ok&&reply["authority"]=="advisory_only"&&strlen(answer)>0&&strlen(answer)<=4096;
      if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(50))==pdTRUE){
        aiUi.phase=ok?AiUiState::Reply:AiUiState::Failed;
        aiAnswer=ok?String(answer).substring(0,960):"No verified response arrived. A model may need more time; use the Companion for long conversations.";
        aiState=ok?"ADVISORY RESPONSE / NOT A FLIGHT COMMAND":"RESPONSE UNAVAILABLE / NO AUTOMATIC RETRY";++aiRevision;xSemaphoreGive(viewMutex);
      }
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

// Old keyboard helpers have no authority to send Pi desktop input. Desktop
// interaction is authenticated separately in the phone browser.
void sendInput(const char*,const char* = "",char=0,int=0,int=0) {}
bool configure(const char* host,const char* net,const char* key,const char* user,const char* pass,bool save=true) {
  if (!privateAddress(host) || !strlen(net) || strlen(net)>32 || strlen(key)<8 || strlen(key)>63 || !strlen(user) || strlen(user)>64 || !strlen(pass) || strlen(pass)>128) return false;
  if(save){if(wifiTrial.active())return false;SavedConnection saved={};saved.version=1;strlcpy(saved.host,host,sizeof(saved.host));strlcpy(saved.net,net,sizeof(saved.net));strlcpy(saved.key,key,sizeof(saved.key));strlcpy(saved.user,user,sizeof(saved.user));strlcpy(saved.pass,pass,sizeof(saved.pass));
    const bool editing=savedConnection;
    bool ok=editing ? wifiTrial.stage(prefs,saved) : prefs.putBytes("connection",&saved,sizeof saved)==sizeof saved;
    clearConnection(saved);if(!ok)return false;savedConnection=true;}
  if(configured){if(!save)return false;Serial.println("{\"event\":\"connection_saved_restarting\"}");Serial.flush();ESP.restart();return true;}
  ssid=net;wifiPass=key;endpoint=host;username=user;password=pass;
  applyConfig=true;configured=true;
  if(xTaskCreatePinnedToCore(networkTask,"pi-status",12288,nullptr,1,&networkHandle,0)!=pdPASS){configured=false;password="";wifiPass="";linkState("NOT ENOUGH MEMORY TO CONNECT");return false;}return true;
}
void aiView(String& answer,String& state){
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))!=pdTRUE){state="STATUS UPDATING";answer="";return;}
  state=aiUi.label(remoteReady);
  answer=!remoteReady?"The Pi link is unavailable. Reconnect before sending another request.":aiUi.phase==AiUiState::Idle?"Choose STATUS, SENSORS, LEARNING, or TYPE. Replies are advisory; the controller keeps flight control.":aiAnswer;
  xSemaphoreGive(viewMutex);
}
void askTeam(const char* prompt){
  if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(50))!=pdTRUE)return;
  aiOffset=0;++aiRevision;
  if(!remoteReady){aiUi.phase=AiUiState::Idle;aiState="PI OFFLINE / RECONNECTING";aiAnswer="Open SETUP to configure the verified Pi connection first.";}
  else{ChatRequest request={};strlcpy(request.message,prompt,sizeof(request.message));
    if(xQueueSend(chatQueue,&request,0)==pdTRUE){aiUi.phase=AiUiState::Waiting;aiState="REQUEST QUEUED / WAITING FOR REPLY";aiAnswer="Your flight team is processing the request. This does not command the aircraft.";}
    else{aiState="REQUEST ALREADY PENDING";}
  }
  xSemaphoreGive(viewMutex);dirty=true;
}
void keyboardTouch(uint16_t x,uint16_t y) {
  bool wasEntry=setupEntry,wasKeyboard=keyboardVisible,wasCaps=keyboardCaps;
  uint8_t oldField=setupField,oldMode=keyboardMode;
  char letter=0;
  if(y>=114&&y<226&&x>=16&&x<466&&(y-114)%28<24&&(x-16)%45<41) {
    letter=keyboardCharacter(keyboardMode,(y-114)/28,(x-16)/45,keyboardCaps);
  }
  if(letter) {
    if(setupEntry) { if(setupValues[setupField].length()<128) setupValues[setupField]+=letter; }
    else sendInput("text","",letter);
  } else if(y>=230&&y<=248&&x>=16&&x<466) {
    int item=(x-16)/91;
    if(item<3)keyboardMode=item;
    if(item==3)keyboardCaps=!keyboardCaps;
    if(item==4){if(setupEntry)setupValues[setupField].remove(setupValues[setupField].length()?setupValues[setupField].length()-1:0);else sendInput("key","backspace");}
  } else if(y>=252&&y<=271&&x>=16&&x<466) {
    int item=(x-16)/114;
    if(item==0){if(setupEntry){if(setupValues[setupField].length()<128)setupValues[setupField]+=' ';}else sendInput("text","",' ');}
    if(item==1){if(setupEntry){setupEntry=false;passwordVisible=false;for(auto& value:setupValues)value="";}else sendInput("key","tab");}
    if(item==2){if(!setupEntry)sendInput("key","enter");}
    if(item==3) {
      passwordVisible=false;
      if(!setupEntry) {
        keyboardVisible=false;dismissedEditableRevision=desktopEditableRevision.load();
        keyboardReturnToDesktop=false;
      }
      else if(entryMode==1) {
        if(setupField==0)++setupField;
        else if(startProtectedHotspot(setupValues[0],setupValues[1])) {
          securityNotice="WPA2/CCMP enabled. Up to 2 clients; no control listener.";setupEntry=false;
          for(auto& value:setupValues)value="";
        } else {securityNotice=WiFi.status()==WL_CONNECTED?"Hotspot unavailable while connected to Pi Wi-Fi.":"Use a 12-63 character password with 5+ distinct characters.";setupEntry=false;for(auto& value:setupValues)value="";}
      }
      else if(entryMode==2) {
        bool ok=openBluetoothPairing(setupValues[0]);
        securityNotice=ok?"Pair now using your PIN; pairing closes after 60 seconds.":"PIN must be 6 digits, not repeated or 123456/654321.";
        setupEntry=false;for(auto& value:setupValues)value="";
      }
      else if(entryMode==3){askTeam(setupValues[0].c_str());setupEntry=false;setupValues[0]="";}
      else if(setupField<4) ++setupField;
      else if(configure(setupValues[2].c_str(),setupValues[0].c_str(),
          configured&&setupValues[0]==ssid&&!setupValues[1].length()?wifiPass.c_str():setupValues[1].c_str(),
          setupValues[3].c_str(),configured&&setupValues[2]==endpoint&&setupValues[3]==username&&!setupValues[4].length()?password.c_str():setupValues[4].c_str())) {
        setupEntry=false; for(auto& value:setupValues)value="";
      }
    }
  }
  if(wasEntry&&setupEntry&&oldField==setupField&&oldMode==keyboardMode&&wasCaps==keyboardCaps)entryValueDirty=true;
  else if(wasEntry!=setupEntry||wasKeyboard!=keyboardVisible||oldField!=setupField||oldMode!=keyboardMode||wasCaps!=keyboardCaps)dirty=true;
}

static bool setLocalProfile(const char* host,const char* origin,const char* home){
  if(localProfileReady())return false;
  WiredLocalProfile candidate{},readback{};
  if(!candidate.set(host,origin,home))return false;
  Preferences store;bool accepted=false;
  if(store.begin("display-local",false)){
    if(!store.isKey("identities")&&store.putBytes("identities",&candidate,sizeof candidate)==sizeof candidate&&
       store.getBytes("identities",&readback,sizeof readback)==sizeof readback&&
       !memcmp(&candidate,&readback,sizeof readback)&&readback.valid()){
      displayLocalProfile=readback;identitiesReady.store(true,std::memory_order_release);accepted=true;}
    store.end();
  }
  memset(&candidate,0,sizeof candidate);memset(&readback,0,sizeof readback);return accepted;
}
static void loadLocalProfile(){
  Preferences store;WiredLocalProfile record{};
  if(store.begin("display-local",true)){
    if(store.getBytesLength("identities")==sizeof record&&store.getBytes("identities",&record,sizeof record)==sizeof record&&record.valid()){
      displayLocalProfile=record;identitiesReady.store(true,std::memory_order_release);}
    store.end();
  }
  memset(&record,0,sizeof record);
}
static bool enrollWiredPair(const char* hex) {
  if(wiredViewer.enrolled()||!hex||strlen(hex)!=64)return false;
  uint8_t inner[32]{},check[32]{};
  if(!decodeHex256(hex,inner)) {mbedtls_platform_zeroize(inner,sizeof inner);return false;}
  Preferences storage;
  bool ok=false, random=false;
  for(uint8_t byte:inner)if(byte){random=true;break;}
  if(random && storage.begin("wired-pair",false)) {
    if(!storage.isKey("inner") && storage.putBytes("inner",inner,sizeof inner)==sizeof inner &&
       storage.getBytes("inner",check,sizeof check)==sizeof check && !memcmp(inner,check,sizeof inner))
      ok=wiredViewer.enroll(check);
    storage.end();
  }
  mbedtls_platform_zeroize(inner,sizeof inner);mbedtls_platform_zeroize(check,sizeof check);
  return ok;
}
static void loadWiredPair() {
  Preferences storage;uint8_t inner[32]{};
  if(storage.begin("wired-pair",true)){
    if(storage.getBytesLength("inner")==sizeof inner && storage.getBytes("inner",inner,sizeof inner)==sizeof inner)
      wiredViewer.enroll(inner);
    storage.end();
  }
  mbedtls_platform_zeroize(inner,sizeof inner);
}
static void wiredUsbExchange(JsonDocument& doc){
  uint32_t id=doc["request_id"].as<uint32_t>();
  bool valid=doc["request_id"].is<uint32_t>()&&id!=0&&doc["seq"].is<uint16_t>()&&doc["down_hex"].is<const char*>();
  uint16_t seq=doc["seq"].as<uint16_t>();
  const char* hex=doc["down_hex"]|"";size_t chars=strlen(hex);
  valid=valid&&chars<=124&&!(chars%2)&&(chars?seq!=0:seq==0);
  uint8_t down[62]{},up[57]{};size_t len=0;
  for(size_t i=0;valid&&i<chars/2;++i){
    int hi=hexNibble(hex[2*i]),lo=hexNibble(hex[2*i+1]);
    if(hi<0||lo<0)valid=false;else down[i]=uint8_t((hi<<4)|lo);
  }
  if(!valid){Serial.printf("{\"request_id\":%u,\"error\":\"invalid_exchange\"}\n",id);return;}
  uint16_t ack=0;bool busy=false;
  wiredViewer.usbExchange(lcd,seq,down,chars/2,!powerMenu&&!sleepPending&&touchReady&&!wiredSafetyPause(),
                          ack,busy,up,len);
  static const char digits[]="0123456789abcdef";
  char out[115]{};
  for(size_t i=0;i<len;i++){out[i*2]=digits[up[i]>>4];out[i*2+1]=digits[up[i]&15];}
  Serial.printf("{\"request_id\":%u,\"ack\":%u,\"busy\":%s,\"up_hex\":\"%s\"}\n",
                id,ack,busy?"true":"false",out);
}
void serialInput() {
  static char line[4096]; static size_t length=0; static bool overflow=false;
  while (Serial.available()) {
    char c=char(Serial.read());
    if (c=='\r') continue;
    if (c!='\n') { if (length<sizeof(line)-1) line[length++]=c; else overflow=true; continue; }
    line[length]=0;
    if (!overflow) {
      // Small local commands must not compete with TLS/telemetry for 6 KiB.
      DynamicJsonDocument doc(length<512?1024:6144);
      if (!deserializeJson(doc,line,DeserializationOption::NestingLimit(12))) {
        const char* action=doc["action"]|"";
        if (!strcmp(action,"wired_usb_exchange")) {
          wiredUsbExchange(doc);
          memset(line,0,sizeof line);length=0;overflow=false;
          return; // Touch sampling and active safety checks run between host requests.
        } else if(!strcmp(action,"wired_local_setup")&&doc["request_id"].is<uint32_t>()){
          bool accepted=doc["target"]==VERSION&&doc["confirm"]=="SET_LOCAL_IDENTITIES_ONCE"&&
            setLocalProfile(doc["tls_dns"]|"",doc["dashboard_origin"]|"",doc["home_ssid"]|"");
          Serial.printf("{\"request_id\":%u,\"accepted\":%s,\"local_setup\":%s}\n",doc["request_id"].as<uint32_t>(),accepted?"true":"false",localProfileReady()?"true":"false");
          doc.clear();memset(line,0,sizeof line);length=0;overflow=false;return;
        } else if (!strcmp(action,"wired_pair_enroll") && doc["request_id"].is<uint32_t>()) {
          bool accepted=doc["target"]==VERSION && doc["confirm"]=="PAIR_THIS_SCREEN_ONCE" &&
            enrollWiredPair(doc["key_hex"]|"");
          Serial.printf("{\"request_id\":%u,\"accepted\":%s,\"paired\":%s}\n",
            doc["request_id"].as<uint32_t>(),accepted?"true":"false",wiredViewer.enrolled()?"true":"false");
        } else if (!strcmp(action,"xiao_lights_probe") && doc["request_id"].is<uint32_t>()){
          bool ok=false;
          if(!doc.containsKey("mode")&&!xiaoLights.pending()){xiaoLights.probe();ok=true;}
          else if(doc["mode"].is<uint8_t>()&&doc["color"].is<uint8_t>()&&doc["brightness"].is<uint8_t>()&&doc["pattern"].is<uint8_t>()&&doc["speed"].is<uint8_t>()&&doc["yellow"].is<uint8_t>()){
            XiaoLights::Config c{doc["mode"].as<uint8_t>(),doc["color"].as<uint8_t>(),doc["brightness"].as<uint8_t>(),doc["pattern"].as<uint8_t>(),doc["speed"].as<uint8_t>(),doc["yellow"].as<uint8_t>()};
            ok=xiaoLights.set(c);
          }
          Serial.printf("{\"request_id\":%u,\"queued\":%s}\n",doc["request_id"].as<uint32_t>(),ok?"true":"false");
        } else if (!strcmp(action,"wired_status") && doc["request_id"].is<uint32_t>()) {
          StaticJsonDocument<1536> report;
          uint8_t mac[6]{};char hex[13]{};
          if(esp_efuse_mac_get_default(mac)==ESP_OK)
            snprintf(hex,sizeof hex,"%02x%02x%02x%02x%02x%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
          report["request_id"]=doc["request_id"].as<uint32_t>();report["firmware"]=VERSION;
          report["local_setup"]=localProfileReady();report["configured_controller"]="CORVON743V2";report["display"]="Hosyond-E32R35T";report["screen_mac"]=hex;
          report["paired"]=wiredViewer.enrolled();report["helper"]=wiredViewer.present();
          report["handshake"]=wiredViewer.established();report["desktop_live"]=wiredViewer.live();
          report["desktop_open"]=wiredViewer.active();report["guard"]=wiredSafetyPause();
          report["guard_reason"]=wiredGuardReason();report["priority_alert"]=wiredPriorityActive();
          report["notice_level"]=wirednotice::label(wiredNoticeNow().level);
          report["route"]=wiredViewer.present()?(wiredViewer.usbActive()?"direct_usb":"xiao_spi"):"none";
          report["back"]=wiredViewer.dismissed();report["paints"]=wiredViewer.paints();
          report["pixels"]=wiredViewer.pixelsDrawn();report["touches"]=wiredViewer.touches();
          report["handshakes"]=wiredViewer.handshakes();
          report["features"]=wiredViewer.pictures.flags()|2|8|16;report["desktop_zoom"]=wiredViewer.zoomLevel();report["zoom_pending"]=wiredViewer.zoomWaiting();report["codec_memory"]=wiredViewer.pictures.reserved()?"reserved":"self_test_failed";report["jpeg_capacity"]=wiredViewer.pictures.reserved()?picturestore::Bytes:0;report["loop_stack_watermark"]=uxTaskGetStackHighWaterMark(nullptr);report["jpeg_frames"]=wiredViewer.pictures.frames;
          report["zlib_tiles"]=wiredViewer.pictures.tiles;report["decode_errors"]=wiredViewer.pictures.failures;
          report["jpeg_receive_ms"]=wiredViewer.pictures.receiveMs;report["jpeg_commit_ms"]=wiredViewer.pictures.commitMs;
          report["uptime_ms"]=millis();report["reset_reason"]=int(esp_reset_reason());report["spi_promotions"]=wiredViewer.fastPromotions;report["led_sideband_frames"]=wiredViewer.sidebandReplies;
          report["telemetry_state"]=telemetryDiag.state.load();report["telemetry_attempts"]=telemetryDiag.attempts.load();report["telemetry_responses"]=telemetryDiag.responses.load();report["telemetry_parsed"]=telemetryDiag.parsed.load();report["telemetry_body_bytes"]=telemetryDiag.bodyBytes.load();report["telemetry_capacity"]=telemetryDiag.capacity.load();report["telemetry_used"]=telemetryDiag.used.load();
          report["network_stack_watermark"]=networkHandle?uxTaskGetStackHighWaterMark(networkHandle):0;
          report["spi_fast"]=wiredViewer.fastSpi();report["spi_fast_xfers"]=wiredViewer.fastTransfers;report["spi_fallbacks"]=wiredViewer.fastFallbacks;report["spi_crc_errors"]=wiredViewer.crcErrors;
          report["input_overflows"]=wiredViewer.droppedInputs;report["input_receipts"]=wiredViewer.keys.accepted;
          auto lights=report.createNestedObject("xiao_lights");lights["available"]=xiaoLights.ready();lights["pending"]=xiaoLights.pending();lights["revision"]=xiaoLights.revision;
          if(xiaoLights.ready()){const auto& c=xiaoLights.confirmed;lights["mode"]=c.mode;lights["color"]=c.color;lights["brightness"]=c.brightness;lights["pattern"]=c.pattern;lights["speed"]=c.speed;lights["yellow"]=c.yellow;lights["r"]=xiaoLights.rgb[0];lights["g"]=xiaoLights.rgb[1];lights["b"]=xiaoLights.rgb[2];lights["duty"]=xiaoLights.duty;lights["power"]=xiaoLights.power;}
          String encoded;serializeJson(report,encoded);encoded+='\n';Serial.print(encoded);
        } else if (!strcmp(action,"telemetry")) flightJson(doc["flight"],"USB TELEMETRY BRIDGE");
        else if(!strcmp(action,"ui_view")&&!calibrating&&!sleepPending&&doc["page"].is<int>()&&doc["page"].as<int>()>=0&&doc["page"].as<int>()<5){
          navigateTo(doc["page"].as<int>());
          int detail=doc["detail"]|-1;if(detail>=0&&detail<TELEMETRY_PAGES)telemetryPage=detail;
          const char* menu=doc["menu"]|"";
          storageMenu=!strcmp(menu,"storage");updateMenu=!strcmp(menu,"updates");powerMenu=!strcmp(menu,"power");maintenanceMenu=false;
          appearanceMenu=!strcmp(menu,"appearance");backgroundMenu=!strcmp(menu,"background");if(!strcmp(menu,"quick"))openQuickJoin();
          if(page==2&&(!strcmp(menu,"desktop")||!strcmp(menu,"maintenance")))openQuickJoin();
          powerGate.cancel();dirty=true;Serial.println("{\"event\":\"local_view_selected\"}");
        }
        else if(!strcmp(action,"appearance_row")&&appearanceMenu&&doc["row"].is<uint8_t>()&&doc["row"].as<uint8_t>()<7){handleTap(100,121+doc["row"].as<uint8_t>()*19);}
        else if(!strcmp(action,"ai_learning_check")&&!sleepPending){askTeam("How is offline learning configured?");Serial.println("{\"event\":\"advisory_learning_requested\"}");}
        else if(!strcmp(action,"ai_sensors_check")&&!sleepPending){askTeam("Which sensors are reporting verified data?");Serial.println("{\"event\":\"advisory_sensors_requested\"}");}
        else if(!strcmp(action,"ai_status_check")&&!sleepPending){askTeam("What is my current flight status?");Serial.println("{\"event\":\"advisory_status_requested\"}");}
        else if(!strcmp(action,"storage_check")){
          uint32_t id=doc["request_id"]|0U;if(!requestStorageCheck(id))
            Serial.printf("{\"event\":\"sd_check_result\",\"request_id\":%u,\"accepted\":false}\n",id);
        }
        else if(!strcmp(action,"storage_mount"))requestStorageMount();
        else if(!strcmp(action,"storage_unmount"))requestStorageUnmount();
        else if(!strcmp(action,"rotate")&&doc["rotation"].is<uint8_t>()&&doc["rotation"].as<uint8_t>()<4&&!calibrating&&!sleepPending){
          screenRotation=(doc["rotation"].as<uint8_t>()+3)%4;rotateDisplay();Serial.println("{\"event\":\"display_orientation_saved\"}");
        }
        else if(!strcmp(action,"forget_connection")){prefs.remove("connection");Serial.println("{\"event\":\"saved_connection_removed_restarting\"}");Serial.flush();ESP.restart();}
        else if(!strcmp(action,"time_key")&&!configured){
          const char* id=doc["device_id"]|"";const char* hex=doc["key_hex64"]|"";uint8_t key[32]={};
          if(bootstrapId(id)&&decodeHex256(hex,key)){
            // One NVS blob commits the identity/key together. Never echo the key.
            uint8_t saved[65]={};memcpy(saved,id,strlen(id));memcpy(saved+33,key,32);
            if(prefs.putBytes("timekey",saved,sizeof(saved))==sizeof(saved)){strlcpy(timeDeviceId,id,sizeof(timeDeviceId));memcpy(timeKey,key,32);timeKeyPresent=true;Serial.println("{\"event\":\"authenticated_time_key_saved\"}");}
            else Serial.println("{\"error\":\"time_key_save_failed\"}");memset(saved,0,sizeof(saved));
          }else Serial.println("{\"error\":\"invalid_time_key\"}");memset(key,0,sizeof(key));
        }
        else if(!strcmp(action,"clock")&&!configured&&doc["unix"].is<uint32_t>()) {
          uint32_t epoch=doc["unix"];if(epoch>=1792022400UL&&epoch<4102444800UL){struct timeval value={time_t(epoch),0};settimeofday(&value,nullptr);Serial.println("{\"event\":\"utc_clock_set_over_local_usb\"}");}
        }
        else if(!strcmp(action,"trust_ca")&&!configured) {
          const char* pem=doc["pem"]|"";
          if(strlen(pem)>512&&strlen(pem)<3500) {
            mbedtls_x509_crt certificate;mbedtls_x509_crt_init(&certificate);
            int parsed=mbedtls_x509_crt_parse(&certificate,reinterpret_cast<const unsigned char*>(pem),strlen(pem)+1);bool ca=certificate.ca_istrue;
            bool valid=parsed==0&&ca;
            mbedtls_x509_crt_free(&certificate);
            if(valid){piTrust=pem;prefs.putString("pica",piTrust);Serial.println("{\"event\":\"pi_tls_ca_provisioned_over_usb\"}");dirty=true;}
            else Serial.printf("{\"error\":\"invalid_ca_certificate\",\"parse_code\":%d,\"ca_flag\":%s,\"pem_bytes\":%u}\n",parsed,ca?"true":"false",unsigned(strlen(pem)));
          } else Serial.println("{\"error\":\"invalid_ca_length\"}");
        }
        else if (!strcmp(action,"configure")) {
          const char* host=doc["host"]|""; const char* net=doc["ssid"]|"";
          const char* key=doc["wifi_password"]|""; const char* user=doc["username"]|"";
          const char* pass=doc["password"]|"";
          if (privateAddress(host) && strlen(net)>0 && strlen(net)<=32 && strlen(key)>=8 && strlen(key)<=63 && strlen(user)>0 && strlen(user)<=64 && strlen(pass)>0 && strlen(pass)<=128) {
            // Configuration changes happen only before a network task is started.
            // Runtime reconfiguration requires a reboot, avoiding String races.
            if (configure(host,net,key,user,pass)) {
              Serial.println("{\"event\":\"connection_saved\"}");
            } else Serial.println("{\"error\":\"restart_before_reconfigure\"}");
          } else Serial.println("{\"error\":\"invalid_configuration\"}");
        } else if (!strcmp(action,"desktop_status")) {
          StaticJsonDocument<1024> report;
          report["request_id"]=doc["request_id"].as<uint32_t>();report["firmware"]=VERSION;report["uptime_ms"]=millis();
          report["free_heap"]=ESP.getFreeHeap();report["largest_free_block"]=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
          report["rotation"]=screenRotation;report["pi_authenticated"]=remoteReady;
          if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){report["pi_last_api_code"]=piLink.lastCode;report["pi_last_api_error"]=piLink.error;xSemaphoreGive(viewMutex);}
          report["desktop_supported"]=false;report["desktop_width"]=desktopWidth.load();report["desktop_height"]=desktopHeight.load();report["desktop_open"]=desktopActive.load();report["desktop_overlay"]=desktopOverlay;
          report["desktop_api_code"]=desktopApiCode.load();report["desktop_frames"]=desktopFrames.load();report["desktop_abort"]=desktopAbort.load();report["desktop_age_ms"]=desktopFrameAt?uint32_t(millis()-desktopFrameAt):UINT32_MAX;report["desktop_zoom"]=desktopZoom.load();
          report["maintenance_unlocked"]=ownerLeaseHeld(maintenanceAccepted,maintenanceEpoch,remoteEpoch,millis(),maintenanceAt);report["maintenance_enabled"]=maintenanceEnabled();report["keyboard_visible"]=keyboardVisible;
          String encoded;encoded.reserve(1024);serializeJson(report,encoded);encoded+='\n';Serial.print(encoded);
        } else if (!strcmp(action,"status")) {
          StaticJsonDocument<3072> report; auto v=snapshot();
          if(doc["request_id"].is<uint32_t>())report["request_id"]=doc["request_id"].as<uint32_t>();
          report["firmware"]=VERSION; report["local_setup"]=localProfileReady();report["configured_controller"]="CORVON743V2";report["display"]="Hosyond-E32R35T";
          report["wired_paired"]=wiredViewer.enrolled();report["wired_helper"]=wiredViewer.present();
          report["wired_desktop_open"]=wiredViewer.active();report["wired_desktop_live"]=wiredViewer.live();
          report["authority"]="advisory_display_only"; report["frames_drawn"]=framesDrawn;report["screen_clears"]=screenClears;report["fault_render_max_us"]=faultRenderMaxUs;report["fault_row_draws"]=faultRowDraws;report["telemetry_page"]=telemetryPage;
          report["touch_calibrated"]=touchReady; report["page"]=page;
          report["live"]=viewFresh(v,millis()); report["telemetry_packets"]=v.packets;
          report["display_link_state"]=v.link;
          report["uptime_ms"]=millis(); report["free_heap"]=ESP.getFreeHeap();
          report["minimum_free_heap"]=ESP.getMinFreeHeap();report["largest_free_block"]=heap_caps_get_largest_free_block(MALLOC_CAP_8BIT);
          report["power_menu"]=powerMenu; report["sleep_prepared"]=powerGate.active;
          report["sleep_pending"]=sleepPending; report["boot_down"]=digitalRead(0)==LOW;
          report["calibrating"]=calibrating; report["calibration_corner"]=calCorner;
          report["touch_irq"]=digitalRead(36);report["raw_pressure"]=rawZ;
          report["raw_x"]=rawX;report["raw_y"]=rawY;
          report["phone_gps_fresh"]=phoneTargetAvailable();report["phone_gps_status"]=phoneTargetLabel();report["hotspot"]=hotspotEnabled();report["bluetooth_pairing"]=bluetoothPairingOpen();
          report["bluetooth_authenticated"]=bluetoothAuthenticated();
          {String answer,state;aiView(answer,state);report["ai_display_status"]=state;report["ai_phase"]=int(aiUi.phase);}
          report["audio_available"]=audioAvailable;report["audio_muted"]=audioMuted();
          report["audio_playing"]=audioPlaying();
          report["pi_tls_trust_present"]=piTrust.length()>0;
          report["pi_tls_required"]=true;report["plain_http_fallback"]=false;
          report["clock_ready"]=time(nullptr)>=1792022400;
          report["unix_epoch"]=uint32_t(time(nullptr));
          report["pi_snapshot_age_ms"]=compactTelemetryEnabled?uint32_t(millis()-displayTelemetry.received):UINT32_MAX;
          report["wifi_connected"]=WiFi.status()==WL_CONNECTED;report["pi_authenticated"]=remoteReady;
          if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){report["pi_identity_verified_age_ms"]=piLink.identityAt?uint32_t(millis()-piLink.identityAt):UINT32_MAX;report["pi_flight_polls_ok"]=piLink.flightPolls;report["pi_status_polls_ok"]=piLink.statusPolls;report["pi_telemetry_polls_ok"]=piLink.telemetryPolls;report["pi_last_api_code"]=piLink.lastCode;report["pi_last_api_error"]=piLink.error;report["pi_last_api_duration_ms"]=piLink.lastDuration;report["tls_last_error"]=piLink.tlsError;report["tls_free_heap_before"]=piLink.tlsHeap;report["tls_largest_block_before"]=piLink.tlsLargest;xSemaphoreGive(viewMutex);}
          report["time_key_present"]=timeKeyPresent;report["connection_saved"]=savedConnection;
          if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){
            uint32_t now=millis();
            const int indices[]={31,32,34};
            const char* names[]={"pi_cpu_busy_percent","pi_cpu_temperature_c","pi_available_memory_bytes"};
            for(int i=0;i<3;++i){int index=indices[i];if(metricFresh(displayTelemetry.fields[index],displayTelemetry.received,now,METRICS[index].ttl))report[names[i]]=displayTelemetry.fields[index].number;else report[names[i]]=nullptr;}
            xSemaphoreGive(viewMutex);
          }
          if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){uint64_t mask=0;for(size_t i=0;i<METRIC_COUNT;++i)if(metricFresh(displayTelemetry.fields[i],displayTelemetry.received,millis(),METRICS[i].ttl))mask|=uint64_t(1)<<i;char bits[17];snprintf(bits,sizeof(bits),"%012llx",(unsigned long long)mask);report["metric_fresh_mask"]=bits;report["speed_reported_zero"]=metricFresh(displayTelemetry.fields[4],displayTelemetry.received,millis(),METRICS[4].ttl)&&displayTelemetry.fields[4].number==0;xSemaphoreGive(viewMutex);}

          report["flight_armed_known"]=v.armedKnown;
          report["drone_gps_known"]=isfinite(v.latitude)&&isfinite(v.longitude);
          report["rotation"]=screenRotation;report["screen_width"]=lcd.width();report["screen_height"]=lcd.height();
          report["maintenance_unlocked"]=ownerLeaseHeld(maintenanceAccepted,maintenanceEpoch,remoteEpoch,millis(),maintenanceAt);report["owner_remaining_seconds"]=ownerLeaseHeld(maintenanceAccepted,maintenanceEpoch,remoteEpoch,millis(),maintenanceAt)?(OWNER_LEASE_MS-uint32_t(millis()-maintenanceAt)+999)/1000:0;report["maintenance_enabled"]=maintenanceEnabled();report["maintenance_ready"]=maintenanceReady();report["appearance_open"]=appearanceMenu;
          report["display_battery_voltage_v"]=batteryFresh()?localBatteryVoltage:NAN;
          report["display_battery_estimate_pct"]=batteryFresh()?displayBatteryEstimate(localBatteryVoltage):-1;
          report["display_battery_capacity_mah"]=400;report["display_battery_charge_state"]="unmeasured";
          report["desktop_editable_revision"]=desktopEditableRevision.load();report["keyboard_visible"]=keyboardVisible;
          report["wifi_dbm"]=WiFi.status()==WL_CONNECTED?WiFi.RSSI():0;
          report["taps"]=tapsSeen;report["swipes"]=swipesSeen;report["theme"]=uiTheme;report["light_mode"]=lightMode;report["light_color"]=lightColor;report["light_brightness"]=lightBrightness;report["performance_mode"]=true;report["matrix_frames"]=matrixFrames;report["background_effect"]=backgroundEffect;report["background_animated"]=backdrop::animated(backgroundEffect);report["background_color"]=backgroundColor;
          report["card_body_draws"]=cardBodyDraws;report["side_bar_draws"]=sideBarDraws;
          report["input_ack_ms"]=inputAckMs.load();report["input_queue_ms"]=inputQueueMs.load();report["input_request_ms"]=inputRequestMs.load();report["input_acknowledged"]=inputAcknowledged.load();report["cpu_mhz"]=getCpuFrequencyMhz();report["wifi_sleep"]=WiFi.getSleep();report["desktop_rows"]=desktopRows.load();report["desktop_abort"]=desktopAbort.load();report["desktop_width"]=desktopWidth.load();report["desktop_height"]=desktopHeight.load();report["desktop_overlay"]=desktopOverlay;report["owner_block_reason"]=maintenanceReason();report["desktop_api_code"]=desktopApiCode.load();report["desktop_zoom"]=desktopZoom.load();report["desktop_frames"]=desktopFrames.load();report["desktop_open"]=desktopActive.load();report["desktop_age_ms"]=desktopFrameAt?uint32_t(millis()-desktopFrameAt):UINT32_MAX;
          report["beacon_pattern"]=beaconPattern;report["light_speed"]=lightSpeed;report["light_period_ms"]=lightPeriod(lightSpeed);report["light_timer_active"]=lightTimer!=nullptr;
          report["theme_color"]=themeColors[uiTheme];report["background_follows_theme"]=backgroundFollowsTheme;
          auto code=codeSnapshot();report["dashboard_qr_ready"]=remoteReady&&code.fresh(millis());report["dashboard_qr_revision"]=code.revision;report["quick_connect_open"]=bool(quickJoin);
          auto info=storageInfo();report["sd_state"]=storageStateName(info.state);report["sd_capacity_mib"]=info.capacityMiB;
          report["sd_records"]=info.records;report["sd_dropped"]=info.dropped;report["sd_write_errors"]=info.errors;
          // One buffered write prevents concurrent TLS diagnostics from
          // interleaving with the many small writes made by serializeJson.
          String encoded;encoded.reserve(4096);serializeJson(report,encoded);
          encoded+='\n';Serial.print(encoded);
        }
      }
    } else Serial.println("{\"error\":\"input_too_long\"}");
    memset(line,0,sizeof(line)); length=0; overflow=false;
  }
}
void setup() {
  setCpuFrequencyMhz(240);wiredViewer.pictures.reserve();
  // No desktop framebuffer queue: phone handles Pi desktop video.
  Serial.setRxBufferSize(4096);Serial.begin(115200); Serial.setTimeout(20);
  setenv("TZ","UTC0",1);tzset();
  gpio_deep_sleep_hold_dis();
  for(int p:{4,16,17,22,27})gpio_hold_dis(gpio_num_t(p));
  rtc_gpio_deinit(GPIO_NUM_0); pinMode(0,INPUT_PULLUP);
  pinMode(36,INPUT);
  pinMode(34,INPUT);analogSetPinAttenuation(34,ADC_11db);
  pinMode(4,OUTPUT); digitalWrite(4,HIGH); // Disable speaker amplifier.
  for (int pin : {22,16,17}) { pinMode(pin,OUTPUT); digitalWrite(pin,HIGH); }
  ledcSetup(0,5000,8); ledcAttachPin(27,0); ledcWrite(0,brightness);
  lcd.init(); lcd.setRotation(1);
  prefs.begin("flightdisplay",false);loadLocalProfile();
  screenRotation=prefs.getUChar("rotation",1);if(screenRotation>3)screenRotation=1;
  lcd.setRotation(screenRotation);
  piTrust=prefs.getString("pica","");
  if(prefs.getBytesLength("timekey")==65){uint8_t saved[65]={};prefs.getBytes("timekey",saved,sizeof(saved));saved[32]=0;
    if(bootstrapId(reinterpret_cast<char*>(saved))){strlcpy(timeDeviceId,reinterpret_cast<char*>(saved),sizeof(timeDeviceId));memcpy(timeKey,saved+33,32);timeKeyPresent=true;}memset(saved,0,sizeof(saved));}
  touchThreshold=prefs.getUShort("pressure",600);
  if(touchThreshold!=350&&touchThreshold!=600&&touchThreshold!=900)touchThreshold=600;
  uiTheme=prefs.getUChar("ui_theme",0)%4;lightColor=prefs.getUChar("led_color",0)%LIGHT_COLOR_COUNT;lightBrightness=prefs.getUChar("led_level",64);
  beaconPattern=prefs.getUChar("beacon_pat",0)%4;
  const uint8_t legacySpeeds[]={17,29,40,52};lightSpeed=constrain(prefs.getUChar("led_speed100",legacySpeeds[prefs.getUChar("led_speed",1)%4]),1,100);
  backgroundEffect=prefs.getUChar("bg_style_v1",0);if(backgroundEffect>=backdrop::Count)backgroundEffect=backdrop::Plain;
  backgroundColor=prefs.getUChar("bg_color",0)%BACKGROUND_COLOR_COUNT;
  for(int i=0;i<4;++i){String key=String("theme_c")+i;themeColors[i]=prefs.getUChar(key.c_str(),themeColors[i])%APPEARANCE_COLOR_COUNT;}
  backgroundFollowsTheme=prefs.getBool("bg_follow",true);applyThemeColors();
  for(int i=0;i<3;++i){int pin=i==0?22:i==1?16:17;digitalWrite(pin,HIGH);pinMode(pin,OUTPUT);ledcSetup(2+i,5000,8);ledcAttachPin(pin,2+i);ledcWrite(2+i,255);}
  esp_timer_create_args_t rearTimer={};rearTimer.callback=driveRearLight;rearTimer.name="rear-led";
  if(esp_timer_create(&rearTimer,&lightTimer)==ESP_OK){if(esp_timer_start_periodic(lightTimer,5000)!=ESP_OK){esp_timer_delete(lightTimer);lightTimer=nullptr;}}
  brightness=prefs.getUChar("brightness",210); ledcWrite(0,brightness);
  audioAvailable=beginAudio(prefs.getBool("mute",false));
  if (prefs.getUChar("touchver",0)==2&&prefs.getBytesLength("touch")==sizeof(calibration)) {
    prefs.getBytes("touch",calibration,sizeof(calibration));
    if(validCalibration(calibration)){touchReady=true;updateOrientationTouch();}
  }
  viewMutex=xSemaphoreCreateMutex(); inputQueue=xQueueCreate(8,sizeof(InputEvent));chatQueue=xQueueCreate(1,sizeof(ChatRequest));
  WiFi.mode(WIFI_STA); WiFi.setSleep(false); WiFi.setAutoReconnect(true); WiFi.persistent(false);
  beginStorage();loadWiredPair();wiredViewer.commitGuard=[](){return !powerMenu&&!sleepPending&&touchReady&&!wiredSafetyPause();};
  bool candidateStarted=false;
  if(wifiTrial.take(prefs,trialProfile,millis())){
    trialLoginConfirmed=false;
    candidateStarted=configure(trialProfile.host,trialProfile.net,trialProfile.key,trialProfile.user,trialProfile.pass,false);
    savedConnection=prefs.getBytesLength("connection")==sizeof(SavedConnection);
    if(!candidateStarted){clearConnection(trialProfile);ESP.restart();return;}
    securityNotice="Testing Wi-Fi and Pi login; old settings are saved.";
  }
  if(!candidateStarted&&prefs.getBytesLength("connection")==sizeof(SavedConnection)){
    SavedConnection saved={};prefs.getBytes("connection",&saved,sizeof(saved));
    if(saved.version==1&&memchr(saved.host,0,sizeof(saved.host))&&memchr(saved.net,0,sizeof(saved.net))&&memchr(saved.key,0,sizeof(saved.key))&&memchr(saved.user,0,sizeof(saved.user))&&memchr(saved.pass,0,sizeof(saved.pass)))
      savedConnection=configure(saved.host,saved.net,saved.key,saved.user,saved.pass,false);
    memset(&saved,0,sizeof(saved));
  }
  frame(); render();
  Serial.printf("{\"event\":\"ready\",\"firmware\":\"%s\",\"authority\":\"advisory_display_only\"}\n",VERSION);
  if(!touchReady)calibrate();
}
void requestSleep() {
  stopAudio();
  requestStorageUnmount();
  remoteReady=false; xQueueReset(inputQueue); sleepPending=true; sleepRequestedAt=millis();
  Serial.println("{\"event\":\"menu_and_boot_sleep_confirmed\"}");
}
void servicePower() {
  static bool raw=false,stable=false; static uint32_t changedAt=0;
  bool down=digitalRead(0)==LOW;
  if(down!=raw) { raw=down; changedAt=millis(); }
  if(uint32_t(millis()-changedAt)>=30)stable=raw;
  if(bootMenuGesture.tick(millis(),stable)&&!powerMenu&&!sleepPending) {
    quickJoin=false;quickWifiCode="";quickBluetoothPin="";passwordVisible=false;
    maintenanceMenu=storageMenu=false;
    maintenanceAccepted=false;xQueueReset(inputQueue);
    powerMenu=true;powerGate.cancel();dirty=true;render();
  }
  bool wasActive=powerGate.active;
  if(powerGate.tick(millis(),stable))requestSleep();
  if(wasActive!=powerGate.active)dirty=true;
  if(!sleepPending)return;
  if(audioPlaying())return;
  auto card=storageInfo();
  if(card.state==1||card.state==2||card.state==5||card.state==6)return; // Never sleep during an SD write/unmount/preparation.
  if(networkHandle&&!networkParked) {
    if(uint32_t(millis()-sleepRequestedAt)>7000) {
      sleepPending=false; dirty=true; Serial.println("{\"error\":\"sleep_cancelled_network_busy\"}");
    }
    return;
  }
  if(tlsRecoveryRequested) {
    uint32_t utc=uint32_t(time(nullptr));
    if(prefs.putULong("tls-restart",utc)!=sizeof(uint32_t)) {
      tlsRecoveryRequested=false;sleepPending=false;
      if(networkHandle){networkParked=false;vTaskResume(networkHandle);}
      linkState("TLS MEMORY RECOVERY NEEDS RESTART");requestStorageMount();return;
    }
    Serial.println("{\"event\":\"tls_memory_recovery_restart\"}");Serial.flush();ESP.restart();return;
  }
  // Check the wake source BEFORE shutting down the display or radio.
  if(esp_sleep_enable_ext0_wakeup(GPIO_NUM_0,0)!=ESP_OK) {
    sleepPending=false;if(networkHandle){networkParked=false;vTaskResume(networkHandle);}dirty=true;return;
  }
  stopWirelessSharing();WiFi.disconnect(true); WiFi.mode(WIFI_OFF); btStop();
  if(lightTimer)esp_timer_stop(lightTimer);lightDriveConfig=0;
  for(int i=0;i<3;++i){int pin=i==0?22:i==1?16:17;ledcWrite(2+i,255);ledcDetachPin(pin);pinMode(pin,OUTPUT);digitalWrite(pin,HIGH);}
  digitalWrite(4,HIGH); ledcWrite(0,0);ledcDetachPin(27);
  lcd.writecommand(0x28); lcd.writecommand(0x10);
  pinMode(27,OUTPUT);digitalWrite(27,LOW);
  for(int p:{4,16,17,22,27})gpio_hold_en(gpio_num_t(p));
  gpio_deep_sleep_hold_en();
  rtc_gpio_pullup_en(GPIO_NUM_0); rtc_gpio_pulldown_dis(GPIO_NUM_0);
  Serial.println("{\"event\":\"deep_sleep_entering\"}"); Serial.flush();
  wiredViewer.pictures.clearView();
  esp_deep_sleep_start();
}
void navigateTo(int target) {
  closeDesktop();page=(target+5)%5;powerGate.cancel();powerMenu=securityMenu=maintenanceMenu=quickJoin=storageMenu=false;
  keyboardReturnToDesktop=false;
  setupEntry=keyboardVisible=passwordVisible=false; // Local navigation preserves the timed owner lease.
  updateMenu=appearanceMenu=backgroundMenu=xiaoLightsMenu=false;
  telemetryPage=-1;
  quickWifiCode="";quickBluetoothPin="";for(auto& value:setupValues)value="";xQueueReset(inputQueue);dirty=true;
}
void openQuickJoin() {
  if(configured){requestDashboardCode();quickJoin=true;quickJoinAt=millis();dirty=true;return;}
  // Wi-Fi is already started in setup(), supplying the hardware RNG entropy.
  const char* alphabet="ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  quickWifiCode="";for(int i=0;i<20;++i)quickWifiCode+=alphabet[esp_random()&31];
  char apName[26];snprintf(apName,sizeof apName,"Display-Setup-%04x",unsigned(esp_random()&0xffff));quickWifiName=apName;
  if(!startProtectedHotspot(quickWifiName,quickWifiCode)){quickWifiCode="";securityNotice="Could not start protected hotspot.";dirty=true;return;}
  quickJoin=true;quickJoinAt=millis();quickBluetoothPin="";dirty=true;
}
void generateQuickPin() {
  if(bluetoothAuthenticated()){quickBluetoothPin="";securityNotice="Stop sharing before starting a new pairing.";dirty=true;return;}
  uint32_t chosen=0;
  for(int i=0;i<16;++i){char value[7];snprintf(value,sizeof(value),"%06lu",(unsigned long)(esp_random()%1000000));if(pairingPin(value,chosen)){quickBluetoothPin=value;break;}}
  if(!quickBluetoothPin.length()||!openBluetoothPairing(quickBluetoothPin))quickBluetoothPin="UNAVAILABLE";
  dirty=true;
}
void handleTap(uint16_t x,uint16_t y) {
  ++tapsSeen;
  if(y<50&&x>=417){rotateDisplay();return;}
  if(y>=278&&x>=12&&x<480){navigateTo(constrain((int(x)-12)/94,0,4));return;}
  if(telemetryPage>=0){if(y>=242&&y<=272){if(x<160)telemetryPage=(telemetryPage+TELEMETRY_PAGES-1)%TELEMETRY_PAGES;else if(x<320)telemetryPage=(telemetryPage+1)%TELEMETRY_PAGES;else telemetryPage=-1;dirty=true;}return;}
  if(page<2&&x>=330&&y>=55&&y<77&&!powerMenu&&!storageMenu&&!quickJoin&&!maintenanceMenu&&!updateMenu){telemetryPage=page==1?4:0;dirty=true;return;}
  if(updateMenu){if(y>=235&&y<=268){if(x>=250)updateMenu=false;else if(x>=18&&remoteReady&&updatePolicyKnown&&updateDesired<0){updateDesired=updatePolicyEnabled?0:1;if(xSemaphoreTake(viewMutex,pdMS_TO_TICKS(20))==pdTRUE){updateNotice="Request pending; Pi applies its flight guards.";xSemaphoreGive(viewMutex);}}dirty=true;}return;}
  if(storageMenu){if(y>=215&&y<=248){if(x>=18&&x<238)requestStorageMount();else if(x>=250&&x<=460)requestStorageUnmount();dirty=true;}return;}
  if(backgroundMenu){
    if(y>=184&&y<218){
      if(x>=16&&x<236){backgroundEffect=(backgroundEffect+1)%backdrop::Count;prefs.putUChar("bg_style_v1",backgroundEffect);}
      else if(x>=245&&x<465){backgroundColor=(effectiveBackgroundColor(backgroundFollowsTheme,themeColors[uiTheme],backgroundColor)+1)%BACKGROUND_COLOR_COUNT;backgroundFollowsTheme=false;prefs.putBool("bg_follow",false);prefs.putUChar("bg_color",backgroundColor);}
      applyThemeColors();
    }
    else if(y>=220&&y<244){backgroundFollowsTheme=!backgroundFollowsTheme;prefs.putBool("bg_follow",backgroundFollowsTheme);applyThemeColors();}
    else if(y>=244&&y<274){backgroundMenu=false;appearanceMenu=true;}
    dirty=true;return;
  }
  if(xiaoLightsMenu){
    if(y>=246&&y<274){xiaoLightsMenu=false;appearanceMenu=true;dirty=true;return;}
    if(y<110||y>=242||!xiaoLights.ready())return;
    auto c=xiaoLights.editBase();int row=(y-110)/22;
    switch(row){
      case 0:c.mode=(c.mode+1)%6;break;case 1:c.color=(c.color+1)%11;break;
      case 2:{int pct=(int(c.brightness)*100+127)/255;pct=constrain(pct+lightAdjustment(x),0,100);c.brightness=(pct*255+50)/100;break;}
      case 3:selectBeacon(c.mode,c.pattern);break;
      case 4:c.speed=constrain(int(c.speed)+lightAdjustment(x),1,100);break;
      case 5:c.yellow=(c.yellow+1)%4;break;
    }
    xiaoLights.set(c);return;
  }
  if(appearanceMenu){
    if(y>=78&&y<=106&&x>=145&&x<298){appearanceMenu=false;xiaoLightsMenu=true;xiaoLights.probe();dirty=true;return;}
    if(y>=78&&y<=106&&x>=300){backgroundMenu=true;appearanceMenu=false;dirty=true;return;}
    if(y>=112&&y<131){uiTheme=(uiTheme+1)%4;prefs.putUChar("ui_theme",uiTheme);applyThemeColors();}
    else if(y>=131&&y<150){themeColors[uiTheme]=(themeColors[uiTheme]+1)%APPEARANCE_COLOR_COUNT;String key=String("theme_c")+uiTheme;prefs.putUChar(key.c_str(),themeColors[uiTheme]);applyThemeColors();}
    else if(y>=150&&y<169)lightMode=(lightMode+1)%6;
    else if(y>=169&&y<188){lightColor=(lightColor+1)%LIGHT_COLOR_COUNT;prefs.putUChar("led_color",lightColor);}
    else if(y>=188&&y<207){int percent=(int(lightBrightness)*100+127)/255;percent=constrain(percent+lightAdjustment(x),0,100);lightBrightness=(percent*255+50)/100;prefs.putUChar("led_level",lightBrightness);}
    else if(y>=207&&y<226){selectBeacon(lightMode,beaconPattern);prefs.putUChar("beacon_pat",beaconPattern);}
    else if(y>=226&&y<245){lightSpeed=constrain(int(lightSpeed)+lightAdjustment(x),1,100);prefs.putUChar("led_speed100",lightSpeed);}
    else if(y>=247&&y<274){if(x<240)lightMode=lightMode==5?0:5;else appearanceMenu=false;}
    dirty=true;return;
  }
  if(quickJoin) {
    if(x>=218&&x<=464&&y>=182&&y<=214){if(configured)requestDashboardCode();else generateQuickPin();dirty=true;}
    else if(x>=218&&x<=464&&y>=244&&y<=269){quickJoin=false;quickWifiCode="";quickBluetoothPin="";dirty=true;}
    return;
  }
  if(maintenanceMenu) {
    if(y>=226&&y<=259){
      if(x>=18&&x<238){
        if(maintenanceAccepted){maintenanceAccepted=false;ownerUnlockPending=false;xQueueReset(inputQueue);}
        else {ownerUnlockPending=true;ownerUnlockDeadline=millis()+8000;}
      }
      else if(x>=250&&x<=460)maintenanceMenu=false;
      dirty=true;
    }return;
  }
  if(powerMenu) {
    if(y>=205&&y<=238){
      if(x>=18&&x<238){powerGate.prepare(millis());dirty=true;}
      else if(x>=250&&x<=460){powerGate.cancel();powerMenu=false;dirty=true;}
    }else if(y>=241&&y<=257){
      if(x>=18&&x<238){setAudioMute(!audioMuted());prefs.putBool("mute",audioMuted());dirty=true;}
      else if(x>=250&&x<=460)queueAudio(0);
    }return;
  }
  if(page==4&&setupEntry&&secretEntry()&&x>=390&&x<=464&&y>=94&&y<=112){passwordVisible=!passwordVisible;passwordShownAt=millis();entryValueDirty=true;return;}
  if((page==2&&keyboardVisible)||((page==3||page==4)&&setupEntry)){keyboardTouch(x,y);return;}
  if(page==3&&y>=125&&y<203){aiOffset+=320;if(aiOffset>=aiAnswer.length())aiOffset=0;dirty=true;return;}
  if(page==3&&y>=207&&y<=237&&x>=16&&x<464){
    int which=(x-16)/114;const char* questions[]={"What is my current flight status?","Which sensors are reporting verified data?","How is offline learning configured?"};
    if(which<3)askTeam(questions[which]);else{entryMode=3;setupEntry=true;setupField=0;setupValues[0]="";dirty=true;}return;
  }
  if(page==4&&!securityMenu&&y>=78&&y<=106&&x>=16&&x<230){appearanceMenu=true;dirty=true;return;}
  if(page==4&&!securityMenu&&y>=78&&y<=106&&x>=352&&x<=464){storageMenu=true;dirty=true;return;}
  if(page==4&&!securityMenu&&y>=78&&y<=106&&x>=238&&x<343){updateMenu=true;dirty=true;return;}
  if(page==2&&y>=113&&y<224&&x>=16&&x<464){openQuickJoin();return;}
  if(page==2&&y>=235&&y<=267&&x>=246&&x<464){
    if(!touchReady){calibrate();return;}
    wiredViewer.select();
    if(wiredViewer.canOpen()&&!wiredSafetyPause())startWiredViewer();
    return;
  }

  if(page==4&&securityMenu){
    if(y>=115&&y<142)openQuickJoin();
    else if(y>=146&&y<173){entryMode=1;setupField=0;setupEntry=true;passwordVisible=false;setupValues[0]="FlightTeam-Display";dirty=true;}
    else if(y>=177&&y<204){entryMode=2;setupField=0;setupEntry=true;passwordVisible=false;dirty=true;}
    else if(y>=208&&y<235){stopWirelessSharing();securityNotice="Hotspot and Bluetooth stopped.";dirty=true;}
    return;
  }
  if(page==2&&y>=235&&y<=267&&x>=16&&x<236){updateMenu=true;dirty=true;
  }else if(page==4&&y>=115&&y<=144){
    entryMode=0;setupEntry=true;setupField=0;passwordVisible=false;for(auto& value:setupValues)value="";
    setupValues[0]=ssid;setupValues[2]=endpoint;setupValues[3]=username;dirty=true;
  }else if(page==4&&y>=185&&y<205){touchThreshold=touchThreshold==350?600:touchThreshold==600?900:350;prefs.putUShort("pressure",touchThreshold);dirty=true;}
  else if(page==4&&y>=244&&y<=271&&x>=16&&x<=236){powerMenu=true;powerGate.cancel();dirty=true;}
  else if(page==4&&y>=244&&y<=271&&x>=245&&x<=465){securityMenu=true;dirty=true;}
  else if(page==4&&y>=207&&y<=237){
    if(x<150)brightness=max(35,int(brightness)-35);else if(x<300)brightness=min(255,int(brightness)+35);else calibrate();
    ledcWrite(0,brightness);prefs.putUChar("brightness",brightness);dirty=true;
  }
}
void loop() {
  if(wifiTrial.active()){
    auto result=wifiTrial.finish(prefs,trialProfile,trialLoginConfirmed.load(),millis());
    if(result!=ConnectionTrial::Result::Waiting){
      clearConnection(trialProfile);
      if(result==ConnectionTrial::Result::Restore){ESP.restart();return;}
      securityNotice="Verified Wi-Fi and Pi login saved.";dirty=true;
    }
  }
  if(tlsRecoveryRequested&&!sleepPending) {
    stopAudio();requestStorageUnmount();remoteReady=false;xQueueReset(inputQueue);
    sleepPending=true;sleepRequestedAt=millis();
    linkState("RECOVERING SECURE CONNECTION");
  }

  serialInput();serviceDisplayBattery();servicePower();serviceAppearance();serviceWireless(viewFresh(snapshot(),millis()));
  if(ownerUnlockPending){
    if(!maintenanceMenu||int32_t(millis()-ownerUnlockDeadline)>=0){ownerUnlockPending=false;dirty=true;}
    else if(maintenanceReady()){maintenanceAt=millis();maintenanceEpoch=remoteEpoch;maintenanceAccepted=true;ownerUnlockPending=false;dirty=true;}
  }
  if(maintenanceAccepted){
    FlightView ownerView=snapshot();uint32_t ownerNow=millis();
    bool revoke=!ownerLeaseHeld(true,maintenanceEpoch,remoteEpoch,ownerNow,maintenanceAt)||(ownerView.armedKnown&&ownerView.armed)||(ownerView.groundKnown&&uint32_t(ownerNow-ownerView.groundReceived)<1500&&!ownerView.onGround);
    if(revoke){maintenanceAccepted=false;xQueueReset(inputQueue);dirty=true;}
    else if(!maintenanceEnabled())xQueueReset(inputQueue); // Pause; never replay queued input after recovery.
  }
  static bool priorPair=false,priorAuth=false;
  bool pair=bluetoothPairingOpen(),auth=bluetoothAuthenticated();
  if((pair!=priorPair||auth!=priorAuth)&&securityMenu)dirty=true;priorPair=pair;priorAuth=auth;
  if(quickJoin&&!configured&&uint32_t(millis()-quickJoinAt)>120000){quickJoin=false;quickWifiCode="";quickBluetoothPin="";dirty=true;}
  if(quickBluetoothPin.length()&&!bluetoothPairingOpen()){quickBluetoothPin="";dirty=true;}
  if(passwordVisible&&uint32_t(millis()-passwordShownAt)>15000){passwordVisible=false;entryValueDirty=true;}
  static uint32_t priorStorage=UINT32_MAX;
  auto info=storageInfo();if(info.state!=priorStorage&&storageMenu)dirty=true;priorStorage=info.state;
  static uint32_t noticeAt=0;
  if(uint32_t(millis()-noticeAt)>=180){noticeAt=millis();wiredViewer.setNotice(lcd,wiredNoticeNow());}
  if(!sleepPending){
    uint32_t previous=xiaoLights.revision;xiaoLights.service(xiaoLightsMenu);
    if(xiaoLightsMenu&&previous!=xiaoLights.revision)dirty=true;
  }
  if(wiredViewer.active()){
    bool priority=wiredPriorityActive();
    bool penDown=digitalRead(36)==LOW,sideband=xiaoLights.pending();
    if(!wiredViewer.step(lcd,touchThreshold,!wiredSafetyPause()&&!powerMenu&&!sleepPending&&touchReady,penDown,sideband)){
      finishWiredViewer();
      if(priority&&!powerMenu&&!sleepPending&&!strcmp(wiredGuardReason(),"new serious alert")){
        wiredPriorityCard=true;wiredCardWaitRelease=true;paintWiredPriorityCard(wiredNoticeNow());
      }
    }
    delay(wiredViewer.bulkSpi(penDown,sideband)?1:2);return;
  }
  if(!sleepPending)wiredViewer.step(lcd,touchThreshold,false,true,xiaoLights.pending());
  if(wiredPriorityCard){
    bool show=!powerMenu&&!sleepPending&&!calibrating&&!setupEntry&&!keyboardVisible&&
              !strcmp(wiredGuardReason(),"new serious alert");
    bool down=digitalRead(36)==LOW;
    if(!down)wiredCardWaitRelease=false;
    bool dismiss=down&&!wiredCardWaitRelease;
    if(show&&!dismiss){paintWiredPriorityCard(wiredNoticeNow());delay(8);return;}
    if(dismiss)wiredViewer.dismiss();
    wiredPriorityCard=false;lastScene="";renderSignature="";dirty=true;waitTouchRelease=true;
  }
  if(calibrating&&!powerMenu){serviceCalibration();delay(8);return;}
  if(waitTouchRelease){if(digitalRead(36)!=LOW)waitTouchRelease=false;delay(8);return;}
  uint16_t x=0,y=0;bool touched=touchReady&&lcd.getTouch(&x,&y,touchThreshold);
  if(touched)wiredLastInteraction=millis();
  if(wiredViewer.canOpen() && touchReady && !touched && !touchGesture.active &&
     (page==0||page==2) && telemetryPage<0 && !powerMenu && !sleepPending &&
     !storageMenu&&!securityMenu&&!maintenanceMenu&&!appearanceMenu&&!backgroundMenu&&!xiaoLightsMenu&&!updateMenu&&
     !setupEntry&&!keyboardVisible&&!quickJoin&&!ownerUnlockPending&&!maintenanceAccepted&&
     uint32_t(millis()-wiredLastInteraction)>2500&&!wiredSafetyPause()) {
    startWiredViewer();return;
  }
  const bool pad=false;
  bool navigation=!pad&&(!(setupEntry||keyboardVisible)||y<75||y>=(portrait()?440:278));
  TouchResult action=touchGesture.feed(millis(),touched,x,y,navigation,!pad);
  if(action.kind==TouchKind::SwipeLeft||action.kind==TouchKind::SwipeRight){++swipesSeen;navigateTo(int(page)+(action.kind==TouchKind::SwipeLeft?1:-1));}
  else if(action.kind==TouchKind::Tap){
    if(portrait()){uint16_t tx,ty;if(portraitAction(portraitHits,portraitHitCount,action.x,action.y,tx,ty))handleTap(tx,ty);}
    else handleTap(action.x,action.y);
  }
  if(!touchReady&&!calibrating&&!powerMenu){rawZ=lcd.getTouchRawZ();if(digitalRead(36)==LOW&&rawZ>touchThreshold&&rawZ<4090)calibrate();}
  if(entryValueDirty&&setupEntry&&!powerMenu&&!quickJoin&&!storageMenu&&!maintenanceMenu){if(portrait())dirty=true;else drawEntryValue();}
  if(dirty||uint32_t(millis()-redrawAt)>750){redrawAt=millis();render();}
  delay(8);
}

void updateOrientationTouch(){if(touchReady){uint16_t values[5];orientedCalibration(calibration,screenRotation,values);lcd.setTouch(values);}}
bool wiredPriorityActive(){
  portENTER_CRITICAL(&wiredNoticeLock);
  bool hard=wiredNotices.hard(millis());
  portEXIT_CRITICAL(&wiredNoticeLock);
  return hard;
}
wirednotice::Notice wiredNoticeNow(){
  portENTER_CRITICAL(&wiredNoticeLock);
  auto notice=wiredNotices.current(millis());
  portEXIT_CRITICAL(&wiredNoticeLock);
  if(notice.level==wirednotice::None&&audioPlaying()){
    notice.level=wirednotice::Audio;strcpy(notice.text,"Display audio playing");
  }
  return notice;
}
const char* wiredGuardReason(){
  FlightView v=snapshot();
  if(v.armedKnown&&v.armed)return "armed";
  if(v.sourceMismatch)return "controller source mismatch";
  if(v.groundKnown&&!v.onGround&&uint32_t(millis()-v.groundReceived)<1500)return "airborne";
  if(wiredPriorityActive())return "new serious alert";
  return "clear";
}
bool wiredSafetyPause(){return strcmp(wiredGuardReason(),"clear")!=0;}
void paintWiredPriorityCard(const wirednotice::Notice& notice){
  static wirednotice::Notice prior;
  if(!dirty&&prior.level==notice.level&&!strcmp(prior.text,notice.text))return;
  prior=notice;dirty=false;
  lcd.fillScreen(0x3000);lcd.setTextColor(TFT_WHITE,0x3000);
  lcd.drawString(wirednotice::label(notice.level),14,18,4);
  lcd.drawString("Paired desktop paused",14,62,2);
  unsigned perLine=(lcd.width()-28)/12;
  for(unsigned start=0,line=0;start<strlen(notice.text)&&line<8;start+=perLine,++line){
    char row[42]{};unsigned n=min(unsigned(strlen(notice.text+start)),min(perLine,41u));
    for(unsigned i=0;i<n;++i){char c=notice.text[start+i];row[i]=(uint8_t(c)>=32&&uint8_t(c)<=126)?c:' ';}
    lcd.drawString(row,14,100+18*line,2);
  }
  lcd.drawString("Tap for normal display",14,lcd.height()-35,2);
}
void startWiredViewer(){
  lcd.setRotation(1);lcd.setTouch(calibration);wiredViewer.open(lcd);
}
void finishWiredViewer(){
  if(wiredViewer.active())wiredViewer.close(lcd,true);
  lcd.setRotation(screenRotation);updateOrientationTouch();
  touchGesture=Gesture();waitTouchRelease=true;lastScene="";renderSignature="";dirty=true;
}
void rotateDisplay(){
  if(calibrating||sleepPending)return;
  closeDesktop();screenRotation=(screenRotation+1)%4;lcd.setRotation(screenRotation);updateOrientationTouch();
  prefs.putUChar("rotation",screenRotation);powerGate.cancel();xQueueReset(inputQueue); // Rotation preserves the timed owner lease; discard only pending input.
  touchGesture=Gesture();waitTouchRelease=true;dirty=true;renderSignature="";
}
#include "PortraitUI.h"
#include "PersonalizationUI.h"
#include "TelemetryUI.h"

bool bootstrapPiTime(){
  if(!timeKeyPresent||WiFi.status()!=WL_CONNECTED)return false;
  uint8_t nonceBytes[32];esp_fill_random(nonceBytes,sizeof(nonceBytes));char nonce[65]={};
  const char* hex="0123456789abcdef";for(int i=0;i<32;++i){nonce[i*2]=hex[nonceBytes[i]>>4];nonce[i*2+1]=hex[nonceBytes[i]&15];}
  StaticJsonDocument<256> request;request["device_id"]=timeDeviceId;request["nonce_hex64"]=nonce;String body;serializeJson(request,body);
  WiFiUDP udp;if(!udp.begin(49152+(esp_random()%16384)))return false;
  IPAddress target,local=WiFi.localIP(),mask=WiFi.subnetMask(),broadcast;
  for(int i=0;i<4;++i)broadcast[i]=local[i]|uint8_t(~mask[i]);
  if(target.fromString(endpoint)&&privateAddress(endpoint.c_str())){udp.beginPacket(target,8444);udp.write(reinterpret_cast<const uint8_t*>(body.c_str()),body.length());udp.endPacket();}
  udp.beginPacket(broadcast,8444);udp.write(reinterpret_cast<const uint8_t*>(body.c_str()),body.length());udp.endPacket();
  uint32_t began=millis();bool accepted=false;
  while(uint32_t(millis()-began)<3000&&!sleepPending){
    int size=udp.parsePacket();if(!size){vTaskDelay(pdMS_TO_TICKS(10));continue;}
    IPAddress source=udp.remoteIP();bool sameSubnet=true;for(int i=0;i<4;++i)if((source[i]&mask[i])!=(local[i]&mask[i]))sameSubnet=false;
    if(size>512||udp.remotePort()!=8444||!sameSubnet||source==local||!privateAddress(source.toString().c_str())){udp.flush();continue;}
    char response[513]={};int count=udp.read(reinterpret_cast<uint8_t*>(response),size);if(count!=size)continue;
    StaticJsonDocument<768> reply;if(deserializeJson(reply,response,size,DeserializationOption::NestingLimit(3)))continue;
    if(reply["device_id"]!=timeDeviceId||reply["nonce_hex64"]!=nonce||!reply["unix"].is<uint32_t>())continue;
    uint32_t epoch=reply["unix"];uint8_t claimed[32],computed[32];const char* mac=reply["mac_hex64"]|"";
    if(!bootstrapEpoch(epoch)||!decodeHex256(mac,claimed))continue;
    char canonical[192];int length=snprintf(canonical,sizeof(canonical),"flight-team-time-v1\n%s\n%s\n%lu\n",timeDeviceId,nonce,(unsigned long)epoch);
    if(length<=0||length>=int(sizeof(canonical)))continue;
    const mbedtls_md_info_t* md=mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if(!md||mbedtls_md_hmac(md,timeKey,32,reinterpret_cast<const uint8_t*>(canonical),length,computed)!=0||!constantTime256(computed,claimed))continue;
    // Only a fresh nonce authenticated by the locally provisioned key may set
    // wall time or discover the Pi address. App TLS still checks CA/name/dates.
    struct timeval value={time_t(epoch),0};if(settimeofday(&value,nullptr)!=0)continue;
    endpoint=source.toString();accepted=true;break;
  }
  udp.stop();return accepted;
}
