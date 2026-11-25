#include "QuickConnect.h"
#include <cassert>
#include <string>
int main(){DashboardCode q;std::string url="https://example-pi.local:8446/#join="+std::string(43,'a');
 assert(!q.fresh(0));assert(q.set(url.c_str(),120,0xfffffff0));assert(q.fresh(20));assert(!q.fresh(120000));
 assert(!q.set("http://evil.invalid",120,1));assert(!q.set(url.c_str(),121,1));
 for(int i=0;i<10000;++i){q.clear();assert(!q.fresh(i));assert(q.set(url.c_str(),120,i));assert(q.fresh(i+119999));assert(!q.fresh(i+120000));}
}
