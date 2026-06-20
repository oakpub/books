#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_code_blocks.py
Post-processes the Obsidian vault to:
1. Add proper language tags to unlabeled fenced code blocks
2. Convert large single-line inline code spans to fenced blocks
"""

import sys
import re
from pathlib import Path

sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

VAULT = Path("CLR_via_CSharp_Obsidian")

# ─── Language detection ────────────────────────────────────────────────────────

CS_KEYWORDS = [
    'using ', 'namespace ', 'class ', 'interface ', 'struct ', 'enum ',
    'public ', 'private ', 'protected ', 'internal ', 'static ', 'sealed ',
    'void ', 'return ', 'new ', 'override ', 'virtual ', 'abstract ',
    'delegate ', 'event ', 'typeof(', 'sizeof(', 'stackalloc ',
    '[assembly:', '[Serializable', '[CLSCompliant', '[Flags',
    '=> {', '=> (', 'async ', 'await ', 'yield ',
]

IL_PATTERNS = [
    r'^\.(method|class|field|assembly|module|namespace)\b',
    r'^IL_[0-9a-fA-F]{4}:',
    r'^(ldstr|ldloc|stloc|call|callvirt|ret|nop|pop|dup|ldc\.|ldarg|starg|br\.|beq|bne|bge|bgt|blt|ble)\b',
    r'^\.maxstack\b',
    r'^\.locals\b',
    r'^\.entrypoint\b',
]

METADATA_PATTERNS = [
    r'^(TypeDef|TypeRef|MemberRef|MethodDef|FieldDef|Property|Event|Assembly|Module)\s+#',
    r'^\s+(Token|ResolutionScope|TypDefName|TypeRefName|Flags|Extends|Implements)\s*:',
    r'^Global (fields|MemberRefs)',
    r'^={3,}',
    r'^ScopeName\s*:',
    r'^MVID\s*:',
]

SHELL_PATTERNS = [
    r'^csc\.exe\b',
    r'^al\.exe\b',
    r'^ildasm\b',
    r'^ngen\.exe\b',
    r'^gacutil\b',
    r'^sn\.exe\b',
    r'^ILDasm\b',
    r'^/out:',
    r'^/target:',
    r'^/t:exe\b',
    r'^/t:library\b',
    r'^@\w+\.rsp\b',
]

PATH_PATTERNS = [
    r'^%\w+%[\\/]',
    r'^[A-Z]:\\',
    r'^HKLM\\',
    r'^HKCU\\',
]

XML_PATTERNS = [
    r'^\s*<[\w?!]',
    r'^\s*</\w',
    r'^\s*<\?xml',
]


def detect_language(block_lines: list[str]) -> str:
    """Determine the best language tag for a code block."""
    stripped = [l.rstrip() for l in block_lines if l.strip()]
    if not stripped:
        return ''

    first = stripped[0].strip()
    all_text = '\n'.join(stripped)

    # Windows paths
    for p in PATH_PATTERNS:
        if re.match(p, first):
            return 'text'

    # Shell / command line
    for p in SHELL_PATTERNS:
        if re.match(p, first, re.IGNORECASE):
            return 'shell'
    # Compiler flags block (starts with / options)
    if re.match(r'^/\w+[\w:.]', first) and not re.search(r'\{|\}|;', all_text):
        return 'shell'

    # IL assembly
    il_score = sum(
        1 for l in stripped
        for p in IL_PATTERNS
        if re.match(p, l.strip(), re.IGNORECASE)
    )
    if il_score >= 2:
        return 'il'

    # ILDasm metadata dump
    meta_score = sum(
        1 for l in stripped
        for p in METADATA_PATTERNS
        if re.match(p, l, re.IGNORECASE)
    )
    if meta_score >= 2:
        return 'text'

    # XML / config
    xml_score = sum(1 for l in stripped for p in XML_PATTERNS if re.match(p, l))
    if xml_score >= 2:
        return 'xml'

    # C# score
    cs_score = sum(1 for l in stripped for kw in CS_KEYWORDS if kw in l)
    has_braces = any('{' in l or '}' in l for l in stripped)
    has_semis = sum(1 for l in stripped if l.rstrip().endswith(';'))
    attr_line = any(re.match(r'^\s*\[[A-Z]', l) for l in stripped)

    if cs_score >= 1 or attr_line or (has_braces and has_semis >= 1):
        return 'csharp'

    # Single-line C# snippet (e.g. "public UInt32 Abc() { return 0; }")
    if len(stripped) <= 3:
        single = ' '.join(stripped)
        if any(kw in single for kw in CS_KEYWORDS):
            return 'csharp'
        if re.search(r'\b(int|string|bool|void|char|byte|long|float|double|decimal)\b', single):
            return 'csharp'

    return 'text'


# ─── Line-by-line conversion of big inline spans ──────────────────────────────

# C# content indicators for inline spans
CS_SPAN_RE = re.compile(
    r'\b(public|private|protected|internal|static|sealed|class|interface|struct|'
    r'namespace|using|void|return|new|override|virtual|abstract|delegate|event|'
    r'async|await|typeof|sizeof)\b'
)

def looks_like_csharp_code(text: str) -> bool:
    """Does this text look like C# code?"""
    return bool(CS_SPAN_RE.search(text))


def has_code_syntax(text: str) -> bool:
    """
    Return True if a backtick span contains actual code syntax —
    not just a bare identifier reference in prose.
    """
    # Has syntax characters common in code
    if re.search(r'[{}();=<>\[\]]', text):
        return True
    # Multi-word content (a space inside the span)
    if ' ' in text:
        return True
    # Very long identifier — likely a complex expression
    if len(text) > 35:
        return True
    return False


def process_big_inline_code(line: str) -> str:
    """
    Convert lines where the ENTIRE content is a single large backtick span
    (or nearly so) into a proper fenced code block.
    
    Pattern: `some long code here` possibly with trailing text
    """
    stripped = line.strip()

    # Single full-line backtick span: `code...`
    m = re.match(r'^`([^`]{40,})`\s*$', stripped)
    if m:
        code = m.group(1)
        if looks_like_csharp_code(code):
            # Split on ; and { } to reconstruct lines
            return f'```csharp\n{code}\n```'

    return line


def process_mixed_inline_code_line(line: str) -> str:
    """
    Handle the pattern where one line contains multiple `code` spans
    interleaved with descriptive Russian text — common in code listings.

    Heuristic: if the line has 3+ code spans, at least ONE span contains
    actual code syntax (braces/parens/semicolons or is multi-word), and the
    combined spans contain C# keywords, convert to a fenced block.

    Spans that are ONLY bare identifier names (like `Main`, `Dial`) inside
    prose sentences are intentionally NOT converted to avoid false positives.
    """
    stripped = line.strip()

    # Find all backtick spans and their positions
    spans = list(re.finditer(r'`([^`]+)`', stripped))

    if len(spans) < 3:
        return line  # Not enough code spans

    total_code_len = sum(len(s.group(1)) for s in spans)
    if total_code_len < 60:
        return line  # Too short to be a real code listing

    # At least one span must have real code syntax (not just an identifier)
    if not any(has_code_syntax(s.group(1)) for s in spans):
        return line  # All spans are simple identifier references in prose

    # Check that code spans actually look like C#
    combined_code = ' '.join(s.group(1) for s in spans)
    if not looks_like_csharp_code(combined_code):
        return line

    # Build a fenced block:
    # Alternate between code spans and interstitial text (as comments)
    parts = []
    prev_end = 0

    for span in spans:
        # Text between previous span and this one
        between = stripped[prev_end:span.start()].strip()
        if between:
            # Make it a comment in the block
            parts.append(f'// {between}')
        # The code itself
        code_content = span.group(1).strip()
        parts.append(code_content)
        prev_end = span.end()

    # Any trailing text
    tail = stripped[prev_end:].strip()
    if tail:
        parts.append(f'// {tail}')

    code_block = '\n'.join(parts)
    return f'```csharp\n{code_block}\n```'


# ─── Main file processor ───────────────────────────────────────────────────────

def process_file(path: Path) -> tuple[int, int, int]:
    """
    Returns (labeled_fenced, converted_inline, converted_big) counts.
    """
    content = path.read_text(encoding='utf-8')
    lines = content.split('\n')
    out = []
    i = 0
    labeled_fenced = 0
    converted_big = 0

    while i < len(lines):
        line = lines[i]

        # ── Fenced code block ───────────────────────────────────────────────
        if re.match(r'^```\s*$', line):
            # Collect the block
            block_lines = []
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith('```'):
                block_lines.append(lines[j])
                j += 1

            lang = detect_language(block_lines)
            if lang:
                out.append(f'```{lang}')
                labeled_fenced += 1
            else:
                out.append(line)  # Keep as-is

            out.extend(block_lines)
            out.append(lines[j] if j < len(lines) else '```')
            i = j + 1
            continue

        # ── Already-labeled fenced block — skip ────────────────────────────
        if re.match(r'^```\w', line):
            out.append(line)
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                out.append(lines[i])
                i += 1
            if i < len(lines):
                out.append(lines[i])
            i += 1
            continue

        # ── Big single-span inline code ─────────────────────────────────────
        converted = process_big_inline_code(line)
        if converted != line:
            out.append(converted)
            converted_big += 1
            i += 1
            continue

        # ── Mixed multi-span inline code ────────────────────────────────────
        converted = process_mixed_inline_code_line(line)
        if converted != line:
            out.append(converted)
            converted_big += 1
            i += 1
            continue

        out.append(line)
        i += 1

    path.write_text('\n'.join(out), encoding='utf-8')
    return labeled_fenced, converted_big, 0


# ─── Run ───────────────────────────────────────────────────────────────────────

def main():
    md_files = sorted(VAULT.rglob('*.md'))
    total_labeled = 0
    total_converted = 0

    print(f"Processing {len(md_files)} markdown files...")
    for f in md_files:
        labeled, converted, _ = process_file(f)
        total_labeled += labeled
        total_converted += converted
        if labeled or converted:
            print(f"  {f.name}: +{labeled} labeled, +{converted} converted")

    print()
    print("─" * 50)
    print(f"✅ Done!")
    print(f"   Fenced blocks labeled:     {total_labeled}")
    print(f"   Inline spans converted:    {total_converted}")
    print("─" * 50)


if __name__ == '__main__':
    main()
