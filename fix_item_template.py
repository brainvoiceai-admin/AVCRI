import re

# Read the file
with open(r'templates\masters\item_master_manage.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the specific issue on line 73-74
# Replace the split if statement with a single line version
old_pattern = r'{% if group_filter==group\.id\|stringformat:"s"\s*%}selected{% endif %}'
new_pattern = r'{% if group_filter == group.id|stringformat:"s" %}selected{% endif %}'
content = re.sub(old_pattern, new_pattern, content, flags=re.MULTILINE | re.DOTALL)

# Also fix any other instances with == without spaces
content = re.sub(r'(\w+)==(\w+\|)', r'\1 == \2', content)

# Write back
with open(r'templates\masters\item_master_manage.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Fixed template syntax in item_master_manage.html")
