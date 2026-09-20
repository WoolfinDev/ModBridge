"""Shared constants: theme, fonts, profile transfer rules."""

import sys

# Per-OS font families: Segoe UI/Consolas exist on Windows only,
# DejaVu ships with most Linux distros.
if sys.platform == "win32":
    UI_FONT = "Segoe UI"
    MONO_FONT = "Consolas"
else:
    UI_FONT = "DejaVu Sans"
    MONO_FONT = "DejaVu Sans Mono"

PROFILE_TRANSFER_HIDE_NAMES = frozenset({
    ".fabric",
    ".mixin.out",
    "data",
    "downloads",
    "debug",
    "crash-reports",
    "logs",
})

PROFILE_TRANSFER_HIDE_PREFIXES = (
    "XaeroWaypoints_BACKUP",
)

PROFILE_TRANSFER_DEFAULT_CHECKED = frozenset({
    "mods",
    "resourcepacks",
    "config",
    "shaderpacks",
    "options.txt",
})

COLORS = {
    "bg": "#0b0f14",
    "panel": "#121922",
    "card": "#1a2330",
    "input": "#0d1218",
    "border": "#2d3d52",
    "text": "#e8eef5",
    "muted": "#8fa3b8",
    "accent": "#66bb6a",
    "accent_hover": "#4caf50",
    "accent_subtle": "#1e3d32",
    "error": "#3d2228",
    "error_fg": "#ffb4b4",
    "progress_bg": "#243041",
    "tab_idle": "#222d3d",
    "tab_idle_hover": "#2a3849",
    "btn_disabled": "#2a3444",
    "warning":   "#3d3320",
    "warning_fg": "#ffcc80",
    "info":      "#1e2a3d",
    "info_fg":   "#90caf9",
}

FONTS = {
    "title": (UI_FONT, 17, "bold"),
    "head": (UI_FONT, 15, "bold"),
    "section": (UI_FONT, 13, "bold"),
    "body": (UI_FONT, 14),
    "small": (UI_FONT, 11),
    "caption": (UI_FONT, 10),
    "mono": (MONO_FONT, 16),
}