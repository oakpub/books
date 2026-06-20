import os
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

vault = Path('CLR_via_CSharp_Obsidian')

fixed = 0

for md_file in vault.rglob('*.md'):
    content = md_file.read_text(encoding='utf-8')
    lines = content.split('\n')
    
    out = []
    i = 0
    changed = False
    
    while i < len(lines):
        line = lines[i]
        
        # Look for the start of a code block
        if line.startswith('```') and not line.strip() == '```':
            lang = line[3:].strip()
            out.append(line)
            i += 1
            
            # Read inside the block until it closes
            while i < len(lines):
                if lines[i].startswith('```'):
                    # Found closing fence
                    
                    # Look ahead to see if the next non-empty line is the SAME opening fence
                    j = i + 1
                    blank_lines = []
                    while j < len(lines) and not lines[j].strip():
                        blank_lines.append(lines[j])
                        j += 1
                    
                    if j < len(lines) and lines[j].strip() == f'```{lang}':
                        # We can MERGE!
                        # Add a single blank line between merged blocks for readability
                        if not blank_lines:
                            out.append('')
                        else:
                            out.extend(blank_lines)
                        
                        # Skip the closing fence (i) and the opening fence (j)
                        i = j + 1
                        changed = True
                        continue # This continues the inner while loop!
                    else:
                        # Cannot merge. Just close it.
                        out.append(lines[i])
                        i += 1
                        break # Break inner loop, go back to outer loop
                else:
                    out.append(lines[i])
                    i += 1
        else:
            out.append(line)
            i += 1

    if changed:
        md_file.write_text('\n'.join(out), encoding='utf-8')
        fixed += 1
        print(f"Merged code blocks in: {md_file.name}")

print(f"Fixed {fixed} markdown files.")
