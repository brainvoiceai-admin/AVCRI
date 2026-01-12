import re

# Read the file
with open(r'templates\masters\item_master_manage.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print("Fixing template syntax issues...")
fixed_count = 0

# Process each line
for i in range(len(lines)):
    original = lines[i]
    
    # Fix pattern: {% if variable=='value' %} -> {% if variable == 'value' %}
    # This handles single quotes
    if "{% if" in lines[i] and "==" in lines[i]:
        # Replace == without spaces with == with spaces
        lines[i] = re.sub(r"(\w+)=='([^']+)'", r"\1 == '\2'", lines[i])
        lines[i] = re.sub(r'(\w+)=="([^"]+)"', r'\1 == "\2"', lines[i])
        
        if lines[i] != original:
            fixed_count += 1
            print(f"  Line {i+1}: Fixed comparison operator")

# Write back
with open(r'templates\masters\item_master_manage.html', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"\n✓ Fixed {fixed_count} lines in item_master_manage.html")

# Now let's verify the specific problematic lines
print("\nVerifying lines 62-64 and 73:")
with open(r'templates\masters\item_master_manage.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i in [61, 62, 63, 72]:  # 0-indexed
        print(f"  Line {i+1}: {lines[i].strip()}")
