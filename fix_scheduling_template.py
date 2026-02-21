"""
Fix multi-line Django {% with %} tags in scheduling.html.
Django's template engine requires {% with %} to be on a single line.
"""
import re

path = r'c:\Users\irfah\OneDrive\Desktop\AVCRI-1\templates\dashboards\scheduling\scheduling.html'

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

result = []
i = 0
fixed = 0

while i < len(lines):
    line = lines[i]
    stripped = line.rstrip('\r\n')
    lstripped = stripped.lstrip()

    # Detect a {% with ... line that does NOT have a closing %}
    if lstripped.startswith('{%') and 'with ' in lstripped and '%}' not in line:
        indent = stripped[:len(stripped) - len(lstripped)]
        parts = [lstripped.rstrip()]
        i += 1
        # Consume lines until we see the closing %}
        while i < len(lines):
            next_line = lines[i].strip().rstrip('\r\n')
            parts.append(next_line)
            i += 1
            if '%}' in next_line:
                break
        # Collapse all parts into one line
        combined = ' '.join(p for p in parts if p)
        # Normalize internal whitespace
        combined = re.sub(r'\s{2,}', ' ', combined)
        result.append(indent + combined + '\r\n')
        fixed += 1
        print(f'  Fixed: {combined[:80]}')
    else:
        result.append(line)
        i += 1

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(result)

print(f'\nTotal fixed: {fixed} multi-line {{% with %}} tags')
