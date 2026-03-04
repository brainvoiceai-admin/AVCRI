import os
import re

template_dir = r'c:\Users\irfah\OneDrive\Desktop\AVCRI-1\templates'
count = 0

def fix_tag_spacing(match):
    tag_content = match.group(0)
    # Give == spaces
    tag_content = re.sub(r'([^\s=!<>])==([^\s=])', r'\1 == \2', tag_content)
    # Give != spaces
    tag_content = re.sub(r'([^\s=!<>])!=([^\s=])', r'\1 != \2', tag_content)
    # Fix multiple spaces around == or !=
    tag_content = re.sub(r' +== +', ' == ', tag_content)
    tag_content = re.sub(r' +!= +', ' != ', tag_content)
    return tag_content

def fix_multiline(match):
    before = match.group(1).replace('\r\n', ' ').replace('\n', ' ')
    before = re.sub(r'\s+', ' ', before)
    return '{%' + before + '%}'

for root, dirs, files in os.walk(template_dir):
    for f in files:
        if f.endswith('.html'):
            filepath = os.path.join(root, f)
            try:
                with open(filepath, 'r', encoding='utf-8') as file:
                    content = file.read()
                
                original_content = content
                
                # Fix line breaks in template tags that crash Django (e.g. {% if \n x == y %})
                content = re.sub(r'\{%([^%]+)%\}', fix_multiline, content)
                
                # Fix missing spaces around operators inside Django tags only 
                # (so we don't break JS code by accident)
                content = re.sub(r'\{%[^%]+%\}', fix_tag_spacing, content)
                content = re.sub(r'\{\{[^\}]+\}\}', fix_tag_spacing, content)
                
                if content != original_content:
                    with open(filepath, 'w', encoding='utf-8') as file:
                        file.write(content)
                    print(f"Fixed: {filepath}")
                    count += 1
            except Exception as e:
                print(f"Error processing {filepath}: {e}")

print(f"Finished fixing template spacing. Total files fixed: {count}")
