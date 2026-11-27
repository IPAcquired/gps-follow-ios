#pragma once
#include <stdint.h>
#include <string.h>
// Inspect signatures only. Never repair or format a user's card on mount failure.
inline uint32_t unsupportedStorageFormat(const uint8_t* sector) {
  if (memcmp(sector+3,"NTFS    ",8)==0) return 7;
  if (memcmp(sector+3,"EXFAT   ",8)==0) return 8;
  return 0;
}
inline uint32_t firstStoragePartition(const uint8_t* sector,uint64_t sectors) {
  if(sector[510]!=0x55||sector[511]!=0xaa)return 0;
  for(unsigned offset=446;offset<510;offset+=16) {
    uint32_t start=uint32_t(sector[offset+8])|(uint32_t(sector[offset+9])<<8)|
      (uint32_t(sector[offset+10])<<16)|(uint32_t(sector[offset+11])<<24);
    if(sector[offset+4]&&start>0&&start<sectors)return start;
  }
  return 0;
}
