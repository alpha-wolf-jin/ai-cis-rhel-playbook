#!/usr/bin/env python3
"""
Parse the CIS RHEL 9 Benchmark text file into structured JSON data.

Each checkpoint is extracted with its sections:
  - name, profile_applicability, description, rationale, impact,
    audit, remediation, default_value, additional_information, references

Bash scripts and commands are preserved exactly as they appear in the text.
"""

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_INPUT = "resources/CIS_Red_Hat_Enterprise_Linux_9_Benchmark_v2.0.0.txt"
DEFAULT_OUTPUT = "resources/CIS_Red_Hat_Enterprise_Linux_9_Benchmark_v2.0.0.json"

# Regex to match checkpoint title lines
# e.g. "1.1.2.1.2 Ensure nodev option set on /tmp partition (Automated)"
CHECKPOINT_RE = re.compile(
    r'^(\d+(?:\.\d+){2,})\s+(.*?\s*\((Manual|Automated)\))\s*$'
)

# Known section headers in order of typical appearance
SECTION_HEADERS = [
    "Profile Applicability:",
    "Description:",
    "Rationale:",
    "Impact:",
    "Audit:",
    "Remediation:",
    "Default Value:",
    "Additional Information:",
    "References:",
    "CIS Controls:",
]

# Map header text to JSON key
HEADER_TO_KEY = {
    "Profile Applicability:": "profile_applicability",
    "Description:": "description",
    "Rationale:": "rationale",
    "Impact:": "impact",
    "Audit:": "audit",
    "Remediation:": "remediation",
    "Default Value:": "default_value",
    "Additional Information:": "additional_information",
    "References:": "references",
    "CIS Controls:": "cis_controls",
}


def find_checkpoints(lines):
    """Find all checkpoint title lines and their line numbers."""
    checkpoints = []
    for i, line in enumerate(lines):
        m = CHECKPOINT_RE.match(line.rstrip())
        if m:
            cp_id = m.group(1)
            cp_title = m.group(2).strip()
            checkpoints.append({
                "line": i,
                "id": cp_id,
                "title": cp_title,
                "name": f"{cp_id} {cp_title}",
            })
    return checkpoints


def is_toc_line(line):
    """Check if a line is a Table of Contents entry (has dots and page number)."""
    return bool(re.search(r'\.{4,}\s*\d+\s*$', line))


def parse_checkpoint(lines, start, end):
    """
    Parse a single checkpoint block (lines[start:end]) into sections.

    Returns a dict with section keys and their text content.
    Bash scripts and commands are preserved exactly as they appear.
    """
    sections = {}
    current_section = None
    current_lines = []

    # First line is the title — skip it
    for i in range(start + 1, end):
        line = lines[i]
        stripped = line.rstrip()

        # Check if this line starts a new section
        matched_header = None
        for header in SECTION_HEADERS:
            if stripped.startswith(header):
                matched_header = header
                break

        if matched_header:
            # Save previous section
            if current_section is not None:
                key = HEADER_TO_KEY[current_section]
                sections[key] = _join_section(current_lines)

            current_section = matched_header
            # Some headers have inline content (e.g., "Impact: Mandatory...")
            remainder = stripped[len(matched_header):].strip()
            current_lines = [remainder] if remainder else []
        else:
            if current_section is not None:
                current_lines.append(line.rstrip())

    # Save last section
    if current_section is not None:
        key = HEADER_TO_KEY[current_section]
        sections[key] = _join_section(current_lines)

    return sections


def _join_section(lines):
    """
    Join section lines into a single string.
    Preserves the exact content including indentation and blank lines.
    Strips leading/trailing blank lines only.
    """
    # Strip leading blank lines
    while lines and not lines[0].strip():
        lines = lines[1:]
    # Strip trailing blank lines
    while lines and not lines[-1].strip():
        lines = lines[:-1]

    return '\n'.join(lines)


def filter_toc_checkpoints(checkpoints, lines):
    """Filter out checkpoint entries that are in the Table of Contents."""
    filtered = []
    for cp in checkpoints:
        line_text = lines[cp["line"]].rstrip()
        if is_toc_line(line_text):
            continue
        # Also skip if "Profile Applicability:" doesn't follow within 3 lines
        has_profile = False
        for offset in range(1, 4):
            idx = cp["line"] + offset
            if idx < len(lines) and lines[idx].strip().startswith("Profile Applicability:"):
                has_profile = True
                break
        if has_profile:
            filtered.append(cp)
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description='Parse CIS RHEL 9 Benchmark text into structured JSON.'
    )
    parser.add_argument(
        '--input', '-i',
        type=str,
        default=DEFAULT_INPUT,
        help=f'Input text file path (default: {DEFAULT_INPUT})'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=DEFAULT_OUTPUT,
        help=f'Output JSON file path (default: {DEFAULT_OUTPUT})'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print detailed progress'
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}")
        sys.exit(1)

    print(f"📄 Reading: {input_path}")
    text = input_path.read_text(encoding='utf-8')
    lines = text.split('\n')
    print(f"   {len(lines)} lines")

    # Find all checkpoint titles
    all_checkpoints = find_checkpoints(lines)
    print(f"   Found {len(all_checkpoints)} checkpoint title lines (including TOC)")

    # Filter out TOC entries
    checkpoints = filter_toc_checkpoints(all_checkpoints, lines)
    print(f"   {len(checkpoints)} actual checkpoint sections")

    # Parse each checkpoint
    results = []
    for idx, cp in enumerate(checkpoints):
        start = cp["line"]
        # End is the start of the next checkpoint, or end of file
        end = checkpoints[idx + 1]["line"] if idx + 1 < len(checkpoints) else len(lines)

        sections = parse_checkpoint(lines, start, end)

        entry = {
            "name": cp["name"],
            "id": cp["id"],
        }

        # Add requested fields (preserve exact content)
        for field in ["description", "rationale", "audit", "remediation", "references"]:
            if field in sections:
                entry[field] = sections[field]
            else:
                entry[field] = ""

        # Add optional fields if present
        for field in ["profile_applicability", "impact", "default_value",
                       "additional_information", "cis_controls"]:
            if field in sections and sections[field]:
                entry[field] = sections[field]

        results.append(entry)

        if args.verbose:
            print(f"   ✅ {cp['name']}")

    # Save to JSON
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    file_size = output_path.stat().st_size
    print(f"✅ Saved {len(results)} checkpoints to: {output_path} ({file_size:,} bytes)")

    # Summary
    fields_present = {
        "description": sum(1 for r in results if r.get("description")),
        "rationale": sum(1 for r in results if r.get("rationale")),
        "audit": sum(1 for r in results if r.get("audit")),
        "remediation": sum(1 for r in results if r.get("remediation")),
        "references": sum(1 for r in results if r.get("references")),
        "impact": sum(1 for r in results if r.get("impact")),
        "default_value": sum(1 for r in results if r.get("default_value")),
        "additional_information": sum(1 for r in results if r.get("additional_information")),
    }
    print("\n📊 Field coverage:")
    for field, count in fields_present.items():
        print(f"   {field}: {count}/{len(results)}")


if __name__ == "__main__":
    main()

