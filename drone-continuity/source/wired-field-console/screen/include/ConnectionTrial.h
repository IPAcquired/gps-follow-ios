#pragma once
#include <stdint.h>
#include <string.h>

// Version 1 is the already deployed "connection" NVS blob.
struct SavedConnection {
  uint32_t version;
  char host[16],net[33],key[64],user[65],pass[129];
};

inline void clearConnection(SavedConnection& profile) {
  volatile uint8_t* p=reinterpret_cast<volatile uint8_t*>(&profile);
  for(unsigned i=0;i<sizeof profile;++i)p[i]=0;
}

inline bool readableConnection(const SavedConnection& p) {
  return p.version==1 && memchr(p.host,0,sizeof p.host) && memchr(p.net,0,sizeof p.net) &&
    memchr(p.key,0,sizeof p.key) && memchr(p.user,0,sizeof p.user) && memchr(p.pass,0,sizeof p.pass);
}

class ConnectionTrial {
 public:
  enum class Result {Waiting,Committed,Restore};
  bool active()const{return trying_;}
  template<class Storage> bool stage(Storage& storage,const SavedConnection& candidate) {
    return !trying_ && readableConnection(candidate) &&
      storage.putBytes("conn-pending",&candidate,sizeof candidate)==sizeof candidate;
  }
  template<class Storage> bool take(Storage& storage,SavedConnection& candidate,uint32_t now) {
    if(storage.getBytesLength("conn-pending")!=sizeof candidate)return false;
    const bool valid=storage.getBytes("conn-pending",&candidate,sizeof candidate)==sizeof candidate &&
      readableConnection(candidate);
    // Consume before use: interruption or a second boot loads the original.
    if(!storage.remove("conn-pending")||!valid){clearConnection(candidate);return false;}
    trying_=true;started_=now;return true;
  }
  template<class Storage> Result finish(Storage& storage,const SavedConnection& tested,bool authenticated,uint32_t now) {
    if(!trying_)return Result::Waiting;
    if(uint32_t(now-started_)<60000 && !authenticated)return Result::Waiting;
    trying_=false;
    if(uint32_t(now-started_)<60000 && authenticated && readableConnection(tested) &&
       storage.putBytes("connection",&tested,sizeof tested)==sizeof tested)return Result::Committed;
    return Result::Restore;
  }
 private:
  bool trying_=false;
  uint32_t started_=0;
};
