#include <assert.h>
#include <stdio.h>
#include "LinkFaultPolicy.h"
int main() {
  assert(!strcmp(displayLinkFault(false,false,"tls_connect_failed",-1,7000),"PI OFFLINE / WI-FI LOST"));
  assert(!strcmp(displayLinkFault(true,false,"tls_connect_failed",-1,7000),"PI OFFLINE"));
  assert(!strcmp(displayLinkFault(true,false,"tls_connect_failed",-1,100),"PI SECURE LINK FAILED"));
  assert(!strcmp(displayLinkFault(true,false,"tls_connect_failed",-0x2700,7000),"PI TLS VERIFICATION FAILED"));
  assert(!strcmp(displayLinkFault(true,true,"ok",0,100),"PI SIGN-IN REQUIRED"));
  assert(!strcmp(displayLinkFault(true,false,"invalid_json",0,100),"PI DATA INVALID / STALE"));
  assert(!strcmp(displayLinkFault(true,false,"session_expired_reauth_pending",0,100),"PI SESSION EXPIRED / RECONNECTING"));
  assert(displayLinkFault(true,false,"ok",0,6000)==nullptr);
  assert(!strcmp(displayLinkFault(true,false,"ok",0,6001),"PI OFFLINE"));
  puts("Link fault labels distinguish radio loss, stale data, transport, and certificate rejection.");
}
