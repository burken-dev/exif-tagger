import re
import sys

new_ver = sys.argv[1]
with open("pyproject.toml") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if re.match(r"^\s*version\s*=", line) and "tomllib" not in str(line):
        indent_match = re.match(r"(\s*)", line)
        indent = indent_match.group(1) if indent_match else ""
        lines[i] = f'{indent}version = "{new_ver}"\n'
        break

with open("pyproject.toml", "w") as f:
    f.writelines(lines)
