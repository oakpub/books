import os
import sys
import re
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

vault = Path('CLR_via_CSharp_Obsidian')
assets = vault / 'assets'

# Mapping of old filename -> new filename
renames = {}

for img in assets.iterdir():
    old_name = img.name
    # Obsidian breaks on '#' inside wikilinks
    if '#' in old_name:
        new_name = old_name.replace('#', 'Sharp')
        img.rename(assets / new_name)
        renames[old_name] = new_name
        print(f"Renamed: {old_name} -> {new_name}")

if not renames:
    print("No images needed renaming.")
else:
    # Update markdown files
    fixed = 0
    for md_file in vault.rglob('*.md'):
        content = md_file.read_text(encoding='utf-8')
        new_content = content
        for old, new in renames.items():
            # Obsidian wikilink syntax
            new_content = new_content.replace(f'![[{old}]]', f'![[{new}]]')
        
        if new_content != content:
            md_file.write_text(new_content, encoding='utf-8')
            fixed += 1
            print(f"Updated links in: {md_file.name}")
    
    print(f"Fixed {fixed} markdown files.")
