#!/usr/bin/env python3
"""ModBridge asset generator (app icon + UI glyphs), painted in code, no fonts.

Produces:
    assets/icon.png    (256x256, for Linux/.desktop/window)
    assets/icon.ico    (16..256 PNG-compressed ICO, for the Windows exe)
    assets/chev_*.png  (QComboBox chevron, light)
    assets/check_*.png (QCheckBox checkmark, dark on accent)
    assets/cross_*.png (delete-button cross, red, 2x)
    assets/globe_*.png (language selector globe, muted, 2x)
    assets/refresh_*.png (profiles refresh arrow, accent, 2x)

Filenames embed theme hex colors: after a palette change the old files
simply stop matching and the app picks up the new ones.

Usage:
    QT_QPA_PLATFORM=offscreen python packaging/make_icon.py           # missing only
    QT_QPA_PLATFORM=offscreen python packaging/make_icon.py --force  # regenerate all

Existing files (e.g. a custom assets/icon.png) are never touched
without --force.
"""

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "assets"

BG_TOP = "#1a2330"
BG_BOTTOM = "#0b0f14"
BORDER = "#2d3d52"
ACCENT = "#66bb6a"
TEXT = "#e8eef5"
MUTED = "#8fa3b8"
ERROR_FG = "#ffb4b4"


def paint_glyph(kind: str):
    """UI glyphs, pixel-identical to the runtime fallbacks in app.py."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    if kind == "chev":
        px = QPixmap(14, 14)
        px.fill(Qt.transparent)
        pt = QPainter(px)
        pt.setRenderHint(QPainter.Antialiasing, True)
        pt.setPen(QPen(QColor(TEXT), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pt.drawLine(3, 5, 7, 9)
        pt.drawLine(7, 9, 11, 5)
        pt.end()
        return px, f"chev_{TEXT.lstrip('#')}.png"
    if kind == "check":
        px = QPixmap(14, 14)
        px.fill(Qt.transparent)
        pt = QPainter(px)
        pt.setRenderHint(QPainter.Antialiasing, True)
        pt.setPen(QPen(QColor(BG_BOTTOM), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pt.drawLine(3, 7.5, 6.5, 11)
        pt.drawLine(6.5, 11, 11.5, 3.5)
        pt.end()
        return px, f"check_{BG_BOTTOM.lstrip('#')}.png"
    if kind == "cross":
        px = QPixmap(32, 32)
        px.fill(Qt.transparent)
        pt = QPainter(px)
        pt.setRenderHint(QPainter.Antialiasing, True)
        pt.setPen(QPen(QColor(ERROR_FG), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pt.drawLine(8, 8, 24, 24)
        pt.drawLine(24, 8, 8, 24)
        pt.end()
        return px, f"cross_{ERROR_FG.lstrip('#')}.png"
    if kind == "globe":
        px = QPixmap(36, 36)
        px.fill(Qt.transparent)
        pt = QPainter(px)
        pt.setRenderHint(QPainter.Antialiasing, True)
        pt.setPen(QPen(QColor(MUTED), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pt.drawEllipse(3, 3, 30, 30)
        pt.drawEllipse(11, 3, 14, 30)
        pt.drawLine(3, 18, 33, 18)
        pt.drawLine(5.3, 10, 30.7, 10)
        pt.drawLine(5.3, 26, 30.7, 26)
        pt.end()
        return px, f"globe_{MUTED.lstrip('#')}.png"
    if kind == "refresh":
        px = QPixmap(36, 36)
        px.fill(Qt.transparent)
        pt = QPainter(px)
        pt.setRenderHint(QPainter.Antialiasing, True)
        pt.setPen(QPen(QColor(ACCENT), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        pt.drawArc(6, 6, 24, 24, 50 * 16, -300 * 16)
        pt.drawLine(14, 7, 6, 5.5)
        pt.drawLine(14, 7, 8.5, 12.5)
        pt.end()
        return px, f"refresh_{ACCENT.lstrip('#')}.png"
    raise ValueError(kind)


def paint(size: int):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap

    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    pt = QPainter(px)
    pt.setRenderHint(QPainter.Antialiasing, True)

    # Rounded square with a vertical gradient.
    grad = QLinearGradient(0, 0, 0, size)
    grad.setColorAt(0, QColor(BG_TOP))
    grad.setColorAt(1, QColor(BG_BOTTOM))
    pt.setBrush(grad)
    pt.setPen(QPen(QColor(BORDER), max(2, size // 64)))
    r = size * 0.22
    m = size * 0.02
    pt.drawRoundedRect(m, m, size - 2 * m, size - 2 * m, r, r)

    # Download arrow into a tray.
    u = size / 256
    pt.setPen(QPen(QColor(ACCENT), 22 * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pt.drawLine(128 * u, 58 * u, 128 * u, 148 * u)  # shaft
    pt.drawLine(128 * u, 158 * u, 88 * u, 116 * u)  # head, left
    pt.drawLine(128 * u, 158 * u, 168 * u, 116 * u)  # head, right
    pt.drawLine(64 * u, 184 * u, 192 * u, 184 * u)  # tray
    pt.end()
    return px


def write_ico(pngs: dict, out: Path):
    """ICO container with PNG-compressed images (Windows Vista+)."""
    entries = sorted(pngs.items())
    n = len(entries)
    header = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    dirs, blobs = b"", b""
    for size, data in entries:
        w = 0 if size >= 256 else size
        dirs += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    out.write_bytes(header + dirs + blobs)


def _save(px, path: Path, force: bool) -> bool:
    """Save an image; keep existing files unless --force is given."""
    if path.exists() and not force:
        print(f"skip (custom file kept): {path.name}")
        return True
    if not px.save(str(path)):
        print(f"failed to save {path.name}")
        return False
    print(f"ok: {path}")
    return True


def main(argv=None) -> int:
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtWidgets import QApplication

    force = "--force" in (argv if argv is not None else sys.argv[1:])

    app = QApplication([])
    ASSETS.mkdir(parents=True, exist_ok=True)

    base = paint(256)
    if not _save(base, ASSETS / "icon.png", force):
        return 1

    from PySide6.QtGui import QImage
    ico_path = ASSETS / "icon.ico"
    if not ico_path.exists() or force:
        sizes = {}
        for s in (16, 32, 48, 64, 128, 256):
            img = base.toImage().scaled(
                s, s, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            sizes[s] = bytes(buf.data())
        write_ico(sizes, ico_path)
        print(f"ok: {ico_path} ({', '.join(map(str, sorted(sizes)))})")
    else:
        print(f"skip (свой файл): {ico_path.name}")

    for kind in ("chev", "check", "cross", "globe", "refresh"):
        px, name = paint_glyph(kind)
        if not _save(px, ASSETS / name, force):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
