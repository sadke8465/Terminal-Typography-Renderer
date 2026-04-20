#!/usr/bin/env python3
import cv2
import numpy as np
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
    "cyber": list(" ▖▚▜█"),
    "math": list(" -+<>=%&8B@"),
    "slashes": list(" \\/|X"),
    "waves": list(" .~≈=")
}

FONTS = [
    ("Simplex", cv2.FONT_HERSHEY_SIMPLEX),
    ("Complex", cv2.FONT_HERSHEY_COMPLEX),
    ("Triplex", cv2.FONT_HERSHEY_TRIPLEX),
    ("Plain", cv2.FONT_HERSHEY_PLAIN),
    ("Script", cv2.FONT_HERSHEY_SCRIPT_COMPLEX)
]

PALETTE = [
    "\033[34m", "\033[35m", "\033[31m", "\033[32m", "\033[36m",
    "\033[33m", "\033[94m", "\033[95m", "\033[92m", "\033[97m"
]
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

# Maximum number of glyphs to sample from a charset for rendering
MAX_GLYPH_SAMPLES = 16

bayer_matrix = np.array([[0, 2], [3, 1]]) / 4.0

# --- INPUT HANDLING ---
def get_key():
    """Read a keypress, handling multi-byte escape sequences for arrow keys."""
    if os.name == 'nt':
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ('\x00', '\xe0'):
                ch2 = msvcrt.getwch()
                mapping = {'H': 'UP', 'P': 'DOWN', 'K': 'LEFT', 'M': 'RIGHT'}
                return mapping.get(ch2, None)
            return ch
        return None
    else:
        if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                if select.select([sys.stdin], [], [], 0.02) == ([sys.stdin], [], []):
                    ch2 = sys.stdin.read(1)
                    if ch2 == '[':
                        if select.select([sys.stdin], [], [], 0.02) == ([sys.stdin], [], []):
                            ch3 = sys.stdin.read(1)
                            mapping = {'A': 'UP', 'B': 'DOWN', 'C': 'RIGHT', 'D': 'LEFT'}
                            return mapping.get(ch3, None)
                return 'ESCAPE'
            elif ch == '\x7f' or ch == '\x08':
                return 'BACKSPACE'
            elif ch == '\n' or ch == '\r':
                return 'ENTER'
            return ch
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


def get_rotation_angle(t, speed):
    """Calculate rotation angle with ease-in-out-back for polished feel."""
    cycle_duration = 4.0 / speed
    t_cycle = (t % cycle_duration) / cycle_duration
    # Pendulum swing: ease from 0 to 1 to 0 over the cycle
    if t_cycle < 0.5:
        progress = t_cycle * 2.0
        eased = ease_in_out_back(progress)
    else:
        progress = (t_cycle - 0.5) * 2.0
        eased = 1.0 - ease_in_out_back(progress)
    # Map to ±30 degrees
    return (eased - 0.5) * 60.0


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


# --- MASK GENERATION ---
def create_text_mask(text, target_w, target_h, font, scale, thickness, is_stroke, x_offset=0, rotation=0.0):
    w, h = target_w * 10, target_h * 10
    canvas = np.zeros((h, w), dtype=np.uint8)

    if not text or not text.strip():
        return canvas.astype(np.float64)

    size, _ = cv2.getTextSize(text, font, scale, thickness)
    text_x = int((w - size[0]) // 2 + x_offset)
    text_y = (h + size[1]) // 2

    if is_stroke:
        outer = thickness + int(scale * 6) + 4
        cv2.putText(canvas, text, (text_x, text_y), font, scale, 255, outer, cv2.LINE_AA)
        cv2.putText(canvas, text, (text_x, text_y), font, scale, 0, thickness, cv2.LINE_AA)
    else:
        cv2.putText(canvas, text, (text_x, text_y), font, scale, 255, thickness, cv2.LINE_AA)

    # Apply rotation if needed
    if abs(rotation) > 0.01:
        center = (w // 2, h // 2)
        rot_matrix = cv2.getRotationMatrix2D(center, rotation, 1.0)
        canvas = cv2.warpAffine(canvas, rot_matrix, (w, h), flags=cv2.INTER_LINEAR)

    return canvas / 255.0


def generate_frame(text, target_w, target_h, font, scale, thickness, is_stroke, is_negative, is_anim, mode, speed):
    curr_time = time.time()
    w_px, h_px = target_w * 10, target_h * 10

    if mode == "MOTION" and is_anim:
        x_off = get_motion_x(curr_time, w_px, speed)
        mask = create_text_mask(text, target_w, target_h, font, scale, thickness, is_stroke, x_off)
        intensity = 1.0 - mask if is_negative else mask

    elif mode == "ROTATE" and is_anim:
        angle = get_rotation_angle(curr_time, speed)
        mask = create_text_mask(text, target_w, target_h, font, scale, thickness, is_stroke, rotation=angle)
        intensity = 1.0 - mask if is_negative else mask

    elif mode == "PULSE" and is_anim:
        pulse_scale = get_pulse_scale(curr_time, scale, speed)
        mask = create_text_mask(text, target_w, target_h, font, pulse_scale, thickness, is_stroke)
        intensity = 1.0 - mask if is_negative else mask

    elif mode == "TYPEWRITER" and is_anim:
        display_text = get_typewriter_text(text, curr_time, speed)
        mask = create_text_mask(display_text, target_w, target_h, font, scale, thickness, is_stroke)
        intensity = 1.0 - mask if is_negative else mask

    else:
        mask = create_text_mask(text, target_w, target_h, font, scale, thickness, is_stroke)
        effective_mask = 1.0 - mask if is_negative else mask

        if mode == "SHEEN" and is_anim:
            cycle = (curr_time * speed) % 2.0
            sheen_center = (cycle - 0.5) * w_px
            x_coords = np.arange(w_px)
            sheen_1d = np.exp(-0.5 * ((x_coords - sheen_center) / (w_px * 0.2)) ** 2)
            intensity = effective_mask * (0.4 + (np.tile(sheen_1d, (h_px, 1)) * 0.6))
        else:
            intensity = effective_mask

    frame_8bit = (intensity * 255).astype(np.uint8)
    return cv2.cvtColor(frame_8bit, cv2.COLOR_GRAY2BGR)


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


def render_frame_to_string(frame, width, height, active_chars, brightness, contrast, num_colors):
    """Convert frame to ASCII art string."""
    frame = cv2.resize(frame, (width, height))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray_norm = np.clip(((gray / 255.0) * contrast) + brightness, 0.0, 1.0)

    tiles_y, tiles_x = (height + 1) // 2, (width + 1) // 2
    dither_map = np.tile(bayer_matrix, (tiles_y, tiles_x))[:height, :width]
    dithered = np.clip(gray_norm + (dither_map - 0.5) * 0.5, 0, 0.999)

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
    mode_list = ["SHEEN", "MOTION", "ROTATE", "PULSE", "TYPEWRITER", "STATIC"]
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
            t_scale = next(p for p in params if p.name == "Font Size").value
            t_thick = int(next(p for p in params if p.name == "Boldness").value)
            speed = next(p for p in params if p.name == "Speed").value
            num_colors = int(next(p for p in params if p.name == "Colors").value)

            font_idx = font_names.index(font_val) if font_val in font_names else 0
            glyph_idx = glyph_names.index(glyph_val) if glyph_val in glyph_names else 0

            # Generate frame
            frame = generate_frame(
                current_text, args.width, args.height,
                FONTS[font_idx][1], t_scale, t_thick,
                is_stroke, is_negative, is_anim, mode_val, speed
            )

            # Build active charset
            base_chars = CHARSETS[glyph_names[glyph_idx]]
            active_chars = np.array(base_chars)[np.linspace(0, len(base_chars) - 1, min(MAX_GLYPH_SAMPLES, len(base_chars))).astype(int)]

            # Render ASCII art
            ascii_output = render_frame_to_string(frame, args.width, args.height, active_chars, brightness, contrast, num_colors)

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
                    elif key == 'UP':
                        selected_idx = (selected_idx - 1) % len(params)
                    elif key == 'DOWN':
                        selected_idx = (selected_idx + 1) % len(params)
                    elif key == 'RIGHT':
                        params[selected_idx].increment()
                    elif key == 'LEFT':
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
