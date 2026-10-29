"""Serial transport and host-side firmware upload implementation."""
from __future__ import annotations

import time
from pathlib import Path
import serial
from serial.tools import list_ports

from .protocol import ACK, NAK, EOT, BLOCK_SIZE, crc32, make_frame


class BootloaderError(RuntimeError):
    pass


class SerialManager:
    def __init__(self):
        self.port: serial.Serial | None = None

    @staticmethod
    def available_ports() -> list[str]:
        return [p.device for p in list_ports.comports()]

    @property
    def connected(self) -> bool:
        return self.port is not None and self.port.is_open

    def connect(self, port_name: str, baud_rate: int = 115200) -> str:
        self.disconnect()
        self.port = serial.Serial(
            port=port_name,
            baudrate=baud_rate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.15,
            write_timeout=2.0,
        )
        self.port.reset_input_buffer()
        self.port.reset_output_buffer()
        return f"Connected to {port_name} at {baud_rate} baud (8-N-1)."

    def disconnect(self) -> None:
        if self.port is not None:
            try:
                if self.port.is_open:
                    self.port.close()
            finally:
                self.port = None

    def _require_port(self) -> serial.Serial:
        if not self.connected:
            raise BootloaderError("Serial port is not connected.")
        return self.port  # type: ignore[return-value]

    def _read_line(self, timeout: float = 2.5) -> str:
        port = self._require_port()
        deadline = time.monotonic() + timeout
        received = bytearray()
        while time.monotonic() < deadline:
            chunk = port.read(1)
            if not chunk:
                continue
            if chunk in (b"\r", b"\n"):
                if received:
                    return received.decode("ascii", errors="replace").strip()
                continue
            received.extend(chunk)
            if len(received) > 512:
                raise BootloaderError("Response line too long.")
        if received:
            return received.decode("ascii", errors="replace").strip()
        raise BootloaderError("Timeout waiting for PIC response.")

    def send_command(self, command: str, timeout: float = 2.5) -> list[str]:
        port = self._require_port()
        if not command or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 " for ch in command):
            raise ValueError("Invalid command.")
        port.reset_input_buffer()
        port.write((command + "\r\n").encode("ascii"))
        port.flush()
        lines: list[str] = []
        # INFO responds with two lines; other commands respond with one.
        expected = 2 if command == "INFO" else 1
        for _ in range(expected):
            lines.append(self._read_line(timeout))
        return lines

    def upload_firmware(self, file_path: str, progress_callback=None) -> str:
        """Transfer a .bin using the protocol documented in protocol.py.

        The current Stage 1 firmware returns 'ERR UNKNOWN COMMAND' for UPLOAD;
        that response is reported as an incompatibility, not as a successful upload.
        """
        path = Path(file_path)
        if not path.is_file():
            raise BootloaderError("Firmware file does not exist.")
        if path.suffix.lower() != ".bin":
            raise BootloaderError("Please select a .bin firmware file.")
        data = path.read_bytes()
        if not data:
            raise BootloaderError("Firmware file is empty.")
        if len(data) > 0xFFFFFFFF:
            raise BootloaderError("Firmware file is too large.")

        port = self._require_port()
        image_crc = crc32(data)
        port.reset_input_buffer()
        request = f"UPLOAD {len(data)} {image_crc:08X}\r\n".encode("ascii")
        port.write(request)
        port.flush()

        response = self._read_line(timeout=5.0)
        if response != "READY":
            if "FLASH UPDATE NOT IMPLEMENTED" in response:
                raise BootloaderError(
                    "PIC bootloader is connected, but flash update is not implemented. "
                    "The .bin was NOT programmed. Update the PIC bootloader before uploading."
                )
            raise BootloaderError(
                f"PIC did not accept the upload request (response: {response!r}). "
                "The current Stage 1 bootloader does not yet support the UPLOAD protocol."
            )

        total = len(data)
        offset = 0
        sequence = 0
        while offset < total:
            payload = data[offset:offset + BLOCK_SIZE]
            frame = make_frame(sequence, payload)
            attempts = 0
            while True:
                port.write(frame)
                port.flush()
                reply = port.read(3)
                if len(reply) == 3:
                    code = reply[0]
                    reply_seq = int.from_bytes(reply[1:3], "big")
                    if reply_seq == sequence and code == ACK:
                        break
                    if reply_seq == sequence and code == NAK:
                        attempts += 1
                    else:
                        attempts += 1
                else:
                    attempts += 1
                if attempts >= 3:
                    raise BootloaderError(f"No valid ACK for block {sequence}; upload aborted.")
            offset += len(payload)
            sequence = (sequence + 1) & 0xFFFF
            if progress_callback:
                progress_callback(offset, total)

        port.write(bytes([EOT]))
        port.flush()
        final = self._read_line(timeout=5.0)
        expected = f"OK {image_crc:08X}"
        if final != expected:
            raise BootloaderError(f"Target did not confirm firmware image (response: {final!r}).")
        return f"Firmware accepted: {path.name} ({total} bytes, CRC32 {image_crc:08X})."
