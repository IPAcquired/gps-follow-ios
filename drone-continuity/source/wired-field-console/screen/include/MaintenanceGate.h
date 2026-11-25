#pragma once
inline int wifiSignalEstimate(int dbm) {
  if(dbm>=0||dbm< -120)return -1;
  int quality=2*(dbm+100);return quality<0?0:quality>100?100:quality;
}
struct MaintenanceEvidence {
  bool heartbeatFresh=false,armedKnown=false,armed=true,controllerAbsent=false;
  bool groundFresh=false,onGround=false,tlsFresh=false,ownerAuthenticated=false,directPiAp=false;
  int wifiDbm=0;
};
inline bool maintenanceConditions(const MaintenanceEvidence& e) {
  // RSSI is an extra link-quality check, NEVER authentication or a range proof.
  return (e.controllerAbsent||(e.heartbeatFresh&&e.armedKnown&&!e.armed))&&
    (!e.groundFresh||e.onGround)&&e.tlsFresh&&e.ownerAuthenticated&&e.directPiAp&&wifiSignalEstimate(e.wifiDbm)>=0;
}
