import sys, re
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
from pathlib import Path

vault = Path('CLR_via_CSharp_Obsidian')

# Sample first 20 unlabeled fenced blocks
count = 0
for f in sorted(vault.rglob('*.md')):
    content = f.read_text(encoding='utf-8')
    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == '```':
            # Collect block content
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                block.append(lines[i])
                i += 1
            sample = '\n'.join(block[:5])
            print(f'--- Block {count+1} in {f.name} ---')
            print(sample[:200])
            print()
            count += 1
            if count >= 25:
                break
        i += 1
    if count >= 25:
        break
