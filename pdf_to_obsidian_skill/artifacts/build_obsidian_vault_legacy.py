#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_obsidian_vault.py
Converts CLR_via_CSharp.md into a structured Obsidian vault.

Output: CLR_via_CSharp_Obsidian/
"""

import sys
import re
import os
import shutil
import json
from pathlib import Path
from datetime import date

# Fix Windows console encoding for Russian output
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

# ─── Config ──────────────────────────────────────────────────────────────────
INPUT_FILE = Path("CLR_via_CSharp.md")
OUTPUT_DIR = Path("CLR_via_CSharp_Obsidian")
ASSETS_SRC = Path("images")
ASSETS_DST = OUTPUT_DIR / "assets"
TODAY      = date.today().isoformat()

# ─── Part / Chapter mapping ───────────────────────────────────────────────────
PARTS = {
    1: ("I",   "Основы CLR",              "01 - Часть I — Основы CLR"),
    2: ("II",  "Проектирование типов",    "02 - Часть II — Проектирование типов"),
    3: ("III", "Основные типы данных",    "03 - Часть III — Основные типы данных"),
    4: ("IV",  "Ключевые механизмы",      "04 - Часть IV — Ключевые механизмы"),
    5: ("V",   "Многопоточность",         "05 - Часть V — Многопоточность"),
}

CHAPTER_PART = {
    **{ch: 1 for ch in range(1, 4)},
    **{ch: 2 for ch in range(4, 14)},
    **{ch: 3 for ch in range(14, 20)},
    **{ch: 4 for ch in range(20, 26)},
    **{ch: 5 for ch in range(26, 31)},
}

CHAPTER_NAMES = {
    1:  "Модель выполнения кода в среде CLR",
    2:  "Компоновка, упаковка, развертывание и администрирование",
    3:  "Совместно используемые сборки и сборки со строгим именем",
    4:  "Основы типов",
    5:  "Примитивные, ссылочные и значимые типы",
    6:  "Основные сведения о членах и типах",
    7:  "Константы и поля",
    8:  "Методы",
    9:  "Параметры",
    10: "Свойства",
    11: "События",
    12: "Обобщения",
    13: "Интерфейсы",
    14: "Символы, строки и обработка текста",
    15: "Перечислимые типы и битовые флаги",
    16: "Массивы",
    17: "Делегаты",
    18: "Настраиваемые атрибуты",
    19: "Null-совместимые значимые типы",
    20: "Исключения и управление состоянием",
    21: "Автоматическое управление памятью (уборка мусора)",
    22: "Хостинг CLR и домены приложений",
    23: "Загрузка сборок и отражение",
    24: "Сериализация",
    25: "Взаимодействие с компонентами WinRT",
    26: "Потоки исполнения",
    27: "Асинхронные вычислительные операции",
    28: "Асинхронные операции ввода-вывода",
    29: "Примитивные конструкции синхронизации потоков",
    30: "Гибридные конструкции синхронизации потоков",
}

# Short filenames for each chapter (used in wikilinks)
def chapter_filename(ch_num):
    name = CHAPTER_NAMES[ch_num]
    # Shorten long names
    SHORT = {
        2:  "Компоновка и развертывание",
        3:  "Сборки со строгим именем",
        6:  "Члены и типы",
        14: "Строки и обработка текста",
        21: "Уборка мусора",
        29: "Примитивные конструкции синхронизации",
        30: "Гибридные конструкции синхронизации",
    }
    short = SHORT.get(ch_num, name)
    return f"Глава {ch_num:02d} — {short}"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def clean_bold(text: str) -> str:
    """Remove **bold** markdown markers."""
    return re.sub(r'\*\*(.+?)\*\*', r'\1', text).strip()


def is_noise_heading(raw: str) -> bool:
    """True for headings that are page numbers or code fragments."""
    clean = clean_bold(raw.strip())
    # Page number headings like "82 Глава.2 ..."
    if re.match(r'^\d{2,3}\s+Глава', clean):
        return True
    # Pure number
    if re.match(r'^\d+$', clean):
        return True
    # Very long code-like lines used as headings
    if '`' in raw and len(raw) > 120:
        return True
    return False


# Patterns that identify a code heading as an actual C# statement / fragment
# rather than an identifier reference or output text
_CS_CODE_HEADING_RE = re.compile(
    r'^('
    r'using\s|namespace\s|public\s|private\s|protected\s|internal\s|'
    r'static\s|sealed\s|abstract\s|class\s|interface\s|struct\s|enum\s|'
    r'override\s|virtual\s|async\s|await\s|'
    r'\[assembly:|\[Serializable|\[Flags|\[CLSCompliant|\[DataContract|\[DataMember|'
    r'#if\s|#region|#endregion|#else|#endif'
    r')|'
    r'[{}]$|.*;$|.*\w\(|.*=.*;?$'  # ends with brace/semicolon or has method-call or assignment
)


def is_code_heading(code_text: str) -> bool:
    """Return True if a ## `code` heading is actually a C# fragment that belongs in a code block."""
    text = code_text.strip()
    # Bare braces
    if text in ('{', '}', '};', '{}'):
        return True
    return bool(_CS_CODE_HEADING_RE.match(text))


CALLOUT_NOTE_RE    = re.compile(r'^##\s+\*\*ПриМеЧание\*\*\s*$')
CALLOUT_WARN_RE    = re.compile(r'^##\s+\*\*ВниМание\*\*\s*$')
CHAPTER_HEADING_RE = re.compile(r'^##\s+\*\*Глава\s+(\d+)\.\s+(.+?)\*\*\s*$', re.IGNORECASE)
PART_HEADING_RE    = re.compile(r'^##\s+\*\*Часть\s+([IVX]+)', re.IGNORECASE)
IMAGE_RE           = re.compile(r'!\[([^\]]*)\]\(images/([^)]+)\)')
SECTION_HEADING_RE = re.compile(r'^##\s+\*\*(.+?)\*\*\s*$')
SECTION_CODE_RE    = re.compile(r'^##\s+`(.+?)`\s*$')


def convert_images(line: str) -> str:
    """Convert markdown image refs to Obsidian wiki embeds."""
    def repl(m):
        filename = Path(m.group(2)).name
        return f'![[{filename}]]'
    return IMAGE_RE.sub(repl, line)


def _flush_pending_as_code(pending: list[str], out: list[str]) -> None:
    """Emit buffered code-heading lines as a fenced block."""
    if not pending:
        return
    out.append('')
    out.append('```')
    out.extend(pending)
    out.append('```')
    out.append('')


def process_lines(raw_lines: list[str]) -> str:
    """
    Transform raw lines from the source MD into Obsidian-ready content.
    Key improvements over previous version:
    - ## `C# code` headings that are actual statements are buffered and
      merged into the NEXT fenced code block (or emitted as a standalone
      fenced block if no code block follows).
    - Fenced code blocks are handled explicitly so that pending code can
      be prepended.
    - Images converted to ![[...]]
    - Noise headings dropped.
    """
    out = []
    pending_code: list[str] = []  # code lines from ## `stmt` headings, queued for next block
    i = 0
    n = len(raw_lines)

    while i < n:
        line = raw_lines[i]

        # ── Fenced code block (explicit handling) ─────────────────────────
        # We catch BOTH unlabeled ``` and already-labeled ```lang openers
        fence_m = re.match(r'^(`{3,})(\w*)\s*$', line)
        if fence_m and fence_m.group(1) == '```':  # only triple-backtick fences
            existing_lang = fence_m.group(2)  # '' if unlabeled
            block_lines = []
            i += 1
            while i < n and not re.match(r'^```', raw_lines[i]):
                block_lines.append(convert_images(raw_lines[i]))
                i += 1
            closing = raw_lines[i] if i < n else '```'

            # Merge pending code-heading lines into this block
            if pending_code:
                combined = pending_code + ([''] if block_lines else []) + block_lines
                pending_code = []
            else:
                combined = block_lines

            # Emit with original label (or unlabeled — fix_code_blocks.py will label it)
            opener = f'```{existing_lang}' if existing_lang else '```'
            out.append(opener)
            out.extend(combined)
            out.append(closing)
            i += 1
            continue

        # ── Callout: Примечание ───────────────────────────────────────────
        if CALLOUT_NOTE_RE.match(line):
            _flush_pending_as_code(pending_code, out)
            pending_code = []
            i += 1
            body = []
            while i < n and not raw_lines[i].startswith('## '):
                body.append(raw_lines[i])
                i += 1
            body_text = '\n'.join(body).strip()
            if body_text:
                out.append('\n> [!note] Примечание')
                for bl in body_text.split('\n'):
                    out.append(f'> {bl}' if bl.strip() else '>')
                out.append('')
            continue

        # ── Callout: Внимание ─────────────────────────────────────────────
        if CALLOUT_WARN_RE.match(line):
            _flush_pending_as_code(pending_code, out)
            pending_code = []
            i += 1
            body = []
            while i < n and not raw_lines[i].startswith('## '):
                body.append(raw_lines[i])
                i += 1
            body_text = '\n'.join(body).strip()
            if body_text:
                out.append('\n> [!warning] Внимание')
                for bl in body_text.split('\n'):
                    out.append(f'> {bl}' if bl.strip() else '>')
                out.append('')
            continue

        # ── Drop noise headings ───────────────────────────────────────────
        if line.startswith('## '):
            heading_content = line[3:].strip()
            if is_noise_heading(heading_content):
                i += 1
                continue

            # ── Bold section heading → ## ─────────────────────────────────
            m = SECTION_HEADING_RE.match(line)
            if m:
                _flush_pending_as_code(pending_code, out)
                pending_code = []
                out.append(f'\n## {m.group(1).strip()}')
                i += 1
                continue

            # ── Code heading ──────────────────────────────────────────────
            m = SECTION_CODE_RE.match(line)
            if m:
                code_content = m.group(1).strip()
                if is_code_heading(code_content):
                    # Buffer it — will be merged into the next code block
                    pending_code.append(code_content)
                else:
                    # It's an identifier/output reference (e.g. `Phone.Dial`)
                    # Flush any pending code first, then keep as heading
                    _flush_pending_as_code(pending_code, out)
                    pending_code = []
                    out.append(f'\n## `{code_content}`')
                i += 1
                continue

            # Generic ## heading — flush pending, keep as-is
            _flush_pending_as_code(pending_code, out)
            pending_code = []
            cleaned = clean_bold(heading_content)
            out.append(f'\n## {cleaned}')
            i += 1
            continue

        # ── # heading (code blocks used as H1) → convert to code ─────────
        if line.startswith('# '):
            heading_content = line[2:].strip()
            # These are usually code lines accidentally parsed as H1
            # Buffer them just like ## `code` headings
            pending_code.append(heading_content)
            i += 1
            continue

        # ── Regular line ──────────────────────────────────────────────────
        # If pending code hasn't been consumed by a code block, flush as
        # a standalone block before non-empty content.
        if pending_code and line.strip():
            _flush_pending_as_code(pending_code, out)
            pending_code = []

        # ── Image references ──────────────────────────────────────────────
        line = convert_images(line)

        out.append(line)
        i += 1

    # Flush any remaining pending code at end of section
    _flush_pending_as_code(pending_code, out)

    return '\n'.join(out)


def make_frontmatter(ch_num: int) -> str:
    part_num = CHAPTER_PART[ch_num]
    roman, part_name, _ = PARTS[part_num]
    title = f"Глава {ch_num}. {CHAPTER_NAMES[ch_num]}"
    tags = [
        "clr-via-csharp",
        f"часть/{roman}",
        f"глава/{ch_num:02d}",
        "dotnet",
        "csharp",
        "книга",
    ]
    fm = f"""---
title: "{title}"
aliases:
  - "Глава {ch_num}"
  - "Chapter {ch_num}"
tags: [{', '.join(tags)}]
chapter: {ch_num}
part: "{roman} — {part_name}"
author: "Джеффри Рихтер"
book: "CLR via C#"
edition: 4
created: "{TODAY}"
---"""
    return fm


def make_nav(ch_num: int) -> tuple[str, str]:
    """Return (top_nav, bottom_nav) strings with wikilinks."""
    moc = "[[📚 CLR via C# — Карта знаний]]"
    prev_link = f"[[{chapter_filename(ch_num - 1)}|← Глава {ch_num - 1}]]" if ch_num > 1 else "*(первая глава)*"
    next_link = f"[[{chapter_filename(ch_num + 1)}|Глава {ch_num + 1} →]]" if ch_num < 30 else "*(последняя глава)*"
    nav = f"{prev_link} | {moc} | {next_link}"
    return nav, nav


# ─── Split source MD into chapter blocks ─────────────────────────────────────

def split_into_chapters(content: str) -> dict:
    """
    Returns:
      {
        'intro': [lines before chapter 1],
        chapters: {1: [lines], 2: [lines], ...}
      }
    """
    lines = content.split('\n')
    result = {'intro': [], 'chapters': {}}

    current_ch = None
    current_lines = []

    for line in lines:
        m = CHAPTER_HEADING_RE.match(line)
        if m:
            # Save previous block
            if current_ch is None:
                result['intro'] = current_lines
            else:
                result['chapters'][current_ch] = current_lines
            # Start new chapter
            current_ch = int(m.group(1))
            current_lines = []
            # Don't include the chapter heading itself — we'll regenerate it
        else:
            current_lines.append(line)

    # Save last block
    if current_ch is not None:
        result['chapters'][current_ch] = current_lines
    else:
        result['intro'] = current_lines

    return result


# ─── Split intro block into named sections ────────────────────────────────────

INTRO_SECTIONS = [
    ("Посвящение",          re.compile(r'Посвящение', re.IGNORECASE)),
    ("Предисловие",         re.compile(r'Предисловие', re.IGNORECASE)),
    ("Введение",            re.compile(r'Введение', re.IGNORECASE)),
    ("Благодарности",       re.compile(r'Благодарности', re.IGNORECASE)),
    ("От издателя перевода",re.compile(r'От издателя перевода', re.IGNORECASE)),
]

def split_intro(lines: list[str]) -> dict[str, list[str]]:
    """Split intro lines into named subsections."""
    sections: dict[str, list[str]] = {}
    current_name = "Краткое содержание"
    current = []

    for line in lines:
        matched = False
        for sec_name, pattern in INTRO_SECTIONS:
            if line.startswith('## ') and pattern.search(line):
                if current:
                    sections[current_name] = current
                current_name = sec_name
                current = []
                matched = True
                break
        if not matched:
            current.append(line)

    if current:
        sections[current_name] = current

    return sections


# ─── MOC builder ─────────────────────────────────────────────────────────────

def build_moc() -> str:
    lines = [
        "---",
        'title: "📚 CLR via C# — Карта знаний"',
        "tags: [clr-via-csharp, moc, dotnet, csharp, книга]",
        f'created: "{TODAY}"',
        "---",
        "",
        "# 📚 CLR via C# — Карта знаний",
        "",
        "> [!abstract] О книге",
        "> **Автор**: Джеффри Рихтер  ",
        "> **Издание**: 4-е (2013)  ",
        "> **Платформа**: .NET Framework 4.5, C#  ",
        "> **Глав**: 30 | **Частей**: 5",
        "",
        "---",
        "",
    ]

    prev_part = None
    for ch_num in sorted(CHAPTER_NAMES.keys()):
        part_num = CHAPTER_PART[ch_num]
        roman, part_name, _ = PARTS[part_num]

        if part_num != prev_part:
            if prev_part is not None:
                lines.append("")
            lines.append(f"## Часть {roman}. {part_name}")
            lines.append("")
            prev_part = part_num

        fname = chapter_filename(ch_num)
        lines.append(f"- [[{fname}|Глава {ch_num}. {CHAPTER_NAMES[ch_num]}]]")

    lines += [
        "",
        "---",
        "",
        "## Справочники",
        "",
        "- [[Глоссарий|🔤 Глоссарий (рус-англ)]]",
        "",
        "---",
        "",
        "## Введение",
        "",
        "- [[Посвящение]]",
        "- [[Предисловие]]",
        "- [[Введение]]",
        "- [[Благодарности]]",
        "- [[От издателя перевода]]",
        "",
    ]
    return '\n'.join(lines)


# ─── Part overview builder ────────────────────────────────────────────────────

def build_part_overview(part_num: int) -> str:
    roman, part_name, _ = PARTS[part_num]
    chapter_nums = [ch for ch, p in CHAPTER_PART.items() if p == part_num]

    lines = [
        "---",
        f'title: "Часть {roman}. {part_name}"',
        f"tags: [clr-via-csharp, часть/{roman}, dotnet]",
        f'created: "{TODAY}"',
        "---",
        "",
        f"# Часть {roman}. {part_name}",
        "",
        f"[[📚 CLR via C# — Карта знаний|← Карта знаний]]",
        "",
        "## Главы",
        "",
    ]
    for ch in chapter_nums:
        lines.append(f"- [[{chapter_filename(ch)}|Глава {ch}. {CHAPTER_NAMES[ch]}]]")

    lines.append("")
    return '\n'.join(lines)


# ─── .obsidian config ─────────────────────────────────────────────────────────

OBSIDIAN_APP_JSON = {
    "useMarkdownLinks": False,
    "newLinkFormat": "shortest",
    "attachmentFolderPath": "assets",
    "defaultViewMode": "preview",
}

OBSIDIAN_CORE_PLUGINS = [
    "file-explorer", "global-search", "switcher", "graph",
    "backlink", "outgoing-link", "tag-pane", "page-preview",
    "daily-notes", "templates", "command-palette", "outline",
    "word-count", "open-with-default-app",
]


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Reading source file...")
    content = INPUT_FILE.read_text(encoding="utf-8")

    # ── Setup output directory ────────────────────────────────────────────
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir()

    # ── Copy images → assets ──────────────────────────────────────────────
    print(f"Copying images to {ASSETS_DST}...")
    if ASSETS_SRC.exists():
        shutil.copytree(ASSETS_SRC, ASSETS_DST)
        print(f"  Copied {len(list(ASSETS_DST.iterdir()))} images.")
    else:
        ASSETS_DST.mkdir()
        print("  WARNING: images/ folder not found, assets/ will be empty.")

    # ── Create .obsidian config ───────────────────────────────────────────
    obsidian_dir = OUTPUT_DIR / ".obsidian"
    obsidian_dir.mkdir()
    (obsidian_dir / "app.json").write_text(
        json.dumps(OBSIDIAN_APP_JSON, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    (obsidian_dir / "core-plugins.json").write_text(
        json.dumps(OBSIDIAN_CORE_PLUGINS, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # ── Split content ─────────────────────────────────────────────────────
    print("Splitting content into chapters...")
    split = split_into_chapters(content)
    print(f"  Found {len(split['chapters'])} chapters.")

    # ── Write intro sections ──────────────────────────────────────────────
    intro_dir = OUTPUT_DIR / "00 - Введение"
    intro_dir.mkdir()
    intro_secs = split_intro(split['intro'])
    for sec_name, sec_lines in intro_secs.items():
        body = process_lines(sec_lines)
        fm = f"---\ntitle: \"{sec_name}\"\ntags: [clr-via-csharp, введение]\ncreated: \"{TODAY}\"\n---\n"
        file_path = intro_dir / f"{sec_name}.md"
        file_path.write_text(fm + "\n# " + sec_name + "\n\n" + body.strip(), encoding="utf-8")
        print(f"  Written: {file_path.name}")

    # ── Create part folders + overview files ──────────────────────────────
    part_dirs = {}
    for part_num, (roman, part_name, folder_name) in PARTS.items():
        d = OUTPUT_DIR / folder_name
        d.mkdir()
        part_dirs[part_num] = d
        overview = build_part_overview(part_num)
        (d / "_Обзор части.md").write_text(overview, encoding="utf-8")

    # ── Write chapter files ───────────────────────────────────────────────
    all_chapter_nums = sorted(split['chapters'].keys())
    for ch_num in all_chapter_nums:
        ch_lines = split['chapters'][ch_num]
        part_num = CHAPTER_PART.get(ch_num)
        if part_num is None:
            print(f"  WARNING: Chapter {ch_num} has no part mapping, skipping.")
            continue

        part_dir = part_dirs[part_num]
        fname = chapter_filename(ch_num) + ".md"

        # Build content
        fm = make_frontmatter(ch_num)
        nav_top, nav_bottom = make_nav(ch_num)
        title_line = f"# Глава {ch_num}. {CHAPTER_NAMES[ch_num]}"
        body = process_lines(ch_lines)

        full_content = "\n".join([
            fm,
            "",
            nav_top,
            "",
            "---",
            "",
            title_line,
            "",
            body.strip(),
            "",
            "---",
            "",
            nav_bottom,
        ])

        file_path = part_dir / fname
        file_path.write_text(full_content, encoding="utf-8")
        print(f"  Written: {fname}")

    # ── Glossary (last section of intro or standalone) ────────────────────
    # The glossary heading appears in the source as the last ## heading
    gloss_match = re.search(
        r'## \*\*словарь соответствия русскоязычных и англоязычных терминов\*\*(.+?)$',
        content,
        re.IGNORECASE | re.DOTALL
    )
    if gloss_match:
        gloss_body = process_lines(gloss_match.group(1).strip().split('\n'))
        gloss_fm = f"---\ntitle: \"Глоссарий\"\ntags: [clr-via-csharp, глоссарий]\ncreated: \"{TODAY}\"\n---\n"
        gloss_path = OUTPUT_DIR / "Глоссарий.md"
        gloss_path.write_text(
            gloss_fm + "\n# 🔤 Глоссарий (русско-английские термины)\n\n" + gloss_body.strip(),
            encoding="utf-8"
        )
        print(f"  Written: Глоссарий.md")

    # ── MOC ───────────────────────────────────────────────────────────────
    moc = build_moc()
    (OUTPUT_DIR / "📚 CLR via C# — Карта знаний.md").write_text(moc, encoding="utf-8")
    print("  Written: 📚 CLR via C# — Карта знаний.md")

    # ── Summary ───────────────────────────────────────────────────────────
    total_files = sum(1 for _ in OUTPUT_DIR.rglob("*.md"))
    total_images = len(list(ASSETS_DST.iterdir())) if ASSETS_DST.exists() else 0
    print("\n" + "─" * 50)
    print(f"✅ Done!")
    print(f"   Vault:   {OUTPUT_DIR.resolve()}")
    print(f"   Files:   {total_files} markdown files")
    print(f"   Images:  {total_images} assets")
    print("─" * 50)


if __name__ == "__main__":
    main()
