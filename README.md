# PIC18F66K80 Firmware Uploader

Windows desktop application written in Python with PySide6 and pySerial.

## Features

- Refresh and select a Windows COM port
- Select baud rate (default: 115200, 8-N-1)
- Connect / Disconnect
- Select a firmware `.bin` file
- Send `INFO`, `BOOT`, and `RUN` commands
- Communication log and upload progress bar
- Host-side binary transfer implementation with per-block ACK/retry and CRC checks

## Run in Visual Studio Code

Install Python 3.11 or newer, then open this folder in VS Code. In the terminal:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

If PowerShell blocks virtual-environment activation, run:
```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Current bootloader compatibility status

The current PIC Stage 1 firmware implements only `INFO`, `BOOT`, and `RUN`. Its `BOOT` response explicitly says `FLASH UPDATE NOT IMPLEMENTED`. Therefore, **the current PIC firmware cannot program a .bin yet**. The uploader's upload client is prepared for the protocol below, but actual programming requires implementing the same protocol and safe Flash erase/write logic in the PIC bootloader.

UART2 hardware settings currently documented in the PIC project:
- RX: RE6
- TX: RE7
- 115200 baud, 8 data bits, no parity, 1 stop bit
- No hardware flow control

## Proposed host ↔ PIC binary upload protocol

All text command lines end with CR/LF.

1. Host sends `UPLOAD <decimal-size> <CRC32-hex>\r\n`.
2. PIC validates size/range and replies `READY\r\n`. Any other response aborts the upload.
3. Host sends frames, one at a time:
   - `SOF = 0x02`
   - `sequence = uint16 big-endian`
   - `length = uint16 big-endian` (1..48)
   - `payload = length bytes`
   - `CRC16 = uint16 big-endian`, CRC-16/CCITT-FALSE over sequence + length + payload
4. PIC replies with `ACK (0x06) + sequence (uint16 big-endian)`, or `NAK (0x15) + sequence`. The host retries a frame up to three times.
5. Host sends `EOT = 0x04` after all blocks.
6. PIC verifies the final image CRC32 and replies `OK <CRC32-hex>\r\n` only after a successful update.

**Safety requirement:** the PIC implementation must reject images that overlap the bootloader region, validate the application start/entry layout, handle the final partial Flash write block, and report success only after verification. The application's configured link offset is currently 0x0800; confirm the exact flash erase/write row sizes and protection/configuration bits against the PIC18F66K80 datasheet and the project's linker configuration before implementing writes.

## Project layout

```
main.py
requirements.txt
bootloader/
  protocol.py
  serial_manager.py
ui/
  main_window.py
```
