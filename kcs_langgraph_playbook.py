#!/usr/bin/env python3
"""
Integrated KCS to Ansible Playbook Generator (LangGraph Version)

This script integrates KCS search and playbook generation into a single
LangGraph workflow with the following nodes:
1. Search KCS URLs
2. Generate matching requirements (to measure if target matches KCS environment/issue)
3. Generate data collection requirements (for playbook to collect data)
4. Generate playbook
5. Save, syntax check, test, analyze, execute

Usage:
    python3 kcs_langgraph_playbook.py --search "kernel panic" --target-host 192.168.122.16
"""

import os
import sys
import json
import argparse
import webbrowser
import shutil
import re
from typing import TypedDict, Literal
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

# Import functions from kcsv2.py
from kcsv2 import (
    get_red_hat_access_token,
    search_v2_kcs,
    strip_html
)

# Import functions from deepseek_generate_playbook.py
# We'll import these after setting up PATH
from deepseek_generate_playbook import (
    generate_playbook as _original_generate_playbook,
    save_playbook,
    analyze_playbook_output,
    check_data_sufficiency,
    analyze_compliance_from_report,
    extract_data_collection_report,
)

# Load environment variables
load_dotenv()


def ensure_venv_in_path():
    """
    Ensure virtual environment's bin directory is in PATH.
    This helps subprocess calls find ansible-navigator and other tools.
    """
    # Get the directory containing the Python executable (usually venv/bin)
    python_dir = os.path.dirname(sys.executable)
    
    # If we're in a virtual environment, add it to PATH
    if 'venv' in python_dir or '.venv' in python_dir or 'VIRTUAL_ENV' in os.environ:
        if python_dir not in os.environ.get('PATH', '').split(os.pathsep):
            os.environ['PATH'] = python_dir + os.pathsep + os.environ.get('PATH', '')
            print(f"✅ Added {python_dir} to PATH")
    
    # Also check for .venv/bin in the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_bin = os.path.join(script_dir, '.venv', 'bin')
    if os.path.exists(venv_bin) and venv_bin not in os.environ.get('PATH', '').split(os.pathsep):
        os.environ['PATH'] = venv_bin + os.pathsep + os.environ.get('PATH', '')
        print(f"✅ Added {venv_bin} to PATH")
    
    # Verify ansible-navigator is now findable
    navigator_path = shutil.which('ansible-navigator')
    if navigator_path:
        print(f"✅ Found ansible-navigator at: {navigator_path}")
    else:
        print("⚠️  Warning: ansible-navigator not found in PATH")
        print("   Make sure ansible-navigator is installed in your virtual environment")


# Ensure virtual environment is in PATH before importing functions that use subprocess
ensure_venv_in_path()


def update_playbook_requirement_index(playbook_content: str, old_idx: int, new_idx: int, 
                                       old_total: int = None, new_total: int = None) -> str:
    """
    Update a playbook's requirement index references when reusing/copying.
    
    Changes all references like req_13, data_13, task_13_*, result_13
    to use the new index (e.g., req_12, data_12, etc.)
    
    Also updates:
    - Report task names: "Part 13/23" -> "Part 12/16" (both part and total)
    - Requirement labels: "REQUIREMENT 13" -> "REQUIREMENT 12"
    
    Args:
        playbook_content: The playbook YAML content
        old_idx: The original requirement index (e.g., 13)
        new_idx: The new requirement index (e.g., 12)
        old_total: The original total number of requirements (optional)
        new_total: The new total number of requirements (optional)
        
    Returns:
        Updated playbook content with new indices
    """
    import re
    
    updated = playbook_content
    
    # Format indices with zero-padding (2 digits)
    old_str_02d = f"{old_idx:02d}"
    new_str_02d = f"{new_idx:02d}"
    old_str = str(old_idx)
    new_str = str(new_idx)
    
    # Update the total count first (if provided)
    # This handles patterns like "Part 10/12" -> "Part 10/16"
    if old_total is not None and new_total is not None and old_total != new_total:
        # Update total in "Part X/Y" patterns - match any part number followed by /old_total
        # Pattern: Part <any number>/<old_total>
        updated = re.sub(
            rf'(Part\s+\d+)/(\d+)',
            lambda m: f"{m.group(1)}/{new_total}",
            updated
        )
        # Also update "X/Y" in task names and report titles where Y is the total
        # Handle both zero-padded and non-padded totals
        old_total_str = str(old_total)
        old_total_02d = f"{old_total:02d}"
        new_total_str = str(new_total)
        
        # Update END OF DATA COLLECTION REPORT patterns too
        updated = re.sub(
            rf'(\(\s*Part\s+\d+)/(\d+)(\s*\))',
            lambda m: f"{m.group(1)}/{new_total}{m.group(3)}",
            updated
        )
    
    # If indices are the same, only total needed updating
    if old_idx == new_idx:
        return updated
    
    # Use regex for precise replacements with word boundaries
    # Pattern pairs: (regex_pattern, replacement)
    regex_patterns = [
        # Variable names with underscore (req_13, data_13, etc.) - use word boundary after number
        (rf'\breq_{old_str_02d}\b', f'req_{new_str_02d}'),
        (rf'\bdata_{old_str_02d}\b', f'data_{new_str_02d}'),
        (rf'\btask_{old_str_02d}_', f'task_{new_str_02d}_'),
        (rf'\bresult_{old_str_02d}\b', f'result_{new_str_02d}'),
        
        # Also handle non-zero-padded variable names (for old playbooks)
        (rf'\breq_{old_str}\b', f'req_{new_str_02d}'),
        (rf'\bdata_{old_str}\b', f'data_{new_str_02d}'),
        (rf'\btask_{old_str}_', f'task_{new_str_02d}_'),
        (rf'\bresult_{old_str}\b', f'result_{new_str_02d}'),
        
        # Report text patterns
        (rf'Req {old_str_02d}\b', f'Req {new_str_02d}'),
        (rf'Req {old_str}\b', f'Req {new_str_02d}'),
        (rf'REQUIREMENT {old_str_02d}\b', f'REQUIREMENT {new_str_02d}'),
        (rf'REQUIREMENT {old_str}\b', f'REQUIREMENT {new_str_02d}'),
        (rf'Requirement {old_str_02d}\b', f'Requirement {new_str_02d}'),
        (rf'Requirement {old_str}\b', f'Requirement {new_str_02d}'),
        
        # Task names with "requirement N" (lowercase)
        (rf'requirement {old_str_02d}\b', f'requirement {new_str_02d}'),
        (rf'requirement {old_str}\b', f'requirement {new_str_02d}'),
        
        # Part number in report titles (Part 13/23) - update the first number
        (rf'Part {old_str_02d}/', f'Part {new_str_02d}/'),
        (rf'Part {old_str}/', f'Part {new_str_02d}/'),
        
        # Playbook filename references
        (rf'part{old_str_02d}\.yml', f'part{new_str_02d}.yml'),
        (rf'part{old_str}\.yml', f'part{new_str_02d}.yml'),
    ]
    
    for pattern, replacement in regex_patterns:
        updated = re.sub(pattern, replacement, updated)
    
    return updated


def get_playbook_path(kcs_id: str, part_num: int = 1, base_dir: str = "./playbooks/verification") -> str:
    """
    Generate the playbook file path based on KCS ID and part number.
    
    Args:
        kcs_id: The KCS article ID (e.g., "12345" or "kcs12345")
        part_num: The part number for multi-part playbooks (default 1)
        base_dir: The base directory for playbooks
        
    Returns:
        Full path like: ./playbooks/verification/12345/kcs_verification_12345_part01.yml
    """
    # Clean up KCS ID (remove any "kcs" prefix if present)
    clean_id = kcs_id.lower().replace('kcs', '').strip()
    
    # Create directory structure
    playbook_dir = os.path.join(base_dir, clean_id)
    os.makedirs(playbook_dir, exist_ok=True)
    
    # Generate filename with zero-padded 2-digit part number
    filename = f"kcs_verification_{clean_id}_part{part_num:02d}.yml"
    
    return os.path.join(playbook_dir, filename)


def get_kcs_id_from_state(state: dict) -> str:
    """Extract KCS ID from state, with fallback to 'unknown'."""
    kcs_article = state.get('kcs_article', {})
    if kcs_article:
        doc_id = kcs_article.get('doc_id', '')
        if doc_id:
            return doc_id
    return 'unknown'


def get_requirements_dir(kcs_id: str, base_dir: str = "./playbooks/verification") -> str:
    """
    Get the directory path for saving requirements files.
    
    Args:
        kcs_id: The KCS article ID
        base_dir: The base directory for playbooks
        
    Returns:
        Directory path like: ./playbooks/verification/12345/
    """
    clean_id = kcs_id.lower().replace('kcs', '').strip()
    requirements_dir = os.path.join(base_dir, clean_id)
    os.makedirs(requirements_dir, exist_ok=True)
    return requirements_dir


def save_requirements_to_file(kcs_id: str, requirements: list[str], filename: str, title: str = None) -> str:
    """
    Save requirements list to a file in the playbook directory.
    
    Args:
        kcs_id: The KCS article ID
        requirements: List of requirement strings (already indexed)
        filename: The filename (e.g., 'matching_requirements.txt')
        title: Optional title for the file header
        
    Returns:
        Full path to the saved file
    """
    requirements_dir = get_requirements_dir(kcs_id)
    filepath = os.path.join(requirements_dir, filename)
    
    with open(filepath, 'w') as f:
        if title:
            f.write(f"{'=' * 80}\n")
            f.write(f"{title}\n")
            f.write(f"{'=' * 80}\n\n")
        
        # Requirements already have indexes, just write them
        for req in requirements:
            f.write(f"{req}\n\n")
    
    return filepath


def check_existing_docs(kcs_id: str, base_dir: str = "./playbooks/verification") -> dict:
    """
    Check if existing docs exist for a KCS article.
    
    Args:
        kcs_id: The KCS article ID
        base_dir: The base directory for playbooks
        
    Returns:
        dict with keys:
            - exists: bool - True if directory and requirements files exist
            - directory: str - Path to the directory
            - matching_requirements_file: str or None - Path to matching requirements file
            - data_collection_requirements_file: str or None - Path to data collection requirements file
            - playbooks: list[str] - List of existing playbook files
    """
    clean_id = kcs_id.lower().replace('kcs', '').strip()
    doc_dir = os.path.join(base_dir, clean_id)
    
    result = {
        'exists': False,
        'directory': doc_dir,
        'matching_requirements_file': None,
        'data_collection_requirements_file': None,
        'playbooks': []
    }
    
    if not os.path.isdir(doc_dir):
        return result
    
    # Check for requirements files
    matching_file = os.path.join(doc_dir, 'matching_requirements.txt')
    data_collection_file = os.path.join(doc_dir, 'data_collection_requirements.txt')
    
    if os.path.isfile(matching_file):
        result['matching_requirements_file'] = matching_file
    
    if os.path.isfile(data_collection_file):
        result['data_collection_requirements_file'] = data_collection_file
    
    # Find existing playbooks
    for filename in os.listdir(doc_dir):
        if filename.endswith('.yml') and filename.startswith('kcs_verification_'):
            result['playbooks'].append(os.path.join(doc_dir, filename))
    
    # Sort playbooks by part number
    result['playbooks'].sort()
    
    # Directory exists if we have at least one requirements file
    result['exists'] = result['matching_requirements_file'] is not None or result['data_collection_requirements_file'] is not None
    
    return result


def read_requirements_from_file(filepath: str) -> list[str]:
    """
    Read requirements from a file.
    
    Args:
        filepath: Path to the requirements file
        
    Returns:
        List of requirement strings (with index numbers)
    """
    if not filepath or not os.path.isfile(filepath):
        return []
    
    requirements = []
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Skip header (everything before the first numbered requirement)
    lines = content.split('\n')
    in_requirements = False
    current_req = []
    
    for line in lines:
        stripped = line.strip()
        
        # Check if this is a numbered requirement start (e.g., "1. ", "2. ", etc.)
        if stripped and len(stripped) > 2 and stripped[0].isdigit():
            # Check for common index patterns: "1. ", "1: ", "1) "
            if len(stripped) > 1 and stripped[1] in '.:)' or (len(stripped) > 2 and stripped[1].isdigit() and stripped[2] in '.:)'):
                # Save previous requirement if exists
                if current_req:
                    requirements.append(' '.join(current_req).strip())
                current_req = [stripped]
                in_requirements = True
                continue
        
        # If we're in requirements and this is a continuation or empty line
        if in_requirements:
            if stripped:
                # Continuation of current requirement
                current_req.append(stripped)
            elif current_req:
                # Empty line - save current requirement
                requirements.append(' '.join(current_req).strip())
                current_req = []
    
    # Don't forget the last requirement
    if current_req:
        requirements.append(' '.join(current_req).strip())
    
    return requirements


def extract_requirement_text(req: str) -> str:
    """
    Extract the text part of a requirement, removing the index number.
    
    Args:
        req: Requirement string like "1. Collect OS version"
        
    Returns:
        Text without index: "Collect OS version"
    """
    import re
    # Remove leading index patterns: "1. ", "1: ", "1) ", "12. ", etc.
    return re.sub(r'^\d+[\.:)\s]+\s*', '', req.strip())


def normalize_requirement_text(text: str) -> str:
    """
    Normalize requirement text for comparison (lowercase, remove extra spaces, etc.)
    """
    import re
    # Remove index prefix
    text = extract_requirement_text(text)
    # Lowercase and normalize whitespace
    text = ' '.join(text.lower().split())
    # Remove common filler words for better matching
    filler_words = {'the', 'a', 'an', 'and', 'or', 'to', 'for', 'of', 'in', 'on', 'is', 'are', 'if', 'about'}
    words = [w for w in text.split() if w not in filler_words]
    return ' '.join(words)


def get_requirement_keywords(text: str) -> set:
    """
    Extract key words from a requirement for similarity comparison.
    """
    normalized = normalize_requirement_text(text)
    # Remove common action verbs to focus on the subject
    action_verbs = {'collect', 'gather', 'retrieve', 'get', 'check', 'verify', 'measure', 'determine', 'find', 'show', 'list', 'display'}
    words = normalized.split()
    # Keep non-action-verb words, or keep all if only action verbs
    keywords = {w for w in words if w not in action_verbs}
    if not keywords:
        keywords = set(words)
    return keywords


def normalize_word(word: str) -> str:
    """
    Normalize a word by removing common suffixes for better matching.
    """
    # Common abbreviation expansions
    abbrevs = {
        'info': 'information',
        'ver': 'version',
        'vers': 'version',
        'cfg': 'configuration',
        'conf': 'configuration',
        'config': 'configuration',
        'pkg': 'package',
        'pkgs': 'packages',
        'svc': 'service',
        'svcs': 'services',
        'sys': 'system',
        'distro': 'distribution',
        'env': 'environment',
        'var': 'variable',
        'vars': 'variables',
        'lib': 'library',
        'libs': 'libraries',
        'dev': 'development',
        'devel': 'development',
        'rpm': 'package',
        'rpms': 'packages',
    }
    
    word = word.lower()
    if word in abbrevs:
        return abbrevs[word]
    
    # Remove common suffixes for stemming
    suffixes = ['ation', 'tion', 'ing', 'ed', 's', 'es']
    for suffix in suffixes:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[:-len(suffix)]
    
    return word


def extract_key_concepts(text: str) -> set:
    """
    Extract key concepts/phrases from requirement text for better duplicate detection.
    
    This catches compound terms and special patterns that keyword extraction might miss.
    
    Args:
        text: Requirement text
        
    Returns:
        Set of normalized key concepts
    """
    text = text.lower()
    concepts = set()
    
    # Compound terms that should be treated as single concepts
    compound_patterns = [
        # PKG_CONFIG patterns
        (r'pkg[_\-]?config[_\-]?path', 'pkgconfig_path'),
        (r'pkg[_\-]?config\s+search\s+path', 'pkgconfig_path'),
        (r'pkgconfig\s+path', 'pkgconfig_path'),
        
        # OS version patterns
        (r'os\s+(distribution|distro|version|release)', 'os_version'),
        (r'(rhel|centos|fedora)\s+\d+', 'os_version'),
        (r'distribution.*version', 'os_version'),
        (r'version.*distribution', 'os_version'),
        
        # ansible-builder patterns
        (r'ansible[_\-]?builder\s+(version|install)', 'ansible_builder_version'),
        (r'(version|install).*ansible[_\-]?builder', 'ansible_builder_version'),
        
        # execution environment patterns
        (r'execution[_\-]?environment\.yml', 'execution_environment'),
        (r'ee\s+(definition|config)', 'execution_environment'),
        (r'build\s+definition\s+file', 'execution_environment'),
        
        # systemd/libsystemd patterns
        (r'libsystemd\.pc', 'libsystemd_pkgconfig'),
        (r'libsystemd[_\-]?journal\.pc', 'libsystemd_pkgconfig'),
        (r'systemd.*pkg[_\-]?config', 'libsystemd_pkgconfig'),
        (r'pkg[_\-]?config.*systemd', 'libsystemd_pkgconfig'),
        (r'systemd[_\-]?devel', 'systemd_development'),
        (r'systemd[_\-]?libs', 'systemd_libs'),
        (r'libsystemd\s+package', 'systemd_libs'),
        
        # container runtime patterns
        (r'(podman|docker)\s+(runtime|config)', 'container_runtime'),
        (r'container\s+runtime', 'container_runtime'),
        
        # python packages
        (r'python\s+(package|version)', 'python_packages'),
        (r'pip\s+package', 'python_packages'),
        (r'systemd[_\-]?python', 'systemd_python'),
    ]
    
    import re
    for pattern, concept in compound_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            concepts.add(concept)
    
    return concepts


def are_requirements_similar(req1: str, req2: str, threshold: float = 0.45) -> bool:
    """
    Check if two requirements are similar enough to be considered duplicates.
    
    Args:
        req1: First requirement text
        req2: Second requirement text
        threshold: Minimum overlap ratio to consider similar (0-1)
        
    Returns:
        True if requirements are similar
    """
    # Exact normalized match
    norm1 = normalize_requirement_text(req1)
    norm2 = normalize_requirement_text(req2)
    if norm1 == norm2:
        return True
    
    # Check for matching key concepts (catches "PKG_CONFIG_PATH" vs "pkg-config search path")
    concepts1 = extract_key_concepts(req1)
    concepts2 = extract_key_concepts(req2)
    if concepts1 and concepts2 and concepts1 & concepts2:
        # If they share any key concept, they're likely duplicates
        return True
    
    # Keyword overlap check with word normalization
    kw1 = get_requirement_keywords(req1)
    kw2 = get_requirement_keywords(req2)
    
    if not kw1 or not kw2:
        return False
    
    # Normalize keywords for comparison
    norm_kw1 = {normalize_word(w) for w in kw1}
    norm_kw2 = {normalize_word(w) for w in kw2}
    
    # Calculate Jaccard similarity on normalized keywords
    intersection = len(norm_kw1 & norm_kw2)
    union = len(norm_kw1 | norm_kw2)
    similarity = intersection / union if union > 0 else 0
    
    # Also check if one set is a subset of the other (common for short vs detailed reqs)
    if norm_kw1.issubset(norm_kw2) or norm_kw2.issubset(norm_kw1):
        return True
    
    return similarity >= threshold


def deduplicate_requirements(requirements: list[str]) -> list[str]:
    """
    Remove duplicate requirements from a list.
    
    Args:
        requirements: List of requirement strings (with or without index numbers)
        
    Returns:
        List of unique requirements (re-indexed)
    """
    unique_reqs = []
    
    for req in requirements:
        # Check if this requirement is similar to any existing unique requirement
        is_duplicate = False
        for existing_req in unique_reqs:
            if are_requirements_similar(req, existing_req):
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique_reqs.append(req)
    
    # Re-index the unique requirements
    reindexed = []
    for idx, req in enumerate(unique_reqs, 1):
        text = extract_requirement_text(req)
        reindexed.append(f"{idx}. {text}")
    
    return reindexed


def is_substantive_change(old_req: str, new_req: str) -> bool:
    """
    Determine if the change between old and new requirement is substantive.
    
    A substantive change means the NEW requirement asks for ADDITIONAL or DIFFERENT
    data/information to collect that wasn't in the old requirement.
    
    A non-substantive change is just rephrasing the same requirement.
    
    Args:
        old_req: Original requirement text
        new_req: New requirement text
        
    Returns:
        True if the change is substantive (new requirement adds meaningful scope)
    """
    # Get normalized keywords (subject matter) for both
    old_keywords = get_requirement_keywords(old_req)
    new_keywords = get_requirement_keywords(new_req)
    
    # Normalize keywords
    old_norm = {normalize_word(w) for w in old_keywords}
    new_norm = {normalize_word(w) for w in new_keywords}
    
    # If keywords are identical, it's just rephrasing
    if old_norm == new_norm:
        return False
    
    # If old keywords contain all new keywords, new is just a simplified version - not substantive
    if new_norm.issubset(old_norm):
        return False
    
    # Check what's NEW (not in old)
    only_in_new = new_norm - old_norm
    
    # Generic/common words that don't indicate substantive change
    generic_words = {
        'data', 'status', 'state', 'value', 'result', 'output', 'current',
        'info', 'inform', 'detail', 'list', 'rpm', 'file', 'log'
    }
    
    # Remove generic words
    significant_new = only_in_new - generic_words
    
    # Substantive ONLY if there are new SIGNIFICANT keywords
    # (i.e., the new requirement asks for something meaningfully different/additional)
    if significant_new:
        # Additional check: make sure the new keywords are meaningful additions
        # e.g., "configuration" added to "service status" is substantive
        meaningful_additions = {'configur', 'network', 'interface', 'connect', 'error', 
                               'fail', 'memory', 'cpu', 'disk', 'storage', 'secur',
                               'auth', 'permiss', 'port', 'process', 'perform'}
        for new_kw in significant_new:
            for meaningful in meaningful_additions:
                if meaningful in new_kw or new_kw in meaningful:
                    return True
    
    # Default: not substantive (just rephrasing)
    return False


def calculate_semantic_similarity(req1: str, req2: str) -> float:
    """
    Calculate semantic similarity between two requirements.
    
    Uses multiple methods:
    1. Exact normalized match = 1.0
    2. Jaccard similarity on normalized keywords
    3. Overlap ratio adjustments
    
    Args:
        req1: First requirement text
        req2: Second requirement text
        
    Returns:
        float: Similarity score between 0.0 and 1.0
    """
    # Extract just the text (without index numbers)
    text1 = extract_requirement_text(req1).lower().strip()
    text2 = extract_requirement_text(req2).lower().strip()
    
    # Exact match after normalization
    norm1 = normalize_requirement_text(req1)
    norm2 = normalize_requirement_text(req2)
    if norm1 == norm2:
        return 1.0
    
    # Check for matching key concepts - if they share concepts, high similarity
    concepts1 = extract_key_concepts(req1)
    concepts2 = extract_key_concepts(req2)
    if concepts1 and concepts2:
        concept_intersection = len(concepts1 & concepts2)
        if concept_intersection > 0:
            # Shared key concepts indicate high semantic similarity
            concept_union = len(concepts1 | concepts2)
            concept_similarity = concept_intersection / concept_union
            # Give significant bonus for shared concepts
            return min(1.0, 0.7 + 0.3 * concept_similarity)
    
    # Get normalized keywords
    kw1 = get_requirement_keywords(req1)
    kw2 = get_requirement_keywords(req2)
    
    if not kw1 or not kw2:
        return 0.0
    
    # Normalize keywords
    norm_kw1 = {normalize_word(w) for w in kw1}
    norm_kw2 = {normalize_word(w) for w in kw2}
    
    # Calculate Jaccard similarity
    intersection = len(norm_kw1 & norm_kw2)
    union = len(norm_kw1 | norm_kw2)
    jaccard = intersection / union if union > 0 else 0
    
    # Bonus for subset relationships (one is more detailed version of other)
    if norm_kw1.issubset(norm_kw2) or norm_kw2.issubset(norm_kw1):
        # One requirement contains all keywords of the other
        subset_bonus = 0.15
        jaccard = min(1.0, jaccard + subset_bonus)
    
    # Check for common action verbs and targets
    action_verbs = {'collect', 'check', 'verify', 'measure', 'get', 'retrieve', 'gather', 'determine', 'find'}
    verbs1 = norm_kw1 & action_verbs
    verbs2 = norm_kw2 & action_verbs
    
    # Get subject keywords (non-verbs)
    subject1 = norm_kw1 - action_verbs
    subject2 = norm_kw2 - action_verbs
    
    # Calculate subject overlap (more important than verb overlap)
    if subject1 and subject2:
        subject_intersection = len(subject1 & subject2)
        subject_union = len(subject1 | subject2)
        subject_similarity = subject_intersection / subject_union if subject_union > 0 else 0
        
        # Weight subject similarity higher than overall Jaccard
        weighted_similarity = 0.4 * jaccard + 0.6 * subject_similarity
        return weighted_similarity
    
    return jaccard


def merge_requirements_text(old_req: str, new_req: str) -> str:
    """
    Merge two similar requirements into a single comprehensive requirement.
    
    Combines specific details from both requirements.
    
    Args:
        old_req: Existing requirement text
        new_req: New requirement text
        
    Returns:
        str: Merged requirement text (without index number)
    """
    old_text = extract_requirement_text(old_req).strip()
    new_text = extract_requirement_text(new_req).strip()
    
    # Get keywords from both
    old_kw = get_requirement_keywords(old_req)
    new_kw = get_requirement_keywords(new_req)
    
    old_norm = {normalize_word(w) for w in old_kw}
    new_norm = {normalize_word(w) for w in new_kw}
    
    # Find unique keywords in each
    only_in_old = old_norm - new_norm
    only_in_new = new_norm - old_norm
    
    # If new has additional details, use new as base and note what old had
    # If old has additional details, keep old as base
    if len(only_in_new) > len(only_in_old):
        # New requirement is more comprehensive - use it
        return new_text
    elif len(only_in_old) > len(only_in_new):
        # Old requirement is more comprehensive - keep it but consider additions
        return old_text
    else:
        # Similar comprehensiveness - prefer the longer one as it likely has more detail
        if len(new_text) > len(old_text):
            return new_text
        else:
            return old_text


# Thresholds for semantic similarity-based merging
SIMILARITY_DUPLICATE_THRESHOLD = 0.80  # Above this: keep existing (duplicate)
SIMILARITY_MERGE_THRESHOLD = 0.20      # Between this and DUPLICATE: merge requirements
# Below MERGE_THRESHOLD: add as new requirement


def compare_requirements(old_reqs: list[str], new_reqs: list[str]) -> dict:
    """
    Compare old and new requirements using semantic similarity-based merging.
    
    Logic Rules (based on similarity score):
    - Similarity > 0.80: Keep existing requirement (duplicate)
    - Similarity 0.20-0.80: Merge requirements into more comprehensive one
    - Similarity < 0.20: Add new requirement as brand-new item

    keep the unselected old requirement(s) unchanged
    
    Args:
        old_reqs: List of old requirements (with index numbers)
        new_reqs: List of new requirements (with index numbers)
        
    Returns:
        dict with:
            - new: list of (index, req) - Requirements that are new (similarity < 0.20)
            - merged: list of (index, old_req, new_req, merged_req, similarity) - Merged requirements
            - unchanged: list of (index, req, similarity) - Requirements kept as existing (similarity > 0.80)
            - mapping: dict of new_index -> old_index for requirements that matched
            - duplicates_removed: int - Number of duplicates removed from new_reqs
            - final_requirements: list[str] - The final list of requirements to use
    """
    # First, deduplicate new requirements
    original_count = len(new_reqs)
    new_reqs = deduplicate_requirements(new_reqs)
    duplicates_removed = original_count - len(new_reqs)
    
    result = {
        'new': [],           # New requirements (similarity < 0.20)
        'merged': [],        # Merged requirements (similarity 0.20-0.80)
        'unchanged': [],     # Keep existing (similarity > 0.80)
        'mapping': {},       # new_index -> old_index
        'duplicates_removed': duplicates_removed,
        'final_requirements': []
    }
    
    used_old_indices = set()
    
    for new_idx, new_req in enumerate(new_reqs):
        # Find the best matching old requirement
        best_match_idx = -1
        best_match_req = None
        best_similarity = 0.0
        
        for old_idx, old_req in enumerate(old_reqs):
            if old_idx in used_old_indices:
                continue  # Skip already matched old requirements
            
            similarity = calculate_semantic_similarity(old_req, new_req)
            
            if similarity > best_similarity:
                best_similarity = similarity
                best_match_idx = old_idx
                best_match_req = old_req
        
        # Apply threshold-based actions
        if best_match_idx >= 0:
            if best_similarity > SIMILARITY_DUPLICATE_THRESHOLD:
                # Action 1: Similarity > 0.80 - Keep existing (duplicate)
                result['unchanged'].append((new_idx + 1, best_match_req, best_similarity))
                result['mapping'][new_idx + 1] = best_match_idx + 1
                result['final_requirements'].append(best_match_req)
                used_old_indices.add(best_match_idx)
                
            elif best_similarity >= SIMILARITY_MERGE_THRESHOLD:
                # Action 2: Similarity 0.20-0.80 - Merge requirements
                merged_text = merge_requirements_text(best_match_req, new_req)
                result['merged'].append((
                    new_idx + 1, 
                    best_match_req, 
                    new_req, 
                    merged_text,
                    best_similarity
                ))
                result['mapping'][new_idx + 1] = best_match_idx + 1
                result['final_requirements'].append(merged_text)
                used_old_indices.add(best_match_idx)
                
            else:
                # Action 3: Similarity < 0.20 - Add as new
                result['new'].append((new_idx + 1, new_req, best_similarity))
                result['final_requirements'].append(new_req)
        else:
            # No old requirements to compare - add as new
            result['new'].append((new_idx + 1, new_req, 0.0))
            result['final_requirements'].append(new_req)
    
    # Track the current count of matched requirements
    matched_count = len(result['final_requirements'])
    
    # Add any unused old requirements (they weren't matched by any new req)
    # But first check if they're duplicates of requirements already in final_requirements
    # These are KEPT as unchanged - existing playbooks should be reused
    result['kept_old'] = []  # Old requirements not impacted by new requirements
    result['skipped_duplicates'] = []  # Old requirements that were duplicates
    
    for old_idx, old_req in enumerate(old_reqs):
        if old_idx not in used_old_indices:
            # Check if this old_req is similar to any existing requirement in final_requirements
            is_dup = False
            for existing in result['final_requirements']:
                if are_requirements_similar(old_req, existing):
                    is_dup = True
                    result['skipped_duplicates'].append((old_idx + 1, old_req, existing))
                    break
            
            if not is_dup:
                # Keep old requirement that wasn't matched - it's unchanged
                new_idx_in_final = len(result['final_requirements']) + 1
                result['kept_old'].append((new_idx_in_final, old_req, old_idx + 1))  # (new_idx, req, original_old_idx)
                result['final_requirements'].append(old_req)
    
    # Final deduplication pass on the entire list
    # This catches any remaining duplicates that slipped through
    final_unique = []
    for req in result['final_requirements']:
        is_dup = False
        for existing in final_unique:
            if are_requirements_similar(req, existing):
                is_dup = True
                break
        if not is_dup:
            final_unique.append(req)
    
    result['final_requirements'] = final_unique
    
    # Re-index final requirements with 2-digit zero-padded format
    result['final_requirements'] = [
        f"{idx + 1}. {extract_requirement_text(req)}" 
        for idx, req in enumerate(result['final_requirements'])
    ]
    
    return result


# Find ansible-navigator full path
ANSIBLE_NAVIGATOR_PATH = shutil.which('ansible-navigator')
if not ANSIBLE_NAVIGATOR_PATH:
    # Fallback: try to construct path
    python_dir = os.path.dirname(sys.executable)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [
        os.path.join(python_dir, 'ansible-navigator'),
        os.path.join(script_dir, '.venv', 'bin', 'ansible-navigator'),
        os.path.join(script_dir, 'venv', 'bin', 'ansible-navigator'),
    ]
    for path in possible_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            ANSIBLE_NAVIGATOR_PATH = path
            break

if ANSIBLE_NAVIGATOR_PATH:
    print(f"✅ Using ansible-navigator at: {ANSIBLE_NAVIGATOR_PATH}")
else:
    print("⚠️  Warning: Could not find ansible-navigator, will use 'ansible-navigator' from PATH")
    ANSIBLE_NAVIGATOR_PATH = 'ansible-navigator'

# Create wrapper functions that use the full path to ansible-navigator
def check_playbook_syntax(filename: str, target_host: str) -> tuple[bool, str]:
    """Wrapper for check_playbook_syntax that uses full path to ansible-navigator."""
    import subprocess
    
    try:
        print(f"\n🔍 Checking playbook syntax: {filename}")
        cmd = [
            ANSIBLE_NAVIGATOR_PATH, 'run', 
            filename, 
            '-i', f'{target_host},',
            '-u', 'root',
            '-v',
            '--syntax-check',
            '--mode', 'stdout'
        ]
        print(f"Command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ.copy()  # Explicitly pass environment
        )
        
        if result.returncode == 0:
            print("✅ Syntax check passed!")
            return True, ""
        else:
            error_output = []
            if result.stdout and result.stdout.strip():
                error_output.append("=== STDOUT ===")
                error_output.append(result.stdout)
            if result.stderr and result.stderr.strip():
                error_output.append("=== STDERR ===")
                error_output.append(result.stderr)
            if not error_output:
                error_output.append("No error output captured.")
            error_msg = "\n".join(error_output)
            print(f"❌ Syntax check failed!")
            return False, error_msg
            
    except subprocess.TimeoutExpired:
        error_msg = "Syntax check timed out after 30 seconds"
        print(f"❌ {error_msg}")
        return False, error_msg
    except FileNotFoundError:
        error_msg = f"ansible-navigator command not found at: {ANSIBLE_NAVIGATOR_PATH}. Please ensure Ansible is installed."
        print(f"❌ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Error during syntax check: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg


def test_playbook_on_server(filename: str, target_host: str = "192.168.122.16", check_mode: bool = False, verbose: bool = False, skip_debug: bool = False) -> tuple[bool, str]:
    """Wrapper for test_playbook_on_server that uses full path to ansible-navigator."""
    import subprocess
    import re
    
    try:
        mode_desc = "check mode (dry-run)" if check_mode else "execution mode"
        if skip_debug:
            mode_desc += " [skipping debug tasks]"
        print(f"\n🧪 Testing playbook on server: {target_host} ({mode_desc})")
        
        # Build ansible-navigator command using full path
        cmd = [
            ANSIBLE_NAVIGATOR_PATH, 'run', 
            filename, 
            '-i', f'{target_host},',
            '-u', 'root',
            '--mode', 'stdout'  # Force stdout mode
        ]
        
        if verbose:
            cmd.append('-v')
        
        if check_mode:
            cmd.append('--check')
        
        if skip_debug:
            cmd.extend(['--skip-tags', 'debug'])
        
        print(f"   Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minutes timeout for execution
            env=os.environ.copy()  # Explicitly pass environment
        )
        
        output = result.stdout + result.stderr
        
        # Check for PLAYBOOK BUGS that require retry/regeneration (same as original)
        playbook_bug_patterns = [
            ("undefined variable", "Undefined variable error"),
            ("is undefined", "Variable is undefined"),
            ("'dict object' has no attribute", "Invalid attribute access"),
            ("Syntax Error while loading YAML", "YAML syntax error"),
            ("template error while templating string", "Jinja2 template error"),
            ("Unexpected end of template", "Jinja2 unclosed block"),
            ("expected token 'end of print statement'", "Jinja2 syntax error"),
            ("Jinja was looking for the following tags", "Jinja2 missing closing tag"),
            ("The error was:", "Ansible task error"),
            ("undefined method", "Undefined method call"),
            ("cannot be converted to", "Type conversion error"),
            ("Invalid/incorrect password", "Authentication error in task"),
        ]
        
        for pattern, description in playbook_bug_patterns:
            if pattern in output:
                print(f"❌ PLAYBOOK BUG DETECTED: {description}")
                print("   This is a playbook error, not a verification failure")
                print("   The playbook needs to be regenerated with corrections")
                print("\n" + "="*80)
                print("ERROR DETAILS:")
                print("="*80)
                # Extract and show the error context
                error_lines = output.split('\n')
                error_context_lines = []
                for i, line in enumerate(error_lines):
                    if pattern in line:
                        start = max(0, i-3)
                        end = min(len(error_lines), i+8)
                        error_context_lines = error_lines[start:end]
                        print('\n'.join(error_context_lines))
                        break
                print("="*80)
                
                full_error_context = '\n'.join(error_context_lines) if error_context_lines else output[:500]
                return False, f"PLAYBOOK BUG: {description}\n\nError context:\n{full_error_context}\n\nFull pattern: {pattern}"
        
        if result.returncode == 0:
            print(f"✅ Playbook executed successfully in {mode_desc}!")
            
            # Check PLAY RECAP for actual task failures
            if "ok=" in output and "PLAY RECAP" in output:
                recap_match = re.search(r'failed=(\d+)', output)
                if recap_match and int(recap_match.group(1)) > 0:
                    print(f"⚠️  Warning: {recap_match.group(1)} task(s) failed, but playbook completed")
                    # Still return True for data collection playbooks - failures are expected
                    return True, output
            
            return True, output
        else:
            print(f"❌ Playbook execution failed (return code: {result.returncode})")
            return False, output
            
    except subprocess.TimeoutExpired:
        error_msg = "Playbook execution timed out after 2 minutes"
        print(f"❌ {error_msg}")
        return False, error_msg
    except FileNotFoundError:
        error_msg = f"ansible-navigator command not found at: {ANSIBLE_NAVIGATOR_PATH}. Please ensure Ansible is installed."
        print(f"❌ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Error during playbook execution: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg

# Initialize LLM model
model = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    max_tokens=None,
    timeout=1800,  # 30 minutes
    request_timeout=1800,
    max_retries=2
)


# Define State for LangGraph workflow
class KCSPlaybookGenerationState(TypedDict):
    """State for the KCS-to-playbook generation workflow."""
    # Input parameters
    search_query: str
    target_host: str
    test_host: str
    become_user: str
    filename: str
    max_retries: int
    num_kcs_results: int
    no_browser: bool
    
    # KCS search state
    kcs_results: dict
    kcs_article: dict  # Extracted article info (environment, issue, resolution, title, url, doc_id)
    access_token: str
    
    # Existing docs state (for incremental updates)
    existing_docs: dict  # Result from check_existing_docs()
    use_existing_docs: bool  # Whether to use existing docs
    requirement_changes: dict  # Result from compare_requirements()
    playbooks_to_generate: list[int]  # List of requirement indices that need new playbooks
    playbooks_to_reuse: list  # List of (idx, path, status) tuples for reusable playbooks
    batch_reuse_info: list[dict]  # Per-batch reuse info: {index, req_index, reuse, status, path}
    
    # Requirements generation state
    matching_requirements: list[str]  # Requirements to measure if target matches KCS
    data_collection_requirements: list[str]  # Requirements for data collection playbook
    playbook_objective: str
    
    # Multi-playbook support (max 1 requirement per playbook)
    requirement_batches: list[list[str]]  # List of requirement batches (each = 1 item)
    current_batch_index: int  # Current batch being processed
    playbook_contents: list[str]  # Generated playbooks for each batch
    playbook_outputs: list[str]  # Test outputs from each batch playbook
    total_batches: int  # Total number of batches
    
    # Phase 2 Analysis state
    all_playbook_outputs: list[dict]  # All playbook outputs stored during generation {batch, output, filename}
    batch_analysis_results: list[dict]  # Analysis results for each batch
    extracted_reports: list[str]  # Extracted DATA COLLECTION REPORT from each batch
    data_collection_summary: str  # Combined data from Part 1 analysis
    combined_report: str  # Combined report for compliance analysis (test host)
    compliance_passed: bool  # Part 2 compliance analysis result
    compliance_message: str  # Part 2 compliance analysis message
    target_combined_report: str  # Combined report from target host
    target_analysis_passed: bool  # Target host analysis result
    target_analysis_message: str  # Target host analysis message
    
    # Playbook generation state (from langgraph workflow)
    requirements: list[str]  # Current requirements for playbook generation (one batch)
    example_output: str
    attempt: int
    playbook_content: str
    syntax_valid: bool
    test_success: bool
    analysis_passed: bool
    analysis_message: str
    final_success: bool
    error_message: str
    test_output: str
    final_output: str
    
    # Control flow
    should_retry: bool
    workflow_complete: bool


def extract_environment_from_kcs(kcs_results):
    """
    Extract ENVIRONMENT information from KCS search results.
    
    Args:
        kcs_results: JSON response from KCS search
        
    Returns:
        dict: {
            'environment': str,
            'issue': str,
            'resolution': str,
            'title': str,
            'url': str,
            'doc_id': str
        }
    """
    if isinstance(kcs_results, str):
        print(f"Error: {kcs_results}")
        return None
    
    response = kcs_results.get('response', {})
    docs = response.get('docs', [])
    
    if not docs:
        print("No KCS articles found.")
        return None
    
    # Get the first (most relevant) result
    doc = docs[0]
    
    # Extract environment information
    environment = (doc.get('solution_environment', '') or
                  doc.get('environment', '') or
                  doc.get('allEnvironment', ''))
    
    if isinstance(environment, list):
        environment = '\n'.join(str(item) for item in environment if item)
    
    environment = strip_html(environment) if environment else ''
    
    # Extract issue information
    issue = (doc.get('solution_issue', '') or
            doc.get('issue', '') or
            doc.get('allIssue', ''))
    
    if isinstance(issue, list):
        issue = '\n'.join(str(item) for item in issue if item)
    
    issue = strip_html(issue) if issue else ''
    
    # Extract resolution information
    resolution = (doc.get('solution_resolution', '') or
                 doc.get('resolution', '') or
                 doc.get('solution', ''))
    
    if isinstance(resolution, list):
        resolution = '\n'.join(str(item) for item in resolution if item)
    
    resolution = strip_html(resolution) if resolution else ''
    
    # Extract metadata
    title = doc.get('allTitle', doc.get('documentTitle', 'No Title'))
    doc_id = doc.get('id', 'N/A')
    view_url = doc.get('view_uri', f"https://access.redhat.com/solutions/{doc_id}")
    
    return {
        'environment': environment,
        'issue': issue,
        'resolution': resolution,
        'title': title,
        'url': view_url,
        'doc_id': doc_id
    }


def search_kcs_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Search KCS articles."""
    print("\n" + "=" * 80)
    print("STEP 1: Searching KCS Articles")
    print("=" * 80)
    print(f"Search Query: {state['search_query']}")
    print(f"Number of Results: {state['num_kcs_results']}")
    print("=" * 80)
    
    try:
        # Get access token if not already set
        if not state.get('access_token'):
            offline_token = os.environ.get('REDHAT_OFFLINE_TOKEN')
            if not offline_token:
                state['error_message'] = "REDHAT_OFFLINE_TOKEN environment variable not set"
                return state
            
            print("Authenticating with Red Hat API...")
            access_token = get_red_hat_access_token(offline_token)
            state['access_token'] = access_token
            print("✅ Authentication successful!")
        
        # Search KCS
        print(f"\n🔍 Searching KCS for: '{state['search_query']}'...")
        kcs_results = search_v2_kcs(state['access_token'], state['search_query'], state['num_kcs_results'])
        
        if isinstance(kcs_results, str):
            state['error_message'] = f"KCS search failed: {kcs_results}"
            return state
        
        num_found = kcs_results.get('response', {}).get('numFound', 0)
        print(f"✅ Found {num_found} KCS articles")
        
        state['kcs_results'] = kcs_results
        
        # Extract article information
        kcs_article = extract_environment_from_kcs(kcs_results)
        if not kcs_article:
            state['error_message'] = "Failed to extract environment information from KCS results"
            return state
        
        state['kcs_article'] = kcs_article
        
        # Set the initial filename based on KCS ID
        kcs_id = kcs_article.get('doc_id', 'unknown')
        state['filename'] = get_playbook_path(kcs_id, part_num=1)
        
        print(f"\n📄 KCS Article: {kcs_article['title']}")
        print(f"🔗 URL: {kcs_article['url']}")
        print(f"🆔 ID: {kcs_article['doc_id']}")
        print(f"📁 Playbook path: {state['filename']}")
        
        # Check for existing docs
        existing_docs = check_existing_docs(kcs_id)
        state['existing_docs'] = existing_docs
        
        if existing_docs['exists']:
            print(f"\n📂 Found existing docs in: {existing_docs['directory']}")
            if existing_docs['matching_requirements_file']:
                print(f"   ✅ matching_requirements.txt exists")
            if existing_docs['data_collection_requirements_file']:
                print(f"   ✅ data_collection_requirements.txt exists")
            if existing_docs['playbooks']:
                print(f"   ✅ Found {len(existing_docs['playbooks'])} existing playbook(s):")
                for pb in existing_docs['playbooks']:
                    print(f"      - {os.path.basename(pb)}")
            state['use_existing_docs'] = True
        else:
            print(f"\n📂 No existing docs found. Will generate new requirements and playbooks.")
            state['use_existing_docs'] = False
        
        # Open URL in browser (unless --no-browser)
        if not state.get('no_browser', False):
            print(f"\n🌐 Opening KCS article in web browser...")
            try:
                webbrowser.open(kcs_article['url'])
                print("   ✅ Browser opened successfully")
            except Exception as e:
                print(f"   ⚠️  Could not open browser automatically: {e}")
                print(f"   Please manually open: {kcs_article['url']}")
        
        # Display KCS article details
        print("\n" + "-" * 80)
        print("📋 KCS ARTICLE DETAILS:")
        print("-" * 80)
        print(f"\n📌 TITLE: {kcs_article['title']}")
        
        if kcs_article['environment']:
            env_display = kcs_article['environment']
            if len(env_display) > 1000:
                print(f"\n🖥️  ENVIRONMENT (truncated):\n{env_display[:1000]}...")
            else:
                print(f"\n🖥️  ENVIRONMENT:\n{env_display}")
        
        if kcs_article['issue']:
            issue_display = kcs_article['issue']
            if len(issue_display) > 1000:
                print(f"\n💡 ISSUE (truncated):\n{issue_display[:1000]}...")
            else:
                print(f"\n💡 ISSUE:\n{issue_display}")
        
        print("-" * 80)
        
    except Exception as e:
        state['error_message'] = f"Error in KCS search: {str(e)}"
        print(f"❌ Error: {state['error_message']}")
    
    return state


def generate_matching_requirements_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Generate requirements to measure if target matches KCS environment/issue."""
    print("\n" + "=" * 80)
    print("STEP 2: Generating Matching Requirements")
    print("=" * 80)
    
    # Check if we have existing requirements
    existing_docs = state.get('existing_docs', {})
    use_existing = state.get('use_existing_docs', False)
    
    # Load existing matching requirements if available
    old_matching_reqs = []
    if use_existing and existing_docs.get('matching_requirements_file'):
        old_matching_reqs = read_requirements_from_file(existing_docs['matching_requirements_file'])
        if old_matching_reqs:
            print(f"📖 Loaded {len(old_matching_reqs)} existing matching requirements")
    
    print("Generating requirements to measure if target host matches KCS environment/issue...")
    print("=" * 80)
    
    kcs_article = state.get('kcs_article', {})
    if not kcs_article:
        state['error_message'] = "KCS article information not available"
        return state
    
    environment_text = kcs_article.get('environment', '')
    issue_text = kcs_article.get('issue', '')
    title = kcs_article.get('title', '')
    
    prompt_template = """You are an expert system administrator analyzing Red Hat KCS articles.

Based on the following KCS article, generate a list of requirements that can be used to MEASURE
whether a target server matches the environment and issue described in the KCS article.

**Purpose:**
These requirements will be used by AI to analyze collected server data and determine:
- Does the server environment match the KCS environment?
- Does the server have the same issue/problem described in the KCS?
- Is the KCS solution applicable to this server?

**KCS Article Title:**
{title}

**Environment Information:**
{environment}

**Issue/Problem:**
{issue}

**Task:**
Generate 5-10 specific requirements that describe what needs to be MEASURED/COMPARED to determine
if a target server matches this KCS article's environment and issue.

**Output Format:**
Return ONLY a valid JSON object with this exact structure (no markdown, no code blocks):
{{
  "requirements": [
    "Measure if OS version matches: <specific version requirement>",
    "Measure if package X is installed and version matches: <version requirement>",
    "Measure if service Y status matches: <expected status>",
    "Measure if configuration Z matches: <expected configuration>",
    "Measure if issue symptom A is present: <symptom description>",
    ...
  ]
}}

**Important Guidelines:**
- Focus on MEASURABLE criteria that can be compared
- Include version numbers, package names, service names mentioned in KCS
- Include symptoms or indicators of the issue
- Frame as "Measure if..." or "Determine if..." (not "Check if..." or "Verify if...")
- These requirements will be used by AI to analyze collected data, not by the playbook directly

Generate the JSON now:"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | model
    
    try:
        response = chain.invoke({
            'title': title,
            'environment': environment_text if environment_text else 'Not specified',
            'issue': issue_text if issue_text else 'Not specified'
        })
        
        response_text = response.content.strip()
        
        # Clean up response - remove markdown code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        # Parse JSON
        result = json.loads(response_text)
        raw_requirements = result.get('requirements', [])
        
        # Add index to each requirement if not already present
        matching_requirements = []
        for idx, req in enumerate(raw_requirements, 1):
            # Check if requirement already has an index prefix like "1." or "1:"
            req_stripped = req.strip()
            if req_stripped and not (req_stripped[0].isdigit() and (req_stripped[1:3].startswith('.') or req_stripped[1:3].startswith(':') or req_stripped[1:3].startswith(')'))):
                matching_requirements.append(f"{idx}. {req}")
            else:
                matching_requirements.append(req)
        
        # Deduplicate requirements
        original_count = len(matching_requirements)
        matching_requirements = deduplicate_requirements(matching_requirements)
        if original_count != len(matching_requirements):
            print(f"   ⚠️ Removed {original_count - len(matching_requirements)} duplicate requirement(s)")
        
        # Compare with existing requirements if available
        kcs_id = get_kcs_id_from_state(state)
        kcs_article = state.get('kcs_article', {})
        kcs_title = kcs_article.get('title', 'KCS Article')
        kcs_url = kcs_article.get('url', '')
        
        if old_matching_reqs:
            match_changes = compare_requirements(old_matching_reqs, matching_requirements)
            
            # Use the final merged requirements
            matching_requirements = match_changes['final_requirements']
            
            print(f"\n📊 MATCHING REQUIREMENTS COMPARISON (Semantic Similarity):")
            print("-" * 80)
            print(f"  Thresholds: >0.80 = Keep existing | 0.20-0.80 = Merge | <0.20 = Add new")
            print("-" * 80)
            if match_changes.get('duplicates_removed', 0) > 0:
                print(f"  ⚠️ DUPLICATES REMOVED: {match_changes['duplicates_removed']}")
            if match_changes['unchanged']:
                print(f"  ✅ KEPT EXISTING (similarity > 0.80): {len(match_changes['unchanged'])}")
                for idx, req, sim in match_changes['unchanged']:
                    print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(req)}")
                    #print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(req)[:50]}...")
            if match_changes['merged']:
                print(f"  🔀 MERGED (similarity 0.20-0.80): {len(match_changes['merged'])}")
                for idx, old_req, new_req, merged_req, sim in match_changes['merged']:
                    print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(merged_req)}")
                    #print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(merged_req)[:50]}...")
            if match_changes['new']:
                print(f"  🆕 NEW (similarity < 0.20): {len(match_changes['new'])}")
                for idx, req, sim in match_changes['new']:
                    print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(req)}")
                    #print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(req)[:50]}...")
            if match_changes.get('kept_old'):
                print(f"  📌 KEPT OLD (not impacted by new): {len(match_changes['kept_old'])}")
                for new_idx, req, old_idx in match_changes['kept_old']:
                    print(f"     {new_idx}. (was #{old_idx}) {extract_requirement_text(req)}")
                    #print(f"     {new_idx}. (was #{old_idx}) {extract_requirement_text(req)[:45]}...")
            print("-" * 80)
        
        state['matching_requirements'] = matching_requirements
        
        print(f"\n✅ Final matching requirements ({len(matching_requirements)}):")
        print("-" * 80)
        for req in matching_requirements:
            print(f"  {req}")
        print("-" * 80)
        
        # Save matching requirements to file
        saved_path = save_requirements_to_file(
            kcs_id=kcs_id,
            requirements=matching_requirements,
            filename='matching_requirements.txt',
            title=f"MATCHING REQUIREMENTS\nKCS Article: {kcs_title}\nURL: {kcs_url}"
        )
        print(f"📁 Saved to: {saved_path}")
        
    except json.JSONDecodeError as e:
        state['error_message'] = f"Failed to parse matching requirements JSON: {e}"
        print(f"❌ Error: {state['error_message']}")
        # Fallback with indexed requirements
        state['matching_requirements'] = [
            "1. Measure if OS version matches KCS environment",
            "2. Measure if packages match KCS environment",
            "3. Measure if services match KCS environment",
            "4. Measure if issue symptoms are present"
        ]
    except Exception as e:
        state['error_message'] = f"Error generating matching requirements: {str(e)}"
        print(f"❌ Error: {state['error_message']}")
        state['matching_requirements'] = []
    
    return state


def generate_data_collection_requirements_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Generate data collection requirements for playbook."""
    print("\n" + "=" * 80)
    print("STEP 3: Generating Data Collection Requirements")
    print("=" * 80)
    
    # Check if we have existing requirements
    existing_docs = state.get('existing_docs', {})
    use_existing = state.get('use_existing_docs', False)
    
    # Load existing data collection requirements if available
    old_data_reqs = []
    if use_existing and existing_docs.get('data_collection_requirements_file'):
        old_data_reqs = read_requirements_from_file(existing_docs['data_collection_requirements_file'])
        if old_data_reqs:
            print(f"📖 Loaded {len(old_data_reqs)} existing data collection requirements")
    
    print("Generating requirements for playbook to collect server data...")
    print("=" * 80)
    
    kcs_article = state.get('kcs_article', {})
    matching_requirements = state.get('matching_requirements', [])
    
    if not kcs_article:
        state['error_message'] = "KCS article information not available"
        return state
    
    environment_text = kcs_article.get('environment', '')
    issue_text = kcs_article.get('issue', '')
    title = kcs_article.get('title', '')
    
    # Build matching requirements context
    matching_context = "\n".join([f"- {req}" for req in matching_requirements])
    
    prompt_template = """You are an expert Ansible playbook developer.

Based on the following KCS article and matching requirements, generate a list of DATA COLLECTION
requirements for an Ansible playbook.

**Purpose:**
The playbook will COLLECT server information that will be analyzed by AI to determine if the
server matches the KCS environment and issue. The collected data will be used to evaluate
the matching requirements.

**KCS Article Title:**
{title}

**Environment Information:**
{environment}

**Issue/Problem:**
{issue}

**Matching Requirements (what needs to be measured):**
{matching_requirements}

**Task:**
Generate specific DATA COLLECTION requirements for an Ansible playbook that will gather
all the information needed to evaluate the matching requirements above.

**Output Format:**
Return ONLY a valid JSON object with this exact structure (no markdown, no code blocks):
{{
  "objective": "Collect server information to compare against KCS article: <title>",
  "requirements": [
    "Collect OS version information",
    ...
  ]
}}

**Important Guidelines:**
- Frame each requirement as "Collect...", "Gather...", or "Retrieve..." (NOT "Verify..." or "Check...")
- Focus on INFORMATION GATHERING, not compliance checking
- Include all data needed to evaluate the matching requirements
- If something doesn't exist (package not installed, file not found), that's valid data to collect
- Requirements should gather facts that can be compared to the KCS environment
- Include OS info etc.

Generate the JSON now:"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | model
    
    try:
        response = chain.invoke({
            'title': title,
            'environment': environment_text if environment_text else 'Not specified',
            'issue': issue_text if issue_text else 'Not specified',
            'matching_requirements': matching_context
        })
        
        response_text = response.content.strip()
        
        # Clean up response - remove markdown code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        
        # Parse JSON
        result = json.loads(response_text)
        objective = result.get('objective', f"Collect server information to compare against KCS article: {title}")
        raw_requirements = result.get('requirements', [])
        
        # Add index to each requirement if not already present
        data_collection_requirements = []
        for idx, req in enumerate(raw_requirements, 1):
            # Check if requirement already has an index prefix like "1." or "1:" or "1)"
            req_stripped = req.strip()
            if req_stripped and not (req_stripped[0].isdigit() and len(req_stripped) > 1 and req_stripped[1] in '.):'):
                data_collection_requirements.append(f"{idx}. {req}")
            else:
                data_collection_requirements.append(req)
        
        # Deduplicate requirements
        original_count = len(data_collection_requirements)
        data_collection_requirements = deduplicate_requirements(data_collection_requirements)
        if original_count != len(data_collection_requirements):
            print(f"   ⚠️ Removed {original_count - len(data_collection_requirements)} duplicate requirement(s)")
        
        state['playbook_objective'] = objective
        state['data_collection_requirements'] = data_collection_requirements
        
        print(f"\n✅ Generated playbook objective:")
        print(f"   {objective}")
        print(f"\n✅ Generated {len(data_collection_requirements)} data collection requirements:")
        print("-" * 80)
        for req in data_collection_requirements:
            print(f"  {req}")
        print("-" * 80)
        
        # Save data collection requirements to file
        kcs_id = get_kcs_id_from_state(state)
        kcs_title = kcs_article.get('title', 'KCS Article')
        kcs_url = kcs_article.get('url', '')
        
        saved_path = save_requirements_to_file(
            kcs_id=kcs_id,
            requirements=data_collection_requirements,
            filename='data_collection_requirements.txt',
            title=f"DATA COLLECTION REQUIREMENTS\nKCS Article: {kcs_title}\nURL: {kcs_url}\n\nObjective: {objective}"
        )
        print(f"📁 Saved to: {saved_path}")
        
        # Compare with existing requirements if available
        if old_data_reqs:
            req_changes = compare_requirements(old_data_reqs, data_collection_requirements)
            state['requirement_changes'] = req_changes
            
            # Use the final merged requirements
            data_collection_requirements = req_changes['final_requirements']
            state['data_collection_requirements'] = data_collection_requirements
            
            print(f"\n📊 DATA COLLECTION REQUIREMENT COMPARISON (Semantic Similarity):")
            print("-" * 80)
            print(f"  Thresholds: >0.80 = Keep existing | 0.20-0.80 = Merge | <0.20 = Add new")
            print("-" * 80)
            if req_changes.get('duplicates_removed', 0) > 0:
                print(f"  ⚠️ DUPLICATES REMOVED: {req_changes['duplicates_removed']}")
            if req_changes['unchanged']:
                print(f"  ✅ KEPT EXISTING (similarity > 0.80): {len(req_changes['unchanged'])}")
                for idx, req, sim in req_changes['unchanged']:
                    print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(req)}")
                    #print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(req)[:55]}...")
            if req_changes['merged']:
                print(f"  🔀 MERGED (similarity 0.20-0.80): {len(req_changes['merged'])}")
                for idx, old_req, new_req, merged_req, sim in req_changes['merged']:
                    print(f"     {idx}. [{sim:.2f}] OLD: {extract_requirement_text(old_req)}")
                    print(f"              NEW: {extract_requirement_text(new_req)}")
                    print(f"              MERGED: {extract_requirement_text(merged_req)}")
                    #print(f"     {idx}. [{sim:.2f}] OLD: {extract_requirement_text(old_req)[:40]}...")
                    #print(f"              NEW: {extract_requirement_text(new_req)[:40]}...")
                    #print(f"              MERGED: {extract_requirement_text(merged_req)[:40]}...")
            if req_changes['new']:
                print(f"  🆕 NEW (similarity < 0.20): {len(req_changes['new'])}")
                for idx, req, sim in req_changes['new']:
                    print(f"     {idx}. [{sim:.2f}] {extract_requirement_text(req)[:55]}...")
            if req_changes.get('kept_old'):
                print(f"  📌 KEPT OLD (not impacted by new): {len(req_changes['kept_old'])}")
                for new_idx, req, old_idx in req_changes['kept_old']:
                    print(f"     {new_idx}. (was #{old_idx}) {extract_requirement_text(req)[:50]}...")
            print("-" * 80)
            
            # Update the saved requirements file with final merged requirements
            saved_path = save_requirements_to_file(
                kcs_id=kcs_id,
                requirements=data_collection_requirements,
                filename='data_collection_requirements.txt',
                title=f"DATA COLLECTION REQUIREMENTS\nKCS Article: {kcs_title}\nURL: {kcs_url}\n\nObjective: {objective}"
            )
            print(f"📁 Updated: {saved_path}")
            
            # Determine which playbooks to generate vs reuse
            existing_playbooks = existing_docs.get('playbooks', [])
            playbooks_to_generate = []
            playbooks_to_reuse = []
            
            # New requirements always need new playbooks
            for idx, req, sim in req_changes['new']:
                playbooks_to_generate.append(idx)
            
            # Merged requirements: use existing playbook as baseline for update
            # Format: (new_idx, old_idx, path, status)
            for idx, old_req, new_req, merged_req, sim in req_changes['merged']:
                old_idx = req_changes['mapping'].get(idx)
                if old_idx and old_idx <= len(existing_playbooks):
                    playbooks_to_reuse.append((idx, old_idx, existing_playbooks[old_idx - 1], 'merged'))
                else:
                    playbooks_to_generate.append(idx)
            
            # Unchanged requirements (kept existing): reuse existing playbook directly
            for idx, req, sim in req_changes['unchanged']:
                old_idx = req_changes['mapping'].get(idx)
                if old_idx and old_idx <= len(existing_playbooks):
                    playbooks_to_reuse.append((idx, old_idx, existing_playbooks[old_idx - 1], 'unchanged'))
                else:
                    playbooks_to_generate.append(idx)
            
            # Kept old requirements (not impacted by new): reuse existing playbook directly
            for new_idx, req, original_old_idx in req_changes.get('kept_old', []):
                if original_old_idx <= len(existing_playbooks):
                    playbooks_to_reuse.append((new_idx, original_old_idx, existing_playbooks[original_old_idx - 1], 'unchanged'))
                else:
                    playbooks_to_generate.append(new_idx)
            
            state['playbooks_to_generate'] = playbooks_to_generate
            state['playbooks_to_reuse'] = playbooks_to_reuse
            
            print(f"\n📦 PLAYBOOK STRATEGY:")
            print(f"   🆕 Playbooks to generate: {playbooks_to_generate if playbooks_to_generate else 'None'}")
            print(f"   ♻️  Playbooks to reuse: {len(playbooks_to_reuse)}")
            for new_idx, old_idx, pb_path, status in playbooks_to_reuse:
                if new_idx != old_idx:
                    print(f"      Req {new_idx} ← was Req {old_idx} ({status}): {os.path.basename(pb_path)}")
                else:
                    print(f"      Req {new_idx} ({status}): {os.path.basename(pb_path)}")
        else:
            # No existing requirements - generate all playbooks
            state['playbooks_to_generate'] = list(range(1, len(data_collection_requirements) + 1))
            state['playbooks_to_reuse'] = []
        
    except json.JSONDecodeError as e:
        state['error_message'] = f"Failed to parse data collection requirements JSON: {e}"
        print(f"❌ Error: {state['error_message']}")
        # Fallback with indexed requirements
        state['playbook_objective'] = f"Collect server information to compare against KCS article: {title}"
        state['data_collection_requirements'] = [
            "1. Collect OS distribution, version, and kernel information",
            "2. Collect installed packages and versions",
            "3. Collect service statuses and configurations",
            "4. Collect system configurations and settings"
        ]
    except Exception as e:
        state['error_message'] = f"Error generating data collection requirements: {str(e)}"
        print(f"❌ Error: {state['error_message']}")
        # Ensure data_collection_requirements exists even on error
        if 'data_collection_requirements' not in state:
            state['data_collection_requirements'] = []
        # Ensure playbook_objective exists
        if 'playbook_objective' not in state:
            kcs_article = state.get('kcs_article', {})
            title = kcs_article.get('title', 'KCS article')
            state['playbook_objective'] = f"Collect server information to compare against KCS article: {title}"
    
    # Combine requirements for playbook generation
    # Add KCS reference and standard data collection requirements
    # Ensure data_collection_requirements exists
    if 'data_collection_requirements' not in state:
        state['data_collection_requirements'] = []
    
    combined_requirements = state['data_collection_requirements'].copy()
    
    # Safely get KCS article URL and title
    kcs_article = state.get('kcs_article', {})
    kcs_url = kcs_article.get('url', '') if kcs_article else ''
    kcs_title = kcs_article.get('title', 'KCS Article') if kcs_article else 'KCS Article'
    
    # Add KCS reference requirement
    combined_requirements.append("Add comment in playbook referencing KCS article: {}".format(kcs_url))
    
    # Add critical requirement for ignore_errors
    combined_requirements.append("CRITICAL: Use ignore_errors: true and failed_when: false on all data collection tasks so the playbook always completes successfully and captures all available data")
    
    # Build the data collection report requirement with explicit format
    # Use quadruple braces to escape for the prompt template (becomes double braces in output)
    num_requirements = len(state.get('data_collection_requirements', []))
    
    report_requirement = """As the LAST task in the playbook, create a 'Generate data collection report' debug task that reports ALL collected data.

**CRITICAL - PLAYBOOK STRUCTURE:**
1. FIRST task: Initialize ALL variables with defaults
2. Collection tasks: Use ignore_errors: true, failed_when: false  
3. Store tasks: Store task name, command, exit code, AND data
4. LAST task: Generate data collection report with | default() filters

**DATA STORAGE - CAPTURE ALL TASK DETAILS:**
For EACH requirement, store: task name, command/module, exit code, data:
```yaml
- name: "Req 1: Check OS version"
  shell: cat /etc/redhat-release
  register: task_1_result
  ignore_errors: true
  failed_when: false
  changed_when: false

- name: Store requirement 1 details
  set_fact:
    task_1_name: "Check OS version"
    task_1_cmd: "cat /etc/redhat-release"
    task_1_rc: "{{{{ task_1_result.rc | default(-1) }}}}"
    data_1: "{{{{ task_1_result.stdout | default('') }}}}"
```

**EXACT REPORT FORMAT REQUIRED (MUST include Task, Command, Exit code, Data):**
- name: Generate data collection report
  debug:
    msg:
      - "========================================================"
      - "        DATA COLLECTION REPORT"
      - "========================================================"
      - "Reference KCS Article: {kcs_url}"
      - "{kcs_title}"
      - "========================================================"
      - ""
      - "REQUIREMENT 1 - {{{{ req_1 }}}}:"
      - "  Task: {{{{ task_1_name | default('Task not recorded') }}}}"
      - "  Command: {{{{ task_1_cmd | default('N/A') }}}}"
      - "  Exit code: {{{{ task_1_rc | default(-1) }}}}"
      - "  Data: {{{{ data_1 | default('Data collection failed') }}}}"
      - ""
      ... (continue for ALL {num_requirements} requirements with same format)
      - ""
      - "========================================================"
      - "        END OF DATA COLLECTION REPORT"
      - "========================================================"

**CRITICAL - ALL 4 FIELDS ARE MANDATORY:**
1. Task: Name of what was done
2. Command: The actual shell/command used (or module name for non-shell)
3. Exit code: The return code from the task
4. Data: The collected output or confirmation of absence

**CRITICAL JINJA2 SYNTAX RULES:**
1. ALWAYS use DOUBLE curly braces: {{{{ variable_name }}}}
2. ALWAYS add | default() filter: {{{{ var | default('fallback') }}}}
3. NEVER use single curly braces - they will print literally!

**VARIABLE INITIALIZATION (FIRST TASK):**
- name: Initialize all data collection variables
  set_fact:
    req_1: "[requirement description]"
    task_1_name: "Not recorded"
    task_1_cmd: "N/A"
    task_1_rc: -1
    data_1: "Not collected yet"
    ... (one set for each requirement)

**WHY ALL 4 FIELDS MATTER:**
- Task: Shows what action was taken
- Command: Shows exactly how data was collected (helps debugging)
- Exit code: Shows if command succeeded (0=success, 1=no match for grep, 2+=error)
- Data: The actual collected information or empty if nothing found

**EXAMPLES:**
✅ CORRECT (all 4 fields):
      - "REQUIREMENT 1 - {{{{ req_1 }}}}:"
      - "  Task: {{{{ task_1_name | default('Task not recorded') }}}}"
      - "  Command: {{{{ task_1_cmd | default('N/A') }}}}"
      - "  Exit code: {{{{ task_1_rc | default(-1) }}}}"
      - "  Data: {{{{ data_1 | default('Data collection failed') }}}}"

❌ WRONG (missing fields):
      - "REQUIREMENT 1 - {{{{ req_1 }}}}:"
      - "  Data: {{{{ data_1 | default('Data collection failed') }}}}"
""".format(
        kcs_url=kcs_url,
        kcs_title=kcs_title,
        num_requirements=num_requirements
    )
    
    # Check if we need to split into multiple playbooks (max 6 requirements per playbook)
    MAX_REQUIREMENTS_PER_PLAYBOOK = 1
    data_reqs = state.get('data_collection_requirements', [])
    
    # Get playbook generation/reuse info
    playbooks_to_generate = state.get('playbooks_to_generate', list(range(1, len(data_reqs) + 1)))
    playbooks_to_reuse = state.get('playbooks_to_reuse', [])
    
    # Build a map of requirement index -> reuse info
    # Format: (new_idx, old_idx, path, status)
    reuse_map = {}
    for new_idx, old_idx, pb_path, status in playbooks_to_reuse:
        reuse_map[new_idx] = {'old_idx': old_idx, 'path': pb_path, 'status': status}
    
    if len(data_reqs) <= MAX_REQUIREMENTS_PER_PLAYBOOK:
        # Single playbook - add report requirement
        combined_requirements.append(report_requirement)
        state['requirements'] = combined_requirements
        state['requirement_batches'] = [combined_requirements]
        state['current_batch_index'] = 0
        state['total_batches'] = 1
        state['playbook_contents'] = []
        state['playbook_outputs'] = []
        
        # Check if this single requirement can reuse existing playbook
        if 1 in reuse_map:
            reuse_info = reuse_map[1]
            state['batch_reuse_info'] = [{
                'index': 0,
                'req_index': 1,
                'old_req_index': reuse_info['old_idx'],  # Track old index for content update
                'reuse': True,
                'status': reuse_info['status'],
                'path': reuse_info['path']
            }]
            print(f"\n✅ Single playbook - REUSE existing ({reuse_info['status']}): {os.path.basename(reuse_info['path'])}")
        else:
            state['batch_reuse_info'] = [{'index': 0, 'req_index': 1, 'old_req_index': 1, 'reuse': False}]
            print(f"\n✅ Single playbook with {len(data_reqs)} requirements (max {MAX_REQUIREMENTS_PER_PLAYBOOK})")
    else:
        # Multiple playbooks needed - split requirements into batches
        # Each batch tracks the original requirement indices
        batches = []
        for i in range(0, len(data_reqs), MAX_REQUIREMENTS_PER_PLAYBOOK):
            batch_reqs = data_reqs[i:i + MAX_REQUIREMENTS_PER_PLAYBOOK]
            # Track original indices (1-based)
            start_idx = i + 1
            batches.append({
                'requirements': batch_reqs,
                'start_index': start_idx,
                'indices': list(range(start_idx, start_idx + len(batch_reqs)))
            })
        
        print(f"\n📦 Splitting {len(data_reqs)} requirements into {len(batches)} playbooks (max {MAX_REQUIREMENTS_PER_PLAYBOOK} each):")
        
        # Build batch reuse info
        batch_reuse_info = []
        for idx, batch in enumerate(batches):
            req_idx = batch['indices'][0]  # First (and usually only) requirement index
            if req_idx in reuse_map:
                reuse_info = reuse_map[req_idx]
                old_req_idx = reuse_info['old_idx']
                batch_reuse_info.append({
                    'index': idx,
                    'req_index': req_idx,
                    'old_req_index': old_req_idx,  # Track old index for content update
                    'reuse': True,
                    'status': reuse_info['status'],
                    'path': reuse_info['path']
                })
                status_icon = "♻️ " if reuse_info['status'] == 'unchanged' else "🔄"
                if req_idx != old_req_idx:
                    print(f"   Playbook part{idx + 1:02d}: Req {req_idx:02d} ← was Req {old_req_idx:02d} [{status_icon} {reuse_info['status'].upper()}] → {os.path.basename(reuse_info['path'])}")
                else:
                    print(f"   Playbook part{idx + 1:02d}: Req {req_idx:02d} [{status_icon} {reuse_info['status'].upper()}] → {os.path.basename(reuse_info['path'])}")
            else:
                batch_reuse_info.append({
                    'index': idx,
                    'req_index': req_idx,
                    'old_req_index': req_idx,  # Same index for new playbooks
                    'reuse': False
                })
                print(f"   Playbook part{idx + 1:02d}: Req {req_idx:02d} [🆕 NEW]")
        
        state['batch_reuse_info'] = batch_reuse_info
        
        # Create requirement batches with their own report requirements
        requirement_batches = []
        for batch_idx, batch_info in enumerate(batches):
            batch_reqs = batch_info['requirements']
            batch_indices = batch_info['indices']
            batch_combined = batch_reqs.copy()
            
            # Add KCS reference
            batch_combined.append("Add comment in playbook referencing KCS article: {}".format(kcs_url))
            
            # Add ignore_errors requirement
            batch_combined.append("CRITICAL: Use ignore_errors: true and failed_when: false on all data collection tasks so the playbook always completes successfully and captures all available data")
            
            # Create batch-specific report requirement with correct requirement indices (2-digit zero-padded)
            batch_num_reqs = len(batch_reqs)
            req_indices_str = ', '.join(f'{i:02d}' for i in batch_indices)
            
            # Build the requirement lines for the report template - ALL 4 FIELDS MANDATORY
            req_report_lines = []
            for local_idx, global_idx in enumerate(batch_indices):
                idx_str = f'{global_idx:02d}'
                req_report_lines.append(f'      - "REQUIREMENT {idx_str} - {{{{{{ req_{idx_str} }}}}}}:"')
                req_report_lines.append(f'      - "  Task: {{{{{{ task_{idx_str}_name | default(\'Task not recorded\') }}}}}}"')
                req_report_lines.append(f'      - "  Command: {{{{{{ task_{idx_str}_cmd | default(\'N/A\') }}}}}}"')
                req_report_lines.append(f'      - "  Exit code: {{{{{{ task_{idx_str}_rc | default(-1) }}}}}}"')
                req_report_lines.append(f'      - "  Data: {{{{{{ data_{idx_str} | default(\'Data collection failed\') }}}}}}"')
                req_report_lines.append('      - ""')
            req_report_block = '\n'.join(req_report_lines)
            
            batch_report = """As the LAST task in the playbook, create a 'Generate data collection report' debug task that reports ALL collected data.

**CRITICAL - PLAYBOOK STRUCTURE:**
1. FIRST task: Initialize ALL variables with defaults
2. Collection tasks: Use ignore_errors: true, failed_when: false  
3. Store tasks: Store task name, command, exit code, AND data
4. LAST task: Generate data collection report with | default() filters

**THIS PLAYBOOK COVERS REQUIREMENT(S): {req_indices_str}**

**DATA STORAGE - CAPTURE ALL TASK DETAILS:**
For EACH requirement, store: task name, command/module, exit code, data:
```yaml
- name: "Req {req_indices_str}: [Task description]"
  shell: [command]
  register: task_{req_indices_str}_result
  ignore_errors: true
  failed_when: false
  changed_when: false

- name: Store requirement {req_indices_str} details
  set_fact:
    task_{req_indices_str}_name: "[Task description]"
    task_{req_indices_str}_cmd: "[command used]"
    task_{req_indices_str}_rc: "{{{{ task_{req_indices_str}_result.rc | default(-1) }}}}"
    data_{req_indices_str}: "{{{{ task_{req_indices_str}_result.stdout | default('') }}}}"
```

**EXACT REPORT FORMAT REQUIRED (ALL 4 FIELDS MANDATORY):**
- name: Generate data collection report (Part {batch_num_padded}/{total_batches_padded} - Requirement {req_indices_str})
  debug:
    msg:
      - "========================================================"
      - "        DATA COLLECTION REPORT (Part {batch_num_padded}/{total_batches_padded})"
      - "========================================================"
      - "Reference KCS Article: {kcs_url}"
      - "{kcs_title}"
      - "========================================================"
      - ""
{req_report_block}
      - "========================================================"
      - "        END OF DATA COLLECTION REPORT (Part {batch_num_padded}/{total_batches_padded})"
      - "========================================================"

**CRITICAL - ALL 4 FIELDS ARE MANDATORY:**
1. Task: Name of what was done
2. Command: The actual shell/command used
3. Exit code: The return code from the task
4. Data: The collected output

**CRITICAL JINJA2 SYNTAX RULES:**
1. ALWAYS use DOUBLE curly braces: {{{{ variable_name }}}}
2. ALWAYS add | default() filter: {{{{ var | default('fallback') }}}}
3. NEVER use single curly braces - they will print literally!
""".format(
                batch_num_padded=f'{batch_idx + 1:02d}',
                total_batches_padded=f'{len(batches):02d}',
                kcs_url=kcs_url,
                req_indices_str=req_indices_str,
                req_report_block=req_report_block,
                kcs_title=kcs_title,
                batch_num_reqs=batch_num_reqs
            )
            batch_combined.append(batch_report)
            requirement_batches.append(batch_combined)
        
        # Store batch information in state
        state['requirement_batches'] = requirement_batches
        state['current_batch_index'] = 0
        state['total_batches'] = len(batches)
        state['playbook_contents'] = []
        state['playbook_outputs'] = []
        
        # Update filename to use the new directory structure
        kcs_id = get_kcs_id_from_state(state)
        state['filename'] = get_playbook_path(kcs_id, part_num=1)
        
        # Set first batch as current requirements
        state['requirements'] = requirement_batches[0]
        print(f"\n✅ Starting with Playbook 01 of {len(batches):02d} ({state['filename']})")
    
    state['example_output'] = ""  # No example output for KCS-based playbooks
    
    print(f"\n✅ Data collection requirements ready ({state['total_batches']} playbook(s) total)")
    
    return state


def update_playbook_with_feedback(existing_playbook: str, error_feedback: str, objective: str) -> str:
    """
    Update an existing playbook based on error feedback instead of regenerating from scratch.
    
    Args:
        existing_playbook: The current playbook content that needs fixing
        error_feedback: The error message or feedback from syntax check/test/analysis
        objective: The original playbook objective
        
    Returns:
        str: Updated playbook content
    """
    from langchain_core.messages import HumanMessage
    
    update_prompt = """You are an expert Ansible playbook developer. You need to FIX an existing playbook based on the error feedback.

**ORIGINAL OBJECTIVE:**
{objective}

**CURRENT PLAYBOOK (needs fixing):**
```yaml
{existing_playbook}
```

**ERROR FEEDBACK:**
{error_feedback}

**TASK:**
Fix the playbook based on the error feedback. Make MINIMAL changes - only fix what's broken.

**RULES:**
1. Keep the overall structure intact
2. Only modify the parts that caused the error
3. Ensure all Jinja2 syntax is correct (use double curly braces for variables)
4. Ensure all YAML syntax is correct
5. Keep ignore_errors: true and failed_when: false on data collection tasks
6. The playbook MUST complete successfully

**CRITICAL - REPORT FORMAT MUST INCLUDE ALL 4 FIELDS:**
The "Generate data collection report" task MUST include these 4 fields for EACH requirement:
```yaml
      - "REQUIREMENT N - {{ req_N }}:"
      - "  Task: {{ task_N_name | default('Task not recorded') }}"
      - "  Command: {{ task_N_cmd | default('N/A') }}"
      - "  Exit code: {{ task_N_rc | default(-1) }}"
      - "  Data: {{ data_N | default('Data collection failed') }}"
```

If the report is missing Task, Command, or Exit code fields, ADD THEM:
1. Store task_N_name with the task description
2. Store task_N_cmd with the shell command used
3. Store task_N_rc with {{ result.rc | default(-1) }}
4. Store data_N with {{ result.stdout | default('') }}

**COMMON YAML FIXES:**

1. Shell commands with colons (:) MUST use multi-line syntax:
   WRONG: shell: grep 'error: failed'
   CORRECT: shell: >
              grep 'error: failed'

2. Strings with backslashes (regex, grep patterns) MUST use literal block scalar (|):
   WRONG: task_cmd: "grep 'pattern1\\|pattern2'"
   CORRECT: task_cmd: |
              grep 'pattern1\\|pattern2'

3. Complex commands in set_fact MUST use | for the value:
   WRONG:
     set_fact:
       task_cmd: "find /var -name '*.log' | xargs grep 'error\\|warn'"
   
   CORRECT:
     set_fact:
       task_cmd: |
         find /var -name '*.log' | xargs grep 'error\\|warn'

4. Parentheses in find commands must be escaped:
   WRONG: find /var -type f ( -name '*.log' )
   CORRECT: find /var -type f \\( -name '*.log' \\)

**OUTPUT:**
Return ONLY the fixed YAML playbook content. Start with --- and do not include markdown code blocks.
"""

    formatted_prompt = update_prompt.format(
        objective=objective,
        existing_playbook=existing_playbook,
        error_feedback=error_feedback[:2000]  # Limit feedback length
    )
    
    print("🔧 Updating existing playbook based on feedback...")
    
    response = model.invoke([HumanMessage(content=formatted_prompt)])
    updated_playbook = response.content.strip()
    
    # Clean up if wrapped in code blocks
    if updated_playbook.startswith("```yaml"):
        updated_playbook = updated_playbook[7:]
    if updated_playbook.startswith("```"):
        updated_playbook = updated_playbook[3:]
    if updated_playbook.endswith("```"):
        updated_playbook = updated_playbook[:-3]
    updated_playbook = updated_playbook.strip()
    
    # Ensure it starts with ---
    if not updated_playbook.startswith("---"):
        updated_playbook = "---\n" + updated_playbook
    
    return updated_playbook


def generate_playbook_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Generate or update playbook using LLM, or reuse existing playbook."""
    print("\n" + "=" * 80)
    
    # Check if this batch can reuse an existing playbook
    batch_idx = state.get('current_batch_index', 0)
    batch_reuse_info = state.get('batch_reuse_info', [])
    current_reuse_info = batch_reuse_info[batch_idx] if batch_idx < len(batch_reuse_info) else {}
    
    can_reuse = current_reuse_info.get('reuse', False)
    reuse_status = current_reuse_info.get('status', '')
    reuse_path = current_reuse_info.get('path', '')
    
    # Check if this is a retry with existing playbook
    is_retry = state['attempt'] > 1 and state.get('playbook_content')
    
    # Determine mode
    if can_reuse and not is_retry and reuse_status == 'unchanged':
        mode = "REUSE_UNCHANGED"
        print(f"STEP 4: Reusing Existing Playbook (Unchanged Requirement)")
    elif can_reuse and not is_retry and reuse_status == 'updated':
        mode = "REUSE_UPDATED"
        print(f"STEP 4: Using Existing Playbook as Baseline (Updated Requirement)")
    elif is_retry:
        mode = "UPDATE"
        print(f"STEP 4: Updating Ansible Playbook (Attempt {state['attempt']}/{state['max_retries']})")
    else:
        mode = "GENERATE"
        print(f"STEP 4: Generating Ansible Playbook (Attempt {state['attempt']}/{state['max_retries']})")
    
    print("=" * 80)
    print(f"Objective: {state['playbook_objective']}")
    print(f"Test Host: {state['test_host']}")
    if state['test_host'] != state['target_host']:
        print(f"Target Host: {state['target_host']}")
    print(f"Become User: {state['become_user']}")
    print(f"Requirements: {len(state['requirements'])} items")
    print(f"Mode: {mode}")
    if can_reuse:
        print(f"Existing playbook: {os.path.basename(reuse_path)}")
    print("=" * 80)
    
    try:
        # Ensure all required state fields exist
        if not state.get('playbook_objective'):
            state['error_message'] = "Playbook objective not set"
            print(f"❌ {state['error_message']}")
            return state
        
        if not state.get('requirements'):
            state['error_message'] = "Requirements not set"
            print(f"❌ {state['error_message']}")
            return state
        
        if mode == "REUSE_UNCHANGED":
            # Load existing playbook directly
            if os.path.isfile(reuse_path):
                with open(reuse_path, 'r') as f:
                    playbook = f.read()
                print(f"\n♻️ Loaded existing playbook: {os.path.basename(reuse_path)}")
                
                # Get old and new requirement indices
                new_req_idx = current_reuse_info.get('req_index', batch_idx + 1)
                old_req_idx = current_reuse_info.get('old_req_index', new_req_idx)
                
                # Get old and new totals
                new_total = state.get('total_batches', 1)
                # Extract old total from playbook content (e.g., "Part 10/12")
                import re
                old_total_match = re.search(r'Part\s+\d+/(\d+)', playbook)
                old_total = int(old_total_match.group(1)) if old_total_match else new_total
                
                # Update playbook content if requirement index or total changed
                needs_update = old_req_idx != new_req_idx or old_total != new_total
                if needs_update:
                    if old_req_idx != new_req_idx:
                        print(f"   📝 Updating requirement index: {old_req_idx} → {new_req_idx}")
                    if old_total != new_total:
                        print(f"   📝 Updating total count: {old_total} → {new_total}")
                    playbook = update_playbook_requirement_index(
                        playbook, old_req_idx, new_req_idx, old_total, new_total
                    )
                
                # Save to new location
                kcs_id = get_kcs_id_from_state(state)
                new_path = get_playbook_path(kcs_id, part_num=batch_idx + 1)
                
                # Always save the (potentially updated) playbook
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                with open(new_path, 'w') as f:
                    f.write(playbook)
                state['filename'] = new_path
                print(f"   💾 Saved to: {os.path.basename(new_path)}")
            else:
                print(f"⚠️ Existing playbook not found: {reuse_path}")
                print("   Falling back to generation...")
                mode = "GENERATE"
        
        if mode == "REUSE_UPDATED":
            # Load existing playbook as baseline, then update with new requirement
            if os.path.isfile(reuse_path):
                with open(reuse_path, 'r') as f:
                    existing_playbook = f.read()
                print(f"\n🔄 Loaded existing playbook as baseline: {os.path.basename(reuse_path)}")
                
                # Update the playbook to use the new requirement
                playbook = update_playbook_with_feedback(
                    existing_playbook=existing_playbook,
                    error_feedback=f"Requirement has been updated. Please update the playbook to collect data for: {state['requirements'][0] if state['requirements'] else 'Unknown requirement'}",
                    objective=state['playbook_objective']
                )
                print("\n📋 Updated playbook based on new requirement:")
            else:
                print(f"⚠️ Existing playbook not found: {reuse_path}")
                print("   Falling back to generation...")
                mode = "GENERATE"
        
        if mode == "UPDATE":
            # UPDATE existing playbook based on error feedback
            error_feedback = state.get('error_message', 'Unknown error')
            print(f"\n📝 Error to fix: {error_feedback[:200]}...")
            
            playbook = update_playbook_with_feedback(
                existing_playbook=state['playbook_content'],
                error_feedback=error_feedback,
                objective=state['playbook_objective']
            )
            
            print("\n📋 Updated Ansible Playbook:")
        
        if mode == "GENERATE":
            # GENERATE new playbook from scratch (first attempt)
            playbook = _original_generate_playbook(
                playbook_objective=state['playbook_objective'],
                target_host=state['test_host'],
                become_user=state['become_user'],
                requirements=state['requirements'],
                example_output=state.get('example_output', '')
            )
            
            print("\n📋 Generated Ansible Playbook:")
        
        print("=" * 80)
        print(playbook)
        print("=" * 80)
        
        state['playbook_content'] = playbook
        state['error_message'] = ""
        
    except Exception as e:
        state['error_message'] = str(e)
        state['playbook_content'] = ""
        print(f"❌ Error generating playbook: {e}")
        import traceback
        print("\n📋 Full traceback:")
        traceback.print_exc()
    
    return state


def increment_attempt_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Increment attempt counter for retry."""
    state['attempt'] += 1
    print(f"\n🔄 Incrementing attempt counter: {state['attempt']}/{state['max_retries']}")
    return state


def save_playbook_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Save playbook to file."""
    if state.get('playbook_content'):
        save_playbook(state['playbook_content'], state['filename'])
        # Verify file was created
        if not os.path.exists(state['filename']):
            state['error_message'] = f"Failed to save playbook to {state['filename']}"
            print(f"❌ {state['error_message']}")
    else:
        state['error_message'] = "No playbook content to save"
        print(f"❌ {state['error_message']}")
    return state


def check_syntax_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Check playbook syntax."""
    # Ensure file exists before checking syntax
    if not os.path.exists(state['filename']):
        state['syntax_valid'] = False
        state['error_message'] = f"Playbook file not found: {state['filename']}"
        print(f"❌ {state['error_message']}")
        return state
    
    is_valid, error_msg = check_playbook_syntax(state['filename'], state['test_host'])
    
    state['syntax_valid'] = is_valid
    if not is_valid:
        state['error_message'] = error_msg
        
        if state['attempt'] < state['max_retries']:
            print(f"\n⚠️  Syntax check failed on attempt {state['attempt']}/{state['max_retries']}")
            print("🔄 Retrying with additional instructions to LLM...")
            error_msg_escaped = error_msg[:200].replace('{', '{{').replace('}', '}}')
            state['requirements'].append(f"IMPORTANT: Previous attempt had syntax error: {error_msg_escaped}")
    
    return state


def test_on_test_host_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Test playbook on test host."""
    batch_idx = state.get('current_batch_index', 0)
    total_batches = state.get('total_batches', 1)
    
    print("\n" + "=" * 80)
    if total_batches > 1:
        print(f"✅ Syntax Valid! Testing Playbook {batch_idx + 1:02d}/{total_batches:02d} on test host: {state['test_host']}...")
    else:
        print(f"✅ Syntax Valid! Now testing on test host: {state['test_host']}...")
    print("=" * 80)
    
    test_success, test_output = test_playbook_on_server(
        state['filename'],
        state['test_host'],
        check_mode=False,
        verbose=False,
        skip_debug=True
    )
    
    state['test_success'] = test_success
    state['test_output'] = test_output
    
    if test_success:
        print("\n" + "=" * 80)
        if total_batches > 1:
            print(f"🎉 SUCCESS! Playbook {batch_idx + 1:02d}/{total_batches:02d} validated on test host: {state['test_host']}!")
        else:
            print(f"🎉 SUCCESS! Playbook validated on test host: {state['test_host']}!")
        print("=" * 80)
        
        # Store playbook content and output for multi-batch scenarios
        if 'playbook_contents' not in state:
            state['playbook_contents'] = []
        if 'playbook_outputs' not in state:
            state['playbook_outputs'] = []
        
        # Add current playbook content and output to lists
        if state.get('playbook_content'):
            state['playbook_contents'].append(state['playbook_content'])
        state['playbook_outputs'].append(test_output)
    else:
        state['error_message'] = test_output
        
        if state['attempt'] < state['max_retries']:
            print(f"\n⚠️  Server test failed on attempt {state['attempt']}/{state['max_retries']}")
            print("🔄 Retrying with test failure feedback to LLM...")
            test_output_escaped = test_output[:300].replace('{', '{{').replace('}', '}}')
            state['requirements'].append(f"IMPORTANT: Previous playbook failed testing: {test_output_escaped}")
    
    return state


def advance_batch_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Advance to the next requirement batch for multi-playbook scenarios."""
    batch_idx = state.get('current_batch_index', 0)
    total_batches = state.get('total_batches', 1)
    requirement_batches = state.get('requirement_batches', [])
    batch_reuse_info = state.get('batch_reuse_info', [])
    
    if batch_idx + 1 < total_batches:
        # Advance to next batch
        new_batch_idx = batch_idx + 1
        state['current_batch_index'] = new_batch_idx
        state['requirements'] = requirement_batches[new_batch_idx]
        state['attempt'] = 1  # Reset attempts for new batch
        state['playbook_content'] = ""  # Reset playbook content
        state['syntax_valid'] = False
        state['test_success'] = False
        
        # Update filename for new batch using the new directory structure
        kcs_id = get_kcs_id_from_state(state)
        state['filename'] = get_playbook_path(kcs_id, part_num=new_batch_idx + 1)
        
        # Get reuse info for this batch
        reuse_info = batch_reuse_info[new_batch_idx] if new_batch_idx < len(batch_reuse_info) else {}
        
        print("\n" + "=" * 80)
        print(f"📦 ADVANCING TO BATCH {new_batch_idx + 1:02d}/{total_batches:02d}")
        print(f"   New filename: {state['filename']}")
        print(f"   Requirements in this batch: {len(requirement_batches[new_batch_idx]) - 3}")  # Subtract boilerplate reqs
        if reuse_info.get('reuse'):
            status = reuse_info.get('status', '')
            icon = "♻️" if status == 'unchanged' else "🔄"
            print(f"   {icon} Reuse status: {status.upper()}")
            print(f"   Existing playbook: {os.path.basename(reuse_info.get('path', ''))}")
        else:
            print(f"   🆕 New playbook will be generated")
        print("=" * 80)
    
    return state


def store_output_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """
    LangGraph node: Check data sufficiency, then store playbook output.
    
    This runs STAGE 1: DATA SUFFICIENCY CHECK for each playbook immediately after testing.
    If data is insufficient and attempts < max_retries, sets error_message for playbook update.
    """
    total_batches = state.get('total_batches', 1)
    batch_idx = state.get('current_batch_index', 0)
    test_output = state.get('test_output', '')
    data_collection_reqs = state.get('data_collection_requirements', [])
    
    # Get the requirement for this batch
    req_idx = batch_idx
    if req_idx < len(data_collection_reqs):
        batch_reqs = [data_collection_reqs[req_idx]]
    else:
        batch_reqs = state.get('requirements', [])[:1]  # Fallback
    
    batch_info = f"Part {batch_idx + 1}/{total_batches}"
    
    # === STAGE 1: DATA SUFFICIENCY CHECK ===
    is_sufficient, message, extracted_report = check_data_sufficiency(
        requirements=batch_reqs,
        playbook_objective=state['playbook_objective'],
        test_output=test_output,
        batch_info=batch_info
    )
    
    if not is_sufficient:
        # Data collection is insufficient - check if we can retry
        if state['attempt'] < state['max_retries']:
            print(f"\n❌ STAGE 1 FAILED: Data collection insufficient")
            print(f"   ⚠️ Playbook {batch_idx + 1:02d}: Data collection INSUFFICIENT")
            print(f"      Reason: {message[:100]}...")
            
            # Pass the feedback message to the playbook update function
            # Include the full advice from the AI analysis
            state['error_message'] = message
            state['data_sufficient'] = False
            
            # Don't store output yet - need to retry
            return state
        else:
            print(f"\n⚠️ Max retries ({state['max_retries']}) reached. Storing output anyway.")
    
    # Data is sufficient OR max retries reached - store the output
    state['data_sufficient'] = True
    
    if 'all_playbook_outputs' not in state:
        state['all_playbook_outputs'] = []
    
    state['all_playbook_outputs'].append({
        'batch': batch_idx + 1,
        'output': test_output,
        'playbook_content': state.get('playbook_content', ''),
        'filename': state.get('filename', ''),
        'extracted_report': extracted_report or ''
    })
    
    if is_sufficient:
        print(f"\n✅ STAGE 1 PASSED: Data collection sufficient for Playbook {batch_idx + 1:02d}/{total_batches:02d}")
    print(f"📦 Stored output for Playbook {batch_idx + 1:02d}/{total_batches:02d}")
    
    return state


def analyze_data_collection_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """
    LangGraph node: PHASE 2 PART 1 - Analyze ALL playbook outputs against data_collection_requirements.txt
    
    This runs AFTER all playbooks are generated and tested.
    Compares collected data against data_collection_requirements.txt.
    Produces a Data Collection Summary for Part 2.
    """
    print("\n" + "=" * 80)
    print("📊 PHASE 2 - PART 1: DATA COLLECTION ANALYSIS")
    print("=" * 80)
    print("Analyzing all playbook outputs against data_collection_requirements.txt")
    print("=" * 80)
    
    total_batches = state.get('total_batches', 1)
    all_outputs = state.get('all_playbook_outputs', [])
    data_collection_reqs = state.get('data_collection_requirements', [])
    
    print(f"\n📋 Data Collection Requirements ({len(data_collection_reqs)} total):")
    for req in data_collection_reqs:
        print(f"   {req}")
    
    print(f"\n📦 Playbook Outputs to Analyze: {len(all_outputs)}")
    
    # Analyze each playbook output and extract reports
    extracted_reports = []
    batch_analysis_results = []
    all_passed = True
    
    for output_info in all_outputs:
        batch_num = output_info['batch']
        output = output_info['output']
        
        print(f"\n--- Analyzing Playbook {batch_num:02d}/{total_batches:02d} ---")
        
        # Get the requirement for this batch (1 requirement per playbook)
        req_idx = batch_num - 1
        if req_idx < len(data_collection_reqs):
            batch_reqs = [data_collection_reqs[req_idx]]
        else:
            batch_reqs = []
        
        batch_info = f"Part {batch_num}/{total_batches}"
        
        # Check data sufficiency for this batch
        is_sufficient, message, extracted_report = check_data_sufficiency(
            requirements=batch_reqs,
            playbook_objective=state['playbook_objective'],
            test_output=output,
            batch_info=batch_info
        )
        
        if extracted_report:
            extracted_reports.append(extracted_report)
        
        batch_analysis_results.append({
            'batch': batch_num,
            'passed': is_sufficient,
            'stage': 'data_sufficiency',
            'message': message[:500] if message else '',
            'requirement': batch_reqs[0] if batch_reqs else ''
        })
        
        if is_sufficient:
            print(f"   ✅ Playbook {batch_num:02d}: Data collection SUFFICIENT")
        else:
            print(f"   ⚠️ Playbook {batch_num:02d}: Data collection INSUFFICIENT")
            print(f"      Reason: {message[:100]}...")
            all_passed = False
    
    # Store results
    state['extracted_reports'] = extracted_reports
    state['batch_analysis_results'] = batch_analysis_results
    
    # Combine all reports into Data Collection Summary
    if extracted_reports:
        combined_report = "\n\n".join([
            f"=== DATA COLLECTION REPORT (Part {i+1}/{len(extracted_reports)}) ===\n{report}"
            for i, report in enumerate(extracted_reports)
        ])
    else:
        combined_report = "\n".join([o.get('output', '') for o in all_outputs])
    
    state['combined_report'] = combined_report
    state['data_collection_summary'] = combined_report
    
    # Summary
    passed_count = sum(1 for r in batch_analysis_results if r.get('passed'))
    
    print("\n" + "=" * 80)
    print("📊 DATA COLLECTION ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"   Total Playbooks: {len(all_outputs)}")
    print(f"   Data Sufficient: {passed_count}")
    print(f"   Data Insufficient: {len(all_outputs) - passed_count}")
    print("-" * 80)
    
    for result in batch_analysis_results:
        status = "✅" if result['passed'] else "⚠️"
        req_text = result.get('requirement', '')[:50]
        print(f"   {status} Req {result['batch']}: {req_text}...")
    
    print("=" * 80)
    
    state['analysis_passed'] = all_passed
    state['analysis_message'] = f"Data collection: {passed_count}/{len(all_outputs)} requirements have sufficient data"
    
    return state


def analyze_compliance_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """
    LangGraph node: PHASE 2 PART 2 - Analyze Data Collection Summary against matching_requirements.txt
    
    This runs AFTER Part 1 (data collection analysis).
    Uses the collected data to evaluate if the system matches the KCS conditions.
    """
    print("\n" + "=" * 80)
    print("🔍 PHASE 2 - PART 2: COMPLIANCE ANALYSIS")
    print("=" * 80)
    print("Analyzing Data Collection Summary against matching_requirements.txt")
    print("=" * 80)
    
    # Get matching requirements
    matching_requirements = state.get('matching_requirements', [])
    data_collection_summary = state.get('data_collection_summary', state.get('combined_report', ''))
    kcs_info = state.get('kcs_article', {})
    
    # Display matching requirements with proper numbering
    print(f"\n📋 Matching Requirements ({len(matching_requirements)} total):")
    for i, req in enumerate(matching_requirements):
        # Check if requirement already has a number prefix
        req_text = req.strip()
        if req_text and req_text[0].isdigit() and '. ' in req_text[:5]:
            # Already numbered
            print(f"   • {req_text}")
        else:
            # Add number
            print(f"   • {i+1}. {req_text}")
    
    print(f"\n📊 Data Collection Summary Length: {len(data_collection_summary)} characters")
    
    # PART 2: Compliance analysis using matching_requirements.txt
    analysis_passed, analysis_message = analyze_compliance_from_report(
        requirements=matching_requirements,
        playbook_objective=state['playbook_objective'],
        combined_report=data_collection_summary,
        kcs_info=kcs_info
    )
    
    state['compliance_passed'] = analysis_passed
    state['compliance_message'] = analysis_message
    
    # Store compliance analysis result
    if 'batch_analysis_results' not in state:
        state['batch_analysis_results'] = []
    state['batch_analysis_results'].append({
        'batch': 'compliance',
        'passed': analysis_passed,
        'stage': 'compliance_analysis',
        'message': analysis_message[:500] if analysis_message else ''
    })
    
    # Display full compliance analysis result (the analyze_compliance_from_report function 
    # already prints the detailed analysis, so we just add a summary here)
    print("\n" + "=" * 80)
    print("📋 COMPLIANCE ANALYSIS SUMMARY")
    print("=" * 80)
    
    if analysis_passed:
        print("✅ OVERALL: Compliance analysis completed successfully")
    else:
        print("❌ OVERALL: Compliance analysis found issues")
    
    # Extract and display summary counts from the analysis message
    if analysis_message:
        # Look for the OVERALL SUMMARY section
        if "OVERALL SUMMARY" in analysis_message:
            summary_start = analysis_message.find("OVERALL SUMMARY")
            summary_section = analysis_message[summary_start:]
            # Extract counts
            import re
            total_match = re.search(r'Total Requirements:\s*(\d+)', summary_section)
            compliant_match = re.search(r'COMPLIANT:\s*(\d+)', summary_section)
            non_compliant_match = re.search(r'NON-COMPLIANT:\s*(\d+)', summary_section)
            unknown_match = re.search(r'UNKNOWN:\s*(\d+)', summary_section)
            
            if total_match:
                print(f"\n📊 Results:")
                print(f"   - Total Requirements: {total_match.group(1)}")
                if compliant_match:
                    print(f"   - COMPLIANT: {compliant_match.group(1)}")
                if non_compliant_match:
                    print(f"   - NON-COMPLIANT: {non_compliant_match.group(1)}")
                if unknown_match:
                    print(f"   - UNKNOWN: {unknown_match.group(1)}")
    
    print("=" * 80)
    
    # Set overall analysis status
    state['analysis_passed'] = analysis_passed
    state['analysis_message'] = analysis_message
    
    return state


def execute_on_target_host_node(state: KCSPlaybookGenerationState) -> KCSPlaybookGenerationState:
    """LangGraph node: Execute playbook(s) on target host and run Stage 2 analysis."""
    
    # If test host is same as target host, analysis was already done
    if state['test_host'] == state['target_host']:
        state['final_success'] = True
        state['final_output'] = state.get('combined_report', state['test_output'])
        state['workflow_complete'] = True
        print("\n" + "=" * 80)
        print("✅ Test host = Target host. Analysis already completed.")
        print("=" * 80)
        return state
    
    total_batches = state.get('total_batches', 1)
    kcs_id = get_kcs_id_from_state(state)
    
    print("\n" + "=" * 80)
    print(f"🚀 EXECUTING ON TARGET HOST: {state['target_host']}")
    print("=" * 80)
    
    # Execute all playbooks on target host and collect reports
    target_reports = []
    target_outputs = []
    all_success = True
    
    for batch_idx in range(total_batches):
        # Get playbook path for this batch
        playbook_file = get_playbook_path(kcs_id, part_num=batch_idx + 1)
        
        if total_batches > 1:
            print(f"\n📦 Executing Playbook {batch_idx + 1:02d}/{total_batches:02d}: {playbook_file}")
        else:
            print(f"\n📦 Executing Playbook: {playbook_file}")
        
        # Execute on target
        success, output = test_playbook_on_server(
            playbook_file,
            state['target_host'],
            check_mode=False,
            verbose=False,
            skip_debug=True
        )
        
        target_outputs.append(output)
        
        if success:
            print(f"   ✅ Execution successful")
            # Extract DATA COLLECTION REPORT
            report = extract_data_collection_report(output)
            if report:
                target_reports.append(report)
                print(f"   📊 Extracted report ({len(report)} chars)")
        else:
            print(f"   ❌ Execution failed")
            all_success = False
    
    # Combine reports from target host
    if target_reports:
        if len(target_reports) > 1:
            target_combined_report = "\n\n".join([
                f"=== TARGET HOST DATA COLLECTION REPORT (Part {i+1}/{len(target_reports)}) ===\n{report}"
                for i, report in enumerate(target_reports)
            ])
        else:
            target_combined_report = target_reports[0]
        
        print("\n" + "=" * 80)
        print(f"📋 COMBINED TARGET HOST REPORTS ({len(target_reports)} reports)")
        print("=" * 80)
        
        # Get requirements for analysis
        data_collection_reqs = state.get('data_collection_requirements', [])
        matching_requirements = state.get('matching_requirements', [])
        kcs_info = state.get('kcs_article', {})
        
        # ============================================================
        # PHASE 2 PART 1: DATA COLLECTION ANALYSIS (Target Host)
        # ============================================================
        print("\n" + "=" * 80)
        print(f"📊 PHASE 2 - PART 1: DATA COLLECTION ANALYSIS (Target Host: {state['target_host']})")
        print("=" * 80)
        print("Analyzing target host playbook outputs against data_collection_requirements.txt")
        print("=" * 80)
        
        print(f"\n📋 Data Collection Requirements ({len(data_collection_reqs)} total):")
        for i, req in enumerate(data_collection_reqs):
            req_text = req.strip()
            if req_text and req_text[0].isdigit() and '. ' in req_text[:5]:
                print(f"   • {req_text}")
            else:
                print(f"   • {i+1}. {req_text}")
        
        print(f"\n📊 Target Host Data Collection Report Length: {len(target_combined_report)} characters")
        
        # Check data sufficiency for target host
        target_data_sufficient = True
        for i, req in enumerate(data_collection_reqs):
            batch_info = f"Part {i+1}/{len(data_collection_reqs)}"
            # Simple check - see if requirement index appears in reports
            req_marker = f"REQUIREMENT {i+1}"
            if req_marker in target_combined_report:
                print(f"   ✅ Requirement {i+1}: Data found in report")
            else:
                print(f"   ⚠️ Requirement {i+1}: Data may be missing from report")
        
        print("\n" + "=" * 80)
        print("📊 TARGET HOST DATA COLLECTION SUMMARY")
        print("=" * 80)
        print(f"   Total Requirements: {len(data_collection_reqs)}")
        print(f"   Reports Collected: {len(target_reports)}")
        print("=" * 80)
        
        # Store target data collection summary
        state['target_combined_report'] = target_combined_report
        state['target_data_collection_summary'] = target_combined_report
        
        # ============================================================
        # PHASE 2 PART 2: COMPLIANCE ANALYSIS (Target Host)
        # ============================================================
        print("\n" + "=" * 80)
        print(f"🔍 PHASE 2 - PART 2: COMPLIANCE ANALYSIS (Target Host: {state['target_host']})")
        print("=" * 80)
        print("Analyzing Data Collection Summary against matching_requirements.txt")
        print("=" * 80)
        
        # Display matching requirements with proper numbering
        print(f"\n📋 Matching Requirements ({len(matching_requirements)} total):")
        for i, req in enumerate(matching_requirements):
            req_text = req.strip()
            if req_text and req_text[0].isdigit() and '. ' in req_text[:5]:
                print(f"   • {req_text}")
            else:
                print(f"   • {i+1}. {req_text}")
        
        print(f"\n📊 Data Collection Summary Length: {len(target_combined_report)} characters")
        
        # Run compliance analysis on target host data
        target_analysis_passed, target_analysis_message = analyze_compliance_from_report(
            requirements=matching_requirements,
            playbook_objective=f"{state['playbook_objective']} (Target Host: {state['target_host']})",
            combined_report=target_combined_report,
            kcs_info=kcs_info
        )
        
        # Store target analysis results
        state['target_analysis_passed'] = target_analysis_passed
        state['target_analysis_message'] = target_analysis_message
        state['target_compliance_passed'] = target_analysis_passed
        state['target_compliance_message'] = target_analysis_message
        
        # Display compliance analysis summary (same format as test host)
        print("\n" + "=" * 80)
        print(f"📋 COMPLIANCE ANALYSIS SUMMARY (Target Host: {state['target_host']})")
        print("=" * 80)
        
        if target_analysis_passed:
            print("✅ OVERALL: Compliance analysis completed successfully")
        else:
            print("❌ OVERALL: Compliance analysis found issues")
        
        # Extract and display summary counts from the analysis message
        if target_analysis_message:
            if "OVERALL SUMMARY" in target_analysis_message:
                summary_start = target_analysis_message.find("OVERALL SUMMARY")
                summary_section = target_analysis_message[summary_start:]
                
                total_match = re.search(r'Total Requirements:\s*(\d+)', summary_section)
                compliant_match = re.search(r'COMPLIANT:\s*(\d+)', summary_section)
                non_compliant_match = re.search(r'NON-COMPLIANT:\s*(\d+)', summary_section)
                unknown_match = re.search(r'UNKNOWN:\s*(\d+)', summary_section)
                
                if total_match:
                    print(f"\n📊 Results:")
                    print(f"   - Total Requirements: {total_match.group(1)}")
                    if compliant_match:
                        print(f"   - COMPLIANT: {compliant_match.group(1)}")
                    if non_compliant_match:
                        print(f"   - NON-COMPLIANT: {non_compliant_match.group(1)}")
                    if unknown_match:
                        print(f"   - UNKNOWN: {unknown_match.group(1)}")
        
        print("=" * 80)
        
        # Add to batch results
        state['batch_analysis_results'].append({
            'batch': 'target_final',
            'passed': target_analysis_passed,
            'stage': 'target_compliance_analysis',
            'host': state['target_host'],
            'message': target_analysis_message[:500] if target_analysis_message else ''
        })
    
    state['final_success'] = all_success
    state['final_output'] = '\n\n'.join(target_outputs)
    state['workflow_complete'] = True
    
    if all_success:
        print("\n" + "=" * 80)
        print(f"🎊 COMPLETE SUCCESS! All playbooks executed on target: {state['target_host']}!")
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print(f"⚠️  Some executions on target host {state['target_host']} had issues")
        print("=" * 80)
    
    return state


# Conditional edge functions
def should_continue_after_kcs_search(state: KCSPlaybookGenerationState) -> Literal["generate_matching", "end"]:
    """Conditional edge: Decide what to do after KCS search."""
    if state.get('error_message') or not state.get('kcs_article'):
        return "end"
    return "generate_matching"


def should_continue_after_matching(state: KCSPlaybookGenerationState) -> Literal["generate_data_collection", "end"]:
    """Conditional edge: Decide what to do after matching requirements generation."""
    if state.get('error_message') or not state.get('matching_requirements'):
        return "end"
    return "generate_data_collection"


def should_continue_after_data_collection(state: KCSPlaybookGenerationState) -> Literal["generate_playbook", "end"]:
    """Conditional edge: Decide what to do after data collection requirements generation."""
    if state.get('error_message') or not state.get('data_collection_requirements'):
        return "end"
    return "generate_playbook"


def should_continue_after_syntax(state: KCSPlaybookGenerationState) -> Literal["test_on_test_host", "retry", "end"]:
    """Conditional edge: Decide what to do after syntax check."""
    if not state['syntax_valid']:
        if state['attempt'] < state['max_retries']:
            return "retry"
        else:
            return "end"
    return "test_on_test_host"


def should_continue_after_test(state: KCSPlaybookGenerationState) -> Literal["store_output", "retry", "end"]:
    """Conditional edge: Decide what to do after test execution."""
    if not state['test_success']:
        if state['attempt'] < state['max_retries']:
            return "retry"
        else:
            return "end"
    
    # Test succeeded - store output and continue (no analysis during generation phase)
    return "store_output"


def should_continue_after_store(state: KCSPlaybookGenerationState) -> Literal["analyze_data_collection", "advance_batch", "retry"]:
    """Conditional edge: After storing output, check data sufficiency, more batches, or start analysis."""
    
    # Check if data was insufficient and we should retry
    if not state.get('data_sufficient', True):
        if state['attempt'] < state['max_retries']:
            return "retry"
    
    # Data is sufficient or max retries reached - proceed
    total_batches = state.get('total_batches', 1)
    current_batch = state.get('current_batch_index', 0)
    
    if current_batch + 1 < total_batches:
        # More batches to generate
        return "advance_batch"
    else:
        # All playbooks generated - start Phase 2 Analysis
        return "analyze_data_collection"


def should_continue_after_data_analysis(state: KCSPlaybookGenerationState) -> Literal["analyze_compliance", "end"]:
    """Conditional edge: After data collection analysis, proceed to compliance analysis."""
    # Always proceed to compliance analysis (Part 2)
    return "analyze_compliance"


def should_continue_after_final_analysis(state: KCSPlaybookGenerationState) -> Literal["execute_on_target", "end"]:
    """Conditional edge: Decide what to do after Stage 2 compliance analysis."""
    # Always proceed to execute on target after final analysis
    # (compliance analysis is informational, doesn't block execution)
    return "execute_on_target"


def should_continue_after_final(state: KCSPlaybookGenerationState) -> Literal["end"]:
    """Conditional edge: After final execution, always end."""
    return "end"


def create_kcs_playbook_workflow() -> StateGraph:
    """Create the LangGraph workflow for KCS-to-playbook generation."""
    
    workflow = StateGraph(KCSPlaybookGenerationState)
    
    # Add nodes
    workflow.add_node("search_kcs", search_kcs_node)
    workflow.add_node("generate_matching", generate_matching_requirements_node)
    workflow.add_node("generate_data_collection", generate_data_collection_requirements_node)
    workflow.add_node("generate_playbook", generate_playbook_node)
    workflow.add_node("save", save_playbook_node)
    workflow.add_node("check_syntax", check_syntax_node)
    workflow.add_node("test_on_test_host", test_on_test_host_node)
    workflow.add_node("advance_batch", advance_batch_node)  # For multi-playbook scenarios
    workflow.add_node("store_output", store_output_node)  # Store output during generation phase
    workflow.add_node("analyze_data_collection", analyze_data_collection_node)  # Phase 2 Part 1: vs data_collection_requirements.txt
    workflow.add_node("analyze_compliance", analyze_compliance_node)  # Phase 2 Part 2: vs matching_requirements.txt
    workflow.add_node("execute_on_target", execute_on_target_host_node)
    workflow.add_node("increment_attempt", increment_attempt_node)
    
    # Define edges
    workflow.set_entry_point("search_kcs")
    
    workflow.add_conditional_edges(
        "search_kcs",
        should_continue_after_kcs_search,
        {
            "generate_matching": "generate_matching",
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "generate_matching",
        should_continue_after_matching,
        {
            "generate_data_collection": "generate_data_collection",
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "generate_data_collection",
        should_continue_after_data_collection,
        {
            "generate_playbook": "generate_playbook",
            "end": END
        }
    )
    
    workflow.add_edge("generate_playbook", "save")
    workflow.add_edge("save", "check_syntax")
    workflow.add_edge("increment_attempt", "generate_playbook")
    
    workflow.add_conditional_edges(
        "check_syntax",
        should_continue_after_syntax,
        {
            "test_on_test_host": "test_on_test_host",
            "retry": "increment_attempt",
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "test_on_test_host",
        should_continue_after_test,
        {
            "store_output": "store_output",  # Store output (no analysis during generation)
            "retry": "increment_attempt",
            "end": END
        }
    )
    
    # After storing output, check data sufficiency, more batches, or start analysis phase
    workflow.add_conditional_edges(
        "store_output",
        should_continue_after_store,
        {
            "retry": "increment_attempt",  # Data insufficient, retry with feedback
            "advance_batch": "advance_batch",  # More playbooks to generate
            "analyze_data_collection": "analyze_data_collection"  # All done, start Phase 2
        }
    )
    
    # After advancing batch, go back to generate new playbook
    workflow.add_edge("advance_batch", "generate_playbook")
    
    # Phase 2 Part 1: After data collection analysis, proceed to compliance analysis
    workflow.add_conditional_edges(
        "analyze_data_collection",
        should_continue_after_data_analysis,
        {
            "analyze_compliance": "analyze_compliance",  # Part 2: matching requirements
            "end": END
        }
    )
    
    # Phase 2 Part 2: After compliance analysis, proceed to execute on target
    workflow.add_conditional_edges(
        "analyze_compliance",
        should_continue_after_final_analysis,
        {
            "execute_on_target": "execute_on_target",
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "execute_on_target",
        should_continue_after_final,
        {
            "end": END
        }
    )
    
    return workflow.compile()


def main():
    """Main execution function."""
    
    parser = argparse.ArgumentParser(
        description='Generate Ansible playbooks from Red Hat KCS articles using LangGraph',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for a KCS article and generate playbook
  python3 kcs_langgraph_playbook.py --search "kernel panic"
  
  # Specify custom target host
  python3 kcs_langgraph_playbook.py --search "systemd failed" --target-host 192.168.122.16
  
  # Two-stage execution
  python3 kcs_langgraph_playbook.py --search "network timeout" \\
    --test-host 192.168.122.16 \\
    --target-host 192.168.122.17
"""
    )
    
    parser.add_argument(
        '--search', '-s',
        type=str,
        required=True,
        help='Search query for Red Hat KCS articles'
    )
    
    parser.add_argument(
        '--target-host', '-t',
        type=str,
        default='192.168.122.16',
        help='Target host to execute the playbook on (default: 192.168.122.16)'
    )
    
    parser.add_argument(
        '--test-host',
        type=str,
        default=None,
        help='Test host for validation before target execution (if not specified, uses target-host)'
    )
    
    parser.add_argument(
        '--become-user', '-u',
        type=str,
        default='root',
        help='User to become when executing tasks (default: root)'
    )
    
    # NOTE: --filename is deprecated. Playbooks are now saved to:
    # ./playbooks/verification/<kcs_id>/kcs_verification_<kcs_id>_partN.yml
    
    parser.add_argument(
        '--num-results',
        type=int,
        default=1,
        help='Number of KCS articles to retrieve (default: 1, uses first result)'
    )
    
    parser.add_argument(
        '--max-retries', '-r',
        type=int,
        default=None,
        help='Maximum number of retry attempts (default: auto-calculated)'
    )
    
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not automatically open KCS article in web browser'
    )
    
    args = parser.parse_args()
    
    # Determine test_host
    test_host = args.test_host if args.test_host else args.target_host
    
    # Calculate max retries
    if args.max_retries is None:
        max_retries = 10  # Default to 10 for playbook generation/data sufficiency retries
        print(f"\n💡 Auto-calculated max retries: {max_retries}")
    else:
        max_retries = args.max_retries
    
    # Display configuration
    print("\n" + "=" * 80)
    print("🎯 CONFIGURATION (KCS LangGraph Workflow)")
    print("=" * 80)
    print(f"Search Query:   {args.search}")
    print(f"Test Host:      {test_host}")
    if test_host != args.target_host:
        print(f"Target Host:    {args.target_host}")
    print(f"Become User:    {args.become_user}")
    print(f"Max Retries:    {max_retries}")
    print(f"Playbook Dir:   ./playbooks/verification/<kcs_id>/")
    print("=" * 80)
    
    # Initialize state
    # NOTE: filename will be set after KCS search based on the KCS article ID
    initial_state: KCSPlaybookGenerationState = {
        "search_query": args.search,
        "target_host": args.target_host,
        "test_host": test_host,
        "become_user": args.become_user,
        "filename": "",  # Will be set after KCS search
        "max_retries": max_retries,
        "num_kcs_results": args.num_results,
        "no_browser": args.no_browser,
        "kcs_results": {},
        "kcs_article": {},
        "access_token": "",
        # Existing docs state (for incremental updates)
        "existing_docs": {},
        "use_existing_docs": False,
        "requirement_changes": {},
        "playbooks_to_generate": [],
        "playbooks_to_reuse": [],
        "batch_reuse_info": [],
        # Requirements
        "matching_requirements": [],
        "data_collection_requirements": [],
        "playbook_objective": "",
        # Multi-playbook support (max 6 requirements per playbook)
        "requirement_batches": [],
        "current_batch_index": 0,
        "playbook_contents": [],
        "playbook_outputs": [],
        "total_batches": 1,
        # Phase 2 Analysis state
        "all_playbook_outputs": [],
        "batch_analysis_results": [],
        "extracted_reports": [],
        "data_collection_summary": "",
        "combined_report": "",
        "compliance_passed": False,
        "compliance_message": "",
        "target_combined_report": "",
        "target_analysis_passed": False,
        "target_analysis_message": "",
        # Standard playbook state
        "requirements": [],
        "example_output": "",
        "attempt": 1,
        "playbook_content": "",
        "syntax_valid": False,
        "test_success": False,
        "analysis_passed": False,
        "analysis_message": "",
        "final_success": False,
        "error_message": "",
        "test_output": "",
        "final_output": "",
        "should_retry": False,
        "workflow_complete": False,
    }
    
    # Create and run workflow
    try:
        print("\n🔄 Starting KCS LangGraph workflow...")
        workflow = create_kcs_playbook_workflow()
        
        # Increase recursion limit for multi-batch scenarios
        # Each batch can take multiple attempts, so we need more headroom
        recursion_limit = max(600, max_retries * 8 * 6)  # max_retries * max_batches * nodes_per_iteration
        final_state = workflow.invoke(
            initial_state,
            {"recursion_limit": recursion_limit}
        )
        
        # Check results
        if final_state['workflow_complete'] and final_state['test_success']:
            print("\n" + "=" * 80)
            print("📊 EXECUTION SUMMARY")
            print("=" * 80)
            print(f"✅ Workflow completed successfully!")
            
            total_batches = final_state.get('total_batches', 1)
            kcs_id = get_kcs_id_from_state(final_state)
            batch_reuse_info = final_state.get('batch_reuse_info', [])
            
            # Count reuse statistics
            reused_count = sum(1 for info in batch_reuse_info if info.get('reuse'))
            generated_count = total_batches - reused_count
            
            print("\n   ━━━ PHASE 1: PLAYBOOK GENERATION ━━━")
            if total_batches > 1:
                print(f"   📦 Generated {total_batches} playbooks:")
                print(f"   📁 Directory: ./playbooks/verification/{kcs_id}/")
                if reused_count > 0:
                    print(f"   ♻️  Reused: {reused_count} playbook(s), 🆕 Generated: {generated_count} playbook(s)")
                for i in range(total_batches):
                    part_filename = get_playbook_path(kcs_id, part_num=i + 1)
                    # Get reuse status
                    reuse_info = batch_reuse_info[i] if i < len(batch_reuse_info) else {}
                    if reuse_info.get('reuse'):
                        status_icon = "♻️" if reuse_info.get('status') == 'unchanged' else "🔄"
                        print(f"      ✅ Playbook {i + 1:02d}: {os.path.basename(part_filename)} [{status_icon} {reuse_info.get('status', '').upper()}]")
                    else:
                        print(f"      ✅ Playbook {i + 1:02d}: {os.path.basename(part_filename)} [🆕 NEW]")
            else:
                print(f"   📁 Playbook path: {final_state['filename']}")
                if batch_reuse_info and batch_reuse_info[0].get('reuse'):
                    status = batch_reuse_info[0].get('status', '')
                    icon = "♻️" if status == 'unchanged' else "🔄"
                    print(f"   {icon} Reused existing playbook ({status.upper()})")
            
            if final_state.get('kcs_article'):
                print(f"\n   📄 KCS Article: {final_state['kcs_article'].get('title', 'N/A')}")
                print(f"   🔗 KCS URL: {final_state['kcs_article'].get('url', 'N/A')}")
            
            # Phase 2 Part 1: Data Collection Analysis
            print("\n   ━━━ PHASE 2 PART 1: DATA COLLECTION ANALYSIS ━━━")
            print(f"   📋 Data Collection Requirements: {len(final_state.get('data_collection_requirements', []))}")
            batch_results = [r for r in final_state.get('batch_analysis_results', []) if r.get('stage') == 'data_sufficiency']
            passed_count = sum(1 for r in batch_results if r.get('passed'))
            print(f"   📊 Data Sufficient: {passed_count}/{len(batch_results)} requirements")
            for result in batch_results:
                status = "✅" if result.get('passed') else "⚠️"
                req_text = result.get('requirement', '')[:40] if result.get('requirement') else ''
                print(f"      {status} Req {result.get('batch', '?')}: {req_text}...")
            
            # Phase 2 Part 2: Compliance Analysis
            print("\n   ━━━ PHASE 2 PART 2: COMPLIANCE ANALYSIS ━━━")
            print(f"   📋 Matching Requirements: {len(final_state.get('matching_requirements', []))}")
            
            # Test host analysis
            test_host = final_state.get('test_host', 'N/A')
            compliance_passed = final_state.get('compliance_passed', False)
            compliance_status = "✅ MATCHES KCS" if compliance_passed else "❌ DOES NOT MATCH"
            print(f"   🖥️  Test Host ({test_host}): {compliance_status}")
            
            # Target host analysis (if different from test host)
            target_host = final_state.get('target_host', 'N/A')
            if target_host != test_host:
                target_analysis_passed = final_state.get('target_analysis_passed', False)
                target_status = "✅ COMPLETE" if target_analysis_passed else "⚠️ ISSUES"
                print(f"      Target Host ({target_host}): {target_status}")
            
            print("=" * 80)
        else:
            print("\n" + "=" * 80)
            print("📊 EXECUTION SUMMARY")
            print("=" * 80)
            print(f"❌ Workflow failed")
            total_batches = final_state.get('total_batches', 1)
            current_batch = final_state.get('current_batch_index', 0)
            if total_batches > 1:
                print(f"   Failed at playbook: {current_batch + 1}/{total_batches}")
            print(f"   Total attempts: {final_state['attempt']}/{max_retries}")
            print(f"   Last error: {final_state['error_message'][:200] if final_state.get('error_message') else 'Unknown error'}")
            print("=" * 80)
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Error in LangGraph workflow: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

