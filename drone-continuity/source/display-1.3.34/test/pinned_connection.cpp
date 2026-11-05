#include <cassert>
#include "PinnedPiClient.h"
int main(){
 PinnedPiClient p(IPAddress(1),"test-ca");
 assert(!p.connect(PinnedPiClient::hostname,8443));
 assert(!p.connect("attacker.local",8443));
 assert(!p.connect(PinnedPiClient::hostname,80));
 assert(p.handshakes==0);
 for(int i=0;i<10000;++i){
  assert(p.connectPrepared()==1);
  assert(!p.connect(PinnedPiClient::hostname,8443,2000));
  assert(!p.connect("attacker.local",8443));
 }
 assert(p.handshakes==10000);
 assert(!strcmp(p.verifiedName,PinnedPiClient::hostname));
 assert(!strcmp(p.certificate,"test-ca"));
 PinnedPiClient missing(IPAddress(1),nullptr);assert(!missing.connectPrepared());
 PinnedPiClient empty(IPAddress(1),"");assert(!empty.connectPrepared());
}
