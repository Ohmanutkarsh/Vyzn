"""
Captures screenshots of /_design at 1440px and 390px in both Dark and Light themes.
"""

import subprocess
import os
import time
from pathlib import Path

WORKSPACE = Path(r"c:\Vyzn Ai")
EDGE_BIN = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

def capture(width, height, theme, output_name):
    out_path = WORKSPACE / output_name
    # Create temporary HTML wrapper setting the theme attribute or use URL
    url = f"http://localhost:8000/_design"
    
    # We can pass custom JS evaluation or load a small wrapper that sets data-theme
    wrapper_html = WORKSPACE / f"temp_{theme}_{width}.html"
    with open(wrapper_html, "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;">
<iframe id="frame" src="http://localhost:8000/_design" style="width:100%;height:{height}px;border:none;"></iframe>
<script>
  const iframe = document.getElementById('frame');
  iframe.onload = () => {{
    try {{
      iframe.contentDocument.documentElement.setAttribute('data-theme', '{theme}');
      if ({width} <= 400) {{
        iframe.contentDocument.getElementById('viewport').classList.add('is-mobile');
      }}
    }} catch(e) {{}}
  }};
</script>
</body>
</html>""")

    cmd = [
        EDGE_BIN,
        "--headless=new",
        "--disable-gpu",
        f"--window-size={width},{height}",
        f"--screenshot={out_path.resolve()}",
        f"file:///{wrapper_html.resolve()}"
    ]
    subprocess.run(cmd, capture_output=True, timeout=20)
    time.sleep(1)
    if wrapper_html.exists():
        wrapper_html.unlink()

    if out_path.exists():
        print(f"Captured {output_name} ({out_path.stat().st_size / 1024:.1f} KB)")
    else:
        print(f"Failed to capture {output_name}")

def main():
    print("Capturing Phase 1 Design Showcase Screenshots...")
    capture(1440, 1100, "dark", "design_1440_dark.png")
    capture(1440, 1100, "light", "design_1440_light.png")
    capture(390, 1200, "dark", "design_390_dark.png")
    capture(390, 1200, "light", "design_390_light.png")

if __name__ == "__main__":
    main()
