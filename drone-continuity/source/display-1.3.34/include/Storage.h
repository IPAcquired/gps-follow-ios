#pragma once
#include <Arduino.h>
#include <FS.h>
struct StorageInfo {uint32_t state=0,capacityMiB=0,records=0,dropped=0;};
void beginStorage();
void requestStorageMount();
void requestStorageUnmount();
bool verifyStorageReadWrite();
StorageInfo storageInfo();
const char* storageStateName(uint32_t state);
#ifdef CARD_PREPARATION_SEED
bool probeFreshCard();
bool prepareFreshCard();
bool startFreshCardPreparation();
#endif
void recordDisplayStatus(bool connected,bool armedKnown,bool armed);
bool openVoiceClip(uint8_t kind,File& file);
int readVoiceClip(File& file,uint8_t* buffer,size_t size);
void closeVoiceClip(File& file);
