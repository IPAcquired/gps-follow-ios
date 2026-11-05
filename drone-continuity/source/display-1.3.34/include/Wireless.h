#pragma once
#include <Arduino.h>
#include "PhoneLocation.h"
PhoneLocation phoneLocationSnapshot();
bool startProtectedHotspot(const String& name,const String& password);
bool openBluetoothPairing(const String& pin);
void stopWirelessSharing();
void serviceWireless(bool flightLive);
bool hotspotEnabled();
bool bluetoothPairingOpen();
bool bluetoothAuthenticated();
void stopBluetooth();
