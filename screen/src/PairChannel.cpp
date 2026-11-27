#include "PairChannel.h"
#include <Arduino.h>
#include <esp_system.h>
#include <mbedtls/gcm.h>
#include <mbedtls/md.h>
#include <string.h>

namespace {
const char context[] = "WiredDesktopPair/v1";
constexpr size_t contextLen = sizeof(context)-1;
constexpr uint8_t Hello=0x60, ScreenProof=0x61, PiProof=0x62, Down=0x63, Up=0x64;
constexpr uint32_t handshakeMs=12000, leaseMs=295000;

void wipe(void *mem, size_t n) {
    volatile uint8_t *p=static_cast<volatile uint8_t*>(mem);
    while (n--) *p++=0;
}

bool hmac256(const uint8_t *key,size_t keyLen,const uint8_t *msg,size_t msgLen,uint8_t out[32]) {
    const auto *md=mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    return md && mbedtls_md_hmac(md,key,keyLen,msg,msgLen,out)==0;
}

bool equal(const uint8_t *a,const uint8_t *b,size_t n) {
    volatile uint8_t d=0;
    for(size_t i=0;i<n;++i) d|=a[i]^b[i];
    return d==0;
}

uint32_t get32(const uint8_t *p) {
    return (uint32_t(p[0])<<24)|(uint32_t(p[1])<<16)|(uint32_t(p[2])<<8)|p[3];
}
void set32(uint8_t *p,uint32_t v) {
    p[0]=v>>24; p[1]=v>>16; p[2]=v>>8; p[3]=v;
}
}

bool PairChannel::begin(const uint8_t inner[32]) {
    reset();
    enrolled_=false;
    wipe(key_,sizeof(key_));
    const uint8_t zero[32]{};
    if (!inner || equal(inner,zero,32)) return false;
    static const char domain[]="wired-screen-v1";
    uint8_t msg[sizeof(domain)+6];
    memcpy(msg,domain,sizeof(domain));  // include domain separator NUL
    if (esp_efuse_mac_get_default(msg+sizeof(domain))!=ESP_OK) return false;
    enrolled_=hmac256(inner,32,msg,sizeof(msg),key_);
    return enrolled_;
}

void PairChannel::reset() {
    state_=State::Idle;
    rx_=tx_=started_=0;
    wipe(session_,sizeof(session_));
    wipe(np_,sizeof(np_)); wipe(ns_,sizeof(ns_)); wipe(ready_,sizeof(ready_));
}

bool PairChannel::established() const {
    return state_==State::Open && uint32_t(millis()-started_)<leaseMs;
}

bool PairChannel::proof(uint8_t label,uint8_t out[16]) const {
    uint8_t msg[contextLen+1+32],full[32];
    memcpy(msg,context,contextLen); msg[contextLen]=label;
    memcpy(msg+contextLen+1,np_,16); memcpy(msg+contextLen+17,ns_,16);
    bool ok=hmac256(key_,32,msg,sizeof(msg),full);
    if(ok) memcpy(out,full,16);
    wipe(full,sizeof(full));
    return ok;
}

bool PairChannel::derive() {
    // RFC 5869 extract and expand, using the ESP32's configured SHA-256 HMAC.
    uint8_t salt[32],prk[32],block[32],msg[32+contextLen+1];
    memcpy(salt,np_,16); memcpy(salt+16,ns_,16);
    bool ok=hmac256(salt,sizeof(salt),key_,32,prk);
    for(uint8_t i=1;ok && i<=3;++i) {
        size_t used=0;
        if(i>1){memcpy(msg,block,32); used=32;}
        memcpy(msg+used,context,contextLen); used+=contextLen; msg[used++]=i;
        ok=hmac256(prk,32,msg,used,block);
        if(ok) memcpy(session_+(i-1)*32,block,i==3?16:32);
    }
    wipe(prk,32); wipe(block,32); wipe(msg,sizeof(msg));
    return ok;
}

bool PairChannel::onRecord(const uint8_t *raw,size_t n,uint8_t out[57],size_t &outLen) {
    outLen=0;
    if(!enrolled_||!raw||n!=17) return false;
    if(state_==State::Open && !established()) reset();
    if(state_==State::Pending && uint32_t(millis()-started_)>=handshakeMs) reset();
    if(raw[0]==Hello) {
        if(state_==State::Open) return false;
        if(state_==State::Idle || memcmp(np_,raw+1,16)!=0) {
            reset(); memcpy(np_,raw+1,16);
            esp_fill_random(ns_,16);
            state_=State::Pending; started_=millis();
        }
        out[0]=ScreenProof; memcpy(out+1,ns_,16);
        if(!proof('S',out+17)) return false;
        outLen=33; return true;
    }
    if(raw[0]!=PiProof||state_==State::Idle) return false;
    uint8_t expected[16];
    if(!proof('P',expected)||!equal(raw+1,expected,16)) return false;
    if(state_==State::Pending) {
        if(!derive()){reset();return false;}
        state_=State::Open;started_=millis();
        const uint8_t ready=0x20;
        if(!wrap(&ready,1,out,outLen)){reset();return false;}
        memcpy(ready_,out,outLen); return true;
    }
    memcpy(out,ready_,sizeof(ready_));outLen=sizeof(ready_);return true;
}

bool PairChannel::wrap(const uint8_t *clear,size_t n,uint8_t out[57],size_t &len) {
    len=0;
    if(!established()||!clear||n==0||n>35||tx_==UINT32_MAX) return false;
    out[0]=Up;set32(out+1,++tx_);
    uint8_t iv[12];memcpy(iv,session_+72,8);memcpy(iv+8,out+1,4);
    mbedtls_gcm_context gcm;mbedtls_gcm_init(&gcm);
    int rc=mbedtls_gcm_setkey(&gcm,MBEDTLS_CIPHER_ID_AES,session_+32,256);
    if(!rc) rc=mbedtls_gcm_crypt_and_tag(&gcm,MBEDTLS_GCM_ENCRYPT,n,iv,12,out,5,
                                         clear,out+5,16,out+5+n);
    mbedtls_gcm_free(&gcm);
    if(rc) return false;
    len=21+n;return true;
}

bool PairChannel::unwrap(const uint8_t *raw,size_t n,uint8_t clear[40],size_t &len) {
    len=0;
    if(!established()||!raw||n<22||n>61||raw[0]!=Down) return false;
    uint32_t count=get32(raw+1);
    if(count<=rx_) return false;
    uint8_t iv[12];memcpy(iv,session_+64,8);memcpy(iv+8,raw+1,4);
    size_t bytes=n-21;
    mbedtls_gcm_context gcm;mbedtls_gcm_init(&gcm);
    int rc=mbedtls_gcm_setkey(&gcm,MBEDTLS_CIPHER_ID_AES,session_,256);
    if(!rc) rc=mbedtls_gcm_auth_decrypt(&gcm,bytes,iv,12,raw,5,raw+5+bytes,16,raw+5,clear);
    mbedtls_gcm_free(&gcm);
    if(rc){wipe(clear,bytes);return false;}
    rx_=count;len=bytes;return true;
}
