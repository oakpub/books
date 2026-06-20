import sys, re
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
from pathlib import Path
from collections import Counter

vault = Path('CLR_via_CSharp_Obsidian')

code_headings = Counter()
false_positive_blocks = 0

CS_STMT = re.compile(r'^(using\s|namespace\s|public\s|private\s|protected\s|internal\s|static\s|sealed\s|class\s|interface\s|struct\s|enum\s|\[assembly:|\[Serializable|\[Flags)')

for f in sorted(vault.rglob('*.md')):
    content = f.read_text(encoding='utf-8')
    lines = content.split('\n')

    # Count ## `code` headings
    for line in lines:
        m = re.match(r'^## `(.+?)`\s*$', line)
        if m:
            code = m.group(1).strip()
            code_headings[code[:40]] += 1

    # Count false-positive csharp blocks (all non-comment lines are bare identifiers)
    i = 0
    while i < len(lines):
        if lines[i].startswith('```csharp'):
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                block.append(lines[i])
                i += 1
            # Check if this is a false positive:
            # - Has lines that are purely // Russian comment
            # - Non-comment lines are bare single identifiers (no spaces, no syntax)
            non_comment = [l for l in block if l.strip() and not l.strip().startswith('//')]
            if non_comment and all(
                not re.search(r'[{}();=<>\[\] ]', l.strip()) and len(l.strip()) > 0
                for l in non_comment
            ):
                false_positive_blocks += 1
        i += 1

print(f'## `code` headings total: {sum(code_headings.values())}')
print(f'False-positive csharp blocks: {false_positive_blocks}')
print()
print('Top code headings:')
for code, count in code_headings.most_common(20):
    stmt = '(C# stmt)' if CS_STMT.match(code) else '(identifier/output)'
    print(f'  {count}x  {stmt}  `{code}`')
