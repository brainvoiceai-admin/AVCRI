import re

path = r'c:\Users\irfah\OneDrive\Desktop\AVCRI-1\templates\dashboards\superadmin\Manage_user.html'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace any occurrence of word=='word' or string=='string' or word=='string'
# This covers cases like request.GET.status=='active'
content = re.sub(r"([^\s=!<>])==([^\s=])", r"\1 == \2", content)

# Make sure we don't accidentally create triple spaces like '  ==  '
content = re.sub(r" +== +", " == ", content)

# Also fix the multiline tags splitting {% and %}
# e.g. {% if request.GET.status=='active' \n %} -> {% if request.GET.status=='active' %}
def fix_multiline(match):
    before = match.group(1).replace('\r\n', ' ').replace('\n', ' ')
    # replace excessive spaces with single space
    before = re.sub(r'\s+', ' ', before)
    return '{%' + before + '%}'

content = re.sub(r'\{%([^%]+)%\}', fix_multiline, content)

# ensure we don't have overlapping fixes.

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done fixing templates via python")
