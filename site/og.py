"""Render the link-preview image (site/og.png) from the built page.

  python site/og.py      # after site/build.py; needs Google Chrome on this machine

Run by daily.sh so the preview shows the current finding. Skips quietly when
Chrome is missing (for example in CI), keeping the last committed image.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def main():
    if not Path(CHROME).exists():
        print("og: Chrome not found, keeping the existing image")
        return
    with tempfile.TemporaryDirectory() as tmp:
        shot = Path(tmp) / "top.png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                        "--window-size=1280,1320", "--virtual-time-budget=5000", f"--screenshot={shot}",
                        (ROOT / "_site" / "index.html").as_uri()], check=True, capture_output=True)
        im = Image.open(shot).convert("RGB")
    bg = im.getpixel((10, 10))
    hero = im.crop((240, 190, 2320, 624))     # title, subtitle, headline, byline (2x pixels)
    kpi = im.crop((240, 1060, 2320, 1460))    # summary tiles
    pad, gap = 80, 72
    can = Image.new("RGB", (hero.width + 2 * pad, hero.height + kpi.height + gap + 2 * pad), bg)
    can.paste(hero, (pad, pad))
    can.paste(kpi, (pad, pad + hero.height + gap))
    can = can.resize((1200, round(can.height * 1200 / can.width)), Image.LANCZOS)
    out = Image.new("RGB", (1200, 630), bg)
    out.paste(can, (0, (630 - can.height) // 2))
    out.save(ROOT / "site" / "og.png", optimize=True)
    print("og: wrote site/og.png")


if __name__ == "__main__":
    sys.exit(main())
