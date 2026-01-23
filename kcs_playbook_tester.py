#!/usr/bin/env python3
"""
KCS Playbook Tester - Simplified workflow for testing existing playbooks.

This module skips requirement and playbook generation when files already exist.
It focuses on:
1. Loading existing requirements and playbooks
2. Testing playbooks (syntax check, run on test host)
3. Checking data sufficiency
4. Updating playbooks based on feedback
5. Running analysis

Usage:
    python kcs_playbook_tester.py <kcs_id> [--test-host <host>] [--max-retries <n>]
"""

import os
import sys
import glob
import re
import argparse
from typing import TypedDict, List, Optional, Dict, Any
from datetime import datetime


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_TEST_HOST = "localhost"
DEFAULT_MAX_RETRIES = 10
BASE_PLAYBOOK_DIR = "./playbooks/verification"


# ============================================================================
# State Definition
# ============================================================================

class PlaybookTestState(TypedDict, total=False):
    """State for playbook testing workflow."""
    kcs_id: str
    matching_requirements: List[str]
    data_collection_requirements: List[str]
    playbook_paths: List[str]
    current_batch: int
    total_batches: int
    test_host: str
    max_retries: int
    attempt: int
    
    # Current playbook state
    current_playbook_path: str
    current_playbook_content: str
    current_requirement: str
    
    # Test results
    syntax_valid: bool
    test_output: str
    data_sufficient: bool
    error_message: str
    
    # Stored outputs for analysis
    playbook_outputs: Dict[str, str]
    
    # Analysis results
    data_collection_summary: str
    compliance_result: str


# ============================================================================
# File Utilities
# ============================================================================

def get_verification_dir(kcs_id: str) -> str:
    """Get the verification directory for a KCS ID."""
    return os.path.join(BASE_PLAYBOOK_DIR, kcs_id)


def get_requirements_path(kcs_id: str, req_type: str = "matching") -> str:
    """Get path to requirements file."""
    filename = f"{req_type}_requirements.txt"
    return os.path.join(get_verification_dir(kcs_id), filename)


def load_requirements(filepath: str) -> List[str]:
    """Load requirements from a text file."""
    if not os.path.isfile(filepath):
        return []
    
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    requirements = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            requirements.append(line)
    
    return requirements


def find_playbooks(kcs_id: str) -> List[str]:
    """Find all playbook files for a KCS ID, sorted by part number."""
    verification_dir = get_verification_dir(kcs_id)
    pattern = os.path.join(verification_dir, f"kcs_verification_{kcs_id}_part*.yml")
    
    playbooks = glob.glob(pattern)
    
    # Sort by part number
    def extract_part_num(path):
        match = re.search(r'part(\d+)\.yml$', path)
        return int(match.group(1)) if match else 0
    
    return sorted(playbooks, key=extract_part_num)


def load_playbook(path: str) -> str:
    """Load playbook content from file."""
    if not os.path.isfile(path):
        return ""
    
    with open(path, 'r') as f:
        return f.read()


def save_playbook(path: str, content: str) -> None:
    """Save playbook content to file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


# ============================================================================
# Playbook Testing Functions
# ============================================================================

def check_syntax(playbook_path: str) -> tuple[bool, str]:
    """
    Check playbook syntax using ansible-navigator.
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    import subprocess
    
    try:
        result = subprocess.run(
            [
                "ansible-navigator", "run", playbook_path,
                "--mode", "stdout",
                "--syntax-check",
                "--pae", "false"
            ],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            return True, ""
        else:
            error_msg = result.stdout + "\n" + result.stderr
            return False, error_msg.strip()
            
    except subprocess.TimeoutExpired:
        return False, "Syntax check timed out after 60 seconds"
    except FileNotFoundError:
        return False, "ansible-navigator not found. Please ensure it's installed."
    except Exception as e:
        return False, f"Syntax check failed: {str(e)}"


def run_playbook(playbook_path: str, test_host: str = "localhost") -> tuple[bool, str]:
    """
    Run playbook on test host using ansible-navigator.
    
    Returns:
        Tuple of (success, output)
    """
    import subprocess
    
    try:
        # Create a temporary inventory
        inventory_content = f"{test_host} ansible_connection=local\n"
        inventory_path = "/tmp/kcs_test_inventory"
        with open(inventory_path, 'w') as f:
            f.write(inventory_content)
        
        result = subprocess.run(
            [
                "ansible-navigator", "run", playbook_path,
                "-i", inventory_path,
                "--mode", "stdout",
                "--pae", "false"
            ],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr
        
        return result.returncode == 0, output.strip()
        
    except subprocess.TimeoutExpired:
        return False, "Playbook execution timed out after 300 seconds"
    except FileNotFoundError:
        return False, "ansible-navigator not found. Please ensure it's installed."
    except Exception as e:
        return False, f"Playbook execution failed: {str(e)}"


def check_data_sufficiency(playbook_output: str, requirement: str) -> tuple[bool, str]:
    """
    Check if the playbook output contains sufficient data.
    
    Uses the AI-based check from the existing module.
    
    Returns:
        Tuple of (is_sufficient, feedback_message)
    """
    from deepseek_generate_playbook import check_data_sufficiency as ai_check
    
    try:
        # The original function signature is:
        # check_data_sufficiency(requirements, playbook_objective, test_output, batch_info)
        # Returns: tuple[bool, str, str] - (is_sufficient, analysis_result, feedback)
        
        requirements = [requirement]
        playbook_objective = f"Collect data to verify: {requirement}"
        
        is_sufficient, analysis_result, feedback = ai_check(
            requirements=requirements,
            playbook_objective=playbook_objective,
            test_output=playbook_output,
            batch_info=""
        )
        
        # Combine analysis and feedback for return
        combined_feedback = f"{analysis_result}\n\n{feedback}" if feedback else analysis_result
        
        return is_sufficient, combined_feedback
            
    except Exception as e:
        return False, f"Data sufficiency check failed: {str(e)}"


# ============================================================================
# Playbook Update Functions
# ============================================================================

def update_playbook_with_feedback(
    playbook_content: str,
    error_feedback: str,
    requirement: str
) -> str:
    """
    Update playbook based on error feedback using AI.
    
    Uses the existing update function from kcs_langgraph_playbook.
    """
    from kcs_langgraph_playbook import update_playbook_with_feedback as ai_update
    
    try:
        # Create a minimal objective for context
        objective = f"Collect data to verify: {requirement}"
        
        updated = ai_update(
            existing_playbook=playbook_content,
            error_feedback=error_feedback,
            objective=objective
        )
        
        return updated
        
    except Exception as e:
        print(f"❌ Failed to update playbook: {e}")
        return playbook_content


# ============================================================================
# Analysis Functions
# ============================================================================

def analyze_data_collection(
    playbook_outputs: Dict[str, str],
    data_collection_requirements: List[str]
) -> str:
    """
    Analyze all playbook outputs against data collection requirements.
    
    Returns a summary of what data was collected.
    """
    from langchain_deepseek import ChatDeepSeek
    
    llm = ChatDeepSeek(model="deepseek-chat", temperature=0)
    
    # Combine all outputs
    combined_output = "\n\n".join([
        f"=== Playbook: {os.path.basename(path)} ===\n{output}"
        for path, output in playbook_outputs.items()
    ])
    
    # Format requirements
    req_text = "\n".join([f"{i+1}. {req}" for i, req in enumerate(data_collection_requirements)])
    
    prompt = f"""Analyze the following playbook outputs against the data collection requirements.

DATA COLLECTION REQUIREMENTS:
{req_text}

PLAYBOOK OUTPUTS:
{combined_output}

For each requirement, determine:
1. Was data collected? (YES/NO/PARTIAL)
2. What specific data was found?
3. Any issues or missing information?

Provide a structured summary in this format:

=== DATA COLLECTION SUMMARY ===

Requirement 1: [requirement text]
- Status: [YES/NO/PARTIAL]
- Data Found: [summary of data]
- Notes: [any issues]

[Continue for all requirements]

=== OVERALL STATUS ===
- Total Requirements: [N]
- Fully Collected: [N]
- Partially Collected: [N]
- Not Collected: [N]
"""
    
    response = llm.invoke(prompt)
    return response.content


def analyze_compliance(
    data_collection_summary: str,
    matching_requirements: List[str]
) -> str:
    """
    Analyze compliance based on collected data and matching requirements.
    
    Returns a compliance analysis report.
    """
    from langchain_deepseek import ChatDeepSeek
    
    llm = ChatDeepSeek(model="deepseek-chat", temperature=0)
    
    # Format requirements
    req_text = "\n".join([f"{i+1}. {req}" for i, req in enumerate(matching_requirements)])
    
    prompt = f"""Based on the data collection summary, analyze compliance against the matching requirements.

MATCHING REQUIREMENTS (conditions that should be met):
{req_text}

DATA COLLECTION SUMMARY:
{data_collection_summary}

For each matching requirement, determine:
1. Is the requirement MET, NOT MET, or UNABLE TO DETERMINE?
2. What evidence supports this conclusion?
3. Any recommendations?

Provide a structured compliance report:

=== COMPLIANCE ANALYSIS REPORT ===

Requirement 1: [requirement text]
- Status: [MET/NOT MET/UNABLE TO DETERMINE]
- Evidence: [supporting data from collection]
- Recommendation: [if any]

[Continue for all requirements]

=== COMPLIANCE SUMMARY ===
- Total Requirements: [N]
- MET: [N]
- NOT MET: [N]
- UNABLE TO DETERMINE: [N]

=== OVERALL COMPLIANCE STATUS ===
[COMPLIANT / NON-COMPLIANT / PARTIAL / INSUFFICIENT DATA]

=== KEY FINDINGS ===
[Summary of important findings and recommendations]
"""
    
    response = llm.invoke(prompt)
    return response.content


# ============================================================================
# Main Testing Workflow
# ============================================================================

class PlaybookTester:
    """Main class for testing existing playbooks."""
    
    def __init__(
        self,
        kcs_id: str,
        test_host: str = DEFAULT_TEST_HOST,
        max_retries: int = DEFAULT_MAX_RETRIES
    ):
        self.kcs_id = kcs_id
        self.test_host = test_host
        self.max_retries = max_retries
        
        # State
        self.matching_requirements: List[str] = []
        self.data_collection_requirements: List[str] = []
        self.playbook_paths: List[str] = []
        self.playbook_outputs: Dict[str, str] = {}
        
    def load_existing_files(self) -> bool:
        """Load existing requirements and playbooks."""
        print(f"\n{'=' * 60}")
        print(f"Loading existing files for KCS {self.kcs_id}")
        print('=' * 60)
        
        # Load matching requirements
        matching_path = get_requirements_path(self.kcs_id, "matching")
        self.matching_requirements = load_requirements(matching_path)
        if self.matching_requirements:
            print(f"✅ Loaded {len(self.matching_requirements)} matching requirements")
        else:
            print(f"❌ No matching requirements found at: {matching_path}")
            return False
        
        # Load data collection requirements
        data_path = get_requirements_path(self.kcs_id, "data_collection")
        self.data_collection_requirements = load_requirements(data_path)
        if self.data_collection_requirements:
            print(f"✅ Loaded {len(self.data_collection_requirements)} data collection requirements")
        else:
            print(f"❌ No data collection requirements found at: {data_path}")
            return False
        
        # Find playbooks
        self.playbook_paths = find_playbooks(self.kcs_id)
        if self.playbook_paths:
            print(f"✅ Found {len(self.playbook_paths)} playbooks")
            for path in self.playbook_paths:
                print(f"   - {os.path.basename(path)}")
        else:
            print(f"❌ No playbooks found in: {get_verification_dir(self.kcs_id)}")
            return False
        
        return True
    
    def test_playbook(self, playbook_path: str, requirement: str) -> tuple[bool, str]:
        """
        Test a single playbook with retry logic.
        
        Returns:
            Tuple of (success, final_output)
        """
        playbook_name = os.path.basename(playbook_path)
        playbook_content = load_playbook(playbook_path)
        
        for attempt in range(1, self.max_retries + 1):
            print(f"\n--- Attempt {attempt}/{self.max_retries} for {playbook_name} ---")
            
            # Step 1: Syntax check
            print("  🔍 Checking syntax...")
            syntax_ok, syntax_error = check_syntax(playbook_path)
            
            if not syntax_ok:
                print(f"  ❌ Syntax error: {syntax_error[:200]}...")
                
                # Update playbook to fix syntax
                print("  🔧 Updating playbook to fix syntax...")
                playbook_content = update_playbook_with_feedback(
                    playbook_content,
                    f"SYNTAX ERROR: {syntax_error}",
                    requirement
                )
                save_playbook(playbook_path, playbook_content)
                continue
            
            print("  ✅ Syntax OK")
            
            # Step 2: Run playbook
            print(f"  🚀 Running playbook on {self.test_host}...")
            run_ok, output = run_playbook(playbook_path, self.test_host)
            
            if not run_ok:
                print(f"  ❌ Execution error: {output[:200]}...")
                
                # Update playbook to fix execution error
                print("  🔧 Updating playbook to fix execution error...")
                playbook_content = update_playbook_with_feedback(
                    playbook_content,
                    f"EXECUTION ERROR: {output}",
                    requirement
                )
                save_playbook(playbook_path, playbook_content)
                continue
            
            print("  ✅ Playbook executed successfully")
            
            # Step 3: Check data sufficiency
            print("  📊 Checking data sufficiency...")
            sufficient, feedback = check_data_sufficiency(output, requirement)
            
            if sufficient:
                print("  ✅ Data collection sufficient")
                return True, output
            else:
                print(f"  ⚠️ Data insufficient: {feedback[:200]}...")
                
                # Update playbook to improve data collection
                print("  🔧 Updating playbook to improve data collection...")
                playbook_content = update_playbook_with_feedback(
                    playbook_content,
                    f"DATA INSUFFICIENT: {feedback}\n\nPlaybook output:\n{output}",
                    requirement
                )
                save_playbook(playbook_path, playbook_content)
                continue
        
        print(f"  ❌ Max retries ({self.max_retries}) exceeded for {playbook_name}")
        return False, output if 'output' in locals() else "No output collected"
    
    def run_all_tests(self) -> bool:
        """Run tests for all playbooks."""
        print(f"\n{'=' * 60}")
        print("Phase 1: Testing All Playbooks")
        print('=' * 60)
        
        total = len(self.playbook_paths)
        success_count = 0
        
        for i, playbook_path in enumerate(self.playbook_paths):
            part_num = i + 1
            print(f"\n{'=' * 40}")
            print(f"Testing Playbook {part_num}/{total}")
            print(f"File: {os.path.basename(playbook_path)}")
            print('=' * 40)
            
            # Get corresponding requirement
            if i < len(self.data_collection_requirements):
                requirement = self.data_collection_requirements[i]
                print(f"Requirement: {requirement[:80]}...")
            else:
                requirement = "Data collection requirement"
                print("⚠️ No matching requirement found, using generic")
            
            success, output = self.test_playbook(playbook_path, requirement)
            
            # Store output
            self.playbook_outputs[playbook_path] = output
            
            if success:
                success_count += 1
                print(f"✅ Playbook {part_num}/{total} completed successfully")
            else:
                print(f"❌ Playbook {part_num}/{total} failed after all retries")
        
        print(f"\n{'=' * 60}")
        print(f"Phase 1 Complete: {success_count}/{total} playbooks succeeded")
        print('=' * 60)
        
        return success_count == total
    
    def run_analysis(self) -> tuple[str, str]:
        """Run data collection and compliance analysis."""
        print(f"\n{'=' * 60}")
        print("Phase 2: Analysis")
        print('=' * 60)
        
        # Part 1: Data Collection Analysis
        print("\n--- Part 1: Data Collection Analysis ---")
        data_summary = analyze_data_collection(
            self.playbook_outputs,
            self.data_collection_requirements
        )
        print(data_summary)
        
        # Part 2: Compliance Analysis
        print("\n--- Part 2: Compliance Analysis ---")
        compliance_result = analyze_compliance(
            data_summary,
            self.matching_requirements
        )
        print(compliance_result)
        
        return data_summary, compliance_result
    
    def run(self) -> bool:
        """Run the complete testing workflow."""
        # Step 1: Load existing files
        if not self.load_existing_files():
            print("\n❌ Cannot proceed: Missing required files")
            print("Please ensure the following files exist:")
            print(f"  - {get_requirements_path(self.kcs_id, 'matching')}")
            print(f"  - {get_requirements_path(self.kcs_id, 'data_collection')}")
            print(f"  - Playbooks in {get_verification_dir(self.kcs_id)}/")
            return False
        
        # Step 2: Run all tests
        all_success = self.run_all_tests()
        
        # Step 3: Run analysis (even if some tests failed)
        data_summary, compliance_result = self.run_analysis()
        
        # Step 4: Save results
        self.save_results(data_summary, compliance_result)
        
        return all_success
    
    def save_results(self, data_summary: str, compliance_result: str) -> None:
        """Save analysis results to files."""
        verification_dir = get_verification_dir(self.kcs_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save data collection summary
        data_path = os.path.join(verification_dir, f"data_collection_summary_{timestamp}.txt")
        with open(data_path, 'w') as f:
            f.write(data_summary)
        print(f"\n📄 Data collection summary saved to: {data_path}")
        
        # Save compliance result
        compliance_path = os.path.join(verification_dir, f"compliance_result_{timestamp}.txt")
        with open(compliance_path, 'w') as f:
            f.write(compliance_result)
        print(f"📄 Compliance result saved to: {compliance_path}")
        
        # Save playbook outputs
        outputs_path = os.path.join(verification_dir, f"playbook_outputs_{timestamp}.txt")
        with open(outputs_path, 'w') as f:
            for path, output in self.playbook_outputs.items():
                f.write(f"{'=' * 60}\n")
                f.write(f"Playbook: {os.path.basename(path)}\n")
                f.write(f"{'=' * 60}\n")
                f.write(output)
                f.write("\n\n")
        print(f"📄 Playbook outputs saved to: {outputs_path}")


# ============================================================================
# CLI Entry Point
# ============================================================================

def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Test existing KCS playbooks and run analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Test playbooks for KCS 7101627
    python kcs_playbook_tester.py 7101627
    
    # Test with custom host and retries
    python kcs_playbook_tester.py 7101627 --test-host myhost --max-retries 5
        """
    )
    
    parser.add_argument(
        "kcs_id",
        help="The KCS article ID (e.g., 7101627)"
    )
    
    parser.add_argument(
        "--test-host",
        default=DEFAULT_TEST_HOST,
        help=f"Target host for testing (default: {DEFAULT_TEST_HOST})"
    )
    
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help=f"Maximum retry attempts per playbook (default: {DEFAULT_MAX_RETRIES})"
    )
    
    args = parser.parse_args()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║            KCS Playbook Tester - Simplified Workflow         ║
╠══════════════════════════════════════════════════════════════╣
║  KCS ID:      {args.kcs_id:<47}║
║  Test Host:   {args.test_host:<47}║
║  Max Retries: {args.max_retries:<47}║
╚══════════════════════════════════════════════════════════════╝
""")
    
    tester = PlaybookTester(
        kcs_id=args.kcs_id,
        test_host=args.test_host,
        max_retries=args.max_retries
    )
    
    success = tester.run()
    
    if success:
        print("\n✅ All tests completed successfully!")
        sys.exit(0)
    else:
        print("\n⚠️ Some tests failed. Check the results for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()

