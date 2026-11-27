#include <cassert>
#include <map>
#include <string>
#include <vector>
#include "ConnectionTrial.h"
#include "WirelessPolicy.h"

struct Storage {
  std::map<std::string,std::vector<uint8_t>> blobs;
  bool fail=false;
  size_t putBytes(const char* key,const void* value,size_t size){
    if(fail)return 0;
    const auto* p=static_cast<const uint8_t*>(value);
    blobs[key]={p,p+size};return size;
  }
  size_t getBytesLength(const char* key){return blobs.count(key)?blobs[key].size():0;}
  size_t getBytes(const char* key,void* output,size_t size){
    if(getBytesLength(key)!=size)return 0;memcpy(output,blobs[key].data(),size);return size;
  }
  bool remove(const char* key){return blobs.erase(key)==1;}
};

int main(){
  Storage storage;
  const SavedConnection old={1,"192.0.2.1","example","old-fixture","user","test-only"};
  auto next=old;strcpy(next.key,"new-fixture");
  storage.putBytes("connection",&old,sizeof old);
  auto original=storage.blobs.at("connection");
  SavedConnection attempted{};
  ConnectionTrial trial;
  assert(!trial.take(storage,attempted,0)); // Back/cancel never stages an edit.
  assert(trial.stage(storage,next)&&storage.blobs.at("connection")==original);
  assert(trial.take(storage,attempted,100)&&!storage.blobs.count("conn-pending"));
  ConnectionTrial fresh;
  assert(!fresh.take(storage,attempted,101)); // Interruption after trying restores the original.
  assert(trial.finish(storage,attempted,false,60098)==ConnectionTrial::Result::Waiting);
  assert(trial.finish(storage,attempted,false,60100)==ConnectionTrial::Result::Restore);
  assert(storage.blobs.at("connection")==original);
  assert(trial.stage(storage,next)&&trial.take(storage,attempted,UINT32_MAX-100));
  assert(trial.finish(storage,attempted,true,10)==ConnectionTrial::Result::Committed);
  assert(memcmp(storage.blobs["connection"].data(),&next,sizeof next)==0);
  assert(trial.stage(storage,old)&&trial.take(storage,attempted,200));
  storage.fail=true;
  assert(trial.finish(storage,attempted,true,201)==ConnectionTrial::Result::Restore);
  assert(memcmp(storage.blobs["connection"].data(),&next,sizeof next)==0);
  assert(!trial.stage(storage,old));
  uint32_t value=99;
  assert(pairingPin("037492",value)&&value==37492);
  assert(!pairingPin("000000",value)&&!pairingPin("123456",value)&&!pairingPin("654321",value));
  assert(pairingWindow(59898,UINT32_MAX-100,true)&&!pairingWindow(59899,UINT32_MAX-100,true));
  assert(!pairingWindow(10,2,false)&&!authenticatedBleLink(false,true,16)&&
         !authenticatedBleLink(true,false,16)&&!authenticatedBleLink(true,true,15));
  assert(authenticatedBleLink(true,true,16)&&strongHotspotPassword("synthetic-pass123"));
  assert(!strongHotspotPassword("short")&&!strongHotspotPassword("aaaaaaaaaaaa"));
}
