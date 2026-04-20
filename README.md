# Terminal-Typography-Renderer

A high-fidelity ASCII art text renderer with an interactive TUI for real-time parameter adjustment and animations. Features a **per-letter glyph segmentation engine** for independent character-level effects.

## Features

- **Per-letter typography engine** — Each character is rendered onto its own sub-buffer with independent Y-offset and opacity, enabling wave and dissolve effects
- **Pillow-based rendering engine** — Uses TrueType/OpenType fonts for razor-sharp text at terminal resolution (1:1 pixel-to-character mapping)
- **Robust input handling** — Properly captures multi-byte ANSI escape sequences for smooth arrow-key navigation
- **8 animation modes** — SHARP_BLADE, MOTION, SPIN_360, PULSE, TYPEWRITER, TYPO_WAVE, ETHEREAL, STATIC
- **Interactive TUI** — Real-time control of font, size, boldness, brightness, contrast, colors, and more
- **Bayer matrix dithering** — High-quality ASCII conversion with ordered dithering and per-frame micro-noise for living texture
- **9 character sets** — standard, blocks, minimal, binary, hex, braille, math, slashes, waves
- **Terminal aspect ratio correction** — Compensates for non-square character cells
- **Normalized loop architecture** — 1.0s cycle with rest phase for professional-looking animations

## Animation Presets

| Preset | Motion Curve | Key Characteristic |
|---|---|---|
| **SHARP_BLADE** | Quintic In-Out | 20° tilted hard-edge "knife" of light |
| **MOTION** | Cubic Bezier | 3-phase slide: In, Wait, Out |
| **SPIN_360** | Snap-to-Settle | Full Z-axis rotation with fast snap + elegant settle |
| **PULSE** | Ease-In-Out Cubic | Smooth breathing scale animation |
| **TYPEWRITER** | CSS Ease / Expo Out | Progressive character reveal with cursor |
| **TYPO_WAVE** | Phase-Shifted √Sine | Per-letter Y-axis bounce with weightless hang |
| **ETHEREAL** | Linear Sequential | Per-letter dither-fade dissolve sequence |
| **STATIC** | None | No animation |

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