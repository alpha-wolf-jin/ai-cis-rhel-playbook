#!/usr/bin/env python3
"""
CIS Checkpoint Index Extractor

This script extracts all CIS RHEL 8 checkpoint indices from the benchmark document
using RAG (Retrieval-Augmented Generation) with an agent-based approach.

Usage:
    python3 get_checkpoint_indexs.py
    python3 get_checkpoint_indexs.py --output checkpoints.txt
    python3 get_checkpoint_indexs.py --verbose
"""

import os
import sys
import re
import argparse
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader

load_dotenv()


# Configuration - Use same directory as cis_checkpoint_to_playbook.py
PDF_PATH = "resources/CIS_Red_Hat_Enterprise_Linux_9_Benchmark_v2.0.0.pdf"

loader = PyPDFLoader(PDF_PATH)
data = loader.load()

# \s*[\s.]+\s* matches any combination of dots and spaces
# \d+$ matches the page number at the end
star_pattern = r"^Recommendations[\s.]+\d+$"
end_pattern = r"^Appendix:\sSummary\sTable[\s.]+\d+$"

# Line Type Patterns
section_start_regex = r"^\d+(\.\d+)+"  # Matches "6.3.3.19"
status_tags_regex = r"\(Automated\)|\(Manual\)"
# Pattern to strip dots and numbers (looks for 2+ dots and everything following)
strip_dots_pattern = r"\s*\.{2,}.*$"

found_start = False
buffer = ""
extracted_items = []

# Assuming data is your list of Document objects
for doc in data:
    lines = doc.page_content.splitlines()
    
    for line in lines:
        clean_line = line.strip()

        # Skip empty lines
        if not clean_line:
            continue

        # 1. Check for the Start (Recommendations)
        # Use re.IGNORECASE just in case
        if re.search(star_pattern, clean_line, re.IGNORECASE):
            found_start = True
            continue

        if re.search(end_pattern, clean_line, re.IGNORECASE):
            found_start = False
            break

        # 2. If we are in the section, print everything
        if found_start:
            # Skip noise
            if re.match(r"Page\s\d+", clean_line) or "Internal Only" in clean_line:
                continue

            clean_line = re.sub(strip_dots_pattern, "", clean_line)
            clean_line = clean_line.strip()
            # 2. Logic to handle wrapped lines
            # If the line starts with a digit (section number), start a new buffer
            if "(Automated)" in clean_line or "(Manual)" in clean_line:
                if re.match(section_start_regex, clean_line):
                    final_text = clean_line
                else:
                    final_text = buffer + " " + clean_line
                print(final_text.strip())
                extracted_items.append(final_text.strip())
            else:
                if re.match(section_start_regex, clean_line):
                    buffer = clean_line

                # If it doesn't start with a number, it's a continuation of the previous line
