#pragma once
#include <stdint.h>
enum class AuthResponse {None,Reauthenticate,CredentialsBlocked,PermissionDenied,Cooldown};
struct SessionPolicy {
  bool blocked=false,loginDelay=false,cooling=false;
  uint32_t loginAt=0,cooldownAt=0;
  AuthResponse response(bool login,int code,uint32_t now){
    if(login&&(code==401||code==403||code==429)){blocked=true;return AuthResponse::CredentialsBlocked;}
    if(!login&&code==401){loginDelay=true;loginAt=now+5000;return AuthResponse::Reauthenticate;}
    if(!login&&code==403)return AuthResponse::PermissionDenied;
    if(code==429){cooling=true;cooldownAt=now+15000;return AuthResponse::Cooldown;}
    return AuthResponse::None;
  }
  bool canRequest(uint32_t now){if(cooling&&int32_t(now-cooldownAt)>=0)cooling=false;return !cooling;}
  bool canLogin(uint32_t now){if(loginDelay&&int32_t(now-loginAt)>=0)loginDelay=false;return !blocked&&!loginDelay&&canRequest(now);}
};
