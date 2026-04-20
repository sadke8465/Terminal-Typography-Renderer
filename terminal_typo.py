#!/usr/bin/env python3
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import sys
import time
import os
import argparse
import select
import math

if os.name != 'nt':
    import tty
    import termios

# --- PRESET GLYPH SETS ---
CHARSETS = {
    "standard": list(" .:-=+*#%@"),
    "blocks": list(" ░▒▓█"),
    "minimal": list(" -+#"),
    "binary": list(" 01"),
    "hex": list(" 0123456789ABCDEF"),
    "braille": list(" ⡀⡄⡆⡇⣇⣧⣷⣿"),
    "math": list(" -+<>=%&8B@"),
    "slashes": list(" \\/|X"),
    "waves": list(" .~≈=")
}

# --- TRUETYPE FONT CONFIGURATION ---
# List of (display_name, font_path) tuples. Paths are searched in order;
# if none exist on the system, Pillow's built-in default font is used.
FONT_SEARCH_PATHS = [
    ("Sans Bold", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/lato/Lato-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]),
    ("Sans Regular", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/lato/Lato-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]),
    ("Serif Bold", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
    ]),
    ("Mono Bold", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "C:/Windows/Fonts/courbd.ttf",
    ]),
    ("Light", [
        "/usr/share/fonts/truetype/lato/Lato-Light.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf",
        "C:/Windows/Fonts/segoeuil.ttf",
    ]),
]


def _resolve_font_path(search_paths):
    """Find the first existing font file from a list of candidate paths."""
    for path in search_paths:
        if os.path.isfile(path):
            return path
    return None


def _build_font_list():
    """Build the FONTS list: [(display_name, resolved_path_or_None), ...]"""
    fonts = []
    for name, paths in FONT_SEARCH_PATHS:
        resolved = _resolve_font_path(paths)
        fonts.append((name, resolved))
    return fonts


FONTS = _build_font_list()

PALETTE = [
    "\033[34m", "\033[35m", "\033[31m", "\033[32m", "\033[36m",
    "\033[33m", "\033[94m", "\033[95m", "\033[92m", "\033[97m"
]
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Maximum number of glyphs to sample from a charset for rendering
MAX_GLYPH_SAMPLES = 16

# Small epsilon to prevent division by zero in animation phase calculations
EPSILON = 0.001

bayer_matrix = np.array([[0, 2], [3, 1]]) / 4.0

# --- INPUT HANDLING ---
def get_key():
    """Read a key press, properly handling multi-byte ANSI escape sequences."""
    if os.name == 'nt':
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b'\x00', b'\xe0'):
                ch2 = msvcrt.getch()
                mapping = {b'H': 'UP', b'P': 'DOWN', b'M': 'RIGHT', b'K': 'LEFT'}
                return mapping.get(ch2, None)
            elif ch == b'\r':
                return 'ENTER'
            elif ch == b'\x08':
                return 'BACKSPACE'
            elif ch == b'\x1b':
                return 'ESCAPE'
            return ch.decode('utf-8', errors='ignore')
        return None
    else:
        # Use os.read() on the raw file descriptor to bypass Python's
        # internal buffering which can swallow multi-byte escape sequences
        # (e.g. arrow keys send \x1b[A but BufferedReader consumes all
        # bytes at once, making subsequent select() calls miss them).
        fd = sys.stdin.fileno()
        if select.select([fd], [], [], 0.02)[0]:
            ch = os.read(fd, 1)
            if ch == b'\x1b':
                # Drain the rest of the escape sequence with a short wait
                # to ensure all bytes of the sequence are available.
                if select.select([fd], [], [], 0.05)[0]:
                    seq = b''
                    while select.select([fd], [], [], 0.01)[0]:
                        seq += os.read(fd, 1)
                        # Safety limit: longest expected sequence is 4 bytes
                        # (e.g. "[5~" for PGUP), 8 covers any extended sequences.
                        if len(seq) >= 8:
                            break
                    mapping = {
                        b'[A': 'UP', b'[B': 'DOWN', b'[C': 'RIGHT', b'[D': 'LEFT',
                        b'[H': 'HOME', b'[F': 'END',
                        b'[5~': 'PGUP', b'[6~': 'PGDN',
                    }
                    return mapping.get(seq, 'ESCAPE')
                return 'ESCAPE'
            elif ch == b'\x7f':
                return 'BACKSPACE'
            elif ch == b'\n' or ch == b'\r':
                return 'ENTER'
            return ch.decode('utf-8', errors='ignore')
        return None

# --- EASING CURVE LIBRARY ---
def ease_linear(t):
    """Linear easing — no acceleration."""
    return t


def ease_in_out_cubic(t):
    """Smooth ease-in-out cubic — ideal for breathing/pulse animations."""
    if t < 0.5:
        return 4.0 * t * t * t
    else:
        p = 2.0 * t - 2.0
        return 0.5 * p * p * p + 1.0


def ease_in_out_back(t):
    """Ease-in-out with overshoot — polished kinetic feel for rotation."""
    c1 = 1.70158
    c2 = c1 * 1.525
    if t < 0.5:
        return (pow(2.0 * t, 2) * ((c2 + 1.0) * 2.0 * t - c2)) / 2.0
    else:
        return (pow(2.0 * t - 2.0, 2) * ((c2 + 1.0) * (t * 2.0 - 2.0) + c2) + 2.0) / 2.0


def ease_out_expo(t):
    """Exponential ease-out — fast start, smooth deceleration for typewriter."""
    if t >= 1.0:
        return 1.0
    return 1.0 - pow(2.0, -10.0 * t)


def ease_css(t):
    """CSS ease equivalent — cubic-bezier(0.25, 0.1, 0.25, 1.0) approximation."""
    # Using a polynomial approximation of the CSS ease curve
    return t * t * (3.0 - 2.0 * t) * (1.0 + 0.5 * t * (1.0 - t))


def ease_in_out_quintic(t):
    """Quintic ease-in-out — strong acceleration/deceleration for Sharp Blade."""
    if t < 0.5:
        return 16.0 * t * t * t * t * t
    else:
        p = 2.0 * t - 2.0
        return 0.5 * p * p * p * p * p + 1.0


def ease_snap_to_settle(t):
    """Snap-to-settle: fast for first 75% (270°), slow elegant settle for last 25% (90°)."""
    if t < 0.75:
        # Fast snap phase — use quintic ease-out for the first 270 degrees
        local_t = t / 0.75
        return (1.0 - pow(1.0 - local_t, 5)) * 0.75
    else:
        # Slow settle phase — gentle ease-out for the final 90 degrees
        local_t = (t - 0.75) / 0.25
        eased = local_t * local_t * (3.0 - 2.0 * local_t)
        return 0.75 + eased * 0.25


def ease_sqrt_sine(t):
    """Square-root sine — longer hang time at the top of the bounce (weightless feel)."""
    raw = math.sin(2.0 * math.pi * t)
    if raw >= 0:
        return math.sqrt(raw)
    else:
        return -math.sqrt(-raw)


def cubic_bezier(t, p1, p2):
    """Simple cubic bezier easing (assuming p0=0 and p3=1)."""
    return 3 * (1 - t)**2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3


# --- MOTION MATH ---
def get_motion_x(t, w, speed):
    """Calculates X offset based on a 3-phase cycle: In, Wait, Out."""
    cycle_duration = 5.0 / speed
    t_cycle = (t % cycle_duration) / cycle_duration

    in_end = 0.2
    stay_end = 0.8

    if t_cycle < in_end:
        progress = t_cycle / in_end
        eased = cubic_bezier(progress, 0.8, 0.0)
        return -w + (eased * w)
    elif t_cycle < stay_end:
        return 0
    else:
        progress = (t_cycle - stay_end) / (1.0 - stay_end)
        eased = cubic_bezier(progress, 1.0, 0.2)
        return eased * w


def get_pulse_scale(t, base_scale, speed):
    """Calculate pulsing scale factor with smooth breathing easing."""
    cycle_duration = 3.0 / speed
    t_cycle = (t % cycle_duration) / cycle_duration
    # Sine wave normalized to [0, 1], then apply ease-in-out-cubic
    sine_val = (math.sin(t_cycle * 2.0 * math.pi - math.pi / 2.0) + 1.0) / 2.0
    eased = ease_in_out_cubic(sine_val)
    # Scale between 70% and 130%
    scale_factor = 0.7 + eased * 0.6
    return base_scale * scale_factor


def get_typewriter_text(text, t, speed):
    """Progressive character reveal with cursor, eased timing."""
    char_count = len(text)
    if char_count == 0:
        return "▌"

    # Full cycle: type in + hold + delete out
    type_duration = (char_count * 0.12) / speed
    hold_duration = 1.5 / speed
    delete_duration = (char_count * 0.06) / speed
    cycle_duration = type_duration + hold_duration + delete_duration

    t_cycle = t % cycle_duration

    if t_cycle < type_duration:
        # Typing phase
        progress = t_cycle / type_duration
        eased = ease_css(progress)
        chars_shown = int(eased * char_count)
        chars_shown = max(0, min(chars_shown, char_count))
        # Blinking cursor
        cursor = "▌" if (t * 3.0) % 1.0 < 0.6 else " "
        return text[:chars_shown] + cursor
    elif t_cycle < type_duration + hold_duration:
        # Hold phase — full text with blinking cursor
        cursor = "▌" if (t * 2.0) % 1.0 < 0.5 else " "
        return text + cursor
    else:
        # Delete phase
        del_progress = (t_cycle - type_duration - hold_duration) / delete_duration
        eased = ease_out_expo(del_progress)
        chars_shown = char_count - int(eased * char_count)
        chars_shown = max(0, min(chars_shown, char_count))
        cursor = "▌" if (t * 4.0) % 1.0 < 0.5 else " "
        return text[:chars_shown] + cursor


# --- MASK GENERATION (Pillow-based Point-to-Grid Engine) ---
# Vertical compensation factor: terminal character cells are typically ~2x taller
# than they are wide (e.g. a cell might be 8px wide × 16px tall). This factor
# compresses the rendering canvas vertically before stretching it back to the full
# terminal height, producing correctly proportioned text. Adjust if your terminal
# uses a non-standard cell aspect ratio.
ASPECT_RATIO_FACTOR = 0.5


def _load_pil_font(font_path, size):
    """Load a TrueType/OpenType font, falling back to default if unavailable."""
    if font_path and os.path.isfile(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except (IOError, OSError):
            pass
    # Fallback to Pillow's built-in default font
    try:
        return ImageFont.load_default(size)
    except TypeError:
        # Older Pillow versions don't accept size in load_default
        return ImageFont.load_default()


def create_text_mask(text, target_w, target_h, font_path, font_size, thickness, is_stroke, x_offset=0, rotation=0.0, aspect_ratio=None):
    """
    Render text directly at terminal resolution (1:1 pixel-to-character mapping).
    Applies aspect ratio correction so text isn't vertically squashed.
    """
    # The canvas is exactly the terminal grid size
    w, h = target_w, target_h

    if not text or not text.strip():
        return np.zeros((h, w), dtype=np.float64)

    # Apply aspect ratio correction: the effective pixel height for rendering
    # is reduced because terminal cells are taller than wide.
    ar_factor = aspect_ratio if aspect_ratio is not None else ASPECT_RATIO_FACTOR
    effective_h = int(h * ar_factor)
    if effective_h < 1:
        effective_h = 1

    # Create a Pillow image at (w, effective_h) for rendering
    img = Image.new('L', (w, effective_h), 0)
    draw = ImageDraw.Draw(img)

    # Load the font at the requested size
    pil_font = _load_pil_font(font_path, int(font_size))

    # Measure text to center it
    bbox = draw.textbbox((0, 0), text, font=pil_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Center the text, applying x_offset
    text_x = int((w - text_w) / 2 + x_offset - bbox[0])
    text_y = int((effective_h - text_h) / 2 - bbox[1])

    if is_stroke:
        # Draw stroke effect: thick outline, then erase interior.
        # Factor 0.4 maps the TUI "Boldness" parameter to a visually balanced
        # PIL stroke_width (keeps strokes visible but not overly thick).
        stroke_width = max(1, int(thickness * 0.4))
        draw.text((text_x, text_y), text, font=pil_font, fill=255,
                  stroke_width=stroke_width, stroke_fill=255)
        # Erase interior by drawing text again in black
        draw.text((text_x, text_y), text, font=pil_font, fill=0)
    else:
        draw.text((text_x, text_y), text, font=pil_font, fill=255)

    # Apply rotation if needed
    if abs(rotation) > 0.01:
        img = img.rotate(rotation, resample=Image.BILINEAR, expand=False,
                         center=(w // 2, effective_h // 2))

    # Stretch vertically back to full terminal height (undo aspect ratio compression)
    img = img.resize((w, h), resample=Image.BILINEAR)

    # Convert to numpy float array normalized to [0, 1]
    return np.array(img, dtype=np.float64) / 255.0


def create_per_letter_masks(text, target_w, target_h, font_path, font_size, thickness, is_stroke,
                            y_offsets=None, alphas=None, aspect_ratio=None):
    """
    Per-letter glyph segmentation engine.

    Renders each character individually onto its own sub-buffer, then composites
    into the main frame. Each glyph can have independent Y-offset and opacity.

    Parameters:
        y_offsets: array of vertical offsets per character (in effective pixels)
        alphas: array of opacity values [0.0, 1.0] per character
        aspect_ratio: vertical aspect ratio factor (overrides global ASPECT_RATIO_FACTOR)
    """
    w, h = target_w, target_h

    if not text or not text.strip():
        return np.zeros((h, w), dtype=np.float64)

    n = len(text)
    if y_offsets is None:
        y_offsets = [0] * n
    if alphas is None:
        alphas = [1.0] * n

    ar_factor = aspect_ratio if aspect_ratio is not None else ASPECT_RATIO_FACTOR
    effective_h = int(h * ar_factor)
    if effective_h < 1:
        effective_h = 1

    pil_font = _load_pil_font(font_path, int(font_size))

    # Measure each character's width for positioning
    char_widths = []
    for ch in text:
        tmp_img = Image.new('L', (1, 1), 0)
        tmp_draw = ImageDraw.Draw(tmp_img)
        bbox = tmp_draw.textbbox((0, 0), ch, font=pil_font)
        char_widths.append(bbox[2] - bbox[0])

    total_text_width = sum(char_widths)

    # Calculate starting x to center the text
    start_x = (w - total_text_width) // 2

    # Composite image
    composite = Image.new('L', (w, effective_h), 0)

    # Measure text height for vertical centering
    tmp_img = Image.new('L', (1, 1), 0)
    tmp_draw = ImageDraw.Draw(tmp_img)
    full_bbox = tmp_draw.textbbox((0, 0), text, font=pil_font)
    text_h = full_bbox[3] - full_bbox[1]
    base_y = int((effective_h - text_h) / 2 - full_bbox[1])

    current_x = start_x
    for i, ch in enumerate(text):
        if ch == ' ':
            current_x += char_widths[i]
            continue

        # Create sub-buffer for this character
        char_img = Image.new('L', (w, effective_h), 0)
        char_draw = ImageDraw.Draw(char_img)

        # Apply individual Y-offset
        char_y = base_y + int(y_offsets[i])

        # Get individual character bbox for precise positioning
        ch_bbox = char_draw.textbbox((0, 0), ch, font=pil_font)

        draw_x = current_x - ch_bbox[0]
        draw_y = char_y

        if is_stroke:
            stroke_width = max(1, int(thickness * 0.4))
            char_draw.text((draw_x, draw_y), ch, font=pil_font, fill=255,
                           stroke_width=stroke_width, stroke_fill=255)
            char_draw.text((draw_x, draw_y), ch, font=pil_font, fill=0)
        else:
            char_draw.text((draw_x, draw_y), ch, font=pil_font, fill=255)

        # Apply alpha for this character
        alpha = max(0.0, min(1.0, alphas[i]))
        if alpha < 1.0:
            char_arr = np.array(char_img, dtype=np.float64) * alpha
            char_img = Image.fromarray(char_arr.astype(np.uint8))

        # Composite onto main buffer
        composite = Image.composite(char_img, composite, char_img)

        current_x += char_widths[i]

    # Stretch vertically back to full terminal height
    composite = composite.resize((w, h), resample=Image.BILINEAR)

    return np.array(composite, dtype=np.float64) / 255.0


# --- NEW ANIMATION PRESETS ---

def get_sharp_blade(t, w, h, speed):
    """
    Sharp Blade: A high-contrast linear 'knife' of light tilted at 20 degrees.
    Uses a hard-edge step function with Ease-In-Out Quintic motion.
    Returns an intensity modifier array of shape (h, w).
    """
    cycle_duration = 1.0 / speed
    t_norm = (t % cycle_duration) / cycle_duration

    # Rest phase at t=0.5 (text fully legible)
    if 0.45 <= t_norm <= 0.55:
        return np.ones((h, w), dtype=np.float64)

    # Map t_norm to sweep progress with quintic easing
    if t_norm < 0.45:
        progress = ease_in_out_quintic(t_norm / 0.45)
    else:
        progress = ease_in_out_quintic((t_norm - 0.55) / 0.45)

    # Blade position sweeps across the diagonal
    blade_center = (progress - 0.5) * 2.0 * (w + h)

    # 20-degree tilt: create coordinate grid
    x_coords = np.arange(w, dtype=np.float64)
    y_coords = np.arange(h, dtype=np.float64)
    xx, yy = np.meshgrid(x_coords, y_coords)

    # Project onto 20-degree tilted axis
    angle_rad = math.radians(20.0)
    projected = xx * math.cos(angle_rad) + yy * math.sin(angle_rad)

    # Hard-edge step function (blade width ~8% of diagonal)
    blade_width = (w + h) * 0.04
    distance = np.abs(projected - blade_center)
    blade = np.where(distance < blade_width, 1.0, 0.0)

    # Final intensity: base 0.4 + blade highlight 0.6
    return 0.4 + blade * 0.6


def get_spin_360_angle(t, speed):
    """
    360 Spin: Full Z-axis rotation with snap-to-settle motion.
    Fast 'snap' for first 270°, slow elegant 'settle' for final 90°.
    Normalized 1.0s cycle with rest phase.
    """
    cycle_duration = 1.0 / speed
    t_norm = (t % cycle_duration) / cycle_duration

    # Rest phase: text is static and legible
    if 0.45 <= t_norm <= 0.55:
        return 0.0

    # Active rotation phases
    if t_norm < 0.45:
        progress = t_norm / 0.45
        eased = ease_snap_to_settle(progress)
        return eased * 360.0
    else:
        progress = (t_norm - 0.55) / 0.45
        eased = ease_snap_to_settle(progress)
        return eased * 360.0


def get_typo_wave_offsets(text, t, speed, amplitude=3.0):
    """
    Typographic Wave: Per-letter vertical bounce with phase-shifted sine.
    Uses square-root sine for 'weightless' hang time at the top.
    Returns array of Y-offsets per character.
    """
    n = len(text)
    if n == 0:
        return []

    cycle_duration = 1.0 / speed
    t_norm = (t % cycle_duration) / cycle_duration

    offsets = []
    for i in range(n):
        # Phase offset per letter
        phi_i = i / n
        # Square-root sine for weightless feel at top
        raw_phase = t_norm + phi_i
        y_offset = amplitude * ease_sqrt_sine(raw_phase)
        offsets.append(y_offset)

    return offsets


def get_ethereal_alphas(text, t, speed):
    """
    Ethereal Reveal: Per-letter dissolve with sequential delay.
    Each letter fades in sequentially, holds, then dissolves out in the same wave.
    Returns array of alpha values [0.0, 1.0] per character.
    """
    n = len(text)
    if n == 0:
        return []

    cycle_duration = 1.0 / speed
    t_norm = (t % cycle_duration) / cycle_duration

    # Phase breakdown: fade-in (0.0-0.35), hold (0.35-0.65), fade-out (0.65-1.0)
    alphas = []
    delay_per_char = 0.5 / max(n, 1)  # stagger across half the phase

    for i in range(n):
        char_delay = i * delay_per_char

        if t_norm < 0.35:
            # Fade-in phase
            local_t = t_norm / 0.35
            char_progress = max(0.0, min(1.0, (local_t - char_delay) / (1.0 - char_delay + EPSILON)))
            alpha = char_progress
        elif t_norm < 0.65:
            # Hold phase — fully visible
            alpha = 1.0
        else:
            # Fade-out phase
            local_t = (t_norm - 0.65) / 0.35
            char_progress = max(0.0, min(1.0, (local_t - char_delay) / (1.0 - char_delay + EPSILON)))
            alpha = 1.0 - char_progress

        alphas.append(max(0.0, min(1.0, alpha)))

    return alphas


def generate_frame(text, target_w, target_h, font_path, font_size, thickness, is_stroke, is_negative, is_anim, mode, speed, aspect_ratio=None):
    """Generate a single frame mask based on the current animation mode."""
    curr_time = time.time()
    w, h = target_w, target_h

    if mode == "MOTION" and is_anim:
        x_off = get_motion_x(curr_time, w, speed)
        mask = create_text_mask(text, target_w, target_h, font_path, font_size, thickness, is_stroke, x_off, aspect_ratio=aspect_ratio)
        intensity = 1.0 - mask if is_negative else mask

    elif mode == "SPIN_360" and is_anim:
        angle = get_spin_360_angle(curr_time, speed)
        mask = create_text_mask(text, target_w, target_h, font_path, font_size, thickness, is_stroke, rotation=angle, aspect_ratio=aspect_ratio)
        intensity = 1.0 - mask if is_negative else mask

    elif mode == "PULSE" and is_anim:
        pulse_scale = get_pulse_scale(curr_time, font_size, speed)
        mask = create_text_mask(text, target_w, target_h, font_path, pulse_scale, thickness, is_stroke, aspect_ratio=aspect_ratio)
        intensity = 1.0 - mask if is_negative else mask

    elif mode == "TYPEWRITER" and is_anim:
        display_text = get_typewriter_text(text, curr_time, speed)
        mask = create_text_mask(display_text, target_w, target_h, font_path, font_size, thickness, is_stroke, aspect_ratio=aspect_ratio)
        intensity = 1.0 - mask if is_negative else mask

    elif mode == "TYPO_WAVE" and is_anim:
        y_offsets = get_typo_wave_offsets(text, curr_time, speed)
        mask = create_per_letter_masks(text, target_w, target_h, font_path, font_size, thickness, is_stroke,
                                       y_offsets=y_offsets, aspect_ratio=aspect_ratio)
        intensity = 1.0 - mask if is_negative else mask

    elif mode == "ETHEREAL" and is_anim:
        alphas = get_ethereal_alphas(text, curr_time, speed)
        mask = create_per_letter_masks(text, target_w, target_h, font_path, font_size, thickness, is_stroke,
                                       alphas=alphas, aspect_ratio=aspect_ratio)
        intensity = 1.0 - mask if is_negative else mask

    else:
        mask = create_text_mask(text, target_w, target_h, font_path, font_size, thickness, is_stroke, aspect_ratio=aspect_ratio)
        effective_mask = 1.0 - mask if is_negative else mask

        if mode == "SHARP_BLADE" and is_anim:
            blade_modifier = get_sharp_blade(curr_time, w, h, speed)
            intensity = effective_mask * blade_modifier
        else:
            intensity = effective_mask

    return intensity


# --- TUI PARAMETER SYSTEM ---
class Parameter:
    """A single TUI parameter with either selector or gauge behavior."""

    def __init__(self, name, param_type, value=None, options=None, min_val=None, max_val=None, step=None, fmt=None):
        self.name = name
        self.param_type = param_type  # 'selector' or 'gauge'
        self.value = value
        self.options = options or []
        self.min_val = min_val
        self.max_val = max_val
        self.step = step or 1
        self.fmt = fmt or "{}"

    def increment(self):
        if self.param_type == 'selector':
            idx = self.options.index(self.value) if self.value in self.options else 0
            self.value = self.options[(idx + 1) % len(self.options)]
        elif self.param_type == 'gauge':
            self.value = min(self.max_val, self.value + self.step)

    def decrement(self):
        if self.param_type == 'selector':
            idx = self.options.index(self.value) if self.value in self.options else 0
            self.value = self.options[(idx - 1) % len(self.options)]
        elif self.param_type == 'gauge':
            self.value = max(self.min_val, self.value - self.step)

    def render(self, selected=False, width=38):
        """Render this parameter as a TUI row."""
        cursor = " ▸" if selected else "  "
        name_col = f"{self.name:<12}"

        if self.param_type == 'selector':
            val_str = str(self.value)
            content = f"◀ {val_str:^10} ▶"
        else:
            # Gauge rendering
            gauge_width = 10
            if self.max_val == self.min_val:
                normalized = 1.0 if self.value >= self.min_val else 0.0
            else:
                normalized = (self.value - self.min_val) / (self.max_val - self.min_val)
            filled = int(normalized * gauge_width)
            gauge = "█" * filled + "░" * (gauge_width - filled)
            val_display = self.fmt.format(self.value)
            content = f"[{gauge}] {val_display:>6}"

        line = f"{cursor} {name_col}{content}"
        # Pad to width
        line = line[:width].ljust(width)
        return line


def build_parameters(mode_list, font_names, glyph_names):
    """Build the list of TUI parameters."""
    params = [
        Parameter("Mode", "selector", value=mode_list[0], options=mode_list),
        Parameter("Font", "selector", value=font_names[0], options=font_names),
        Parameter("Glyphs", "selector", value=glyph_names[0], options=glyph_names),
        Parameter("Animation", "selector", value="ON", options=["ON", "OFF"]),
        Parameter("Stroke", "selector", value="OFF", options=["ON", "OFF"]),
        Parameter("Negative", "selector", value="OFF", options=["ON", "OFF"]),
        Parameter("Brightness", "gauge", value=0.0, min_val=-1.0, max_val=1.0, step=0.05, fmt="{:+.2f}"),
        Parameter("Contrast", "gauge", value=1.0, min_val=0.1, max_val=3.0, step=0.1, fmt="{:.2f}"),
        Parameter("Font Size", "gauge", value=10.0, min_val=0.5, max_val=30.0, step=0.5, fmt="{:.1f}"),
        Parameter("Boldness", "gauge", value=4.0, min_val=1.0, max_val=20.0, step=1.0, fmt="{:.0f}"),
        Parameter("Speed", "gauge", value=1.0, min_val=0.1, max_val=5.0, step=0.1, fmt="{:.1f}"),
        Parameter("Colors", "gauge", value=10.0, min_val=1.0, max_val=10.0, step=1.0, fmt="{:.0f}"),
        Parameter("Resolution", "gauge", value=1.0, min_val=0.25, max_val=2.0, step=0.1, fmt="{:.2f}x"),
        Parameter("V. Aspect", "gauge", value=0.5, min_val=0.3, max_val=1.0, step=0.05, fmt="{:.2f}"),
    ]
    return params


def render_tui_panel(params, selected_idx, current_text, text_editing, panel_width=42):
    """Render the TUI parameter panel with box-drawing characters."""
    lines = []
    top_border = "┌" + "─" * panel_width + "┐"
    mid_border = "├" + "─" * panel_width + "┤"
    bot_border = "└" + "─" * panel_width + "┘"

    lines.append(f"{RESET}{top_border}")

    # Text field — compute visible length without ANSI codes for correct padding
    cursor_char = "█" if text_editing else ""
    max_text_len = panel_width - 9  # "  TEXT: " is 8 chars + cursor
    if len(current_text) > max_text_len:
        display_text = current_text[:max_text_len - 3] + "..."
    else:
        display_text = current_text
    raw_content = f"  TEXT: {display_text}{cursor_char}"
    padding = max(0, panel_width - len(raw_content))
    if text_editing:
        lines.append(f"│{BOLD}{raw_content}{RESET}{' ' * padding}│")
    else:
        lines.append(f"│{raw_content}{' ' * padding}│")

    lines.append(f"{mid_border}")

    # Parameters
    for i, param in enumerate(params):
        is_selected = (i == selected_idx)
        row = param.render(selected=is_selected, width=panel_width)
        if is_selected:
            lines.append(f"│{BOLD}{row}{RESET}│")
        else:
            lines.append(f"│{row}│")

    lines.append(f"{bot_border}")

    # Help line
    lines.append(f"{DIM}  ↑↓ Navigate  ←→ Adjust  Enter: Edit text  Esc: Stop  q: Quit{RESET}")

    return "\n".join(lines)


def render_frame_to_string(intensity, width, height, active_chars, brightness, contrast, num_colors, is_anim=True):
    """Convert intensity mask directly to ASCII art string (no resize needed).
    Sub-pixel dither is refreshed every frame for subtle living texture when animated."""
    # intensity is already at (height, width) — direct 1:1 mapping
    gray_norm = np.clip((intensity * contrast) + brightness, 0.0, 1.0)

    tiles_y, tiles_x = (height + 1) // 2, (width + 1) // 2
    dither_map = np.tile(bayer_matrix, (tiles_y, tiles_x))[:height, :width]
    # Sub-pixel dither refresh: only add per-frame micro-noise when animating
    if is_anim:
        frame_noise = np.random.uniform(-0.02, 0.02, (height, width))
    else:
        frame_noise = 0.0
    dithered = np.clip(gray_norm + (dither_map - 0.5) * 0.5 + frame_noise, 0, 0.999)

    ascii_indices = (dithered * len(active_chars)).astype(int)
    color_indices = (dithered * num_colors).astype(int)

    output = ""
    for y in range(height):
        row = ""
        for x in range(width):
            row += f"{PALETTE[color_indices[y, x]]}{active_chars[ascii_indices[y, x]]}"
        output += row + f"{RESET}\n"

    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="?", default="Hello", help="Initial display text (editable live via TUI)")
    parser.add_argument("-w", "--width", type=int, default=80)
    parser.add_argument("-H", "--height", type=int, default=30)
    parser.add_argument("-s", "--speed", type=float, default=1.0)
    args = parser.parse_args()

    # Mode list with new presets
    mode_list = ["SHARP_BLADE", "MOTION", "SPIN_360", "PULSE", "TYPEWRITER", "TYPO_WAVE", "ETHEREAL", "STATIC"]
    font_names = [f[0] for f in FONTS]
    glyph_names = list(CHARSETS.keys())

    # Build TUI parameters
    params = build_parameters(mode_list, font_names, glyph_names)

    # Mutable state
    current_text = args.text
    text_editing = False
    selected_idx = 0

    # Set initial speed from args
    speed_param = next(p for p in params if p.name == "Speed")
    speed_param.value = args.speed

    os.system('clear')
    sys.stdout.write("\033[?25l")

    if os.name != 'nt':
        old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

    try:
        while True:
            start_time = time.time()

            # Read current param values
            mode_val = next(p for p in params if p.name == "Mode").value
            font_val = next(p for p in params if p.name == "Font").value
            glyph_val = next(p for p in params if p.name == "Glyphs").value
            is_anim = next(p for p in params if p.name == "Animation").value == "ON"
            is_stroke = next(p for p in params if p.name == "Stroke").value == "ON"
            is_negative = next(p for p in params if p.name == "Negative").value == "ON"
            brightness = next(p for p in params if p.name == "Brightness").value
            contrast = next(p for p in params if p.name == "Contrast").value
            t_size = next(p for p in params if p.name == "Font Size").value
            t_thick = int(next(p for p in params if p.name == "Boldness").value)
            speed = next(p for p in params if p.name == "Speed").value
            num_colors = int(next(p for p in params if p.name == "Colors").value)
            resolution = next(p for p in params if p.name == "Resolution").value
            aspect_ratio = next(p for p in params if p.name == "V. Aspect").value

            font_idx = font_names.index(font_val) if font_val in font_names else 0
            glyph_idx = glyph_names.index(glyph_val) if glyph_val in glyph_names else 0

            # Get the resolved font path for the selected font
            font_path = FONTS[font_idx][1]

            # Compute internal rendering resolution
            render_w = max(1, int(args.width * resolution))
            render_h = max(1, int(args.height * resolution))

            # Generate frame (returns intensity mask at internal resolution)
            intensity = generate_frame(
                current_text, render_w, render_h,
                font_path, t_size, t_thick,
                is_stroke, is_negative, is_anim, mode_val, speed,
                aspect_ratio=aspect_ratio
            )

            # Resize intensity back to terminal dimensions if resolution != 1.0
            if render_w != args.width or render_h != args.height:
                from PIL import Image as _PILImage
                intensity_img = _PILImage.fromarray((intensity * 255).astype(np.uint8))
                intensity_img = intensity_img.resize((args.width, args.height), resample=_PILImage.BILINEAR)
                intensity = np.array(intensity_img, dtype=np.float64) / 255.0

            # Build active charset
            base_chars = CHARSETS[glyph_names[glyph_idx]]
            active_chars = np.array(base_chars)[np.linspace(0, len(base_chars) - 1, min(MAX_GLYPH_SAMPLES, len(base_chars))).astype(int)]

            # Render ASCII art
            ascii_output = render_frame_to_string(intensity, args.width, args.height, active_chars, brightness, contrast, num_colors, is_anim=is_anim)

            # Render TUI panel
            tui_panel = render_tui_panel(params, selected_idx, current_text, text_editing)

            # Combine and display
            sys.stdout.write("\033[H" + ascii_output + "\n" + tui_panel)
            sys.stdout.flush()

            # Handle input
            key = get_key()
            if key:
                if text_editing:
                    # Text editing mode
                    if key == 'ESCAPE' or key == 'ENTER':
                        text_editing = False
                    elif key == 'BACKSPACE':
                        current_text = current_text[:-1]
                    elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                        current_text += key
                else:
                    # Navigation mode
                    if key == 'q':
                        break
                    elif key == 'ESCAPE':
                        break
                    elif key == 'UP' or key == 'w':
                        selected_idx = (selected_idx - 1) % len(params)
                    elif key == 'DOWN' or key == 's':
                        selected_idx = (selected_idx + 1) % len(params)
                    elif key == 'RIGHT' or key == 'd':
                        params[selected_idx].increment()
                    elif key == 'LEFT' or key == 'a':
                        params[selected_idx].decrement()
                    elif key == 'ENTER' or key == 't':
                        text_editing = True

            time.sleep(max(0, 0.033 - (time.time() - start_time)))
    finally:
        if os.name != 'nt':
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
