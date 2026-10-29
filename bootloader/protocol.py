"""UART bootloader protocol shared with the planned PIC implementation.

Text commands use CR/LF. Binary upload frame:
    SOF (0x02), sequence (uint16 big-endian), length (uint16 big-endian),
    payload (1..BLOCK_SIZE bytes), CRC16-CCITT (uint16 big-endian).
The CRC16 covers sequence + length + payload. The target acknowledges each
frame with ACK (0x06) + sequence (uint16 big-endian), or NAK (0x15) + sequence.
Upload starts with: UPLOAD <decimal-size> <8-hex-digit-CRC32>\r\n
Target replies READY\r\n, then accepts frames. Host ends with EOT (0x04);
target replies OK <8-hex-digit-CRC32>\r\n.

NOTE: this protocol is a host-side contract for the next bootloader revision.
The currently published PIC Stage 1 does NOT implement it yet.
"""
import zlib

SOF = 0x02
ACK = 0x06
NAK = 0x15
EOT = 0x04
BLOCK_SIZE = 48


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection/xorout."""
    crc = initial
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def make_frame(sequence: int, payload: bytes) -> bytes:
    if not payload or len(payload) > BLOCK_SIZE:
        raise ValueError(f"Payload length must be 1..{BLOCK_SIZE} bytes")
    header = sequence.to_bytes(2, "big") + len(payload).to_bytes(2, "big")
    body = header + payload
    return bytes([SOF]) + body + crc16_ccitt(body).to_bytes(2, "big")
