// Driver fixture for the actual Wireless.cpp callbacks; synthetic peers only.
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <ArduinoJson.h>
struct String:std::string{using std::string::string;};
uint32_t now=10;
uint32_t millis(){return now;}
using portMUX_TYPE=int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) ((void)p)
#define portEXIT_CRITICAL(p) ((void)p)
void esp_fill_random(void* p,size_t n){memset(p,7,n);}
#define MYNEWT_VAL(x) 1
enum{WL_CONNECTED=3,WIFI_AP_STA=2,WIFI_IF_AP=1,WIFI_AUTH_WPA2_PSK=3,WIFI_CIPHER_TYPE_CCMP=4,ESP_OK=0,BLE_HS_IO_DISPLAY_ONLY=1};
struct wifi_config_t{struct{int authmode,pairwise_cipher;}ap;};
wifi_config_t accessPoint{};
int esp_wifi_get_config(int,wifi_config_t* c){*c=accessPoint;return ESP_OK;}
int esp_wifi_set_config(int,const wifi_config_t* c){accessPoint=*c;return ESP_OK;}
struct {bool online=false,running=false;unsigned clients=0;
 int status(){return online?WL_CONNECTED:0;}void persistent(bool value){assert(!value);}
 bool mode(int){return true;}bool softAP(const char*,const char*,int,bool,unsigned count){clients=count;running=true;return true;}
 void softAPdisconnect(bool){running=false;}
} WiFi;
struct NimBLEConnInfo{
 uint16_t handle;bool secure,mitm;unsigned bytes;auto getConnHandle(){return handle;}
 bool isEncrypted(){return secure;}bool isAuthenticated(){return mitm;}unsigned getSecKeySize(){return bytes;}
};
struct NimBLEServer;struct NimBLECharacteristic;
struct NimBLEServerCallbacks{
 virtual void onConnect(NimBLEServer*,NimBLEConnInfo&)=0;
 virtual uint32_t onPassKeyDisplay()=0;virtual void onConfirmPassKey(NimBLEConnInfo&,uint32_t)=0;
 virtual void onAuthenticationComplete(NimBLEConnInfo&)=0;virtual void onDisconnect(NimBLEServer*,NimBLEConnInfo&,int)=0;
};
struct NimBLECharacteristicCallbacks{
 virtual void onRead(NimBLECharacteristic*,NimBLEConnInfo&){};virtual void onWrite(NimBLECharacteristic*,NimBLEConnInfo&){};
};
struct NIMBLE_PROPERTY{enum{READ=1,READ_ENC=2,READ_AUTHEN=4,WRITE=8,WRITE_ENC=16,WRITE_AUTHEN=32};};
struct NimBLECharacteristic{
 std::string value;NimBLECharacteristicCallbacks* cb=nullptr;
 void setCallbacks(NimBLECharacteristicCallbacks* p){cb=p;}
 void setValue(const char* v){value=v;}std::string getValue(){return value;}
};
struct MockService{
 NimBLECharacteristic chars[2];unsigned count=0;
 auto createCharacteristic(const char*,unsigned props,unsigned=0){
   assert(props==(count?56u:7u));return &chars[count++];
 }
};
struct NimBLEServer{
 NimBLEServerCallbacks* cb=nullptr;MockService service;std::vector<unsigned> dropped;
 void setCallbacks(NimBLEServerCallbacks* p,bool){cb=p;}void advertiseOnDisconnect(bool value){assert(!value);}
 auto createService(const char*){service.count=0;return &service;}
 bool start(){return true;}auto getPeerDevices(){return std::vector<uint16_t>{};}
 void disconnect(uint16_t id){dropped.push_back(id);}
};
struct Adv{void setName(const char*){};void addServiceUUID(const char*){};void enableScanResponse(bool){};};
struct NimBLEDevice{
 static inline NimBLEServer server;static inline Adv ad;static inline bool advert=false;static inline uint32_t pin=0;
 static bool init(const char*){return true;}static void deinit(bool){};static auto createServer(){return &server;}
 static auto getServer(){return &server;}static auto getAdvertising(){return &ad;}
 static bool startAdvertising(){return advert=true;}static void stopAdvertising(){advert=false;}
 static void setSecurityAuth(bool bond,bool mitm,bool sc){assert(!bond&&mitm&&sc);}
 static void setSecurityIOCap(int cap){assert(cap==BLE_HS_IO_DISPLAY_ONLY);}
 static void setSecurityPasskey(uint32_t key){pin=key;}static void startSecurity(uint16_t){}
 static void injectConfirmPasskey(NimBLEConnInfo&,bool yes){assert(!yes);}
};
#include "../src/Wireless.cpp"
int main(){
 assert(!startProtectedHotspot("test","short"));
 assert(startProtectedHotspot("test","dummy-password-80")&&WiFi.clients==2&&hotspotEnabled());
 assert(accessPoint.ap.authmode==WIFI_AUTH_WPA2_PSK&&accessPoint.ap.pairwise_cipher==WIFI_CIPHER_TYPE_CCMP);
 WiFi.online=true;assert(!startProtectedHotspot("test","dummy-password-80"));WiFi.online=false;
 auto& s=NimBLEDevice::server;
 assert(!openBluetoothPairing("123456")&&openBluetoothPairing("037492"));
 assert(bluetoothPairingOpen()&&s.cb->onPassKeyDisplay()==37492&&NimBLEDevice::advert);
 NimBLEConnInfo a{4,true,true,16},b{8,true,false,16};
 s.cb->onConnect(&s,b);s.cb->onAuthenticationComplete(b);
 assert(!bluetoothAuthenticated()&&bluetoothPairingOpen()&&s.dropped.back()==8);
 s.cb->onConnect(&s,a);s.cb->onAuthenticationComplete(a);
 assert(bluetoothAuthenticated()&&!bluetoothPairingOpen()&&!NimBLEDevice::advert);
 assert(!openBluetoothPairing("357951"));
 s.cb->onDisconnect(&s,b,0);assert(bluetoothAuthenticated());
 auto& status=s.service.chars[0];status.cb->onRead(&status,a);assert(!status.value.empty());
 status.cb->onRead(&status,b);assert(status.value.empty());
 s.cb->onDisconnect(&s,a,0);assert(!bluetoothAuthenticated()&&!NimBLEDevice::advert);
 assert(openBluetoothPairing("813695"));now+=60000;serviceWireless(false);
 assert(!bluetoothPairingOpen()&&!NimBLEDevice::advert&&s.cb->onPassKeyDisplay()==0);
 s.cb->onConnect(&s,a);assert(s.dropped.back()==4);
 stopWirelessSharing();assert(!hotspotEnabled()&&!WiFi.running&&!bluetoothAuthenticated());
}
