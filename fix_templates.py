import os
import re

directory = r'C:\Users\irfah\OneDrive\Desktop\AVCRI-1\templates\masters'

def add_spaces_around_equals(content):
    def fix_if_tag(match):
        inner = match.group(1)
        # Add space before == if not present
        fixed = re.sub(r'([^ \n\r])==', r'\1 ==', inner)
        # Add space after == if not present
        fixed = re.sub(r'==([^ \n\r])', r'== \1', fixed)
        return f'{{% if {fixed} %}}'

    return re.sub(r'\{% if (.*?) %\}', fix_if_tag, content, flags=re.DOTALL)

for filename in os.listdir(directory):
    if filename.endswith('.html'):
        filepath = os.path.join(directory, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        new_content = add_spaces_around_equals(content)
        
        if new_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Fixed: {filename}")
        else:
            print(f"No changes: {filename}")
