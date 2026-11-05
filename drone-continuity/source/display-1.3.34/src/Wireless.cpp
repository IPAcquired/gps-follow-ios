#include <Arduino.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <NimBLEDevice.h>
#include <atomic>
#include <ArduinoJson.h>
#include "Wireless.h"
#include "WirelessPolicy.h"
namespace {
static_assert(MYNEWT_VAL(BLE_SM_SC_ONLY)==1,"Legacy BLE pairing must not be accepted");
bool ap=false,initialized=false;
std::atomic<bool> window{false},authenticated{false},live{false};
std::atomic<uint32_t> openedAt{0},passkey{0};
NimBLECharacteristic* statusCharacteristic=nullptr;
PhoneLocation location;
portMUX_TYPE locationMux=portMUX_INITIALIZER_UNLOCKED;
void stopPhoneLocation(){portENTER_CRITICAL(&locationMux);if(location.active){location.active=false;if(location.seq<UINT32_MAX-1)++location.seq;++location.revision;}portEXIT_CRITICAL(&locationMux);}
constexpr const char* SERVICE="7357f100-1d32-4f53-9a30-402131baa301";
class PeerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* server,NimBLEConnInfo& peer) override {
    if(!pairingWindow(millis(),openedAt,window)) {server->disconnect(peer.getConnHandle());return;}
    NimBLEDevice::startSecurity(peer.getConnHandle());
  }
  uint32_t onPassKeyDisplay() override {return passkey;}
  void onConfirmPassKey(NimBLEConnInfo& peer,uint32_t) override {
    // This device uses display-only PIN entry. Never auto-accept comparison.
    NimBLEDevice::injectConfirmPasskey(peer,false);
  }
  void onAuthenticationComplete(NimBLEConnInfo& peer) override {
    if(!pairingWindow(millis(),openedAt,window)||!peer.isEncrypted()||!peer.isAuthenticated()||peer.getSecKeySize()!=16) {
      NimBLEDevice::getServer()->disconnect(peer.getConnHandle());return;
    }
    window=false;NimBLEDevice::stopAdvertising();
    PhoneLocation next;uint8_t epoch[16];esp_fill_random(epoch,sizeof(epoch));const char* hex="0123456789abcdef";
    for(int i=0;i<16;++i){next.epoch[i*2]=hex[epoch[i]>>4];next.epoch[i*2+1]=hex[epoch[i]&15];}
    portENTER_CRITICAL(&locationMux);next.revision=location.revision+1;location=next;portEXIT_CRITICAL(&locationMux);
    authenticated=true;
  }
  void onDisconnect(NimBLEServer*,NimBLEConnInfo&,int) override {
    authenticated=false;
    stopPhoneLocation();
    if(pairingWindow(millis(),openedAt,window))NimBLEDevice::startAdvertising();
  }
} peerCallbacks;
class StatusCallbacks : public NimBLECharacteristicCallbacks {
  void onRead(NimBLECharacteristic* characteristic,NimBLEConnInfo& peer) override {
    // ATT requires MITM-authenticated encryption. GPS has a separate bounded
    // observation-only characteristic; no flight-command characteristic exists.
    if(!peer.isEncrypted()||!peer.isAuthenticated()||peer.getSecKeySize()!=16) {
      characteristic->setValue("");NimBLEDevice::getServer()->disconnect(peer.getConnHandle());return;
    }
    characteristic->setValue(live?"flight-team;telemetry=live;authority=display-only":"flight-team;telemetry=unavailable;authority=display-only");
  }
} statusCallbacks;
class LocationCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic,NimBLEConnInfo& peer) override {
    if(!authenticated||!peer.isEncrypted()||!peer.isAuthenticated()||peer.getSecKeySize()!=16){NimBLEDevice::getServer()->disconnect(peer.getConnHandle());return;}
    auto value=characteristic->getValue();if(value.length()==0||value.length()>192)return;
    StaticJsonDocument<512> doc;if(deserializeJson(doc,value.data(),value.length(),DeserializationOption::NestingLimit(2)))return;
    if(!doc["v"].is<int>()||doc["v"].as<int>()!=1||!doc["seq"].is<uint32_t>()||doc["seq"].is<bool>())return;
    uint32_t seq=doc["seq"],now=millis();PhoneLocation previous=phoneLocationSnapshot();
    if(seq<=previous.seq||seq==0||seq==UINT32_MAX||!previous.epoch[0])return;
    if(doc["stop"].is<bool>()&&doc["stop"].as<bool>()){
      portENTER_CRITICAL(&locationMux);location.active=false;location.seq=seq;location.received=now;++location.revision;portEXIT_CRITICAL(&locationMux);return;
    }
    if(!doc["age_ms"].is<uint32_t>()||doc["age_ms"].is<bool>()||!doc["lat"].is<double>()||doc["lat"].is<bool>()||!doc["lon"].is<double>()||doc["lon"].is<bool>()||!doc["accuracy_m"].is<double>()||doc["accuracy_m"].is<bool>())return;
    uint32_t age=doc["age_ms"];double lat=doc["lat"],lon=doc["lon"],accuracy=doc["accuracy_m"];
    if(!phoneLocationValues(seq,previous.seq,age,lat,lon,accuracy)||(previous.active&&uint32_t(now-previous.received)<150))return;
    previous.seq=seq;previous.age=age;previous.received=now;previous.latitude=lat;previous.longitude=lon;previous.accuracy=accuracy;previous.active=true;++previous.revision;
    portENTER_CRITICAL(&locationMux);location=previous;portEXIT_CRITICAL(&locationMux);
  }
} locationCallbacks;
}
bool startProtectedHotspot(const String& name,const String& password) {
  if(WiFi.status()==WL_CONNECTED)return false; // Preserve heap for authenticated Pi TLS.
  if(name.length()<1||name.length()>32||!strongHotspotPassword(password.c_str()))return false;
  // Runtime-only password, WPA2-PSK/CCMP. This IDF 4.4 SoftAP lacks a PMF setting;
  // do not claim deauthentication/jamming resistance.
  // No captive portal, HTTP server, NAT, remote shell or firmware update listener.
  WiFi.persistent(false);
  if(!WiFi.mode(WIFI_AP_STA)||!WiFi.softAP(name.c_str(),password.c_str(),1,false,2))return false;
  wifi_config_t config={};
  if(esp_wifi_get_config(WIFI_IF_AP,&config)!=ESP_OK){WiFi.softAPdisconnect(true);return false;}
  config.ap.authmode=WIFI_AUTH_WPA2_PSK;config.ap.pairwise_cipher=WIFI_CIPHER_TYPE_CCMP;
  if(esp_wifi_set_config(WIFI_IF_AP,&config)!=ESP_OK){WiFi.softAPdisconnect(true);return false;}
  ap=true;return true;
}
bool openBluetoothPairing(const String& pin) {
  uint32_t chosen;if(!pairingPin(pin.c_str(),chosen))return false;
  if(!initialized) {
    if(!NimBLEDevice::init("FlightTeam-Display"))return false;
    initialized=true;
    NimBLEDevice::setSecurityAuth(false,true,true); // No retained bonds; MITM + secure connections.
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);
    auto server=NimBLEDevice::createServer();server->setCallbacks(&peerCallbacks,false);
    server->advertiseOnDisconnect(false);
    auto service=server->createService(SERVICE);
    statusCharacteristic=service->createCharacteristic("7357f101-1d32-4f53-9a30-402131baa301",NIMBLE_PROPERTY::READ|NIMBLE_PROPERTY::READ_ENC|NIMBLE_PROPERTY::READ_AUTHEN);
    statusCharacteristic->setCallbacks(&statusCallbacks);statusCharacteristic->setValue("");
    auto gps=service->createCharacteristic("7357f102-1d32-4f53-9a30-402131baa301",NIMBLE_PROPERTY::WRITE|NIMBLE_PROPERTY::WRITE_ENC|NIMBLE_PROPERTY::WRITE_AUTHEN,192);
    gps->setCallbacks(&locationCallbacks);
    if(!server->start()){stopBluetooth();return false;}
    auto advertising=NimBLEDevice::getAdvertising();advertising->setName("FlightTeam-Display");advertising->addServiceUUID(SERVICE);advertising->enableScanResponse(true);
  }
  window=false;NimBLEDevice::stopAdvertising();
  for(auto handle:NimBLEDevice::getServer()->getPeerDevices())NimBLEDevice::getServer()->disconnect(handle);
  authenticated=false;passkey=chosen;NimBLEDevice::setSecurityPasskey(chosen);
  openedAt=millis();window=true;
  if(!NimBLEDevice::startAdvertising()){window=false;return false;}
  return true;
}
void serviceWireless(bool flightLive) {
  live=flightLive;
  if(window&&!pairingWindow(millis(),openedAt,window)) {
    window=false;NimBLEDevice::stopAdvertising();
    for(auto handle:NimBLEDevice::getServer()->getPeerDevices())NimBLEDevice::getServer()->disconnect(handle);
  }
}
void stopBluetooth() {
  window=false;authenticated=false;
  stopPhoneLocation();
  if(initialized){NimBLEDevice::stopAdvertising();NimBLEDevice::deinit(true);initialized=false;statusCharacteristic=nullptr;}
  passkey=0;
}
void stopWirelessSharing() {if(ap)WiFi.softAPdisconnect(true);ap=false;stopBluetooth();}
bool hotspotEnabled(){return ap;}
bool bluetoothPairingOpen(){return pairingWindow(millis(),openedAt,window);}
bool bluetoothAuthenticated(){return authenticated;}
PhoneLocation phoneLocationSnapshot(){portENTER_CRITICAL(&locationMux);PhoneLocation copy=location;portEXIT_CRITICAL(&locationMux);return copy;}
