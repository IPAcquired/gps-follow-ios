"""Specification-based electrical checks and a simplified AT-radio emulator.

This is neither a SPICE circuit simulation nor a physical RF/flight test.
It exercises startup and failure handling against documented constraints.
"""
from dataclasses import dataclass, field
from uwb_follow import LineFramer, radio_settings, counter_payload, TAG_ADDRESS, finite


@dataclass
class DeskPlan:
    battery_max_v: float = 25.2
    regulator_input_max_v: float = 40.0  # User-reported, exact model pending.
    compute_v: float | None = None
    regulator_a: float | None = None
    estimated_compute_a: float = 4.0    # Test budget only, not measured current.
    uwb_v: float = 3.3
    servo_v: float = 6.0
    servo_supply_a: float = 5.0
    servo_count: int = 4
    servo_stall_a: float = 1.4  # Tower Pro published figure; clones must be measured.
    optional_trick_travel_deg: float = 270.0
    servo_available_travel_deg: float = 159.0  # Standard manufacturer model, not all variants.
    servo_rail_shared: bool = False
    common_ground: bool = True
    crossed_tx_rx: bool = True
    uart_logic_v: float = 3.3
    uwb_baud: int = 115200
    lidar_baud: int = 460800
    tof_transport: str = "usb"
    tof_baud: int = 115200
    tof_width: int = 100
    tof_fps: int = 10
    uwb_port: str = "UNVERIFIED_SPARE_UART"
    uart_pins_verified: bool = False
    reserved_ports: tuple = ("/dev/ttyS1",)
    owners: dict = field(default_factory=lambda: {
        "uwb": "UNVERIFIED_SPARE_UART", "lidar": "LIDAR_DEDICATED_UART",
        "tof": "TOF_USB_BY_ID", "fc": "FC_USB_BY_ID", "camera": "CAMERA_USB_BY_ID"})
    os_target: str = "Orange Pi Zero 3W A733"
    usb_host_and_power_verified: bool = False
    reset_wire_verified: bool = False


def audit(plan: DeskPlan) -> list[str]:
    issues = []
    for name in ("servo_rail_shared","common_ground","crossed_tx_rx","uart_pins_verified",
                 "usb_host_and_power_verified","reset_wire_verified"):
        if type(getattr(plan,name)) is not bool:
            return ["invalid_wiring_flag_"+name]
    if type(plan.tof_width) is not int or plan.tof_width not in (25,50,100):
        return ["invalid_tof_resolution"]
    if type(plan.tof_fps) is not int or not 1 <= plan.tof_fps <= 19:
        return ["invalid_tof_framerate"]
    if type(plan.tof_baud) is not int or plan.tof_baud <= 0:
        return ["invalid_tof_baudrate"]
    for name in ("battery_max_v","regulator_input_max_v","estimated_compute_a","uwb_v","servo_v","uart_logic_v",
                 "servo_supply_a","servo_stall_a","optional_trick_travel_deg","servo_available_travel_deg"):
        if not finite(getattr(plan,name)) or getattr(plan,name) <= 0:
            return ["invalid_electrical_rating_"+name]
    for name in ("compute_v","regulator_a"):
        if getattr(plan,name) is not None and (not finite(getattr(plan,name)) or getattr(plan,name) <= 0):
            return ["invalid_electrical_rating_"+name]
    if plan.battery_max_v > plan.regulator_input_max_v: issues.append("regulator_input_overvoltage")
    if plan.compute_v is None: issues.append("compute_output_voltage_unverified")
    elif not 4.75 <= plan.compute_v <= 5.25: issues.append("compute_output_wrong_voltage")
    if plan.regulator_a is None: issues.append("regulator_current_unverified")
    elif plan.regulator_a < plan.estimated_compute_a: issues.append("compute_power_budget_insufficient")
    if not 2.4 <= plan.uwb_v <= 3.6: issues.append("uwb_supply_wrong_voltage")
    if plan.uart_logic_v > 3.3: issues.append("uart_logic_overvoltage")
    if plan.servo_rail_shared: issues.append("servo_compute_rails_must_be_separate")
    if not 4.8 <= plan.servo_v <= 6.6: issues.append("servo_supply_wrong_voltage")
    if type(plan.servo_count) is not int or not 0 <= plan.servo_count <= 4:
        issues.append("invalid_servo_count")
    elif plan.servo_stall_a * plan.servo_count > plan.servo_supply_a:
        issues.append("servo_simultaneous_stall_exceeds_supply")
    if plan.optional_trick_travel_deg > plan.servo_available_travel_deg:
        issues.append("optional_trick_exceeds_standard_servo_travel")
    if not plan.common_ground: issues.append("no_common_signal_ground")
    if not plan.crossed_tx_rx: issues.append("tx_rx_not_crossed")
    if plan.uwb_baud != 115200: issues.append("uwb_wrong_baud")
    if plan.lidar_baud != 460800: issues.append("c1_wrong_baud")
    if plan.tof_transport == "uart":
        # 8N1, image data plus minimum described header/checksum overhead.
        utilization = (plan.tof_width**2 + 22) * plan.tof_fps * 10 / plan.tof_baud
        if utilization > .70: issues.append("tof_uart_bandwidth_overload")
    elif plan.tof_transport != "usb": issues.append("tof_wrong_interface")
    if plan.uwb_port in plan.reserved_ports: issues.append("uwb_port_reserved_for_bluetooth")
    if not plan.uart_pins_verified: issues.append("orange_pi_uart_pinmux_unverified")
    if len(set(plan.owners.values())) != len(plan.owners): issues.append("two_devices_share_one_port")
    if plan.owners.get("uwb") != plan.uwb_port: issues.append("uwb_device_path_mismatch")
    if plan.os_target != "Orange Pi Zero 3W A733": issues.append("wrong_orange_pi_os_image")
    if not plan.usb_host_and_power_verified: issues.append("usb_host_ports_power_or_backfeed_unverified")
    if not plan.reset_wire_verified: issues.append("wearable_reset_wire_unverified")
    return issues


class RadioFailure(RuntimeError):
    """Messages deliberately exclude settings values and private keys."""


class RadioEmulator:
    """RYUW122 AT dialect fixture, including stored TAG_SEND payload."""
    def __init__(self):
        self.settings = {"MODE":"0", "CHANNEL":"5", "BANDWIDTH":"0",
                         "NETWORKID":"Anchor12", "ADDRESS":"TAG12345",
                         "CPIN":"0"*32, "TAGD":"0,0", "RSSI":"0"}
        self.payload = "00000000"
        self.powered = True
        self.rf_open = True
        self.link_ok = True
        self.bad_readback = None
        self.flash_writes = 0
        self.reply_override = None

    def command(self, raw: bytes) -> bytes:
        if not self.powered or not self.link_ok: return b""
        if self.reply_override is not None: return self.reply_override
        if not raw.endswith(b"\r\n"): return b"+ERR=1\r\n"
        command = raw[:-2].decode("ascii")
        if command == "AT": return b"+OK\r\n"
        if command == "AT+IPR?": return b"+IPR=115200\r\n"
        if command.startswith("AT+") and command.endswith("?"):
            name = command[3:-1]
            if name not in self.settings: return b"+ERR=1\r\n"
            value = "BAD" if name == self.bad_readback else self.settings[name]
            return f"+{name}={value}\r\n".encode()
        if command.startswith("AT+TAG_SEND=8,"):
            self.payload = command.split(",",1)[1]
            return b"+OK\r\n"
        if command.startswith("AT+") and "=" in command:
            name, value = command[3:].split("=",1)
            if name not in self.settings: return b"+ERR=1\r\n"
            self.settings[name] = value
            self.flash_writes += 1
            return b"+OK\r\n"
        return b"+ERR=1\r\n"

    def reset(self):
        # Conservative interpretation of the guide's CPIN reset warning.
        self.settings["CPIN"] = "0"*32
        self.payload = "00000000"

    def range_response(self, tag, *, cm=700) -> bytes:
        if not self.powered or not tag.powered or not self.rf_open or not tag.rf_open: return b""
        if self.settings["MODE"] != "1" or tag.settings["MODE"] != "0": return b""
        if any(self.settings[k] != tag.settings[k] for k in ("CHANNEL","BANDWIDTH","CPIN","NETWORKID")): return b""
        if tag.settings["ADDRESS"] != TAG_ADDRESS: return b""
        return f"+ANCHOR_RCV={TAG_ADDRESS},8,{tag.payload},{cm} cm,-63\r\n".encode()


class DeskRadioHost:
    """Finite virtual transaction deadline; no real UART or hardware access."""
    def __init__(self, radio, *, fragment_size=3, byte_interval_ms=.0868, timeout_ms=250):
        self.radio = radio
        self.fragment_size = fragment_size
        self.byte_interval_ms = byte_interval_ms
        self.timeout_ms = timeout_ms
        self.ready = False
        self.reset_asserted = True
        self.transactions = 0

    def exchange(self, command, prefix):
        self.transactions += 1
        response = self.radio.command((command+"\r\n").encode("ascii"))
        framer = LineFramer()
        elapsed = 0.0
        for start in range(0,len(response),self.fragment_size):
            piece = response[start:start+self.fragment_size]
            elapsed += len(piece)*self.byte_interval_ms
            if elapsed >= self.timeout_ms: break
            lines = framer.feed(piece)
            if framer.rejected: break
            for line in lines:
                if line in ("+READY","+RESET") or line.startswith("+ERR"):
                    self.ready = False
                    self.reset_asserted = True
                    raise RadioFailure("radio reset or error during transaction")
                if line.startswith(prefix): return line[len(prefix):]
        self.ready = False
        self.reset_asserted = True
        raise RadioFailure("UART transaction failed or timed out")

    def start(self, aes_key, *, tag):
        self.ready = False
        self.reset_asserted = True
        desired = radio_settings(aes_key, tag=tag)
        try:
            if self.exchange("AT", "+OK") != "": raise RadioFailure("invalid acknowledgement")
            if self.exchange("AT+IPR?", "+IPR=") != "115200": raise RadioFailure("wrong baud readback")
            for name,value in desired.items():
                if self.exchange(f"AT+{name}?",f"+{name}=") != value:
                    if self.exchange(f"AT+{name}={value}","+OK") != "": raise RadioFailure("invalid acknowledgement")
                    if self.exchange(f"AT+{name}?",f"+{name}=") != value: raise RadioFailure("setting readback mismatch")
        except (RadioFailure, ValueError):
            self.reset_asserted = True
            raise
        self.ready = True
        self.reset_asserted = False

    def heartbeat(self, sequence):
        if not self.ready: raise RadioFailure("radio not initialized")
        if self.exchange("AT+TAG_SEND=8,"+counter_payload(sequence),"+OK") != "":
            self.ready = False
            self.reset_asserted = True
            raise RadioFailure("invalid acknowledgement")
