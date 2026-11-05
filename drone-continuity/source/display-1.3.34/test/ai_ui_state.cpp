#include "AiUiState.h"
#include <cassert>
#include <cstring>
int main(){AiUiState s;assert(!strcmp(s.label(true),"PI CONNECTED / CHOOSE A REQUEST"));
 assert(!strcmp(s.label(false),"PI OFFLINE / RECONNECTING"));
 s.phase=AiUiState::Waiting;s.disconnected();assert(s.phase==AiUiState::Failed);
 assert(!strcmp(s.label(true),"PI CONNECTED / RESPONSE UNAVAILABLE"));
 s.phase=AiUiState::Reply;s.disconnected();assert(s.phase==AiUiState::Reply);
 assert(!strcmp(s.label(false),"PI OFFLINE / RECONNECTING"));
 for(int i=0;i<10000;++i){s.phase=AiUiState::Idle;assert(strstr(s.label(true),"OFFLINE")==nullptr);s.phase=AiUiState::Waiting;s.disconnected();assert(s.phase!=AiUiState::Waiting);}
}
