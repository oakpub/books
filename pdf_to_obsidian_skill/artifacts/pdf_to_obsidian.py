#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf_to_obsidian.py — Universal PDF → Obsidian Vault converter
==============================================================

Converts any text-based PDF into a structured Obsidian vault.
Designed to be invoked by an AI agent that handles topic/language
detection and user interaction before calling this script.

Usage (direct):
  python pdf_to_obsidian.py <input.pdf> [options]

Options:
  --output <dir>         Output vault directory (default: <name>_Obsidian)
  --title <title>        Document title (auto-detected from heading/filename)
  --author <name>        Author name
  --lang <language>      Primary programming language for code highlighting.
                         Supported: python, javascript, typescript, java,
                         csharp, cpp, c, rust, go, sql, html, css, bash,
                         powershell, r, kotlin, swift, ruby, php, text
                         Use 'text' for non-code documents.
  --tags <t1,t2>         Comma-separated tags for YAML frontmatter
  --structure <type>     Document structure: auto|chapters|sections|flat
                         auto = detect from headings (default)
  --domain <domain>      Subject domain: programming|math|science|history|...
  --no-images            Skip image extraction to assets/
  --extra-langs <l1,l2>  Secondary languages that may appear in code blocks
"""

import sys
import re
import os
import shutil
import json
import argparse
from pathlib import Path
from datetime import date
from collections import Counter

# ─── Fix Windows console encoding ────────────────────────────────────────────
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

TODAY = date.today().isoformat()

# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 0: PDF EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_pdf(pdf_path: Path, images_dir: Path) -> str:
    """Extract PDF to markdown using PyMuPDF4LLM."""
    try:
        import pymupdf4llm
    except ImportError:
        sys.exit("ERROR: pymupdf4llm not installed. Run: pip install pymupdf4llm")

    print(f"Extracting: {pdf_path.name} ...")
    md = pymupdf4llm.to_markdown(
        str(pdf_path),
        write_images=True,
        image_path=str(images_dir),
        image_format="png",
    )
    print(f"  Extracted {len(md):,} chars, images → {images_dir}")
    return md


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: DOCUMENT STRUCTURE ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════

# Multilingual chapter/part patterns
_CHAPTER_PATTERNS = [
    # Russian
    re.compile(r'^##\s+\*\*Глава\s+(\d+)[.\s]+(.+?)\*\*\s*$'),
    # English
    re.compile(r'^##\s+\*\*Chapter\s+(\d+)[.\s]+(.+?)\*\*\s*$', re.IGNORECASE),
    # German
    re.compile(r'^##\s+\*\*Kapitel\s+(\d+)[.\s]+(.+?)\*\*\s*$', re.IGNORECASE),
    # French
    re.compile(r'^##\s+\*\*Chapitre\s+(\d+)[.\s]+(.+?)\*\*\s*$', re.IGNORECASE),
    # Italian
    re.compile(r'^##\s+\*\*Capitolo\s+(\d+)[.\s]+(.+?)\*\*\s*$', re.IGNORECASE),
    # Spanish
    re.compile(r'^##\s+\*\*Capítulo\s+(\d+)[.\s]+(.+?)\*\*\s*$', re.IGNORECASE),
    # Generic: "## 1. Title" or "## 1 Title"
    re.compile(r'^##\s+(\d+)[.\s]+(.+?)\s*$'),
]

_PART_PATTERNS = [
    re.compile(r'^##\s+\*\*Часть\s+([IVX]+)', re.IGNORECASE),       # Russian
    re.compile(r'^##\s+\*\*Part\s+([IVX]+)', re.IGNORECASE),        # English
    re.compile(r'^##\s+\*\*Teil\s+([IVX]+)', re.IGNORECASE),        # German
    re.compile(r'^##\s+\*\*Partie\s+([IVX]+)', re.IGNORECASE),      # French
    re.compile(r'^##\s+\*\*Parte\s+([IVX]+)', re.IGNORECASE),       # Spanish/Italian
    re.compile(r'^##\s+\*\*Section\s+([IVX]+)', re.IGNORECASE),     # English alt
]

_SECTION_HEADING_RE = re.compile(r'^##\s+(.+?)\s*$')


class DocChapter:
    def __init__(self, num: int, title: str, lines: list[str]):
        self.num = num
        self.title = title
        self.lines = lines

    @property
    def safe_title(self) -> str:
        """Filesystem-safe title (remove bold markers, limit length)."""
        t = re.sub(r'\*\*(.+?)\*\*', r'\1', self.title).strip()
        t = re.sub(r'[<>:"/\\|?*]', '_', t)
        return t[:80]


class DocPart:
    def __init__(self, roman: str, title: str, chapters: list[DocChapter]):
        self.roman = roman
        self.title = title
        self.chapters = chapters


class DocumentStructure:
    def __init__(self):
        self.parts: list[DocPart] = []
        self.chapters: list[DocChapter] = []   # flat if no parts
        self.intro_lines: list[str] = []
        self.has_parts: bool = False
        self.has_chapters: bool = False

    def all_chapters(self) -> list[DocChapter]:
        if self.has_parts:
            result = []
            for p in self.parts:
                result.extend(p.chapters)
            return result
        return self.chapters


def detect_structure_type(md_content: str) -> str:
    """
    Auto-detect structure: 'chapters', 'sections', or 'flat'.
    """
    lines = md_content.split('\n')
    chapter_count = 0
    section_count = 0
    for line in lines:
        if any(p.match(line) for p in _CHAPTER_PATTERNS):
            chapter_count += 1
        elif _SECTION_HEADING_RE.match(line):
            section_count += 1
    if chapter_count >= 3:
        return 'chapters'
    if section_count >= 3:
        return 'sections'
    return 'flat'


def parse_chapters(md_content: str) -> DocumentStructure:
    """Parse full document into parts/chapters/sections."""
    struct = DocumentStructure()
    lines = md_content.split('\n')
    n = len(lines)

    current_part_roman = None
    current_part_title = ''
    current_ch_num = None
    current_ch_title = ''
    current_ch_lines: list[str] = []
    chapters_in_part: list[DocChapter] = []
    intro: list[str] = []

    def save_chapter():
        nonlocal current_ch_num, current_ch_title, current_ch_lines
        if current_ch_num is not None:
            ch = DocChapter(current_ch_num, current_ch_title, current_ch_lines[:])
            if current_part_roman:
                chapters_in_part.append(ch)
            else:
                struct.chapters.append(ch)
        current_ch_num = None
        current_ch_title = ''
        current_ch_lines = []

    def save_part():
        nonlocal current_part_roman, current_part_title, chapters_in_part
        if current_part_roman and chapters_in_part:
            struct.parts.append(DocPart(current_part_roman, current_part_title, chapters_in_part[:]))
        chapters_in_part = []

    for i, line in enumerate(lines):
        # Check for part heading
        part_match = next((p.match(line) for p in _PART_PATTERNS if p.match(line)), None)
        if part_match:
            save_chapter()
            save_part()
            current_part_roman = part_match.group(1).strip()
            # Get title from the rest of the line
            current_part_title = re.sub(r'\*\*', '', line.split(current_part_roman, 1)[-1]).strip()
            struct.has_parts = True
            continue

        # Check for chapter heading
        ch_match = next((p.match(line) for p in _CHAPTER_PATTERNS if p.match(line)), None)
        if ch_match:
            save_chapter()
            current_ch_num = int(ch_match.group(1))
            raw_title = ch_match.group(2).strip()
            current_ch_title = re.sub(r'\*\*', '', raw_title).strip()
            struct.has_chapters = True
            continue

        # Accumulate lines
        if current_ch_num is not None:
            current_ch_lines.append(line)
        else:
            intro.append(line)

    # Save last chapter and part
    save_chapter()
    save_part()

    struct.intro_lines = intro

    return struct


def split_into_sections(md_content: str) -> list[tuple[str, list[str]]]:
    """
    For 'sections' structure: split by ## headings.
    Returns list of (heading_title, lines).
    """
    lines = md_content.split('\n')
    sections = []
    current_title = 'Introduction'
    current_lines: list[str] = []

    for line in lines:
        m = _SECTION_HEADING_RE.match(line)
        if m:
            if current_lines:
                sections.append((current_title, current_lines[:]))
            current_title = re.sub(r'\*\*', '', m.group(1)).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))

    return sections


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: CONTENT PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
_CALLOUT_NOTE = re.compile(r'^##\s+\*\*(?:Note|Примечание|Hinweis|Note|Nota)\*\*\s*$', re.IGNORECASE)
_CALLOUT_WARN = re.compile(r'^##\s+\*\*(?:Warning|Внимание|Warnung|Avertissement|Atención)\*\*\s*$', re.IGNORECASE)
_CALLOUT_TIP  = re.compile(r'^##\s+\*\*(?:Tip|Совет|Tipp|Conseil|Consejo)\*\*\s*$', re.IGNORECASE)
_CALLOUT_IMPORTANT = re.compile(r'^##\s+\*\*(?:Important|Важно|Wichtig)\*\*\s*$', re.IGNORECASE)
_BOLD_HEADING = re.compile(r'^##\s+\*\*(.+?)\*\*\s*$')
_CODE_HEADING  = re.compile(r'^##\s+`(.+?)`\s*$')
_PAGE_NUM      = re.compile(r'^\*\*\d{1,4}\*\*\s*$')

# Code-heading that is actually a C-like statement
_CODE_STMT_RE  = re.compile(
    r'^(using\s|namespace\s|public\s|private\s|protected\s|internal\s|'
    r'static\s|sealed\s|abstract\s|class\s|interface\s|struct\s|enum\s|'
    r'override\s|virtual\s|async\s|await\s|import\s|from\s|def\s|fn\s|'
    r'func\s|package\s|#include|#import|#pragma|'
    r'\[assembly:|\[Serializable|\[Flags|\[DataContract|'
    r'#if\s|#region|#endregion|#else|#endif'
    r')|[{}]$|.*;$|.*\w\(|.*=.*;?$'
)


def _is_code_heading(text: str) -> bool:
    t = text.strip()
    if t in ('{', '}', '};', '{}', '};'):
        return True
    return bool(_CODE_STMT_RE.match(t))


def convert_images(line: str, assets_folder: str = 'assets') -> str:
    def repl(m):
        src = m.group(2)
        filename = Path(src).name
        return f'![[{filename}]]'
    return IMAGE_RE.sub(repl, line)


def _flush_pending(pending: list, out: list) -> None:
    if not pending:
        return
    out.append('')
    out.append('```')
    out.extend(pending)
    out.append('```')
    out.append('')


def process_content(raw_lines: list[str]) -> str:
    """
    Generic content processor:
    - Converts Callout headings (Note, Warning, Tip, Important) → > [!type]
    - Converts `code` headings that are actual statements → fenced block
    - Drops page-number-only lines
    - Converts image refs → ![[...]]
    - Cleans bold section headings → ## Heading
    """
    out = []
    pending_code: list[str] = []
    i = 0
    n = len(raw_lines)

    def next_nonempty_line(from_i: int) -> str:
        j = from_i
        while j < n and not raw_lines[j].strip():
            j += 1
        return raw_lines[j] if j < n else ''

    while i < n:
        line = raw_lines[i]

        # ── Fenced block (explicit handling) ────────────────────────────
        fence_m = re.match(r'^(`{3,})(\w*)\s*$', line)
        if fence_m and fence_m.group(1) == '```':
            existing_lang = fence_m.group(2)
            block_lines = []
            i += 1
            while i < n and not re.match(r'^```', raw_lines[i]):
                block_lines.append(convert_images(raw_lines[i]))
                i += 1
            closing = raw_lines[i] if i < n else '```'
            if pending_code:
                block_lines = pending_code + ([''] if block_lines else []) + block_lines
                pending_code = []
            opener = f'```{existing_lang}' if existing_lang else '```'
            out.append(opener)
            out.extend(block_lines)
            out.append(closing)
            i += 1
            continue

        # ── Callouts ────────────────────────────────────────────────────
        callout_type = None
        if _CALLOUT_NOTE.match(line):
            callout_type = 'note'
        elif _CALLOUT_WARN.match(line):
            callout_type = 'warning'
        elif _CALLOUT_TIP.match(line):
            callout_type = 'tip'
        elif _CALLOUT_IMPORTANT.match(line):
            callout_type = 'important'

        if callout_type:
            _flush_pending(pending_code, out)
            pending_code = []
            label = line.split('**')[1].strip() if '**' in line else callout_type.capitalize()
            i += 1
            body = []
            while i < n and not raw_lines[i].startswith('## '):
                body.append(raw_lines[i])
                i += 1
            body_text = '\n'.join(body).strip()
            if body_text:
                out.append(f'\n> [!{callout_type}] {label}')
                for bl in body_text.split('\n'):
                    out.append(f'> {bl}' if bl.strip() else '>')
                out.append('')
            continue

        # ── ## headings ─────────────────────────────────────────────────
        if line.startswith('## '):
            heading_raw = line[3:].strip()

            # Drop page-number noise headings (e.g. "**42**")
            if _PAGE_NUM.match(heading_raw) or re.match(r'^\d+$', re.sub(r'\*\*', '', heading_raw)):
                i += 1
                continue

            # Bold heading → ## Clean Title
            m = _BOLD_HEADING.match(line)
            if m:
                _flush_pending(pending_code, out)
                pending_code = []
                out.append(f'\n## {m.group(1).strip()}')
                i += 1
                continue

            # Code heading
            m = _CODE_HEADING.match(line)
            if m:
                code_content = m.group(1).strip()
                if _is_code_heading(code_content):
                    pending_code.append(code_content)
                else:
                    _flush_pending(pending_code, out)
                    pending_code = []
                    out.append(f'\n## `{code_content}`')
                i += 1
                continue

            # Generic heading
            _flush_pending(pending_code, out)
            pending_code = []
            cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', heading_raw).strip()
            out.append(f'\n## {cleaned}')
            i += 1
            continue

        # ── # headings (code blocks mis-parsed as H1) ────────────────────
        if line.startswith('# '):
            heading_content = line[2:].strip()
            pending_code.append(heading_content)
            i += 1
            continue

        # ── Page numbers like "**123**" ──────────────────────────────────
        if _PAGE_NUM.match(line.strip()):
            i += 1
            continue

        # ── Regular line ─────────────────────────────────────────────────
        if pending_code and line.strip():
            _flush_pending(pending_code, out)
            pending_code = []

        out.append(convert_images(line))
        i += 1

    _flush_pending(pending_code, out)
    return '\n'.join(out)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: CODE BLOCK LANGUAGE LABELING
# ═══════════════════════════════════════════════════════════════════════════════

# Language detection patterns: (name, keywords, syntax_patterns, indicators)
LANGUAGE_PROFILES = {
    'python': {
        'keywords': ['def ', 'import ', 'from ', 'print(', 'self.', 'lambda ', 'async def', 'yield ', 'super()', '__init__'],
        'syntax':   [r'^\s*def\s+\w+\s*\(', r'^\s*class\s+\w+[:(]', r'^\s*@\w+', r':$'],
        'file_exts': ['.py'],
    },
    'javascript': {
        'keywords': ['function ', 'const ', 'let ', 'var ', '=>', 'require(', 'module.exports', 'console.log(', 'document.', 'window.'],
        'syntax':   [r'^\s*function\s+\w+\s*\(', r'const\s+\w+\s*=', r'=>\s*\{', r'\.then\('],
        'file_exts': ['.js', '.mjs'],
    },
    'typescript': {
        'keywords': ['interface ', ': string', ': number', ': boolean', 'readonly ', 'export ', 'type ', 'enum ', 'async ', 'await '],
        'syntax':   [r':\s*(string|number|boolean|void|any|never)\b', r'interface\s+\w+', r'type\s+\w+\s*='],
        'file_exts': ['.ts'],
    },
    'java': {
        'keywords': ['public class ', 'private void ', 'import java.', 'System.out.', 'extends ', 'implements ', 'throws ', 'new '],
        'syntax':   [r'^\s*public\s+(class|interface|enum)\s+\w+', r'^\s*import\s+java\.', r'@Override'],
        'file_exts': ['.java'],
    },
    'csharp': {
        'keywords': ['using ', 'namespace ', 'public sealed ', 'async Task', 'await ', 'var ', '=> {', '[Serializable', 'Console.'],
        'syntax':   [r'^\s*using\s+\w+;', r'^\s*namespace\s+\w+', r'^\s*\[.+\]$', r'public\s+(sealed\s+)?class\s+\w+'],
        'file_exts': ['.cs'],
    },
    'cpp': {
        'keywords': ['#include', 'std::', 'cout <<', 'nullptr', 'template<', 'virtual ~', '::'],
        'syntax':   [r'^#include\s*[<"]', r'std::\w+', r'\w+::\w+\('],
        'file_exts': ['.cpp', '.cc', '.cxx', '.h', '.hpp'],
    },
    'c': {
        'keywords': ['#include', 'printf(', 'malloc(', 'void *', 'struct ', 'typedef ', 'NULL', 'int main('],
        'syntax':   [r'^#include\s*[<"]', r'^\s*typedef\s+', r'\w+\s*\*\s*\w+'],
        'file_exts': ['.c', '.h'],
    },
    'rust': {
        'keywords': ['fn ', 'let mut ', 'impl ', 'use std::', '-> Result', 'Option<', 'Vec<', 'println!', 'match ', 'enum '],
        'syntax':   [r'^\s*fn\s+\w+\s*\(', r'^\s*impl\s+\w+', r'->\s*\w+', r'!\w+\!'],
        'file_exts': ['.rs'],
    },
    'go': {
        'keywords': ['func ', 'package ', 'import (', ':=', 'defer ', 'go ', 'chan ', 'map[', 'var ', 'make('],
        'syntax':   [r'^\s*func\s+\w+\s*\(', r'^\s*package\s+\w+', r'\w+\s*:=\s*'],
        'file_exts': ['.go'],
    },
    'kotlin': {
        'keywords': ['fun ', 'val ', 'var ', 'data class', 'companion object', 'override fun', '?: ', 'null', 'println('],
        'syntax':   [r'^\s*fun\s+\w+\s*\(', r'^\s*data\s+class\s+\w+', r'val\s+\w+\s*='],
        'file_exts': ['.kt'],
    },
    'swift': {
        'keywords': ['func ', 'var ', 'let ', 'class ', 'struct ', 'enum ', 'guard ', 'if let ', 'optional', 'print('],
        'syntax':   [r'^\s*func\s+\w+\s*\(', r'^\s*class\s+\w+', r'guard\s+let\s+'],
        'file_exts': ['.swift'],
    },
    'ruby': {
        'keywords': ['def ', 'end', 'class ', 'module ', 'require ', 'attr_', 'puts ', 'do |', '@', 'nil'],
        'syntax':   [r'^\s*def\s+\w+', r'^\s*class\s+\w+', r'\bdo\s+\|'],
        'file_exts': ['.rb'],
    },
    'php': {
        'keywords': ['<?php', 'function ', 'echo ', '$', 'array(', '=>', 'class ', 'namespace ', 'use '],
        'syntax':   [r'<\?php', r'^\s*\$\w+\s*=', r'function\s+\w+\s*\('],
        'file_exts': ['.php'],
    },
    'sql': {
        'keywords': ['SELECT ', 'FROM ', 'WHERE ', 'INSERT INTO', 'CREATE TABLE', 'DROP ', 'JOIN ', 'GROUP BY', 'ORDER BY'],
        'syntax':   [r'^\s*SELECT\b', r'^\s*FROM\b', r'^\s*WHERE\b', r'^\s*CREATE\s+(TABLE|INDEX)'],
        'file_exts': ['.sql'],
    },
    'html': {
        'keywords': ['<html>', '<div>', '<p>', '<head>', '<body>', '<!DOCTYPE', '</'],
        'syntax':   [r'<[a-zA-Z]\w*(\s[^>]*)?>'],
        'file_exts': ['.html', '.htm'],
    },
    'css': {
        'keywords': ['color:', 'margin:', 'padding:', 'font-size:', 'background:', 'border:'],
        'syntax':   [r'^\s*[\w.#\[:][\w\s.#\[\]:,>~+]*\s*\{', r'^\s*\w[\w-]*\s*:'],
        'file_exts': ['.css', '.scss', '.less'],
    },
    'bash': {
        'keywords': ['#!/bin/bash', '#!/bin/sh', 'echo ', 'export ', 'grep ', 'sed ', 'awk ', 'if [ ', 'fi', 'done'],
        'syntax':   [r'^#!/', r'^\s*if\s+\[', r'\|\s*grep\b', r'\$\(', r'\$\{'],
        'file_exts': ['.sh', '.bash'],
    },
    'powershell': {
        'keywords': ['$', 'Get-', 'Set-', 'Write-', 'Invoke-', 'param(', 'function ', 'foreach ('],
        'syntax':   [r'^\s*\$\w+\s*=', r'\$[A-Z]\w+\b', r'Get-\w+|Set-\w+|Write-\w+'],
        'file_exts': ['.ps1'],
    },
    'r': {
        'keywords': ['library(', '<-', 'data.frame(', 'ggplot(', 'function(', 'c(', 'matrix(', 'print('],
        'syntax':   [r'\w+\s*<-\s*', r'^\s*library\(', r'function\s*\('],
        'file_exts': ['.r', '.R'],
    },
    'matlab': {
        'keywords': ['function ', 'end', 'for ', 'while ', 'plot(', 'zeros(', 'ones(', 'fprintf('],
        'syntax':   [r'^\s*function\s+\[?\w+\]?\s*=', r'^\s*for\s+\w+\s*=', r'^\s*%'],
        'file_exts': ['.m'],
    },
}

# IL Assembly (for CLR / JVM bytecode docs)
IL_PATTERNS = [
    re.compile(r'^\.(method|class|field|assembly|module|namespace)\b'),
    re.compile(r'^IL_[0-9a-fA-F]{4}:'),
    re.compile(r'^(ldstr|ldloc|stloc|call|callvirt|ret|nop|pop|dup|ldc\.|ldarg|starg|br\.)\b'),
]

# Shell / command line
SHELL_PATTERNS = [
    re.compile(r'^csc\.exe\b'),
    re.compile(r'^(javac|java)\s+'),
    re.compile(r'^python[\d.]?\s+'),
    re.compile(r'^node\s+'),
    re.compile(r'^go\s+(build|run|test)'),
    re.compile(r'^cargo\s+(build|run|test)'),
    re.compile(r'^npm\s+'),
    re.compile(r'^pip\s+'),
    re.compile(r'^git\s+'),
    re.compile(r'^docker\s+'),
    re.compile(r'^kubectl\s+'),
    re.compile(r'^/out:'),
    re.compile(r'^/target:'),
    re.compile(r'^@\w+\.rsp\b'),
]

PATH_PATTERNS = [
    re.compile(r'^%\w+%[\\/]'),
    re.compile(r'^[A-Z]:\\'),
    re.compile(r'^HKLM\\|^HKCU\\'),
]

XML_PATTERNS = [
    re.compile(r'^\s*<[\w?!]'),
    re.compile(r'^\s*</\w'),
    re.compile(r'^\s*<\?xml'),
]

JSON_PATTERNS = [
    re.compile(r'^\s*\{'),
    re.compile(r'^\s*"[\w-]+"\s*:'),
    re.compile(r'^\s*\['),
]


def _score_language(block_lines: list[str], lang: str) -> int:
    """Score how well a code block matches a given language."""
    profile = LANGUAGE_PROFILES.get(lang, {})
    text = '\n'.join(block_lines)
    score = 0
    for kw in profile.get('keywords', []):
        if kw.lower() in text.lower():
            score += 2
    for pat in profile.get('syntax', []):
        if re.search(pat, text, re.MULTILINE):
            score += 3
    return score


def detect_code_language(block_lines: list[str], primary_lang: str = 'text') -> str:
    """
    Determine the best language tag for a code block.
    primary_lang: the document's main programming language (used as tiebreaker).
    """
    stripped = [l.rstrip() for l in block_lines if l.strip()]
    if not stripped:
        return ''

    first = stripped[0].strip()
    all_text = '\n'.join(stripped)

    # Windows paths
    for p in PATH_PATTERNS:
        if p.match(first):
            return 'text'

    # Shell / command line
    for p in SHELL_PATTERNS:
        if p.match(first, ):
            return 'shell'
    if re.match(r'^/\w+[\w:.]+', first) and not re.search(r'\{|\}|;', all_text):
        return 'shell'

    # IL Assembly
    il_score = sum(1 for l in stripped for p in IL_PATTERNS if p.match(l.strip()))
    if il_score >= 2:
        return 'il'

    # XML
    xml_score = sum(1 for l in stripped for p in XML_PATTERNS if p.match(l))
    if xml_score >= 2:
        return 'xml'

    # JSON
    json_score = sum(1 for l in stripped for p in JSON_PATTERNS if p.match(l))
    if json_score >= 2 and all_text.count('{') + all_text.count('[') >= 2:
        return 'json'

    # Score all languages
    scores = {lang: _score_language(stripped, lang) for lang in LANGUAGE_PROFILES}

    # Boost primary language (slight tiebreaker)
    if primary_lang in scores:
        scores[primary_lang] += 1

    best_lang = max(scores, key=scores.get)
    best_score = scores[best_lang]

    if best_score < 2:
        # Low confidence — fall back to primary or text
        return primary_lang if primary_lang != 'text' else 'text'

    return best_lang


def has_code_syntax(text: str) -> bool:
    """Return True if text looks like actual code syntax, not just an identifier."""
    if re.search(r'[{}();=<>\[\]]', text):
        return True
    if ' ' in text:
        return True
    if len(text) > 35:
        return True
    return False


CS_SPAN_RE = re.compile(
    r'\b(public|private|protected|internal|static|sealed|class|interface|struct|'
    r'namespace|using|void|return|new|override|virtual|abstract|delegate|event|'
    r'async|await|typeof|sizeof|def|func|import|function|const|let|var|'
    r'fn|impl|package|module|require)\b'
)


def label_code_blocks(vault_path: Path, primary_lang: str = 'text') -> dict:
    """
    Post-process all .md files: add language tags to unlabeled code blocks.
    Returns stats dict.
    """
    stats = {'labeled': 0, 'files': 0}
    for f in sorted(vault_path.rglob('*.md')):
        content = f.read_text(encoding='utf-8')
        lines = content.split('\n')
        out = []
        i = 0
        changed = False

        while i < len(lines):
            line = lines[i]

            # Already-labeled block: skip
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

            # Unlabeled block
            if re.match(r'^```\s*$', line):
                block = []
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith('```'):
                    block.append(lines[j])
                    j += 1
                lang = detect_code_language(block, primary_lang)
                if lang:
                    out.append(f'```{lang}')
                    changed = True
                    stats['labeled'] += 1
                else:
                    out.append(line)
                out.extend(block)
                out.append(lines[j] if j < len(lines) else '```')
                i = j + 1
                continue

            # Convert large inline code spans to fenced block
            stripped = line.strip()
            spans = list(re.finditer(r'`([^`]+)`', stripped))
            if (len(spans) >= 3
                    and sum(len(s.group(1)) for s in spans) >= 60
                    and any(has_code_syntax(s.group(1)) for s in spans)
                    and CS_SPAN_RE.search(' '.join(s.group(1) for s in spans))):
                # Convert to fenced block
                parts = []
                prev_end = 0
                for span in spans:
                    between = stripped[prev_end:span.start()].strip()
                    if between:
                        parts.append(f'// {between}')
                    parts.append(span.group(1).strip())
                    prev_end = span.end()
                tail = stripped[prev_end:].strip()
                if tail:
                    parts.append(f'// {tail}')
                code_block = '\n'.join(parts)
                out.append(f'```{primary_lang if primary_lang != "text" else ""}\n{code_block}\n```')
                changed = True
                i += 1
                continue

            out.append(line)
            i += 1

        if changed:
            f.write_text('\n'.join(out), encoding='utf-8')
            stats['files'] += 1

    return stats


def merge_code_blocks(vault_path: Path) -> int:
    """
    Merge consecutive code blocks that share the same language tag.
    Returns the number of files modified.
    """
    fixed = 0
    for f in vault_path.rglob('*.md'):
        content = f.read_text(encoding='utf-8')
        lines = content.split('\n')
        out = []
        i = 0
        changed = False

        while i < len(lines):
            line = lines[i]
            if line.startswith('```') and not line.strip() == '```':
                lang = line[3:].strip()
                out.append(line)
                i += 1
                while i < len(lines):
                    if lines[i].startswith('```'):
                        j = i + 1
                        blank_lines = []
                        while j < len(lines) and not lines[j].strip():
                            blank_lines.append(lines[j])
                            j += 1
                        
                        if j < len(lines) and lines[j].strip() == f'```{lang}':
                            if not blank_lines:
                                out.append('')
                            else:
                                out.extend(blank_lines)
                            i = j + 1
                            changed = True
                            continue
                        else:
                            out.append(lines[i])
                            i += 1
                            break
                    else:
                        out.append(lines[i])
                        i += 1
            else:
                out.append(line)
                i += 1

        if changed:
            f.write_text('\n'.join(out), encoding='utf-8')
            fixed += 1
    return fixed


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: FRONTMATTER & METADATA
# ═══════════════════════════════════════════════════════════════════════════════

def make_frontmatter(title: str, config: dict, extra: dict = None) -> str:
    """Generate YAML frontmatter adapted to document domain."""
    tags = list(config.get('tags', []))
    domain = config.get('domain', 'general')
    lang = config.get('primary_lang', '')
    author = config.get('author', '')

    # Domain-specific tag additions
    if domain == 'programming' and lang and lang != 'text':
        if lang not in tags:
            tags.append(lang)
    if 'book' not in tags and 'книга' not in tags:
        tags.append('book')

    fm_lines = ['---', f'title: "{title}"']
    if author:
        fm_lines.append(f'author: "{author}"')
    fm_lines.append(f'tags: [{", ".join(tags)}]')
    if domain != 'general':
        fm_lines.append(f'domain: {domain}')
    if lang and lang != 'text':
        fm_lines.append(f'language: {lang}')
    if extra:
        for k, v in extra.items():
            fm_lines.append(f'{k}: {json.dumps(v, ensure_ascii=False)}')
    fm_lines += [f'created: "{TODAY}"', '---']
    return '\n'.join(fm_lines)


def make_nav_links(chapter_filenames: list[str], current_idx: int, moc_link: str) -> str:
    prev_link = f'[[{chapter_filenames[current_idx - 1]}|← Prev]]' if current_idx > 0 else '*(first)*'
    next_link = f'[[{chapter_filenames[current_idx + 1]}|Next →]]' if current_idx < len(chapter_filenames) - 1 else '*(last)*'
    return f'{prev_link} | {moc_link} | {next_link}'


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5: VAULT BUILDING
# ═══════════════════════════════════════════════════════════════════════════════

def build_moc(title: str, structure: DocumentStructure, config: dict) -> str:
    """Generate MOC (Map of Content) file."""
    tags = config.get('tags', ['book'])
    domain = config.get('domain', 'general')
    author = config.get('author', '')

    lines = [
        '---',
        f'title: "📚 {title} — Map of Contents"',
        f'tags: [{", ".join(tags)}, moc]',
        f'created: "{TODAY}"',
        '---',
        '',
        f'# 📚 {title}',
        '',
    ]
    if author:
        lines += [f'> [!abstract] About', f'> **Author**: {author}', '']

    lines.append('---')
    lines.append('')

    if structure.has_parts:
        for part in structure.parts:
            lines.append(f'## Part {part.roman}. {part.title}')
            lines.append('')
            for ch in part.chapters:
                fname = f'Ch{ch.num:02d} — {ch.safe_title}'
                lines.append(f'- [[{fname}|Chapter {ch.num}. {ch.title}]]')
            lines.append('')
    elif structure.has_chapters:
        lines.append('## Chapters')
        lines.append('')
        for ch in structure.chapters:
            fname = f'Ch{ch.num:02d} — {ch.safe_title}'
            lines.append(f'- [[{fname}|Chapter {ch.num}. {ch.title}]]')
        lines.append('')

    return '\n'.join(lines)


def slugify(text: str, max_len: int = 60) -> str:
    """Create a filesystem-safe slug from text."""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    s = re.sub(r'[<>:"/\\|?*]', '_', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:max_len]


def build_vault_chapters(
        struct: DocumentStructure,
        output_dir: Path,
        config: dict,
        doc_title: str,
) -> None:
    """Build vault from chapter structure (with optional parts)."""
    all_chapters = struct.all_chapters()
    chapter_filenames = [f'Ch{ch.num:02d} — {ch.safe_title}' for ch in all_chapters]
    moc_name = '📚 Map of Contents'
    moc_link = f'[[{moc_name}]]'

    # Part folders
    if struct.has_parts:
        for part in struct.parts:
            part_dir = output_dir / slugify(f'Part {part.roman} — {part.title}')
            part_dir.mkdir(exist_ok=True)
    else:
        chapters_dir = output_dir / 'Chapters'
        chapters_dir.mkdir(exist_ok=True)

    for idx, ch in enumerate(all_chapters):
        # Find chapter's directory
        if struct.has_parts:
            # Find which part this chapter belongs to
            part = next((p for p in struct.parts if ch in p.chapters), None)
            ch_dir = output_dir / slugify(f'Part {part.roman} — {part.title}') if part else output_dir
        else:
            ch_dir = output_dir / 'Chapters'

        fname = chapter_filenames[idx]
        nav = make_nav_links(chapter_filenames, idx, moc_link)
        fm = make_frontmatter(
            f'Chapter {ch.num}. {ch.title}',
            config,
            extra={'chapter': ch.num},
        )
        body = process_content(ch.lines)
        h1 = f'# Chapter {ch.num}. {ch.title}'

        content = '\n'.join([fm, '', nav, '', '---', '', h1, '', body.strip(), '', '---', '', nav])
        (ch_dir / f'{fname}.md').write_text(content, encoding='utf-8')

    # MOC
    moc = build_moc(doc_title, struct, config)
    (output_dir / f'{moc_name}.md').write_text(moc, encoding='utf-8')

    # Intro
    if struct.intro_lines:
        intro_body = process_content(struct.intro_lines)
        intro_fm = make_frontmatter('Introduction', config)
        intro_content = '\n'.join([intro_fm, '', '# Introduction', '', intro_body.strip()])
        (output_dir / 'Introduction.md').write_text(intro_content, encoding='utf-8')


def build_vault_sections(
        sections: list[tuple[str, list[str]]],
        output_dir: Path,
        config: dict,
        doc_title: str,
) -> None:
    """Build vault from sections (no chapter structure)."""
    section_dir = output_dir / 'Sections'
    section_dir.mkdir(exist_ok=True)

    section_names = [slugify(title) for title, _ in sections]
    moc_name = '📚 Map of Contents'
    moc_link = f'[[{moc_name}]]'

    for idx, (title, lines) in enumerate(sections):
        fname = f'{idx+1:02d} — {slugify(title)}'
        nav = make_nav_links(section_names, idx, moc_link) if len(sections) > 1 else ''
        fm = make_frontmatter(title, config)
        body = process_content(lines)
        h1 = f'# {title}'

        parts = [fm, '', h1, '']
        if nav:
            parts = [fm, '', nav, '', '---', '', h1, '']
        parts.append(body.strip())

        content = '\n'.join(parts)
        (section_dir / f'{fname}.md').write_text(content, encoding='utf-8')

    # Simple MOC for sections
    moc_lines = ['---', f'title: "📚 {doc_title}"', f'tags: [{", ".join(config.get("tags", []))}]', f'created: "{TODAY}"', '---', '', f'# 📚 {doc_title}', '', '## Sections', '']
    for idx, (title, _) in enumerate(sections):
        fname = f'{idx+1:02d} — {slugify(title)}'
        moc_lines.append(f'- [[{fname}|{title}]]')
    (output_dir / f'{moc_name}.md').write_text('\n'.join(moc_lines), encoding='utf-8')


def build_vault_flat(
        md_content: str,
        output_dir: Path,
        config: dict,
        doc_title: str,
) -> None:
    """Build vault as single file (article/paper)."""
    fm = make_frontmatter(doc_title, config)
    body = process_content(md_content.split('\n'))
    content = '\n'.join([fm, '', f'# {doc_title}', '', body.strip()])
    (output_dir / f'{slugify(doc_title)}.md').write_text(content, encoding='utf-8')


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='Universal PDF → Obsidian Vault converter',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('pdf', help='Input PDF file')
    parser.add_argument('--output', help='Output vault directory')
    parser.add_argument('--title', help='Document title')
    parser.add_argument('--author', default='', help='Author name')
    parser.add_argument('--lang', default='text',
                        help='Primary programming language (python|js|java|csharp|cpp|...)')
    parser.add_argument('--tags', default='book', help='Comma-separated tags')
    parser.add_argument('--structure', default='auto',
                        choices=['auto', 'chapters', 'sections', 'flat'],
                        help='Document structure type')
    parser.add_argument('--domain', default='general',
                        help='Subject domain (programming|math|science|...)')
    parser.add_argument('--no-images', action='store_true', help='Skip image extraction')
    parser.add_argument('--extra-langs', default='',
                        help='Comma-separated secondary languages for code blocks')

    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f'ERROR: File not found: {pdf_path}')

    # Output directory
    stem = pdf_path.stem
    output_dir = Path(args.output) if args.output else Path(f'{stem}_Obsidian')
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir()

    # Images
    images_src = pdf_path.parent / 'images'
    assets_dst = output_dir / 'assets'

    # Config
    config = {
        'primary_lang': args.lang,
        'tags': [t.strip() for t in args.tags.split(',') if t.strip()],
        'domain': args.domain,
        'author': args.author,
    }

    # ── Step 1: Extract PDF ────────────────────────────────────────────────
    md_content = extract_pdf(pdf_path, images_src)
    md_path = pdf_path.parent / f'{stem}.md'
    md_path.write_text(md_content, encoding='utf-8')
    print(f"  Saved intermediate MD: {md_path.name}")

    # ── Step 2: Copy images ────────────────────────────────────────────────
    if not args.no_images and images_src.exists():
        shutil.copytree(images_src, assets_dst)
        print(f"  Copied {len(list(assets_dst.iterdir()))} images → assets/")
    else:
        assets_dst.mkdir()

    # ── Step 3: Detect title ───────────────────────────────────────────────
    doc_title = args.title
    if not doc_title:
        # Try to get from first heading or filename
        for line in md_content.split('\n')[:50]:
            m = re.match(r'^#\s+(.+)', line)
            if m:
                doc_title = re.sub(r'\*\*', '', m.group(1)).strip()[:80]
                break
        if not doc_title:
            doc_title = stem.replace('_', ' ').replace('-', ' ')
    print(f"  Title: {doc_title}")

    # ── Step 4: Detect structure ───────────────────────────────────────────
    structure_type = args.structure
    if structure_type == 'auto':
        structure_type = detect_structure_type(md_content)
    print(f"  Structure: {structure_type}")

    # ── Step 5: Build vault ────────────────────────────────────────────────
    if structure_type == 'chapters':
        struct = parse_chapters(md_content)
        print(f"  Found {len(struct.all_chapters())} chapters, {len(struct.parts)} parts")
        build_vault_chapters(struct, output_dir, config, doc_title)
    elif structure_type == 'sections':
        sections = split_into_sections(md_content)
        print(f"  Found {len(sections)} sections")
        build_vault_sections(sections, output_dir, config, doc_title)
    else:
        print(f"  Flat structure — single/few files")
        build_vault_flat(md_content, output_dir, config, doc_title)

    # ── Step 6: Label code blocks ──────────────────────────────────────────
    print(f"  Labeling code blocks (primary: {args.lang}) ...")
    stats = label_code_blocks(output_dir, args.lang)
    print(f"  Labeled {stats['labeled']} code blocks in {stats['files']} files")

    # ── Step 6.5: Merge consecutive code blocks ────────────────────────────
    merged = merge_code_blocks(output_dir)
    if merged:
        print(f"  Merged consecutive code blocks in {merged} files")

    # ── Step 7: Obsidian config ────────────────────────────────────────────
    obs_dir = output_dir / '.obsidian'
    obs_dir.mkdir()
    (obs_dir / 'app.json').write_text(json.dumps({
        'useMarkdownLinks': False,
        'newLinkFormat': 'shortest',
        'attachmentFolderPath': 'assets',
        'defaultViewMode': 'preview',
    }, indent=2), encoding='utf-8')

    # ── Summary ────────────────────────────────────────────────────────────
    total_md = sum(1 for _ in output_dir.rglob('*.md'))
    total_img = len(list(assets_dst.iterdir())) if assets_dst.exists() else 0
    print('\n' + '─' * 55)
    print('✅  Vault ready!')
    print(f'    📂 {output_dir.resolve()}')
    print(f'    📄 {total_md} markdown files')
    print(f'    🖼️  {total_img} images')
    print('─' * 55)


if __name__ == '__main__':
    main()
