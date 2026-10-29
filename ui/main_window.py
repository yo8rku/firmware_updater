from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)
from serial import SerialException

from bootloader.serial_manager import SerialManager, BootloaderError


class TaskWorker(QThread):
    log = Signal(str)
    progress = Signal(int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, manager: SerialManager, task: str, file_path: str = ""):
        super().__init__()
        self.manager = manager
        self.task = task
        self.file_path = file_path

    def run(self):
        try:
            if self.task == "INFO":
                result = self.manager.send_command("INFO")
                for line in result:
                    self.log.emit(f"PIC: {line}")
                self.finished_ok.emit("INFO command completed.")
            elif self.task in ("BOOT", "RUN"):
                result = self.manager.send_command(self.task)
                for line in result:
                    self.log.emit(f"PIC: {line}")
                if self.task == "BOOT" and any("NOT IMPLEMENTED" in line for line in result):
                    self.failed.emit("Bootloader is in test mode; flash update is not implemented.")
                else:
                    self.finished_ok.emit(f"{self.task} command completed.")
            elif self.task == "UPLOAD":
                result = self.manager.upload_firmware(
                    self.file_path,
                    lambda done, total: self.progress.emit(int(done * 100 / total)),
                )
                self.finished_ok.emit(result)
        except (BootloaderError, SerialException, OSError, ValueError) as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PIC18F66K80 Firmware Uploader")
        self.resize(820, 600)
        self.serial_manager = SerialManager()
        self.worker: TaskWorker | None = None
        self.firmware_path = ""

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        connection_box = QGroupBox("Serial connection — UART2, 8-N-1")
        connection_layout = QGridLayout(connection_box)
        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh")
        self.baud_combo = QComboBox()
        for baud in (9600, 19200, 38400, 57600, 115200, 230400):
            self.baud_combo.addItem(str(baud), baud)
        self.baud_combo.setCurrentText("115200")
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.setEnabled(False)
        connection_layout.addWidget(QLabel("COM port:"), 0, 0)
        connection_layout.addWidget(self.port_combo, 0, 1)
        connection_layout.addWidget(self.refresh_button, 0, 2)
        connection_layout.addWidget(QLabel("Baud rate:"), 1, 0)
        connection_layout.addWidget(self.baud_combo, 1, 1)
        connection_layout.addWidget(self.connect_button, 1, 2)
        connection_layout.addWidget(self.disconnect_button, 1, 3)
        root.addWidget(connection_box)

        firmware_box = QGroupBox("Firmware image")
        firmware_layout = QGridLayout(firmware_box)
        self.file_label = QLabel("No .bin file selected")
        self.file_label.setWordWrap(True)
        self.browse_button = QPushButton("Browse .bin…")
        self.upload_button = QPushButton("Upload firmware")
        self.upload_button.setEnabled(False)
        firmware_layout.addWidget(self.file_label, 0, 0, 1, 2)
        firmware_layout.addWidget(self.browse_button, 0, 2)
        firmware_layout.addWidget(self.upload_button, 1, 2)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        firmware_layout.addWidget(self.progress_bar, 1, 0, 1, 2)
        root.addWidget(firmware_box)

        command_box = QGroupBox("Bootloader commands")
        command_layout = QHBoxLayout(command_box)
        self.info_button = QPushButton("INFO")
        self.boot_button = QPushButton("BOOT")
        self.run_button = QPushButton("RUN")
        for button in (self.info_button, self.boot_button, self.run_button):
            button.setEnabled(False)
            command_layout.addWidget(button)
        root.addWidget(command_box)

        root.addWidget(QLabel("Communication log"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        root.addWidget(self.log_view, 1)
        self.status_label = QLabel("Disconnected")
        root.addWidget(self.status_label)

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.connect_serial)
        self.disconnect_button.clicked.connect(self.disconnect_serial)
        self.browse_button.clicked.connect(self.choose_firmware)
        self.upload_button.clicked.connect(self.upload_firmware)
        self.info_button.clicked.connect(lambda: self.start_task("INFO"))
        self.boot_button.clicked.connect(lambda: self.start_task("BOOT"))
        self.run_button.clicked.connect(self.confirm_run)

        self.refresh_ports()
        self.log("Application ready. PIC UART2 default: 115200 baud, 8-N-1.")
        self.log("NOTE: the currently installed Stage 1 firmware does not support flash upload yet.")

    def log(self, message: str):
        self.log_view.appendPlainText(message)

    def refresh_ports(self):
        selected = self.port_combo.currentText()
        self.port_combo.clear()
        ports = self.serial_manager.available_ports()
        self.port_combo.addItems(ports)
        if selected in ports:
            self.port_combo.setCurrentText(selected)
        if not ports:
            self.port_combo.addItem("(no COM ports found)")
            self.port_combo.setEnabled(False)
        else:
            self.port_combo.setEnabled(True)
        self.log(f"Serial ports refreshed: {', '.join(ports) if ports else 'none found'}")

    def connect_serial(self):
        port_name = self.port_combo.currentText()
        if not port_name or port_name.startswith("("):
            QMessageBox.warning(self, "No COM port", "Select a valid COM port first.")
            return
        try:
            message = self.serial_manager.connect(port_name, int(self.baud_combo.currentData()))
            self.log(message)
            self.status_label.setText(message)
            self.connect_button.setEnabled(False)
            self.disconnect_button.setEnabled(True)
            self.port_combo.setEnabled(False)
            self.baud_combo.setEnabled(False)
            self.refresh_button.setEnabled(False)
            for button in (self.info_button, self.boot_button, self.run_button):
                button.setEnabled(True)
            self.upload_button.setEnabled(bool(self.firmware_path))
        except (SerialException, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Connection failed", str(exc))
            self.log(f"ERROR: {exc}")

    def disconnect_serial(self):
        self.serial_manager.disconnect()
        self.log("Serial port disconnected.")
        self.status_label.setText("Disconnected")
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.port_combo.setEnabled(True)
        self.baud_combo.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.upload_button.setEnabled(False)
        for button in (self.info_button, self.boot_button, self.run_button):
            button.setEnabled(False)

    def choose_firmware(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select PIC firmware binary", "", "Binary firmware (*.bin);;All files (*)"
        )
        if path:
            self.firmware_path = path
            from pathlib import Path
            p = Path(path)
            self.file_label.setText(f"{p.name}  —  {p.stat().st_size:,} bytes\n{p}")
            self.progress_bar.setValue(0)
            self.upload_button.setEnabled(self.serial_manager.connected)
            self.log(f"Selected firmware: {p.name} ({p.stat().st_size} bytes)")

    def start_task(self, task: str, file_path: str = ""):
        if not self.serial_manager.connected:
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "Wait for the current operation to finish.")
            return
        self.set_operation_enabled(False)
        self.log(f">>> {task}" + (f" {file_path}" if file_path else ""))
        self.worker = TaskWorker(self.serial_manager, task, file_path)
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.finished_ok.connect(self.task_succeeded)
        self.worker.failed.connect(self.task_failed)
        self.worker.finished.connect(lambda: self.set_operation_enabled(True))
        self.worker.start()

    def upload_firmware(self):
        if not self.firmware_path:
            return
        answer = QMessageBox.warning(
            self,
            "Firmware upload",
            "The current PIC Stage 1 bootloader does not implement flash programming. "
            "This uploader will attempt the defined UPLOAD protocol and report an error "
            "if the PIC firmware has not been updated. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.progress_bar.setValue(0)
            self.start_task("UPLOAD", self.firmware_path)

    def confirm_run(self):
        answer = QMessageBox.question(
            self, "Start application",
            "Send RUN? The PIC will leave the bootloader and start the application.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.start_task("RUN")

    def set_operation_enabled(self, enabled: bool):
        connected = self.serial_manager.connected
        for button in (self.info_button, self.boot_button, self.run_button,
                       self.upload_button, self.browse_button, self.connect_button,
                       self.disconnect_button, self.refresh_button):
            button.setEnabled(enabled)
        self.upload_button.setEnabled(enabled and connected and bool(self.firmware_path))
        self.info_button.setEnabled(enabled and connected)
        self.boot_button.setEnabled(enabled and connected)
        self.run_button.setEnabled(enabled and connected)
        self.browse_button.setEnabled(enabled)
        self.disconnect_button.setEnabled(enabled and connected)
        self.connect_button.setEnabled(enabled and not connected)
        self.refresh_button.setEnabled(enabled and not connected)

    def task_succeeded(self, message: str):
        self.log(f"OK: {message}")
        self.status_label.setText(message)

    def task_failed(self, message: str):
        self.log(f"ERROR: {message}")
        self.status_label.setText("Operation failed")
        QMessageBox.warning(self, "Operation failed", message)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, "Operation in progress", "Wait for the current operation to finish.")
            event.ignore()
            return
        self.serial_manager.disconnect()
        event.accept()
