"""Native, filesystem-only regression of the production 1 KiB SD probe."""
import os
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
src=(root/"src/Storage.cpp").read_text()
function=src[src.index("bool verifyStorageReadWrite(){"):src.index("\nStorageInfo storageInfo()",src.index("bool verifyStorageReadWrite(){"))]
fixture=r'''
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <fcntl.h>
#include <unistd.h>
#include <cassert>
#include <filesystem>
#include <fstream>
static std::string dir;
int cardLock=1,state=2,unmountWanted=0;bool muted=false;unsigned nextName=21;
bool audioPlaying(){return muted;}
int pdMS_TO_TICKS(int n){return n;}constexpr int pdTRUE=1;
int xSemaphoreTake(int,int){return 1;}void xSemaphoreGive(int){}
uint32_t esp_random(){return nextName;}
struct Console{template<class... A>void printf(const char*,A...){};} Serial;
std::string path(const char* raw){return dir+"/"+std::filesystem::path(raw).filename().string();}
int testOpen(const char* raw,int flags,int mode){return open(path(raw).c_str(),flags,mode);}
int testUnlink(const char* raw){return unlink(path(raw).c_str());}
#define open testOpen
#define unlink testUnlink
IMPL
#undef open
#undef unlink
int main(int argc,char**argv){
 dir=argv[1];std::string existing=dir+"/check-00000015.tmp";
 std::ofstream(existing)<<"untouched";
 assert(!verifyStorageReadWrite());assert(std::filesystem::file_size(existing)==9);
 ++nextName;assert(verifyStorageReadWrite());assert(std::distance(std::filesystem::directory_iterator(dir),std::filesystem::directory_iterator())==1);
 unmountWanted=1;assert(!verifyStorageReadWrite());
}
'''
with tempfile.TemporaryDirectory() as tmp:
 t=Path(tmp);(t/"volume").mkdir();(t/"probe.cpp").write_text(fixture.replace("IMPL",function))
 subprocess.run(["g++","-std=c++17",str(t/"probe.cpp"),"-o",str(t/"probe")],check=True)
 subprocess.run([str(t/"probe"),str(t/"volume")],check=True)
print("PASS exclusive ownership, orphan preservation, 1024-byte write/sync/read/compare, own-file cleanup, safe unmount gate.")
