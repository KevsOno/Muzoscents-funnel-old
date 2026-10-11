"""
Rewrite migration status checks in main.py:
    if <var>.status_code != 200:    →    if <var>.status_code not in (200, 204):

Leaves alone any block that contains `raise HTTPException` (those are
runtime handlers that need the response body, not migrations).
"""
import re

PATH = "main.py"
with open(PATH, "r", encoding="utf-8") as f:
    lines = f.readlines()

out: list = []
replaced = 0
skipped = 0
i = 0
while i < len(lines):
    line = lines[i]
    m = re.match(r"^(\s*)if\s+(\w+)\.status_code\s*\!\=\s*200\s*:\s*$", line.rstrip("\n"))
    if m:
        indent = m.group(1)
        var = m.group(2)
        # Scan the block body for `raise HTTPException`
        j = i + 1
        found_raise = False
        while j < len(lines):
            nxt = lines[j].rstrip("\n")
            if not nxt.strip():
                j += 1
                continue
            body_indent = len(nxt) - len(nxt.lstrip())
            if body_indent <= len(indent):
                break
            if "raise HTTPException" in nxt:
                found_raise = True
                break
            j += 1
        if found_raise:
            out.append(line)
            skipped += 1
        else:
            out.append(f"{indent}if {var}.status_code not in (200, 204):\n")
            replaced += 1
    else:
        out.append(line)
    i += 1

with open(PATH, "w", encoding="utf-8") as f:
    f.writelines(out)

print(f"Replaced: {replaced}")
print(f"Skipped (raise HTTPException inside block): {skipped}")
