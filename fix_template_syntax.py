import re

# Read the file
with open(r'templates\masters\item_master_manage.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix all instances of == without spaces in if statements
# Pattern: {% if variable=='value' %} -> {% if variable == 'value' %}
content = re.sub(r"(\{%\s+if\s+\w+)=='([^']+)'", r"\1 == '\2'", content)

# Also fix == with double quotes
content = re.sub(r'(\{%\s+if\s+\w+)=="([^"]+)"', r'\1 == "\2"', content)

# Write back
with open(r'templates\masters\item_master_manage.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Fixed all template syntax issues")
print("  Replaced all '==' without spaces with ' == ' in if statements")
