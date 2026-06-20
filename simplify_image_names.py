import os
import sys
import re
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

vault = Path('CLR_via_CSharp_Obsidian')
assets = vault / 'assets'

renames = {}

# Match the page and index from the end of the filename, e.g., "0194-07.png"
suffix_re = re.compile(r'-(\d{4}-\d{2}\.png)$')

for img in assets.iterdir():
    old_name = img.name
    match = suffix_re.search(old_name)
    if match:
        new_name = f"img-{match.group(1)}"
        img.rename(assets / new_name)
        renames[old_name] = new_name
        print(f"Renamed: {old_name[:20]}... -> {new_name}")

if not renames:
    print("No images needed renaming.")
else:
    fixed = 0
    for md_file in vault.rglob('*.md'):
        content = md_file.read_text(encoding='utf-8')
        new_content = content
        for old, new in renames.items():
            new_content = new_content.replace(f'![[{old}]]', f'![[{new}]]')
        
        if new_content != content:
            md_file.write_text(new_content, encoding='utf-8')
            fixed += 1
            print(f"Updated links in: {md_file.name}")
    
    print(f"Fixed {fixed} markdown files.")
