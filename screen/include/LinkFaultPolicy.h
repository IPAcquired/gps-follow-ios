#pragma once
#include <stdint.h>
#include <string.h>

// A TCP timeout is not evidence of an invalid certificate. Preserve a specific
// certificate rejection, but let a lost radio or expired telemetry report offline.
inline const char* displayLinkFault(bool wifiConnected, bool authBlocked,
                                   const char* error, int tlsError,
                                   uint32_t snapshotAge) {
  if (!wifiConnected) return "PI OFFLINE / WI-FI LOST";
  if (!strcmp(error, "tls_connect_failed") && tlsError == -0x2700)
    return "PI TLS VERIFICATION FAILED";
  if (snapshotAge > 6000) return "PI OFFLINE";
  if (authBlocked) return "PI SIGN-IN REQUIRED";
  if (!strcmp(error, "tls_connect_failed")) return "PI SECURE LINK FAILED";
  if (!strcmp(error, "transport_failed")) return "PI TRANSPORT FAILED";
  if (!strcmp(error, "session_expired_reauth_pending"))
    return "PI SESSION EXPIRED / RECONNECTING";
  if (!strcmp(error, "invalid_display_schema") || !strcmp(error, "invalid_json") ||
      !strcmp(error, "json_capacity_exceeded")) return "PI DATA INVALID / STALE";
  return nullptr;
}
