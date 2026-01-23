#!/usr/bin/env python3
"""
KCS Status Checker - Quick check of existing files for a KCS ID.

Usage:
    python kcs_status.py <kcs_id>
"""

import os
import sys
import glob
import re


BASE_PLAYBOOK_DIR = "./playbooks/verification"


def get_verification_dir(kcs_id: str) -> str:
    """Get the verification directory for a KCS ID."""
    return os.path.join(BASE_PLAYBOOK_DIR, kcs_id)


def count_requirements(filepath: str) -> int:
    """Count non-empty, non-comment lines in requirements file."""
    if not os.path.isfile(filepath):
        return 0
    
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    return len([l for l in lines if l.strip() and not l.strip().startswith('#')])


def find_playbooks(kcs_id: str) -> list:
    """Find all playbook files for a KCS ID."""
    verification_dir = get_verification_dir(kcs_id)
    pattern = os.path.join(verification_dir, f"kcs_verification_{kcs_id}_part*.yml")
    
    playbooks = glob.glob(pattern)
    
    def extract_part_num(path):
        match = re.search(r'part(\d+)\.yml$', path)
        return int(match.group(1)) if match else 0
    
    return sorted(playbooks, key=extract_part_num)


def check_status(kcs_id: str) -> dict:
    """Check the status of files for a KCS ID."""
    verification_dir = get_verification_dir(kcs_id)
    
    status = {
        'kcs_id': kcs_id,
        'directory_exists': os.path.isdir(verification_dir),
        'matching_requirements': {
            'path': os.path.join(verification_dir, 'matching_requirements.txt'),
            'exists': False,
            'count': 0
        },
        'data_collection_requirements': {
            'path': os.path.join(verification_dir, 'data_collection_requirements.txt'),
            'exists': False,
            'count': 0
        },
        'playbooks': {
            'paths': [],
            'count': 0
        },
        'ready_for_testing': False
    }
    
    # Check matching requirements
    matching_path = status['matching_requirements']['path']
    if os.path.isfile(matching_path):
        status['matching_requirements']['exists'] = True
        status['matching_requirements']['count'] = count_requirements(matching_path)
    
    # Check data collection requirements
    data_path = status['data_collection_requirements']['path']
    if os.path.isfile(data_path):
        status['data_collection_requirements']['exists'] = True
        status['data_collection_requirements']['count'] = count_requirements(data_path)
    
    # Check playbooks
    playbooks = find_playbooks(kcs_id)
    status['playbooks']['paths'] = playbooks
    status['playbooks']['count'] = len(playbooks)
    
    # Determine if ready for testing
    status['ready_for_testing'] = (
        status['matching_requirements']['exists'] and
        status['data_collection_requirements']['exists'] and
        status['playbooks']['count'] > 0
    )
    
    return status


def print_status(status: dict) -> None:
    """Print status in a formatted way."""
    kcs_id = status['kcs_id']
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                    KCS Status Report                         ║
╠══════════════════════════════════════════════════════════════╣
║  KCS ID: {kcs_id:<52}║
╚══════════════════════════════════════════════════════════════╝
""")
    
    # Directory
    dir_icon = "✅" if status['directory_exists'] else "❌"
    print(f"{dir_icon} Verification directory: {BASE_PLAYBOOK_DIR}/{kcs_id}/")
    
    # Matching requirements
    mr = status['matching_requirements']
    mr_icon = "✅" if mr['exists'] else "❌"
    print(f"\n{mr_icon} Matching Requirements:")
    print(f"   Path: {mr['path']}")
    if mr['exists']:
        print(f"   Count: {mr['count']} requirements")
    else:
        print("   Status: NOT FOUND")
    
    # Data collection requirements
    dcr = status['data_collection_requirements']
    dcr_icon = "✅" if dcr['exists'] else "❌"
    print(f"\n{dcr_icon} Data Collection Requirements:")
    print(f"   Path: {dcr['path']}")
    if dcr['exists']:
        print(f"   Count: {dcr['count']} requirements")
    else:
        print("   Status: NOT FOUND")
    
    # Playbooks
    pb = status['playbooks']
    pb_icon = "✅" if pb['count'] > 0 else "❌"
    print(f"\n{pb_icon} Playbooks:")
    if pb['count'] > 0:
        print(f"   Count: {pb['count']} playbooks")
        for path in pb['paths']:
            print(f"   - {os.path.basename(path)}")
    else:
        print("   Status: NO PLAYBOOKS FOUND")
    
    # Ready for testing
    print(f"\n{'=' * 60}")
    if status['ready_for_testing']:
        print("✅ READY FOR TESTING")
        print(f"\nRun: python kcs_playbook_tester.py {kcs_id}")
    else:
        print("❌ NOT READY FOR TESTING")
        print("\nMissing files:")
        if not mr['exists']:
            print(f"  - {mr['path']}")
        if not dcr['exists']:
            print(f"  - {dcr['path']}")
        if pb['count'] == 0:
            print(f"  - Playbooks in {BASE_PLAYBOOK_DIR}/{kcs_id}/")
    
    print()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python kcs_status.py <kcs_id>")
        print("Example: python kcs_status.py 7101627")
        sys.exit(1)
    
    kcs_id = sys.argv[1]
    status = check_status(kcs_id)
    print_status(status)
    
    sys.exit(0 if status['ready_for_testing'] else 1)


if __name__ == "__main__":
    main()

