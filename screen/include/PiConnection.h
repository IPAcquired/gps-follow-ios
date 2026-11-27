#pragma once
#include <new>
// Owned and used only by the network task. Sharing one authenticated socket
// avoids repeated TLS handshakes and the memory cost of parallel TLS clients.
struct PiConnection {
  String trust;
  IPAddress address;
  PinnedPiClient client;
  HTTPClient http;
  PiConnection(IPAddress ip,const String& certificate):trust(certificate),address(ip),client(ip,trust.c_str()){}
};
PiConnection* sharedPiConnection(IPAddress address,const String& certificate){
  static PiConnection* connection=nullptr;
  if(!connection)connection=new(std::nothrow) PiConnection(address,certificate);
  // Provisioning changes require reboot; never reuse a socket for another peer.
  if(connection&&(connection->address!=address||connection->trust!=certificate)){
    connection->client.stop();return nullptr;
  }
  return connection;
}
