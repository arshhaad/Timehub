import os
import re

search_dir = r'c:\Users\arsh\OneDrive\Desktop\Timehub\user_apps'
files = []
for root, dirs, filenames in os.walk(search_dir):
    for filename in filenames:
        if filename.endswith('.html'):
            files.append(os.path.join(root, filename))

for filepath in files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    modified = False

    # Remove security link block
    security_pattern = re.compile(r'\s*<a href=\"\{% url \'account_edit\' %\}.*?<span>Security</span>\s*</a>', re.DOTALL)
    if security_pattern.search(content):
        content = security_pattern.sub('', content)
        modified = True

    # Remove logout link block
    logout_pattern = re.compile(r'\s*\{% if request\.user\.is_authenticated %\}.*?<a href=\"\{% url \'logout\' %\}.*?<span>Logout</span>\s*</a>\s*\{% endif %\}', re.DOTALL)
    if logout_pattern.search(content):
        content = logout_pattern.sub('', content)
        modified = True
    
    logout_pattern2 = re.compile(r'\s*<a href=\"\{% url \'logout\' %\}.*?<span>Logout</span>\s*</a>', re.DOTALL)
    if logout_pattern2.search(content):
        content = logout_pattern2.sub('', content)
        modified = True

    if modified:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print('Modified ' + filepath)
