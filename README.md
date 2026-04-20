# Terminal-Typography-Renderer

A high-fidelity ASCII art text renderer with an interactive TUI for real-time parameter adjustment and animations.

## Features

- **Pillow-based rendering engine** — Uses TrueType/OpenType fonts for razor-sharp text at terminal resolution (1:1 pixel-to-character mapping)
- **Robust input handling** — Properly captures multi-byte ANSI escape sequences for smooth arrow-key navigation
- **Multiple animation modes** — SHEEN, MOTION, ROTATE, PULSE, TYPEWRITER, STATIC
- **Interactive TUI** — Real-time control of font, size, boldness, brightness, contrast, colors, and more
- **Bayer matrix dithering** — High-quality ASCII conversion with ordered dithering
- **10 character sets** — standard, blocks, minimal, binary, hex, braille, cyber, math, slashes, waves
- **Terminal aspect ratio correction** — Compensates for non-square character cells

## Installation

```bash
pip install pillow numpy
```

## Usage

```bash
python terminal_typo.py [text] [-w WIDTH] [-H HEIGHT] [-s SPEED]
```

### Examples

```bash
python terminal_typo.py "Hello World"
python terminal_typo.py "ASCII" -w 120 -H 40 -s 1.5
```

### TUI Controls

| Key | Action |
|-----|--------|
| ↑/↓ | Navigate parameters |
| ←/→ | Adjust selected parameter |
| Enter | Edit text |
| Esc / q | Quit |

## Font Support

The renderer automatically detects TrueType fonts installed on your system:

- **Linux**: `/usr/share/fonts/truetype/` (DejaVu, Liberation, Lato, etc.)
- **Windows**: `C:/Windows/Fonts/` (Arial, Times, Courier, etc.)

If no system font is found, it falls back to Pillow's built-in bitmap font.