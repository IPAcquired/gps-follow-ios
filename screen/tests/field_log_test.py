"""Exercise production append, flush, health encoding and unmount on a temporary filesystem."""
from pathlib import Path
import subprocess,tempfile

root=Path(__file__).resolve().parents[1]
source=(root/"src/Storage.cpp").read_text()
impl=source[source.index("void loseLog("):source.index("\n}\n}\nvoid beginStorage()")+2]
# This isolated logger fixture does not schedule SD integrity checks.
impl=impl.replace("    if(verifyWanted.load(std::memory_order_acquire)){", "    if(false){")
impl=impl[:impl.index("    if(false){")]+impl[impl.index("    if(xQueueReceive(records,"):]

test=r'''
#include "FieldLog.h"
#include <unistd.h>
#include <fcntl.h>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <string>
std::atomic<uint32_t> state{2},dropped{0},writeErrors{0},written{0},producers{0};
std::atomic<bool> mountWanted{false},unmountWanted{false};
uint32_t now=0;uint32_t millis(){return now;}
unsigned pending=0;uint32_t flushedAt=0,logBytes=0;int logFd=-1;char logPath[96]="/first";
int cardLock=1,records=1,sequence=0;bool didEnd=false,failSync=false,waitForFlush=false;
struct End{};struct Driver{void end(){didEnd=true;}} SD,cardBus;
int xSemaphoreTake(int,int){return 1;}void xSemaphoreGive(int){}
#define pdTRUE 1
#define pdMS_TO_TICKS(x) (x)
std::deque<FieldSample> queue;
int xQueueReceive(int,FieldSample* item,int ticks){
  now+=ticks;if(queue.empty()){if(didEnd||(waitForFlush&&written))throw End();return 0;}
  *item=queue.front();queue.pop_front();return 1;
}
unsigned uxQueueMessagesWaiting(int){return queue.size();}bool audioPlaying(){return false;}
void mountCard(){state=2;}void nextLog(){snprintf(logPath,sizeof logPath,"/segment-%d",++sequence);logBytes=0;}
int testOpen(const char* path,int flags,int mode){assert(!strncmp(path,"/sd/",4));return ::open(path+4,flags,mode);}
int testSync(int fd){return failSync?-1:::fsync(fd);}
#define open testOpen
#define fsync testSync
IMPL
#undef open
#undef fsync
int main(int argc,char**argv){
  assert(argc==2&&::chdir(argv[1])==0);
  auto sample=[](unsigned seq){FieldSample s;s.sequence=seq;s.publication=1800000000000ULL+seq;
    s.uptime=seq*500;s.sensors[0]={FieldHealth::Fresh,15};s.sensors[1]={FieldHealth::Missing,UINT32_MAX};
    if(seq==1){s.batteryMv=12145;s.groundspeedMmps=0;}return s;};
  assert(fieldAge(15,20)==35&&fieldAge(UINT32_MAX-1,3)==UINT32_MAX);
  for(unsigned i=1;i<=11;++i)queue.push_back(sample(i));
  unmountWanted=true;try{task(nullptr);}catch(const End&){}
  assert(state==4&&written==11&&pending==0&&!dropped&&!writeErrors&&logFd==-1&&queue.empty());
  std::ifstream input("first");std::string line;unsigned n=0;
  while(std::getline(input,line)){++n;assert(line.find("\"seq\":"+std::to_string(n)+",")!=std::string::npos);
    assert(line.find("\"armed\":null")!=std::string::npos&&line.find("\"health\":\"missing\"")!=std::string::npos);
    assert(line.find(n==1?"\"battery_voltage_v\":12.145":"\"battery_voltage_v\":null")!=std::string::npos);
    assert(line.find(n==1?"\"groundspeed_mps\":0.000":"\"groundspeed_mps\":null")!=std::string::npos);}
  assert(n==11);auto original=std::filesystem::file_size("first");
  state=2;appendSample(sample(12));assert(writeErrors==1&&dropped==1&&std::filesystem::file_size("first")==original);
  state=2;nextLog();appendSample(sample(13));failSync=true;assert(!syncLog(true));assert(writeErrors==2&&dropped==2&&written==11);
  failSync=false;state=2;nextLog();didEnd=false;written=0;waitForFlush=true;
  queue.push_back(sample(14));try{task(nullptr);}catch(const End&){}assert(written==1&&pending==0);assert(syncLog(true));
}
'''
test=test.replace("?-1:::fsync","? -1 : ::fsync").replace("IMPL",impl)
with tempfile.TemporaryDirectory(dir=root/"tests") as tmp:
    folder=Path(tmp);(folder/"fixture.cpp").write_text(test)
    subprocess.run(["g++","-std=c++17","-I",str(root/"include"),str(folder/"fixture.cpp"),"-o",str(folder/"fixture")],check=True)
    subprocess.run([str(folder/"fixture"),str(folder)],check=True)
print("PASS production SD append, sync, drain, partial batches, exclusive create and unavailable fields.")
