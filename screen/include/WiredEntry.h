#pragma once
#include <stdint.h>

namespace wiredentry {
enum class State : uint8_t { Available,Waiting,HelperOnly,NotPaired,Checking,ProofFailed,ProofTimeout,NoDesktop,FirstImage,FirstImageDelayed,Live,
  Dropped,Stalled,FrameFailed,InputFailed,Paused,Locked,Guard,Service,OwnerPaused,Armed,Airborne,Source,Alert,Back };
struct Message { const char* label;const char* help;bool issue; };
inline Message message(State s){
  switch(s){
    case State::Available:return {"Wired link detected","Open Wired Desktop to connect.",false};
    case State::Waiting:return {"Waiting for XIAO or Pi USB","Check power, data cable and the Pi service.",true};
    case State::HelperOnly:return {"XIAO detected; waiting for Pi","Check XIAO USB data and the Pi desktop service.",true};
    case State::NotPaired:return {"Screen pairing required","Pair this screen locally with its Orange Pi.",true};
    case State::Checking:return {"Verifying paired Orange Pi","Keep the cable connected.",false};
    case State::ProofFailed:return {"Pair verification failed","Check that this is the enrolled screen and Pi.",true};
    case State::ProofTimeout:return {"Pi verification timed out","Check the cable and the Pi sender.",true};
    case State::NoDesktop:return {"Pi desktop has not started","Unlock the Pi and check its desktop service.",true};
    case State::FirstImage:return {"Waiting for first desktop image","Keep the local Linux desktop unlocked.",false};
    case State::FirstImageDelayed:return {"First desktop image delayed","Check the link and Pi desktop service.",true};
    case State::Live:return {"Wired desktop connected","",false};
    case State::Dropped:return {"Wired connection lost","Check the XIAO harness or direct USB cable.",true};
    case State::Stalled:return {"Wired desktop stopped responding","Check the Pi service and cable.",true};
    case State::FrameFailed:return {"Desktop data could not be read","The screen will verify the connection again.",true};
    case State::InputFailed:return {"Desktop input interrupted","Wait for reconnection, then retry the action.",true};
    case State::Paused:return {"Pi paused desktop sharing","Check local login and the Pi safety status.",true};
    case State::Locked:return {"Pi desktop unavailable or locked","Sign in locally and unlock the desktop.",true};
    case State::Guard:return {"Pi safety check pending","Check the controller and fresh telemetry.",true};
    case State::Service:return {"Pi desktop service unavailable","Check the local desktop service on the Pi.",true};
    case State::OwnerPaused:return {"Owner paused desktop sharing","Resume desktop sharing on the local Pi.",true};
    case State::Armed:return {"Desktop paused: controller armed","Wait until the aircraft is safely disarmed.",true};
    case State::Airborne:return {"Desktop paused: aircraft airborne","Wait until the aircraft is safely on the ground.",true};
    case State::Source:return {"Controller source mismatch","Check the configured telemetry source.",true};
    case State::Alert:return {"Desktop paused: serious alert","Review the local controller alert.",true};
    case State::Back:return {"Desktop closed with Back","Tap Wired Desktop to enter again.",false};
  }
  return {"Wired desktop unavailable","Check the local Pi.",true};
}
inline bool mayOpen(bool calibrated,bool touched,bool gesture,uint32_t idle,bool protectedPage,bool operation,bool guarded){
  return calibrated&&!touched&&!gesture&&idle>2500&&!protectedPage&&!operation&&!guarded;
}
}
