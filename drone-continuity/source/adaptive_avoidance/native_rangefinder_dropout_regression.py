#!/usr/bin/env python3
"""Compile the actual proximity RangeFinder bridge against minimal native stubs.

Tests packet freshness, deduplication, individual loss, recovery and out-of-range
semantics. The source .cpp/.h are copied unmodified into a temporary directory.
Stubs provide rangefinder samples, boundary recording, clock, text and logging;
this does not simulate vehicle dynamics or validate the real boundary filter.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

COMMON = r'''
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>
#define MAX(a,b) std::max((a),(b))
using std::isfinite;
inline bool is_positive(float v) { return v > 0; }
enum Rotation { ROTATION_NONE=0, ROTATION_YAW_90=2, ROTATION_YAW_270=6,
 ROTATION_YAW_315=7, ROTATION_PITCH_90=24, ROTATION_PITCH_270=25 };
namespace AP_HAL { inline uint32_t clock_ms=10000;
 inline uint32_t millis(){return clock_ms;} inline uint64_t micros64(){return uint64_t(clock_ms)*1000;}}
'''
RF = r'''
#pragma once
#include <common.h>
#define RANGEFINDER_MAX_INSTANCES 10
class AP_RangeFinder_Backend;
class RangeFinder { public:
 enum class Type {None, MAVLink, Analog};
 enum class Status {NotConnected,NoData,OutOfRangeLow,OutOfRangeHigh,Good};
 AP_RangeFinder_Backend *sensors[10]{}; uint8_t count=3;
 uint8_t num_sensors() const{return count;}
 AP_RangeFinder_Backend* get_backend(uint8_t i) const {return sensors[i];}
};
namespace AP { inline RangeFinder *rf=nullptr; inline RangeFinder* rangefinder(){return rf;} }
'''
RFB = r'''
#pragma once
#include "AP_RangeFinder.h"
class AP_RangeFinder_Backend { public:
 Rotation orient=ROTATION_NONE; RangeFinder::Type type=RangeFinder::Type::MAVLink;
 RangeFinder::Status stat=RangeFinder::Status::Good;
 float d=2, dmin=.1f,dmax=8; int8_t quality=-1; uint32_t ts=10000;
 Rotation orientation()const{return orient;} RangeFinder::Type allocated_type()const{return type;}
 float distance()const{return d;} float min_distance()const{return dmin;} float max_distance()const{return dmax;}
 uint32_t last_reading_ms()const{return ts;} int8_t signal_quality_pct()const{return quality;}
 RangeFinder::Status status()const{return stat;}
 bool has_data()const{return stat!=RangeFinder::Status::NoData&&stat!=RangeFinder::Status::NotConnected;}
};
'''
BACKEND = r'''
#pragma once
#include <common.h>
class AP_Proximity_Boundary_3D { public:
 struct Face {uint8_t sector;}; bool valid[8]{}; float distance[8]{}; unsigned puts[8]{},resets[8]{};
 Face get_face(float angle)const{return {uint8_t(angle/45)};}
 void set_face_attributes(Face f,float,float d,uint8_t){valid[f.sector]=true;distance[f.sector]=d;++puts[f.sector];}
 void reset_face(Face f,uint8_t){valid[f.sector]=false;++resets[f.sector];}
};
class AP_Proximity { public: enum class Status{NotConnected,NoData,Good};
 struct Proximity_State {uint8_t instance=0;Status status=Status::NotConnected;};
 AP_Proximity_Boundary_3D boundary;
};
struct AP_Proximity_Params {};
class AP_Proximity_Backend {public:
 inline static unsigned database_writes=0; inline static bool ignore_all=false;
 AP_Proximity_Backend(AP_Proximity&f, AP_Proximity::Proximity_State&s, AP_Proximity_Params&p):frontend(f),state(s),params(p){}
 virtual ~AP_Proximity_Backend()=default; virtual void update()=0;
 virtual float distance_max_m()const=0;virtual float distance_min_m()const=0;
 virtual bool get_upward_distance(float&)const{return false;}
 virtual uint8_t horizontal_dropout_mask()const{return 0;}
 protected: void set_status(AP_Proximity::Status s){state.status=s;}
 bool ignore_reading(float,float,bool)const{return ignore_all;}
 static void database_push(float,float){++database_writes;}
 AP_Proximity &frontend; AP_Proximity::Proximity_State &state; AP_Proximity_Params &params;
};
'''
LOG = r'''
#pragma once
#include <common.h>
struct FakeLogger {std::vector<uint8_t> masks;void WriteStreaming(const char*,const char*,const char*,uint64_t,uint8_t m){masks.push_back(m);}};
namespace AP {inline FakeLogger log;inline FakeLogger& logger(){return log;}}
'''
GCS = r'''
#pragma once
#include <common.h>
#define MAV_SEVERITY_WARNING 4
#define MAV_SEVERITY_INFO 6
inline std::vector<std::string> messages;
inline void send_text(int,const char*fmt,...){char b[100];va_list a;va_start(a,fmt);vsnprintf(b,sizeof(b),fmt,a);va_end(a);messages.emplace_back(b);}
#define GCS_SEND_TEXT(...) send_text(__VA_ARGS__)
'''
TEST = r'''
#include <iostream>
#include <limits>
#include <array>
#include <new>
#include <cstring>
#include "AP_Proximity_RangeFinder.h"
#include <AP_RangeFinder/AP_RangeFinder_Backend.h>
#include <AP_Logger/AP_Logger.h>
#include <GCS_MAVLink/GCS.h>
unsigned checks=0,failures=0;
void check(bool yes,const char *what){++checks;if(!yes){++failures;std::cerr<<"FAIL "<<what<<'\n';}}
struct Fixture {
 AP_Proximity prx{}; AP_Proximity::Proximity_State state{}; AP_Proximity_Params params{};
 AP_RangeFinder_Backend sensors[3]{}; RangeFinder rf{};
 alignas(AP_Proximity_RangeFinder) unsigned char mem[sizeof(AP_Proximity_RangeFinder)];
 AP_Proximity_RangeFinder *b;
 Fixture(){std::memset(mem,0,sizeof(mem));b=new(mem) AP_Proximity_RangeFinder(prx,state,params);
 AP_HAL::clock_ms=10000;AP::rf=&rf;messages.clear();AP::log.masks.clear();
 AP_Proximity_Backend::ignore_all=false;AP_Proximity_Backend::database_writes=0;
 for(int i=0;i<3;++i){rf.sensors[i]=&sensors[i];sensors[i].orient=Rotation(i==0?0:i==1?2:6);sensors[i].d=2+i;}}
 ~Fixture(){b->~AP_Proximity_RangeFinder();}
 void tick(uint32_t delta=100,bool front=true,bool right=true,bool left=true){AP_HAL::clock_ms+=delta;
 bool update[]={front,right,left};for(int i=0;i<3;++i)if(update[i])sensors[i].ts=AP_HAL::clock_ms;b->update();}
 void recover(){for(int i=0;i<12;++i)tick();}
};
int main(){
 {Fixture f;f.b->update();check(f.b->horizontal_dropout_mask()==0,"healthy initial");
 for(int k=0;k<4;++k)f.tick(100,false,false,false);
 check(f.prx.boundary.puts[0]==1&&AP_Proximity_Backend::database_writes==3,"cached reads do not update filter/boundary/database");
 f.tick(100,false,true,true);check(f.b->horizontal_dropout_mask()==0,"500ms remains fresh");
 f.tick(1,false,true,true);check(f.b->horizontal_dropout_mask()==1,"front lost at501ms despite healthy sides");
 check(!f.prx.boundary.valid[0]&&f.prx.boundary.valid[2]&&f.prx.boundary.valid[6],"loss invalidates only missing face");
 check(f.state.status==AP_Proximity::Status::NoData,"latched loss exposes NoData");
 check(messages.size()==1&&messages[0].find("front")!=std::string::npos,"directional warning once");
 for(int k=0;k<10;++k){f.tick(100,false,true,true);}
 check(messages.size()==1,"repeated loss does not flood warnings");
 f.tick();for(int k=0;k<9;++k)f.tick();check(f.b->horizontal_dropout_mask()==1,"recovery requires full second");
 f.tick();check(f.b->horizontal_dropout_mask()==0,"fresh all sensors recover after1s");
 check(AP::log.masks==std::vector<uint8_t>({1,0}),"PRXL transition masks");
 }
 {Fixture f;f.sensors[0].ts=0;f.b->update();check(f.b->horizontal_dropout_mask()==1,"startup no packet loss");
 f.tick();for(int k=0;k<15;++k)f.tick(100,false,true,true);
 check(f.b->horizontal_dropout_mask()==1,"one returning packet cannot complete recovery");
 f.recover();check(f.b->horizontal_dropout_mask()==0,"continuous packets recover startup loss");}
 {Fixture f;f.b->update();f.sensors[0].quality=0;f.tick();check(f.b->horizontal_dropout_mask()==1,"explicit zero quality lost");
 f.sensors[0].quality=-1;f.recover();check(f.b->horizontal_dropout_mask()==0,"unknown quality accepted");
 f.sensors[1].d=std::numeric_limits<float>::quiet_NaN();f.tick();check(f.b->horizontal_dropout_mask()==4,"nonfinite sample lost");
 f.sensors[1].d=3;f.tick();for(int k=0;k<6;++k)f.tick();
 f.sensors[2].stat=RangeFinder::Status::NoData;f.tick();check(f.b->horizontal_dropout_mask()==68,"new loss accumulates directional mask");
 f.sensors[2].stat=RangeFinder::Status::Good;f.tick();for(int k=0;k<9;++k)f.tick();
 check(f.b->horizontal_dropout_mask()==68,"second loss restarts recovery timer");f.tick();check(f.b->horizontal_dropout_mask()==0,"all recover after restarted interval");}
 {Fixture f;f.b->update();f.sensors[0].stat=RangeFinder::Status::OutOfRangeHigh;f.sensors[0].d=9;f.tick();
 check(!f.prx.boundary.valid[0]&&f.b->horizontal_dropout_mask()==0,"fresh out-high is healthy clear");
 AP_Proximity_Backend::ignore_all=true;f.sensors[0].stat=RangeFinder::Status::OutOfRangeLow;f.sensors[0].d=0;f.tick();
 check(f.prx.boundary.valid[0]&&std::fabs(f.prx.boundary.distance[0]-.1f)<1e-6f,"too-close protected despite ignore heuristic");
 f.sensors[0].dmin=0;f.tick();check(std::fabs(f.prx.boundary.distance[0]-.01f)<1e-6f,"protective minimum positive");
 f.sensors[0].dmax=std::numeric_limits<float>::infinity();f.tick();check(f.b->horizontal_dropout_mask()==1,"nonfinite range config lost");}
 // All six arrival orders must recover only after every sensor has real data.
 std::array<int,3> order={0,1,2};do{Fixture f;for(auto &s:f.sensors)s.ts=0;f.b->update();
 check(f.b->horizontal_dropout_mask()==69,"all missing startup mask");
 for(int i:order){AP_HAL::clock_ms+=100;f.sensors[i].ts=AP_HAL::clock_ms;f.b->update();}
 check(f.b->horizontal_dropout_mask()==69,"partial/initial arrivals retain latch");f.recover();
 check(f.b->horizontal_dropout_mask()==0,"all six arrival permutations recover");
 for(int i=0;i<3;++i)check(std::fabs(f.prx.boundary.distance[i==0?0:i==1?2:6]-(2+i))<1e-6f,"unequal readings retained");
 }while(std::next_permutation(order.begin(),order.end()));
 {Fixture f;f.sensors[0].type=RangeFinder::Type::Analog;f.sensors[0].stat=RangeFinder::Status::NoData;f.tick();
 check(f.b->horizontal_dropout_mask()==0,"non-MAV horizontal unaffected");
 f.sensors[1].orient=ROTATION_PITCH_270;f.sensors[1].stat=RangeFinder::Status::NoData;f.tick();
 check(f.b->horizontal_dropout_mask()==0,"downward loss not horizontal mask");}
 {Fixture f;AP_HAL::clock_ms=0xfffffff0U;for(auto&s:f.sensors)s.ts=AP_HAL::clock_ms;f.b->update();
 f.tick(500,false,true,true);check(f.b->horizontal_dropout_mask()==0,"freshness wrap500ms");f.tick(1,false,true,true);
 check(f.b->horizontal_dropout_mask()==1,"freshness wrap501ms");f.recover();check(f.b->horizontal_dropout_mask()==0,"recovery across clock wrap");}
 std::cout<<"{\"checks\":"<<checks<<",\"failures\":"<<failures<<"}\n";return failures?1:0;
}
'''

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source-dir', default='/home/daddy_nate/ardupilot-adaptive-clean')
    p.add_argument('--output')
    args = p.parse_args()
    root = Path(args.source_dir) / 'libraries/AP_Proximity'
    originals = {name:(root/name).read_bytes() for name in ('AP_Proximity_RangeFinder.cpp','AP_Proximity_RangeFinder.h')}
    files = {'common.h':COMMON, 'AP_Proximity_Backend.h':BACKEND,
      'AP_Proximity_config.h':'#define AP_PROXIMITY_RANGEFINDER_ENABLED 1\n#define HAL_LOGGING_ENABLED 1\n',
      'AP_HAL/AP_HAL.h':'#include <common.h>\n', 'AP_RangeFinder/AP_RangeFinder.h':RF,
      'AP_RangeFinder/AP_RangeFinder_Backend.h':RFB,'AP_Logger/AP_Logger.h':LOG,
      'GCS_MAVLink/GCS.h':GCS,'test.cpp':TEST}
    with tempfile.TemporaryDirectory(prefix='prx-dropout-native-') as tmp:
        d=Path(tmp)
        for name, data in files.items():
            q=d/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(data)
        for name,data in originals.items():(d/name).write_bytes(data)
        subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror','-O1','-g',
            '-fsanitize=undefined,address','-I',str(d),str(d/'AP_Proximity_RangeFinder.cpp'),str(d/'test.cpp'),'-o',str(d/'test')],check=True)
        run=subprocess.run([str(d/'test')],capture_output=True,text=True)
        if run.stderr:print(run.stderr,end='')
        result=json.loads(run.stdout)
        result['source_sha256']={name:hashlib.sha256(data).hexdigest() for name,data in originals.items()}
        result['limitations']='Native actual bridge source; sensor, boundary, log, and clock dependencies stubbed. No dynamics.'
        print(json.dumps(result,indent=2))
        if args.output:Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
        raise SystemExit(run.returncode)

if __name__=='__main__': main()
