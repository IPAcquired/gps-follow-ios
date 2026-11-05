#include "StorageFormat.h"
#include <assert.h>
#include <stdio.h>
int main(){
  uint8_t sector[512]={};
  assert(unsupportedStorageFormat(sector)==0);
  memcpy(sector+3,"NTFS    ",8);assert(unsupportedStorageFormat(sector)==7);
  memcpy(sector+3,"EXFAT   ",8);assert(unsupportedStorageFormat(sector)==8);
  memcpy(sector+3,"MSDOS5.0",8);assert(unsupportedStorageFormat(sector)==0);
  assert(firstStoragePartition(sector,250347520)==0);
  sector[510]=0x55;sector[511]=0xaa;sector[450]=0x07;sector[455]=8;
  assert(firstStoragePartition(sector,250347520)==2048);
  assert(firstStoragePartition(sector,2048)==0);
  sector[455]=0;assert(firstStoragePartition(sector,250347520)==0);
  sector[450]=0;sector[466]=7;sector[471]=16;
  assert(firstStoragePartition(sector,250347520)==4096);
  sector[511]=0;assert(firstStoragePartition(sector,250347520)==0);
  puts("PASS: 10 filesystem/partition signature checks; no card writes");
}
