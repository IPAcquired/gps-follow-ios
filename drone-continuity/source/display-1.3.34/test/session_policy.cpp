#include "SessionPolicy.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>
int main(){
  SessionPolicy p;
  assert(p.response(false,401,100)==AuthResponse::Reauthenticate);assert(!p.blocked&&!p.canLogin(5099));assert(p.canLogin(5100));
  // A replacement token after Pi restart/expiry can poll normally; the old
  // session's 401 never poisons valid saved credentials.
  assert(p.response(true,200,5200)==AuthResponse::None&&p.canLogin(5200));assert(p.response(false,200,5300)==AuthResponse::None);
  assert(p.response(false,403,5400)==AuthResponse::PermissionDenied&&p.canLogin(5400));
  assert(p.response(false,429,5500)==AuthResponse::Cooldown&&!p.canRequest(20499)&&p.canRequest(20500));
  for(int code: {401,403,429}){SessionPolicy bad;assert(bad.response(true,code,0)==AuthResponse::CredentialsBlocked);assert(!bad.canLogin(1000000));}
  SessionPolicy wrap;wrap.response(false,401,UINT32_MAX-1000);assert(!wrap.canLogin(100));assert(wrap.canLogin(3999));
  puts("session policy: protected401 reauth, login refusal no retry, permission isolation, bounded429 and wrap cases passed");
}
