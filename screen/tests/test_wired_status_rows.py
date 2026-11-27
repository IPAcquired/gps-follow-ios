"""Check actual portrait status and menu-banner paints after errors and recovery."""
from pathlib import Path
import subprocess
import tempfile

base=Path(__file__).resolve().parents[1]
project=base if (base/"src/main.cpp").is_file() else base/"project"
def function(path, name):
    s=(project/path).read_text()
    start=s.index("void "+name+"(")
    return s[start:s.index("\n}",start)+2]
with tempfile.TemporaryDirectory() as tmp:
    work=Path(tmp)
    fixture= r'''
#include "WiredEntry.h"
#include <cassert>
#include <map>
#include <string>
using std::string;
const int BG=0,AMBER=1,MUTED=2;
struct Viewer{
 wiredentry::State connection=wiredentry::State::Dropped;
 uint32_t connectionRevision=1;
 string where;
 bool showIssue(){return wiredentry::message(connection).issue;}
 void drewStatus(const char* label){where=label;}
}wiredViewer;
std::map<int,string> rows;
bool upright=true;bool portrait(){return upright;}
struct {void fillRect(int,int y,int,int,int){rows[y].clear();}}lcd;
void text(const string& s,int,int y,int,int){rows[y]=s;}
void portraitText(const string& s,int,int y,int,int,int){rows[y]=s;}
'''
    fixture+=function("include/PortraitUI.h","portraitWiredStatus")+"\n"
    fixture+=function("src/main.cpp","drawWiredMenuStatus")+"\n"
    fixture+=r'''
int main(){
 for(bool vertical:{true,false}){
  upright=vertical;const int banner=vertical?67:39;
  wiredViewer.connection=wiredentry::State::Dropped;++wiredViewer.connectionRevision;
  drawWiredMenuStatus(true);assert(rows[banner]=="Wired connection lost"&&wiredViewer.where=="menu_banner");
  portraitWiredStatus();assert(rows[356]=="Wired connection lost"&&!rows[422].empty()&&wiredViewer.where=="pi_page");
  wiredViewer.connection=wiredentry::State::Available;++wiredViewer.connectionRevision;
  drawWiredMenuStatus(false);
  assert(rows[banner]==(vertical?"":"YOUR DRONE. ONE CLEAR VIEW."));
  portraitWiredStatus();assert(rows[356]=="Wired link detected"&&rows[422].empty());
 }
}
'''
    source=work/"ui.cpp";source.write_text(fixture)
    subprocess.run(["g++","-std=c++17","-I",str(project/"include"),str(source),"-o",str(work/"ui")],check=True)
    subprocess.run([str(work/"ui")],check=True)
print("PASS native portrait Pi caption and normal-menu repaint after loss and recovery in both orientations.")
