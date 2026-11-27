#pragma once
#include <Arduino.h>
#include <FS.h>
#include "FieldLog.h"
struct StorageInfo {uint32_t state=0,capacityMiB=0,records=0,dropped=0,errors=0;};
void beginStorage();
bool wiredDesktopTransfer(uint8_t* request,uint8_t* reply,size_t count,bool fast);
bool wiredDesktopExchange(uint8_t* request, uint8_t* reply, size_t count);
void requestStorageMount();
void requestStorageUnmount();
bool verifyStorageReadWrite();
bool requestStorageCheck(uint32_t id);
StorageInfo storageInfo();
const char* storageStateName(uint32_t state);
void recordFieldSample(FieldSample sample);
bool openVoiceClip(uint8_t kind,File& file);
int readVoiceClip(File& file,uint8_t* buffer,size_t size);
void closeVoiceClip(File& file);
