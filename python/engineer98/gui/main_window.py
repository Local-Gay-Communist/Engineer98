"""Engineer98 main window.

Layout: partition list and file tree on the left, tabbed view on the
right (Hex / Disassembly). Everything here goes through the public
`engineer98` API — nothing reaches into the Rust core directly.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from engineer98 import (
    ExeFile,
    FatVolume,
    FunctionBuilder,
    Image,
    Partition,
    Traversal,
)


IMAGE_FILTER = (
    "PC-98 disk images (*.hdi *.fdi *.d88 *.hdm *.img *.nhd *.hdd);;All files (*)"
)

HEX_PREVIEW_BYTES = 4096
MAX_DISASM_LINES = 100_000  # safety cap for very large listings


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def hex_dump(data: bytes, base: int = 0, width: int = 16) -> str:
    """Format ``data`` as a classic hex + ASCII dump."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + i:08x}  {hex_part:<{width * 3}}  {ascii_part}")
    return "\n".join(lines)


def format_disassembly(instructions) -> str:
    """One line per instruction, mnemonic + operand string."""
    lines = []
    for insn in instructions[:MAX_DISASM_LINES]:
        hexb = insn.bytes_.hex(" ")
        lines.append(
            f"{insn.address:08x}  {hexb:<24}  {insn.mnemonic:<8} {insn.op_str}".rstrip()
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Engineer98")
        self.resize(1400, 800)

        # --- State ----------------------------------------------------------
        self.image: Image | None = None
        self.volume: FatVolume | None = None
        self.loaded_exe: ExeFile | None = None
        self.function_map = None
        self._last_preview_path: str | None = None

        # --- Header ---------------------------------------------------------
        self.header = QLabel("No image loaded.")
        self.header.setStyleSheet("padding: 6px; font-weight: bold;")

        # --- Partitions -----------------------------------------------------
        self.partition_list = QListWidget()
        self.partition_list.currentRowChanged.connect(self._on_partition_selected)

        # --- File tree ------------------------------------------------------
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Name", "Size"])
        self.file_tree.itemClicked.connect(self._on_file_clicked)
        self.file_tree.itemDoubleClicked.connect(self._on_file_double_clicked)

        left_top = QWidget()
        left_top_layout = QVBoxLayout(left_top)
        left_top_layout.setContentsMargins(0, 0, 0, 0)
        left_top_layout.addWidget(QLabel("Partitions"))
        left_top_layout.addWidget(self.partition_list)

        left_bottom = QWidget()
        left_bottom_layout = QVBoxLayout(left_bottom)
        left_bottom_layout.setContentsMargins(0, 0, 0, 0)
        left_bottom_layout.addWidget(QLabel("Files"))
        left_bottom_layout.addWidget(self.file_tree)

        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(left_top)
        left_splitter.addWidget(left_bottom)
        left_splitter.setStretchFactor(0, 1)
        left_splitter.setStretchFactor(1, 3)

        # --- Hex view -------------------------------------------------------
        self.hex_view = QPlainTextEdit()
        self.hex_view.setReadOnly(True)
        self.hex_view.setStyleSheet("font-family: monospace;")
        self.hex_view.setPlaceholderText("Select a partition or file.")

        # --- Disassembly view -----------------------------------------------
        self.function_combo = QComboBox()
        self.function_combo.currentIndexChanged.connect(self._on_function_selected)

        self.disasm_view = QPlainTextEdit()
        self.disasm_view.setReadOnly(True)
        self.disasm_view.setStyleSheet("font-family: monospace;")
        self.disasm_view.setPlaceholderText(
            "Double-click an .EXE in the file tree to disassemble it."
        )

        disasm_tab = QWidget()
        disasm_layout = QVBoxLayout(disasm_tab)
        disasm_layout.setContentsMargins(4, 4, 4, 4)
        disasm_layout.addWidget(self.function_combo)
        disasm_layout.addWidget(self.disasm_view)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.hex_view, "Hex")
        self.tabs.addTab(disasm_tab, "Disassembly")

        # --- Assemble main splitter ----------------------------------------
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(self.tabs)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(self.header)
        central_layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        # --- Status bar -----------------------------------------------------
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready.")

        # --- Menu -----------------------------------------------------------
        open_action = QAction("&Open image…", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_image)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(open_action)

    # -- Image loading -------------------------------------------------------

    def _open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open disk image", str(Path.home()), IMAGE_FILTER
        )
        if not path:
            return
        try:
            self.image = Image.open(path)
        except Exception as exc:  # noqa: BLE001
            self.image = None
            self.header.setText(f"Failed to open: {path}")
            self.partition_list.clear()
            self.file_tree.clear()
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

        # Reset per-partition state.
        self.volume = None
        self.file_tree.clear()
        self._clear_disassembly()
        self._last_preview_path = None

        if self.partition_list.count() > 0:
            self.partition_list.setCurrentRow(0)
        else:
            self.hex_view.setPlainText(
                "No partitions. This image may be a raw floppy."
            )

    # -- Partition selection -------------------------------------------------

    def _on_partition_selected(self, row: int) -> None:
        if self.image is None or row < 0:
            return
        item = self.partition_list.item(row)
        if item is None:
            return
        p: Partition = item.data(Qt.UserRole)

        # Hex preview of the partition's first sectors.
        g = self.image.geometry()
        sectors_to_read = max(1, HEX_PREVIEW_BYTES // g.sector_size)
        try:
            data = self.image.read_sectors(p.start_lba, sectors_to_read)
        except Exception as exc:  # noqa: BLE001
            self.hex_view.setPlainText(f"Failed to read: {exc}")
        else:
            self.hex_view.setPlainText(
                hex_dump(data, base=p.start_lba * g.sector_size)
            )

        # Try to mount a FAT volume on this partition.
        self.volume = None
        self.file_tree.clear()
        self._clear_disassembly()
        self._last_preview_path = None
        try:
            self.volume = FatVolume(self.image, p)
        except Exception as exc:  # noqa: BLE001
            root = QTreeWidgetItem([f"(not a FAT volume: {exc})", ""])
            self.file_tree.addTopLevelItem(root)
            return

        self._populate_tree()

    # -- File tree -----------------------------------------------------------

    def _populate_tree(self) -> None:
        assert self.volume is not None
        self.file_tree.clear()

        def add_dir(parent_item: QTreeWidgetItem | None, path: str) -> None:
            try:
                entries = self.volume.list_dir(path)
            except Exception:
                return
            for e in entries:
                if e.name in (".", ".."):
                    continue
                full = (
                    f"{path.rstrip('/')}/{e.name}" if path != "/" else f"/{e.name}"
                )
                size = "" if e.is_directory else f"{e.size}"
                child = QTreeWidgetItem([e.name, size])
                child.setData(0, Qt.UserRole, full)
                child.setData(0, Qt.UserRole + 1, e.is_directory)
                if parent_item is None:
                    self.file_tree.addTopLevelItem(child)
                else:
                    parent_item.addChild(child)
                if e.is_directory:
                    add_dir(child, full)

        add_dir(None, "/")

    def _on_file_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if self.volume is None:
            return
        path = item.data(0, Qt.UserRole)
        is_dir = item.data(0, Qt.UserRole + 1)
        if path is None or is_dir:
            return
        if self._last_preview_path == path:
            return
        try:
            data = self.volume.read_file(path)
        except Exception as exc:  # noqa: BLE001
            self.hex_view.setPlainText(f"Failed to read {path}: {exc}")
            return
        self._last_preview_path = path
        preview = data[:HEX_PREVIEW_BYTES]
        suffix = (
            "" if len(data) <= HEX_PREVIEW_BYTES
            else f"\n\n... ({len(data):,} bytes total, showing first {HEX_PREVIEW_BYTES})"
        )
        self.hex_view.setPlainText(hex_dump(preview) + suffix)
        self.tabs.setCurrentWidget(self.hex_view)

    def _on_file_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if self.volume is None:
            return
        path = item.data(0, Qt.UserRole)
        is_dir = item.data(0, Qt.UserRole + 1)
        if path is None or is_dir:
            return
        if not path.upper().endswith(".EXE"):
            return
        self._load_exe(path)

    # -- Disassembly ---------------------------------------------------------

    def _clear_disassembly(self) -> None:
        self.loaded_exe = None
        self.function_map = None
        self.function_combo.blockSignals(True)
        self.function_combo.clear()
        self.function_combo.blockSignals(False)
        self.disasm_view.clear()

    def _load_exe(self, path: str) -> None:
        assert self.volume is not None

        # Disassembly of a full EXE is CPU-bound Python work; a wait cursor
        # and a status message are enough for now. If we start seeing large
        # binaries where this is more than a couple of seconds, move it to a
        # QThread.
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.statusBar().showMessage(f"Disassembling {path}…")
        QApplication.processEvents()
        try:
            data = self.volume.read_file(path)
            exe = ExeFile.from_bytes(data)
            trav = Traversal.from_exe(exe)
            entry = Traversal.entry_offset(exe)
            cmap = trav.trace(entry)
            fmap = FunctionBuilder(cmap, entry_point=entry).build()
        except Exception as exc:  # noqa: BLE001
            self.disasm_view.setPlainText(f"Failed to disassemble {path}: {exc}")
            self.statusBar().showMessage(f"Error: {exc}", 8000)
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.loaded_exe = exe
        self.function_map = fmap

        self.function_combo.blockSignals(True)
        self.function_combo.clear()
        for f in sorted(fmap.functions.values(), key=lambda x: x.entry):
            label = (
                f"{f.name}  @ {f.entry:06x}  "
                f"({f.instruction_count} insns, {len(f.calls_out)} callees)"
            )
            self.function_combo.addItem(label, f.entry)
        self.function_combo.blockSignals(False)

        if self.function_combo.count() > 0:
            self.function_combo.setCurrentIndex(0)
            self._on_function_selected(0)

        self.tabs.setCurrentIndex(1)
        self.statusBar().showMessage(
            f"{path}: {len(fmap)} functions, {len(cmap)} instructions", 5000
        )

    def _on_function_selected(self, index: int) -> None:
        if self.function_map is None or index < 0:
            return
        entry = self.function_combo.itemData(index)
        if entry is None:
            return
        func = self.function_map.get(entry)
        if func is None:
            return
        self.disasm_view.setPlainText(format_disassembly(func.instructions))
        self.disasm_view.verticalScrollBar().setValue(0)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.show()
    return app.exec()