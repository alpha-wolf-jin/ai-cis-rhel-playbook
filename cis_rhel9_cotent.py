#!/usr/bin/env python3
"""
CIS RHEL 9 Benchmark PDF to Text Extractor

This script reads the CIS RHEL 9 Benchmark PDF, repairs lines broken by PDF
column-width extraction, and saves the cleaned content to a text file.

Usage:
    python3 cis_rhel9_cotent.py
    python3 cis_rhel9_cotent.py --output custom_output.txt
    python3 cis_rhel9_cotent.py --verbose
    python3 cis_rhel9_cotent.py --no-repair   # skip line repair
"""

import re
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader

load_dotenv()

# Configuration
#PDF_PATH = "resources/CIS_Red_Hat_Enterprise_Linux_9_Benchmark_v2.0.0.pdf"
#DEFAULT_OUTPUT = "resources/CIS_Red_Hat_Enterprise_Linux_9_Benchmark_v2.0.0.txt"

PDF_PATH = "resources/CIS_Red_Hat_Enterprise_Linux_8_Benchmark_v4.0.0.pdf"
DEFAULT_OUTPUT = "resources/CIS_Red_Hat_Enterprise_Linux_8_Benchmark_v4.0.0.txt"


def _count_unbalanced_double_quotes(text):
    """
    Count unescaped double-quotes that are NOT inside single-quoted regions.

    In bash, single quotes suppress all interpretation, so a `"` between
    `'...'` is literal and should not count toward double-quote balance.
    Example:  sed -e 's/"//g'  — the `"` here is inside single quotes.

    Args:
        text: A single line of text.

    Returns:
        Number of "open" double quotes (odd = unbalanced).
    """
    in_single_quote = False
    count = 0
    prev_char = ''
    for ch in text:
        if ch == "'" and not in_single_quote:
            in_single_quote = True
        elif ch == "'" and in_single_quote:
            in_single_quote = False
        elif ch == '"' and not in_single_quote and prev_char != '\\':
            count += 1
        prev_char = ch
    return count


def _is_broken_continuation(current_stripped, next_line, in_block=False):
    """
    Determine if next_line is a PDF-broken continuation of the current line.

    PDF extraction breaks long lines at the page column boundary.  This function
    detects the most common break patterns in bash/command blocks and prose so
    that they can be rejoined into single logical lines.

    Args:
        current_stripped: Current line with trailing whitespace removed.
        next_line:        The raw next line (preserving leading whitespace).
        in_block:         True if we are inside a { ... } code block.

    Returns:
        True if the two lines should be joined.
    """
    next_stripped = next_line.strip()

    # ── Never join across structural boundaries ────────────────────────────
    if not next_stripped:
        return False
    if next_stripped.startswith('=' * 5):          # page separator
        return False
    if re.match(r'^Page \d+\s*$', next_stripped):  # page header
        return False

    # Never merge into a line that starts with a section / checkpoint number
    # (e.g. "2.2.1 Ensure …", "4.3 Configure …").  These are structural
    # headings in the CIS document and are never continuation fragments.
    if re.match(r'^\d+\.\d+', next_stripped):
        return False

    # ── BASH / COMMAND RULES ──────────────────────────────────────────────

    # Helper: "is the current line code?"
    #   Outside { } blocks we require 3+ leading spaces (conservative).
    #   Inside  { } blocks even 1 leading space counts as indented code.
    _is_code = (current_stripped.startswith('   ')
                or (in_block and current_stripped and current_stripped[0] == ' '))

    # 1. Here-string operator (<<<) must have its argument on the same line
    if current_stripped.endswith('<<<'):
        return True

    # 2. Unclosed command substitution  $(
    if current_stripped.endswith('$('):
        return True

    # 3. Logical operators broken at end of line
    if current_stripped.endswith('||') or current_stripped.endswith('&&'):
        return True

    # 4. Single pipe broken at end of a code line (not ||)
    if (current_stripped.endswith('|')
            and not current_stripped.endswith('||')
            and _is_code):
        return True

    # 5. Redirect broken at end of line  (>> /path  or  > /path)
    if re.search(r'>>\s*$', current_stripped) and next_stripped.startswith('/'):
        return True

    # 6. Broken bash parameter expansion: ${var//-\n/_}
    #    e.g.  ${l_mod_name//-        (line break)
    #          /_}'...
    if current_stripped.endswith('-') and next_stripped.startswith('/_'):
        return True

    # 7. Code line ends with `--` (option terminator) — the next arg
    #    (pattern/path) was broken to the next line.
    #    e.g.  grep -P --
    #          '\b(install|blacklist)...'
    if (current_stripped.endswith('--')
            and _is_code
            and next_stripped
            and next_stripped[0] in "'\"/\\$"):
        return True

    # 8a. Unbalanced (odd) double-quotes in a code line indicates the
    #    string was split across the line break.
    #    IMPORTANT: Only merge when the NEXT line is at column-0.
    #    Inside a { ... } block every real code statement is indented;
    #    a col-0 continuation is the PDF break artifact.
    if (_is_code
            and next_line and next_line[0] != ' '):   # next is col-0
        unescaped_dq = _count_unbalanced_double_quotes(current_stripped)
        if unescaped_dq % 2 == 1:
            return True

    # 8b. Code line followed by a column-0 (no indentation) line.
    #    If a line is in code context and the very next line suddenly
    #    starts at column 0, it is almost always a PDF column-width break.
    #    Real code statements would be indented; new prose sections start
    #    with structural markers.
    #    Exceptions (do NOT join):
    #      - `}` alone on a line  → closing brace of a bash function
    #      - empty / whitespace-only lines
    #      - page separators / headers
    if (_is_code
            and next_line
            and next_line[0] != ' '           # column-0
            and not re.match(r'^}\s*$', next_stripped)  # not a closing brace
            and not next_stripped.startswith('=====')  # page separator
            and not re.match(r'^Page \d+', next_stripped)):
        return True

    # ── CHECKPOINT TITLE RULES ─────────────────────────────────────────

    # 11. Checkpoint title split across two lines.
    #    First line starts with a checkpoint ID (e.g. "1.6.3 Ensure ...")
    #    but does NOT end with (Manual) or (Automated).
    #    Next line contains (Manual) or (Automated).
    if (re.match(r'^\d+\.\d+', current_stripped)
            and not re.search(r'\(Manual\)|\(Automated\)', current_stripped)
            and re.search(r'\(Manual\)|\(Automated\)', next_stripped)):
        return True

    # ── PROSE / DESCRIPTION RULES ─────────────────────────────────────────

    # 9. Line ends with a preposition/article and next line starts with a
    #    path, quoted text, or variable — strong signal of a broken sentence.
    if re.search(
        r'\b(the|in|a|an|to|of|for|with|from|by|or|and|into|onto)\s*$',
        current_stripped, re.IGNORECASE
    ):
        if next_stripped and next_stripped[0] in '"\'/\\$':
            return True
        # Also join when the next word is lowercase (continuation of prose)
        if next_stripped and next_stripped[0].islower():
            return True

    # 10. Non-code, non-bullet line that doesn't end with sentence-ending
    #    punctuation, and next line starts with a lowercase word.
    #    Only apply when current line is "long enough" to have been broken
    #    at a column boundary (> 60 chars).
    if (not current_stripped.startswith('   ')                       # not code
            and len(current_stripped) > 60                           # long line
            and not re.search(r'[.:;!?}\])\'"]\s*$', current_stripped)  # no terminator
            and next_stripped and next_stripped[0].islower()
            and not next_stripped.startswith(('- ', '• '))):
        return True

    return False


def repair_broken_lines(text):
    """
    Repair lines that were artificially broken by PDF column-width extraction.

    Strategy (traditional / heuristic):
      - For bash/command lines:  detect operators (<<<, $(, ||, &&, |, >>),
        unbalanced double-quotes, and broken parameter expansions.
      - For prose:  detect lines ending with prepositions/articles whose
        continuation starts with lowercase or a path.

    The function iterates through all lines and greedily joins any line whose
    successor matches a continuation pattern.

    Args:
        text: The raw extracted text (full document or single page).

    Returns:
        The text with broken lines rejoined.
    """
    lines = text.split('\n')
    result = []
    i = 0
    block_depth = 0          # Track { ... } code block nesting

    while i < len(lines):
        current = lines[i]

        # Track { ... } block boundaries (bare braces on their own line)
        cur_stripped = current.strip()
        if re.match(r'^{\s*$', cur_stripped):
            block_depth += 1
        elif re.match(r'^}\s*$', cur_stripped):
            block_depth = max(0, block_depth - 1)

        in_block = block_depth > 0

        # Greedily merge continuation lines
        while i + 1 < len(lines):
            stripped = current.rstrip()
            if _is_broken_continuation(stripped, lines[i + 1], in_block):
                i += 1
                # Join: stripped current + single space + left-stripped next
                current = stripped + ' ' + lines[i].lstrip()
            else:
                break

        result.append(current)
        i += 1

    return '\n'.join(result)


def main():
    parser = argparse.ArgumentParser(
        description='Extract text from CIS RHEL 9 Benchmark PDF and save to a text file.'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=DEFAULT_OUTPUT,
        help=f'Output text file path (default: {DEFAULT_OUTPUT})'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print progress and page details'
    )
    parser.add_argument(
        '--no-repair',
        action='store_true',
        help='Skip broken-line repair (output raw PDF text)'
    )
    args = parser.parse_args()

    pdf_path = Path(PDF_PATH)
    output_path = Path(args.output)

    if not pdf_path.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        sys.exit(1)

    print(f"📄 Reading PDF: {pdf_path}")
    loader = PyPDFLoader(str(pdf_path))
    pages = loader.load()
    print(f"   Loaded {len(pages)} pages")

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect all pages into one text, stripping page number lines
    all_parts = []
    for i, page in enumerate(pages):
        content = page.page_content

        # Strip "Page NNN" lines and any surrounding blank lines
        content = re.sub(r'\n*^Page\s+\d+\s*$\n*', '\n', content, flags=re.MULTILINE)
        content = content.strip('\n')

        if content:
            all_parts.append(content)

    full_text = '\n'.join(all_parts)
    print(f"   Joined {len(all_parts)} pages")

    # Run line repair on the entire document so cross-page breaks are caught
    lines_repaired = 0
    if not args.no_repair:
        original_line_count = full_text.count('\n')
        full_text = repair_broken_lines(full_text)
        lines_repaired = original_line_count - full_text.count('\n')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_text)
        f.write("\n")

    file_size = output_path.stat().st_size
    print(f"✅ Saved to: {output_path} ({file_size:,} bytes, {len(pages)} pages)")
    if not args.no_repair:
        print(f"🔧 Repaired {lines_repaired} broken line(s)")


if __name__ == "__main__":
    main()
