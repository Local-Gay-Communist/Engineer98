"""Engineer98 main window.

Minimal but functional: open a disk image, browse its partition table,
and inspect raw sectors in a hex view. This is the skeleton the real UI
will grow from — everything here exercises the Rust core through the
public `engineer98` API.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from engineer98 import Image


IMAGE_FILTER = (
    "PC-98 disk images (*.hdi *.fdi *.d88 *.hdm *.img *.nhd *.hdd);;All files (*)"
)

# How many bytes to show in the hex view when a partition is selected.
HEX_PREVIEW_BYTES = 2048


def hex_dump(data: bytes, base: int = 0, width: int = 16) -> str:
    """Format `data` as a classic hex + ASCII dump.

    `base` is the offset the first byte should be labelled with, so that
    reading from the middle of an image shows real file offsets.
    """
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + i:08x}  {hex_part:<{width * 3}}  {ascii_part}")
    return "\n".join(lines)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Engineer98")
        self.resize(1100, 700)

        self.image: Image | None = None

        # --- Central layout -------------------------------------------------
        self.header = QLabel("No image loaded.")
        self.header.setStyleSheet("padding: 6px; font-weight: bold;")

        self.partition_list = QListWidget()
        self.partition_list.currentRowChanged.connect(self._on_partition_selected)

        self.hex_view = QPlainTextEdit()
        self.hex_view.setReadOnly(True)
        self.hex_view.setStyleSheet("font-family: monospace;")
        self.hex_view.setPlaceholderText(
            "Select a partition to preview its first bytes."
        )

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Partitions"))
        left_layout.addWidget(self.partition_list)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self.hex_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(self.header)
        central_layout.addWidget(splitter)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready.")

        # --- Menu -----------------------------------------------------------
        open_action = QAction("&Open image…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_image)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(open_action)

    # -- Actions -------------------------------------------------------------

    def _open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open disk image", str(Path.home()), IMAGE_FILTER
        )
        if not path:
            return
        try:
            self.image = Image.open(path)
        except Exception as exc:  # noqa: BLE001 — surface any parse error
            self.image = None
            self.header.setText(f"Failed to open: {path}")
            self.partition_list.clear()
            self.hex_view.setPlainText(str(exc))
            self.statusBar().showMessage(f"Error: {exc}", 8000)
            return

        self._refresh()
        self.statusBar().showMessage(f"Opened {path}", 5000)

    def _refresh(self) -> None:
        assert self.image is not None
        g = self.image.geometry()
        self.header.setText(
            f"{self.image.format_name()} — "
            f"{g.cylinders} cyl × {g.heads} heads × {g.sectors_per_track} spt, "
            f"{g.sector_size} bytes/sector "
            f"({g.total_bytes():,} bytes total)"
        )

        self.partition_list.clear()
        for idx, p in enumerate(self.image.partitions()):
            label = (
                f"{idx}: {p.name or '(unnamed)'}  "
                f"[lba {p.start_lba}, {p.sector_count} sectors]"
                + ("  (boot)" if p.bootable else "")
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, p)
            self.partition_list.addItem(item)

        if self.partition_list.count() == 0:
            self.hex_view.setPlainText(
                "No partitions. Use the geometry above for raw sector access."
            )

    def _on_partition_selected(self, row: int) -> None:
        if self.image is None or row < 0:
            return
        item = self.partition_list.item(row)
        if item is None:
            return
        p = item.data(Qt.UserRole)

        g = self.image.geometry()
        bytes_per_sector = g.sector_size
        sectors_to_read = max(1, HEX_PREVIEW_BYTES // bytes_per_sector)

        try:
            data = self.image.read_sectors(p.start_lba, sectors_to_read)
        except Exception as exc:  # noqa: BLE001
            self.hex_view.setPlainText(f"Failed to read: {exc}")
            return

        # Absolute offset in the file so the hex addresses make sense next
        # to a hexdump of the raw image.
        file_offset = p.start_lba * bytes_per_sector
        self.hex_view.setPlainText(hex_dump(data, base=file_offset))


def run() -> int:
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    return app.exec()