import os
import re
import sys

DEFAULTS = {
    "DEFAULT_BACKEND_URL": (
        "KDBS_BACKEND_URL",
        sys.argv[1] if len(sys.argv) > 1 else "https://kevsono-kevs-digital-bos.hf.space",
    ),
    "DEFAULT_BI_URL": (
        "KDBS_BI_URL",
        "https://kevsono-kevs-digital-business-intelligencev2.hf.space",
    ),
    "DEFAULT_CONCIERGE_URL": (
        "KDBS_CONCIERGE_URL",
        "https://kevsono-penafort-concierge.hf.space",
    ),
}

config_path = os.path.join("muzoscents-funnel old", "kd-config.js")
with open(config_path, "r", encoding="utf-8") as f:
    content = f.read()

for const_name, (env_key, fallback_val) in DEFAULTS.items():
    val = (os.environ.get(env_key) or fallback_val).strip().rstrip("/")
    if not val:
        print(f"Error: Empty value for {const_name}", file=sys.stderr)
        sys.exit(1)
    content, count = re.subn(
        rf'const {const_name} = "[^"]*";',
        f'const {const_name} = "{val}";',
        content,
        count=1,
    )
    if count == 0:
        print(f"Error: Could not find {const_name} in kd-config.js", file=sys.stderr)
        sys.exit(1)
    print(f"{const_name} -> {val}")

with open(config_path, "w", encoding="utf-8") as f:
    f.write(content)
