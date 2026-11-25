#include "WiredLocalProfile.h"
#include "QuickConnect.h"
#include <cassert>
#include <string>
WiredLocalProfile displayLocalProfile;
bool installed=false;
bool localProfileReady(){return installed;}
int main(){
  WiredLocalProfile p;
  assert(!p.valid());
  assert(!p.set("panel.local","http://panel.local:8446","example"));
  assert(!p.set("panel.local","https://other.local:8446","example"));
  assert(!p.set(".local","https://.local:8446","example"));
  assert(!p.set("a-.local","https://a-.local:8446","example"));
  assert(!p.set("panel.local","https://panel.local:8446",""));
  assert(!p.set("panel.local","https://panel.local:8446","bad\nnetwork"));
  assert(p.set("panel.local","https://panel.local:8446","example")&&p.valid());
  DashboardCode code;std::string token(43,'a'),good=std::string(p.origin)+"/#join="+token;
  assert(!code.set(good.c_str(),120,10));
  installed=true;displayLocalProfile=p;
  assert(code.set(good.c_str(),120,10));
  assert(!code.set(("https://other.local:8446/#join="+token).c_str(),120,10));
  assert(!code.set((good+"b").c_str(),120,10));assert(!code.fresh(120010));
  std::memset(p.dns,'x',sizeof p.dns);assert(!p.valid());
  puts("PASS blank/invalid identities fail closed, configured exact TLS/QR destination, bounded time and nonterminated record.");
}
