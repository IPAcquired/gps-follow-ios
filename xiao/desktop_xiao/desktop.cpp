#include <Arduino.h>
#include <hardware/dma.h>
#include <hardware/gpio.h>
#include <hardware/pio.h>
#include <hardware/sync.h>
#include <pico/time.h>
#include <errno.h>
#include <stdarg.h>
#include "desktop_link.pio.h"
#include "protocol.h"
#include "board_lights.h"

namespace {
using namespace desktop;
constexpr unsigned CLOCK_PAD = D8, INPUT_PAD = D9, OUTPUT_PAD = D10, SELECT_PAD = D3;
static_assert(CLOCK_PAD == 2 && INPUT_PAD == 4 && OUTPUT_PAD == 3 && SELECT_PAD == 5, "Select Seeed XIAO RP2350");
constexpr uint32_t LEASE_US = 2000000, SELECT_LIMIT_US = 50000;
PIO const bus = pio1;
int exchangeSm, gateSm, txDma, rxDma;
uint exchangeOffset, gateOffset, mask;
pio_sm_config exchangeConfig, gateConfig;
dma_channel_config txConfig, rxConfig;
uint32_t txWords[FRAME+1], rxWords[FRAME];
uint16_t sentSeq = 0, lastAck = 0, lastEvent = 0;
bool seenScreen = false, seenEvent = false, haveTimer = false;
Slot slot, lastDelivered;
volatile bool active = false, timeoutFlag = false;
volatile uint32_t usbAt = 0, screenAt = 0;
uint32_t selectedAt;
bool timingSelection = false;
repeating_timer_t timer;
BoardLights lights;
volatile bool ledPending=false;
uint16_t ledSeq=0;
uint8_t ledResult=0;
uint32_t ledAt=0, totalFrames=0, badFrames=0, lostCount=0, ledChanges=0;
volatile uint32_t stuckCount=0;
void armExchange();

// Nonblocking lines preserve order; even a busy USB reader cannot stall the SPI loop.
char outgoing[24][124];
uint8_t lastUp[57], lastUpLength=0;
uint32_t lastUpAt=0;
uint8_t head = 0, count = 0;
char line[145];
size_t lineLen = 0;
bool discarding = false;

void isolate() { gpio_set_oeover(OUTPUT_PAD, GPIO_OVERRIDE_LOW); }

bool watchdog(repeating_timer_t*) {
  if ((!active && !ledPending) || timeoutFlag) return true;
  uint32_t now = time_us_32();
  if (pio_sm_get_pc(bus, gateSm) == gateOffset + desktop_gate_offset_selected) {
    if (!timingSelection) { selectedAt = now; timingSelection = true; }
  } else timingSelection = false;
  if ((active && (now - usbAt >= LEASE_US || now - screenAt >= LEASE_US)) ||
      (timingSelection && now - selectedAt >= SELECT_LIMIT_US)) {
    isolate();
    if(timingSelection && now-selectedAt>=SELECT_LIMIT_US)++stuckCount;
    timeoutFlag = true;
  }
  return true;
}

void park() {
  isolate();
  pio_set_sm_mask_enabled(bus, mask, false);
  dma_channel_abort(txDma);
  dma_channel_abort(rxDma);
}

void endSession() {
  active = false;
  ledPending=false;
  park();
  timeoutFlag = false;
  timingSelection = false;
  slot = {};
  seenScreen = seenEvent = false;
  lastUpLength=0;
  lastUpAt=0;
  lastAck = 0;
  lastDelivered = {};
  armExchange();   // receive on the dedicated CS, with MISO high impedance
}

void sendLine(const char *format, ...) {
  constexpr unsigned limit = sizeof(outgoing)/sizeof(outgoing[0]);
  if (count == limit) {
    endSession();
    count = 1;
    head = 0;
    strcpy(outgoing[0], "LOST\n");
    return;
  }
  char *out = outgoing[(head + count) % limit];
  va_list ap;
  va_start(ap, format);
  vsnprintf(out, sizeof(outgoing[0])-1, format, ap);
  va_end(ap);
  strcat(out, "\n");
  ++count;
}

void flushLine() {
  if (!count) return;
  const size_t n = strlen(outgoing[head]);
  const int available=Serial.availableForWrite();
  if(available<=0) return;
  const size_t chunk=n<size_t(available)?n:size_t(available);
  size_t wrote = Serial.write(reinterpret_cast<uint8_t *>(outgoing[head]), chunk);
  if (wrote == n) {
    head = (head + 1) % (sizeof(outgoing)/sizeof(outgoing[0]));
    --count;
  } else if (wrote) {
    memmove(outgoing[head], outgoing[head] + wrote, n - wrote + 1);
  }
}

void armExchange() {
  park();
  uint8_t frame[FRAME];
  if(ledPending) lamps::reply(frame,ledSeq,ledResult,lights.settings,lights.applied);
  else reply(frame,slot);
  sentSeq=ledPending?0:slot.seq;
  for (size_t i=0; i<FRAME; ++i) txWords[i] = uint32_t(frame[i]) << 24;
  txWords[FRAME] = 0; // trailing refill for the MSB-first autopull engine
  pio_sm_init(bus, exchangeSm, exchangeOffset, &exchangeConfig);
  pio_sm_init(bus, gateSm, gateOffset, &gateConfig);
  pio_sm_set_consecutive_pindirs(bus, gateSm, OUTPUT_PAD, 1, false);
  for (uint irq = 0; irq <= 2; ++irq) pio_interrupt_clear(bus, irq);
  pio_sm_put(bus, exchangeSm, FRAME * 8 - 1);
  dma_channel_configure(txDma, &txConfig, &bus->txf[exchangeSm], txWords, FRAME+1, false);
  dma_channel_configure(rxDma, &rxConfig, rxWords, &bus->rxf[exchangeSm], FRAME, false);
  dma_start_channel_mask((1u << txDma) | (1u << rxDma));
  const uint32_t irqState = save_and_disable_interrupts();
  if (!timeoutFlag) {
    if((active||ledPending)&&haveTimer) gpio_set_oeover(OUTPUT_PAD, GPIO_OVERRIDE_NORMAL);
    pio_enable_sm_mask_in_sync(bus, mask);
  }
  restore_interrupts(irqState);
}

void receive(const Request &req) {
  screenAt = time_us_32();
  lastAck = req.ack;
  if(req.upLength && (req.upLength!=lastUpLength ||
        memcmp(lastUp,req.up,req.upLength) || screenAt-lastUpAt>=250000)) {
    static constexpr char digits[]="0123456789abcdef";
    char hex[2*sizeof(lastUp)+1];
    for(unsigned i=0;i<req.upLength;++i) {
      hex[2*i]=digits[req.up[i]>>4];
      hex[2*i+1]=digits[req.up[i]&15];
    }
    hex[2*req.upLength]='\0';
    memcpy(lastUp,req.up,req.upLength);
    lastUpLength=req.upLength;
    lastUpAt=screenAt;
    sendLine("UP %s",hex);
  }
  if (seenScreen && req.action && (!seenEvent || lastEvent != req.event))
    sendLine("TOUCH %u %u %u %u", unsigned(req.event), unsigned(req.action),
             unsigned(req.x), unsigned(req.y));
  if (!active) return; // queue overflow ended this session
  if (req.action) { seenEvent = true; lastEvent = req.event; }
  seenScreen = true;
  if (confirmed(slot, sentSeq, req.ack)) {
    lastDelivered = slot;
    slot = {};
    sendLine("ACK %u", unsigned(lastDelivered.seq));
  }
}

void serviceBus() {
  if (timeoutFlag) {
    const bool wasActive=active;
    endSession();
    if(wasActive){++lostCount;count=head=0;sendLine("LOST");}
    return;
  }
  if(ledPending && time_us_32()-ledAt>=150000 && gpio_get(SELECT_PAD) &&
     !pio_interrupt_get(bus,1)){
    ledPending=false;
    armExchange();
  }
  if (!pio_interrupt_get(bus, 1)) return;
  if (pio_interrupt_get(bus, 0) && !pio_interrupt_get(bus, 2) &&
      !dma_channel_is_busy(rxDma)) {
    uint8_t bytes[FRAME];
    for (size_t i=0; i<FRAME; ++i) bytes[i] = uint8_t(rxWords[i]);
    lamps::Command command;
    auto type=lamps::parse(bytes,command);
    if(type==lamps::Type::Request){
      ++totalFrames;
      ledResult=command.status;ledSeq=command.seq;
      if(command.set && !ledResult && command.settings.mode && !lights.rgbReady())ledResult=2;
      if(command.set && !ledResult){lights.set(command.settings);lights.tick(millis());++ledChanges;}
      ledPending=true;ledAt=time_us_32();
    } else if(type==lamps::Type::Poll){
      ++totalFrames;ledPending=false;
    } else if(type==lamps::Type::Other){
      Request req;
      if(parse(bytes,req)){++totalFrames;if(active)receive(req);}
      else ++badFrames;
    } else ++badFrames;
  } else ++badFrames;
  armExchange();
}

int nibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

void offer(const char *arg) {
  if (*arg < '0' || *arg > '9') { sendLine("ERROR SEQUENCE"); return; }
  char *end;
  errno = 0;
  const unsigned long seq = strtoul(arg, &end, 10);
  if (errno || *end != ' ' || !seq || seq > 65535) { sendLine("ERROR SEQUENCE"); return; }
  const char *hex = end + 1;
  const size_t n = strlen(hex);
  if (!n || n % 2 || n > PAYLOAD*2) { sendLine("ERROR PAYLOAD"); return; }
  Slot next{};
  next.seq = seq;
  next.length = n / 2;
  for (unsigned i=0; i<next.length; ++i) {
    int hi=nibble(hex[2*i]), lo=nibble(hex[2*i+1]);
    if (hi < 0 || lo < 0) { sendLine("ERROR PAYLOAD"); return; }
    next.data[i] = (hi << 4) | lo;
  }
  usbAt = time_us_32();
  if (!seenScreen) { sendLine("BUSY"); return; }
  if (slot.seq) {
    bool same = slot.seq == seq && slot.length == next.length &&
                memcmp(slot.data, next.data, slot.length) == 0;
    if (same) sendLine("QUEUED %lu", seq); else sendLine("BUSY");
    return;
  }
  if (lastDelivered.seq == seq) {
    if (lastDelivered.length == next.length && !memcmp(lastDelivered.data, next.data, next.length))
      sendLine("ACK %lu", seq);
    else sendLine("ERROR SEQUENCE");
    return;
  }
  if (lastAck == seq) { sendLine("ERROR SEQUENCE"); return; }
  slot = next;
  sendLine("QUEUED %lu", seq);
}

void command(const char *s) {
  if(!strcmp(s,"INFO")){sendLine("INFO XIAO-PAIR-LIGHTS 1 PIO-DMA PWM");return;}
  if(!strcmp(s,"LEDVER")){sendLine("LEDVER 2 CONTINUOUS-RAINBOW");return;}
  if(!strcmp(s,"LED?")){
    auto &l=lights.settings; auto &v=lights.applied;
    sendLine("LED %u %u %u %u %u %u %u %u %u %u %u %u",l.mode,l.color,l.brightness,
             l.beacon,l.speed,l.yellow,v.r,v.g,v.b,v.y,v.power,unsigned(ledSeq));return;
  }
  if(!strcmp(s,"STATS")){
    sendLine("STATS %lu %lu %lu %lu %lu %u %u",(unsigned long)totalFrames,(unsigned long)badFrames,
             (unsigned long)stuckCount,(unsigned long)lostCount,(unsigned long)ledChanges,
             unsigned(active),unsigned(seenScreen));return;
  }
  if (!strcmp(s, "CAPS")) { sendLine("CAPS PAIR 1"); return; }
  if (!strcmp(s, "HELLO")) { sendLine("DESKTOP XIAO 1"); return; }
  if (!strcmp(s, "END")) {
    endSession(); count = head = 0; sendLine("ENDED"); return;
  }
  if (!strcmp(s, "BEGIN")) {
    endSession(); count = head = 0;
    if (!haveTimer) { sendLine("ERROR TIMER"); return; }
    usbAt = screenAt = time_us_32();
    active = true;
    armExchange();
    sendLine("READY");
    return;
  }
  if (!active) { sendLine("ERROR INACTIVE"); return; }
  if (!strcmp(s, "PING")) { usbAt = time_us_32(); sendLine("PONG"); }
  else if (!strcmp(s, "SYNC")) { usbAt = time_us_32(); sendLine("SYNC %u", unsigned(lastAck)); }
  else if (!strncmp(s, "PUT ", 4)) offer(s+4);
  else sendLine("ERROR COMMAND");
}
}

void setup() {
  lights.begin();
  gpio_init(OUTPUT_PAD);
  isolate();
  const uint pads[] = {CLOCK_PAD,INPUT_PAD,OUTPUT_PAD,SELECT_PAD};
  for (uint p : pads) { pio_gpio_init(bus, p); gpio_disable_pulls(p); }
  gpio_pull_up(SELECT_PAD);
  isolate();
  exchangeSm = pio_claim_unused_sm(bus, true);
  gateSm = pio_claim_unused_sm(bus, true);
  mask = (1u << exchangeSm) | (1u << gateSm);
  exchangeOffset = pio_add_program(bus, &desktop_exchange_program);
  gateOffset = pio_add_program(bus, &desktop_gate_program);
  exchangeConfig = desktop_exchange_program_get_default_config(exchangeOffset);
  sm_config_set_out_pins(&exchangeConfig, OUTPUT_PAD, 1);
  sm_config_set_in_pins(&exchangeConfig, INPUT_PAD);
  sm_config_set_jmp_pin(&exchangeConfig, SELECT_PAD);
  sm_config_set_out_shift(&exchangeConfig, false, true, 8);
  sm_config_set_in_shift(&exchangeConfig, false, true, 8);
  gateConfig = desktop_gate_program_get_default_config(gateOffset);
  sm_config_set_set_pins(&gateConfig, OUTPUT_PAD, 1);
  txDma = dma_claim_unused_channel(true); rxDma = dma_claim_unused_channel(true);
  txConfig = dma_channel_get_default_config(txDma); rxConfig = dma_channel_get_default_config(rxDma);
  channel_config_set_transfer_data_size(&txConfig, DMA_SIZE_32);
  channel_config_set_transfer_data_size(&rxConfig, DMA_SIZE_32);
  channel_config_set_read_increment(&txConfig, true); channel_config_set_write_increment(&txConfig, false);
  channel_config_set_read_increment(&rxConfig, false); channel_config_set_write_increment(&rxConfig, true);
  channel_config_set_dreq(&txConfig, pio_get_dreq(bus, exchangeSm, true));
  channel_config_set_dreq(&rxConfig, pio_get_dreq(bus, exchangeSm, false));
  haveTimer = add_repeating_timer_ms(-1, watchdog, nullptr, &timer);
  armExchange();
  Serial.begin(115200);
}

void loop() {
  lights.tick(millis());
  serviceBus();
  if (!Serial) {
    if (active) endSession();
    count = head = lineLen = 0;
    discarding = false;
    return;
  }
  for (unsigned budget = 0; budget < 48 && Serial.available(); ++budget) {
    int c = Serial.read();
    if (c < 0) break;
    if (c == '\r') continue;
    if (c == '\n') {
      if (discarding) sendLine("ERROR LINE");
      else if (lineLen) { line[lineLen] = 0; command(line); }
      lineLen = 0; discarding = false;
    } else if (c < 32 || c > 126 || lineLen >= sizeof(line)-1) discarding = true;
    else if (!discarding) line[lineLen++] = char(c);
  }
  flushLine();
}
