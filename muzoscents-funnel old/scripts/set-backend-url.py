import os
import re
import sys

DEFAULT_URL = "https://kevsono-kevs-digital-bos.hf.space"
target_url = (os.environ.get("KDBS_BACKEND_URL") or (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL)).strip().rstrip("/")

if not target_url:
    print("Error: Backend URL cannot be empty.", file=sys.stderr)
    sys.exit(1)

config_path = os.path.join("muzoscents-funnel old", "kd-config.js")
with open(config_path, "r", encoding="utf-8") as f:
    content = f.read()

updated, count = re.subn(
    r'const DEFAULT_BACKEND_URL = "[^"]*";',
    f'const DEFAULT_BACKEND_URL = "{target_url}";',
    content,
    count=1,
)

if count == 0:
    print("Error: Could not find DEFAULT_BACKEND_URL in kd-config.js", file=sys.stderr)
    sys.exit(1)

with open(config_path, "w", encoding="utf-8") as f:
    f.write(updated)

print(f"Updated {config_path} -> {target_url}")
