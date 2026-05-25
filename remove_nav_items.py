import os
import re

search_dir = r"c:\Users\arsh\OneDrive\Desktop\Timehub\user_apps"

# We want to remove the Security and Logout blocks from the mobile-bottom-nav-inner
regex_security = re.compile(
    r'\s*<a href="\{% url \'account_edit\' %\}" class="mobile-nav-item.*?</a>',
    re.DOTALL
)

regex_logout = re.compile(
    r'\s*\{% if request\.user\.is_authenticated %\}\s*<a href="\{% url \'logout\' %\}" class="mobile-nav-item logout-btn">\s*<i class="fas fa-right-from-bracket"></i>\s*<span>Logout</span>\s*</a>\s*\{% endif %\}',
    re.DOTALL
)

modified_files = []

for root, dirs, files in os.walk(search_dir):
    for file in files:
        if file.endswith(".html"):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            new_content = content
            if "mobile-bottom-nav" in new_content:
                new_content = regex_security.sub('', new_content)
                new_content = regex_logout.sub('', new_content)
                
                if new_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    modified_files.append(path)

print(f"Modified {len(modified_files)} files:")
for m in modified_files:
    print(m)
