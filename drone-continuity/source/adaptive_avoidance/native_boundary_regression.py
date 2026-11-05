#!/usr/bin/env python3
"""Compile the actual AP_Proximity boundary translation unit in an isolated harness.

Run in WSL, e.g. python3 native_boundary_regression.py --source-dir
/home/daddy_nate/ardupilot-adaptive-clean --compare-original.

The actual boundary .cpp/.h are used unmodified for CURRENT. --compare-original
also builds the git HEAD version and a temporary copy with the proposed guard.
Only temporary build files are written; the source checkout is never modified.

Stubs are limited to clock, scalar 0-Hz filter, and vector primitives. The tests
inspect native boundary vertices and validity. They do NOT validate the real
low-pass filter, vehicle dynamics, controller stopping, or physical clearance.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import tempfile


COMMON = r'''
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cfloat>
#define WARN_IF_UNUSED
#define MIN(a,b) std::min((a),(b))
#define MAX(a,b) std::max((a),(b))
namespace AP_HAL { extern uint32_t test_clock_ms; inline uint32_t millis() { return test_clock_ms; } }
inline float wrap_360(float v) { v=std::fmod(v,360.0f); return v<0?v+360:v; }
inline float constrain_float(float v,float lo,float hi) { return std::clamp(v,lo,hi); }
inline bool is_equal(float a,float b) { return std::fabs(a-b)<1e-6f; }
'''

MATH = r'''
#pragma once
#include <AP_Common/AP_Common.h>
struct Vector3f {
  float x{},y{},z{};
  Vector3f()=default;
  Vector3f(float a,float b,float c):x(a),y(b),z(c){}
  Vector3f operator*(float s) const { return {x*s,y*s,z*s}; }
  Vector3f operator+(const Vector3f& q) const { return {x+q.x,y+q.y,z+q.z}; }
  Vector3f operator-(const Vector3f& q) const { return {x-q.x,y-q.y,z-q.z}; }
  bool operator==(const Vector3f& q) const { return x==q.x&&y==q.y&&z==q.z; }
  float dot(const Vector3f& q) const { return x*q.x+y*q.y+z*q.z; }
  float length() const { return std::sqrt(dot(*this)); }
  void offset_bearing(float bearing_deg,float pitch_deg,float d) {
    const float a=bearing_deg*0.0174532925199433f,p=pitch_deg*0.0174532925199433f;
    x+=d*std::cos(p)*std::cos(a); y+=d*std::cos(p)*std::sin(a); z+=d*std::sin(p);
  }
  static Vector3f point_on_line_closest_to_other_point(const Vector3f& a,const Vector3f& b,const Vector3f& p) {
    auto ab=b-a; float n=ab.dot(ab); return a+ab*(n>0?std::clamp((p-a).dot(ab)/n,0.0f,1.0f):0.0f);
  }
  // Unused by these vertex tests. Linker discards the only referencing method.
  static void segment_to_segment_closest_point(const Vector3f&,const Vector3f&,const Vector3f&,const Vector3f&,Vector3f&);
  static bool segment_plane_intersect(const Vector3f&,const Vector3f&,const Vector3f&,const Vector3f&);
};
'''

FILTER = r'''
#pragma once
class LowPassFilterFloat {
  float value{},cutoff{};
public:
  void set_cutoff_frequency(float v) { cutoff=v; }
  float get_cutoff_freq() const { return cutoff; }
  float get() const { return value; }
  float apply(float v,float) { value=v; return value; }
  void reset(float v) { value=v; }
};
'''

TEST = r'''
#include <AP_Common/AP_Common.h>
#include <AP_Math/AP_Math.h>
#include <Filter/LowPassFilter.h>
#include <array>
#include <cstring>
#include <iostream>
#include <new>
#include <sstream>
#include <string>
#include <vector>
#define private public
#include "AP_Proximity_Boundary_3D.h"
#undef private
uint32_t AP_HAL::test_clock_ms=10000;
using B=AP_Proximity_Boundary_3D;
struct Fixture {
  alignas(B) unsigned char memory[sizeof(B)]; B* b;
  Fixture() { std::memset(memory,0,sizeof(memory)); b=new(memory) B; b->set_filter_freq(0); }
  ~Fixture() { b->~B(); }
};
int checks=0, failures=0;
void check(bool ok,const std::string& text) {
  ++checks;
  if(!ok) { ++failures; std::cerr << "FAIL " << text << '\n'; }
}
void put(B& b,int sector,float d) { b.set_face_attributes({2,uint8_t(sector)},float(sector*45),d,0); }
float radius(const B& b,int vertex) { return b._boundary_points[2][vertex].length()/100.0f; }
void check_valid_ownership(const B& b,const std::string& tag) {
  for(int s=0;s<8;++s) if(b._distance_valid[2][s]) {
    float own=b._distance[2][s];
    for(int v: {s,(s+7)%8}) {
      std::ostringstream msg; msg<<tag<<" valid sector "<<s<<" vertex "<<v<<" radius "<<radius(b,v)<<" own "<<own;
      check(radius(b,v)<=own+0.0001f,msg.str());
    }
  }
}
int main() {
  // Six update permutations for three substantially different geometries.
  const std::array<std::array<float,3>,3> ranges={{{2,19.99f,19.99f},{8,2,10},{4,8,1}}};
  for(size_t scenario=0;scenario<ranges.size();++scenario) {
    std::array<int,3> order={0,1,2};
    int permutation=0;
    do {
      Fixture f; B& b=*f.b; const int sector[3]={0,2,6};
      const std::string tag="scenario "+std::to_string(scenario)+" permutation "+std::to_string(permutation++);
      for(int i:order) { put(b,sector[i],ranges[scenario][i]); check_valid_ownership(b,tag+" partial"); }
      check_valid_ownership(b,tag+" complete");
      // Refresh each side again: near front vertices must not be pushed outward.
      put(b,2,ranges[scenario][1]); put(b,6,ranges[scenario][2]);
      check_valid_ownership(b,tag+" refresh");
      for(int i=0;i<3;++i) {
        float d=0; check(b.get_distance({2,uint8_t(sector[i])},d)&&std::fabs(d-ranges[scenario][i])<1e-5f,tag+" raw");
      }
    } while(std::next_permutation(order.begin(),order.end()));
  }
  // Reset each sensor, in each arrival order, without corrupting survivors.
  for(int removed: {0,2,6}) {
    std::array<int,3> order={0,2,6};
    do {
      Fixture f; B& b=*f.b;
      for(int s:order) put(b,s,s==0?2.0f:19.99f);
      b.reset_face({2,uint8_t(removed)},0);
      float d=0; check(!b.get_distance({2,uint8_t(removed)},d),"reset invalidates face");
      check_valid_ownership(b,"reset survivors");
      if(removed==0) {
        Vector3f v; check(!b.get_obstacle(2*8+7,v),"reset front removes its central segment");
        put(b,0,8.0f);
        check(std::fabs(radius(b,0)-8)<0.001f&&std::fabs(radius(b,7)-8)<0.001f,"reacquire farther front clears stale near front");
      }
    } while(std::next_permutation(order.begin(),order.end()));
  }
  // Timeout only front while sides receive fresh data, then reacquire farther.
  {
    Fixture f; B& b=*f.b; AP_HAL::test_clock_ms=20000;
    put(b,0,2); put(b,2,19.99f); put(b,6,19.99f);
    AP_HAL::test_clock_ms=21500; put(b,2,19.99f); put(b,6,19.99f); b.check_face_timeout();
    float d=0; check(!b.get_distance({2,0},d),"front expiry invalidates raw face");
    check_valid_ownership(b,"front expiry survivors");
    Vector3f v; check(!b.get_obstacle(23,v),"front expiry removes its central segment");
    put(b,0,8); check(std::fabs(radius(b,0)-8)<0.001f&&std::fabs(radius(b,7)-8)<0.001f,"expired front reacquisition clears stale near vertices");
    b.reset();
    for(int i=0;i<40;++i) check(!b.get_obstacle(i,v),"whole reset invalidates all obstacle segments");
    put(b,0,9); check(std::fabs(radius(b,0)-9)<0.001f&&std::fabs(radius(b,7)-9)<0.001f,"whole reset reacquisition clears stale front");
  }
  std::cout<<"{\"checks\":"<<checks<<",\"failures\":"<<failures<<",\"pass\":"<<(failures==0?"true":"false")<<"}\n";
  return failures?1:0;
}
'''


def build_case(work, name, cpp, header):
    case = work / name
    case.mkdir()
    for rel, content in {
        'AP_Common/AP_Common.h': COMMON,
        'AP_Math/AP_Math.h': MATH,
        'Filter/LowPassFilter.h': FILTER,
        'AP_Proximity_Boundary_3D.h': header,
        'AP_Proximity_Boundary_3D.cpp': cpp,
        'test.cpp': TEST,
    }.items():
        path = case / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    binary = case / 'boundary-regression'
    command = ['g++', '-std=c++17', '-O1', '-g', '-ffunction-sections',
               '-fdata-sections', '-Wl,--gc-sections', '-I', str(case),
               str(case/'test.cpp'), str(case/'AP_Proximity_Boundary_3D.cpp'),
               '-o', str(binary)]
    compiled = subprocess.run(command, capture_output=True, text=True)
    if compiled.returncode:
        return {'case': name, 'compile_pass': False, 'stderr': compiled.stderr}
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    result = json.loads(run.stdout)
    result.update(case=name, compile_pass=True,
                  source_sha256=hashlib.sha256(cpp.encode()).hexdigest(),
                  stderr=run.stderr, exit_code=run.returncode)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=pathlib.Path, required=True)
    parser.add_argument('--compare-original', action='store_true')
    parser.add_argument('--output', type=pathlib.Path)
    args = parser.parse_args()
    rel = 'libraries/AP_Proximity/AP_Proximity_Boundary_3D'
    cpp = (args.source_dir/(rel+'.cpp')).read_text()
    header = (args.source_dir/(rel+'.h')).read_text()
    with tempfile.TemporaryDirectory(prefix='native-boundary-regression-') as temp:
        work = pathlib.Path(temp)
        results = [build_case(work, 'current', cpp, header)]
        if args.compare_original:
            original = subprocess.check_output(['git','-C',str(args.source_dir),'show','HEAD:'+rel+'.cpp'],text=True)
            needle = 'if (!_distance_valid[layer][next_sector]) {'
            guarded = original.replace(needle, 'if (!_distance_valid[layer][next_sector] && !_distance_valid[layer][get_next_sector(next_sector)]) {',1)
            assert guarded != original
            results.extend([build_case(work,'git-head',original,header),build_case(work,'proposed-guard-isolated',guarded,header)])
        report = {'scope':'Actual native boundary translation unit; clock/vector/filter scaffolding; zero-Hz geometry and validity only. No hardware or flight simulator.', 'results':results}
        rendered = json.dumps(report,indent=2)
        print(rendered)
        if args.output:
            args.output.write_text(rendered+'\n')
        raise SystemExit(0 if results[0].get('pass') else 1)


if __name__ == '__main__':
    main()
