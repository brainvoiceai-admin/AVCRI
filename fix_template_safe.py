import re

path = r'c:\Users\irfah\OneDrive\Desktop\AVCRI-1\templates\dashboards\superadmin\Manage_user.html'

try:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find and fix request.GET.status=='active' type of issues
    content = re.sub(r'([^\s=!<>])==([^\s=])', r'\1 == \2', content)
    
    # Fix instances where extra spaces were added
    content = re.sub(r' +== +', ' == ', content)

    # Fix multiline template tags
    def fix_multiline(match):
        before = match.group(1).replace('\r\n', ' ').replace('\n', ' ')
        # replace excessive spaces with single space
        before = re.sub(r'\s+', ' ', before)
        return '{%' + before + '%}'

    content = re.sub(r'\{%([^%]+)%\}', fix_multiline, content)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

    print('Successfully fixed template spacing in Manage_user.html')
except Exception as e:
    print(f'Error: {e}')
