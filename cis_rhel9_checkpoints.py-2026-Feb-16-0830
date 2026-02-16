#!/usr/bin/env python3
"""
Extract all checkpoint names from the CIS RHEL 9 Benchmark JSON file.

Usage:
    python3 cis_rhel9_checkpoints.py
    python3 cis_rhel9_checkpoints.py -o checkpoints.txt
    python3 cis_rhel9_checkpoints.py --id-only
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_INPUT = "resources/CIS_Red_Hat_Enterprise_Linux_9_Benchmark_v2.0.0.json"


def main():
    parser = argparse.ArgumentParser(
        description='Extract checkpoint names from CIS RHEL 9 Benchmark JSON.'
    )
    parser.add_argument(
        '--input', '-i',
        type=str,
        default=DEFAULT_INPUT,
        help=f'Input JSON file path (default: {DEFAULT_INPUT})'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output file path (default: print to stdout)'
    )
    parser.add_argument(
        '--id-only',
        action='store_true',
        help='Print only checkpoint IDs (e.g. 1.1.1.1)'
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding='utf-8'))

    lines = []
    for cp in data:
        if args.id_only:
            lines.append(cp['id'])
        else:
            lines.append(cp['name'])

    output = '\n'.join(lines) + '\n'

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding='utf-8')
        print(f"✅ Saved {len(lines)} checkpoints to: {output_path}")
    else:
        sys.stdout.write(output)
        print(f"\nTotal: {len(lines)} checkpoints", file=sys.stderr)


if __name__ == "__main__":
    main()

