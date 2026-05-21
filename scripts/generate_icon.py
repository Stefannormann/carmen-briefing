"""
Generate a simple 512x512 PNG app icon for Carmen Briefing.
Run once: python scripts/generate_icon.py
Requires: Pillow
"""

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Installing Pillow…")
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont

SIZE = 512
BG = (26, 26, 46)       # #1a1a2e
ACCENT = (233, 69, 96)  # #e94560
GOLD = (245, 166, 35)   # #f5a623
TEXT = (232, 232, 240)  # #e8e8f0

img = Image.new("RGB", (SIZE, SIZE), BG)
draw = ImageDraw.Draw(img)

# Background circle
draw.ellipse([20, 20, SIZE-20, SIZE-20], fill=ACCENT)

# Inner dark circle
draw.ellipse([60, 60, SIZE-60, SIZE-60], fill=BG)

# Microphone body
mic_x, mic_y = SIZE//2, SIZE//2 - 30
mic_w, mic_h = 80, 110
draw.rounded_rectangle(
    [mic_x - mic_w//2, mic_y - mic_h//2, mic_x + mic_w//2, mic_y + mic_h//2],
    radius=40, fill=ACCENT
)

# Microphone stand arc
draw.arc([mic_x - 80, mic_y + 10, mic_x + 80, mic_y + 130],
         start=0, end=180, fill=GOLD, width=10)

# Stand vertical line
draw.line([mic_x, mic_y + 70, mic_x, mic_y + 130], fill=GOLD, width=10)
draw.line([mic_x - 40, mic_y + 130, mic_x + 40, mic_y + 130], fill=GOLD, width=10)

# Sound waves (left)
for i, r in enumerate([105, 130, 155]):
    alpha = 200 - i * 50
    draw.arc([mic_x - r - 10, mic_y - 60, mic_x - 10, mic_y + 60],
             start=130, end=230, fill=(*TEXT, alpha), width=6)

# Sound waves (right)
for i, r in enumerate([105, 130, 155]):
    alpha = 200 - i * 50
    draw.arc([mic_x + 10, mic_y - 60, mic_x + r + 10, mic_y + 60],
             start=310, end=50, fill=(*TEXT, alpha), width=6)

out = Path("web/icon.png")
out.parent.mkdir(exist_ok=True)
img.save(str(out), "PNG")
print(f"Icon saved → {out}")
