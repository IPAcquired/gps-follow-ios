#pragma once
#include <stdint.h>
bool beginAudio(bool mute);
void setAudioMute(bool mute);
bool audioMuted();
bool audioPlaying();
void queueAudio(uint8_t kind); // 0 startup chime, 1..6 advisory warning voices.
void stopAudio();
