#!/usr/bin/env python3
import cv2
import numpy as np
import sys
import time
import os
import argparse
import select

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

bayer_matrix = np.array([[0, 2], [3, 1]]) / 4.0

def get_key():
    if os.name == 'nt':
        import msvcrt
        if msvcrt.kbhit(): return msvcrt.getwch()
        return None
    else:
        if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
            return sys.stdin.read(1)
        return None

# --- MOTION MATH ---
def cubic_bezier(t, p1, p2):
    """Simple cubic bezier easing (assuming p0=0 and p3=1)."""
    return 3 * (1 - t)**2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3

def get_motion_x(t, w, speed):
    """Calculates X offset based on a 3-phase cycle: In, Wait, Out."""
    cycle_duration = 5.0 / speed
    t_cycle = (t % cycle_duration) / cycle_duration
    
    # Phase timings
    in_end = 0.2
    stay_end = 0.8
    
    if t_cycle < in_end: # Fly In
        progress = t_cycle / in_end
        eased = cubic_bezier(progress, 0.8, 0.0) # Steep snap in
        return -w + (eased * w)
    elif t_cycle < stay_end: # Sit in middle
        return 0
    else: # Fly Out
        progress = (t_cycle - stay_end) / (1.0 - stay_end)
        eased = cubic_bezier(progress, 1.0, 0.2) # Steep snap out
        return eased * w

# --- MASK GENERATION ---
def create_text_mask(text, target_w, target_h, font, scale, thickness, is_stroke, x_offset=0):
    w, h = target_w * 10, target_h * 10
    canvas = np.zeros((h, w), dtype=np.uint8)
    size, _ = cv2.getTextSize(text, font, scale, thickness)
    text_x = int((w - size[0]) // 2 + x_offset)
    text_y = (h + size[1]) // 2
    
    if is_stroke:
        outer = thickness + int(scale * 6) + 4
        cv2.putText(canvas, text, (text_x, text_y), font, scale, 255, outer, cv2.LINE_AA)
        cv2.putText(canvas, text, (text_x, text_y), font, scale, 0, thickness, cv2.LINE_AA)
    else:
        cv2.putText(canvas, text, (text_x, text_y), font, scale, 255, thickness, cv2.LINE_AA)
    return canvas / 255.0 

def generate_frame(text, target_w, target_h, font, scale, thickness, is_stroke, is_negative, is_anim, mode, speed):
    curr_time = time.time()
    w_px, h_px = target_w * 10, target_h * 10
    
    if mode == "MOTION" and is_anim:
        x_off = get_motion_x(curr_time, w_px, speed)
        mask = create_text_mask(text, target_w, target_h, font, scale, thickness, is_stroke, x_off)
        intensity = 1.0 - mask if is_negative else mask
    else:
        # Static or Sheen Mode
        mask = create_text_mask(text, target_w, target_h, font, scale, thickness, is_stroke)
        effective_mask = 1.0 - mask if is_negative else mask
        
        if mode == "SHEEN" and is_anim:
            cycle = (curr_time * speed) % 2.0 
            sheen_center = (cycle - 0.5) * w_px
            x_coords = np.arange(w_px)
            sheen_1d = np.exp(-0.5 * ((x_coords - sheen_center) / (w_px * 0.2)) ** 2)
            intensity = effective_mask * (0.4 + (np.tile(sheen_1d, (h_px, 1)) * 0.6))
        else: # STATIC
            intensity = effective_mask
            
    frame_8bit = (intensity * 255).astype(np.uint8)
    return cv2.cvtColor(frame_8bit, cv2.COLOR_GRAY2BGR)

def render_frame(frame, width, height, active_chars, brightness, contrast, glyph_name, num_colors, t_scale, t_thick, f_name, is_stroke, is_neg, is_anim, mode):
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
    
    hud = f"\n{RESET}--- LIVE CONTROLS ---\n"
    hud += f" [ / ] : Brightness ({brightness:+.2f})  |  - / = : Contrast ({contrast:.2f})\n"
    hud += f" u / j : Font Size ({t_scale:>4.1f})   |  i / k : Boldness  ({t_thick:>2})\n"
    hud += f"   f   : Font ({f_name.ljust(9)})    |    g    : Glyphs ({glyph_name.ljust(10)})\n"
    hud += f"   m   : Mode ({mode.ljust(10)})    |    a    : Anim ({'ON' if is_anim else 'OFF'})\n"
    hud += f"   o/n : Stroke/Negative        |    q    : Quit\n"
    
    sys.stdout.write("\033[H" + output + hud)
    sys.stdout.flush()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("-w", "--width", type=int, default=80)
    parser.add_argument("-H", "--height", type=int, default=40)
    parser.add_argument("-s", "--speed", type=float, default=1.0)
    args = parser.parse_args()

    mode_list = ["SHEEN", "MOTION", "STATIC"]
    mode_idx = 0
    is_anim, is_stroke, is_negative = True, False, False
    t_scale, t_thick = 10.0, 4.0 # Default starting values
    font_idx, glyph_idx = 0, 0
    target_glyph_amt, target_color_amt = 16, 10

    os.system('clear')
    sys.stdout.write("\033[?25l")
    
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())

    try:
        while True:
            start_time = time.time()
            frame = generate_frame(args.text, args.width, args.height, FONTS[font_idx][1], t_scale, int(t_thick), is_stroke, is_negative, is_anim, mode_list[mode_idx], args.speed)
            
            base_chars = CHARSETS[list(CHARSETS.keys())[glyph_idx]]
            active_chars = np.array(base_chars)[np.linspace(0, len(base_chars)-1, min(target_glyph_amt, len(base_chars))).astype(int)]

            render_frame(frame, args.width, args.height, active_chars, 0.0, 1.0, list(CHARSETS.keys())[glyph_idx], target_color_amt, t_scale, t_thick, FONTS[font_idx][0], is_stroke, is_negative, is_anim, mode_list[mode_idx])
            
            key = get_key()
            if key:
                k = key.lower()
                if k == 'q': break
                elif k == 'm': mode_idx = (mode_idx + 1) % len(mode_list)
                elif k == 'a': is_anim = not is_anim
                elif k == 'o': is_stroke = not is_stroke
                elif k == 'n': is_negative = not is_negative
                elif k == 'f': font_idx = (font_idx + 1) % len(FONTS)
                elif k == 'g': glyph_idx = (glyph_idx + 1) % len(CHARSETS)
                elif k == 'u': t_scale += 0.5
                elif k == 'j': t_scale = max(0.5, t_scale - 0.5)
                elif k == 'i': t_thick += 1
                elif k == 'k': t_thick = max(1, t_thick - 1)

            time.sleep(max(0, 0.033 - (time.time() - start_time)))
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\033[?25h")

if __name__ == "__main__":
    main()
