"""Open this paired ESP32 CH340 for diagnostics without pulsing its reset circuit.
Explicit esptool firmware flashing uses its own reset sequence and must not use this helper.
"""
import serial
import termios

PORT='/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0'

def open_diagnostics(timeout=.1):
    port=serial.Serial(port=None,baudrate=115200,timeout=timeout,write_timeout=1)
    # This board's auto-reset circuit is inactive when both controls are asserted.
    # Initializing both False caused POWERON_RESET on every subsequent open.
    port.dtr=True
    port.rts=True
    port.port=PORT
    port.open()
    try:
        flags=termios.tcgetattr(port.fileno())
        flags[2]&=~termios.HUPCL
        termios.tcsetattr(port.fileno(),termios.TCSANOW,flags)
    except BaseException:
        port.close()
        raise
    return port
