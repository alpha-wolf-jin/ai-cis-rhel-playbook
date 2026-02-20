#!/usr/bin/env python3
"""
Generic Ansible Remediation Playbook Generator (LangGraph Version)

This script wraps the remediation playbook generator with LangGraph for better
state management, retry logic, and workflow visualization.

The interface (inputs, outputs, and main functions) remains exactly the same
as deepseek_generate_remediation_playbook.py for compatibility.
"""

from typing import TypedDict, Literal
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

# Import all functions from the original module
from deepseek_generate_remediation_playbook import (
    generate_playbook,
    save_playbook,
    check_playbook_syntax,
    test_playbook_on_server,
    analyze_playbook_output,
    analyze_playbook,
    extract_playbook_issues_from_analysis,
    verify_status_alignment,
    extract_analysis_statuses,
)

# Load environment variables
load_dotenv()

# Define State for LangGraph workflow
class PlaybookGenerationState(TypedDict):
    """State for the playbook generation workflow."""
    # Input parameters
    playbook_objective: str
    target_host: str
    test_host: str
    become_user: str
    requirements: list[str]
    example_output: str
    filename: str
    max_retries: int
    audit_procedure: str  # CIS Benchmark remediation procedure (kept as audit_procedure for interface compat)
    
    # Workflow state
    attempt: int
    playbook_content: str
    playbook_modified: bool  # True if playbook was generated/enhanced, False if loaded from existing file unchanged
    syntax_valid: bool
    playbook_structure_valid: bool  # New field for playbook structure analysis result
    playbook_structure_analysis: str  # New field for playbook structure analysis message
    test_success: bool
    analysis_passed: bool  # New field for analysis result
    analysis_message: str  # New field for analysis message
    final_success: bool
    error_message: str
    test_output: str
    final_output: str
    connection_error: bool  # Flag for connection errors (cannot validate on host)
    
    # Control flow
    should_retry: bool
    workflow_complete: bool
    enhance: bool  # If True, check for existing playbook and skip generation if found
    skip_execution: bool  # If True, skip execution on target host (only test on test hosts)
    skip_test: bool  # If True, skip all test-related tasks and execute directly on target host
    skip_playbook_analysis: bool  # New field for playbook structure analysis message
    test_hosts: list[str]  # List of test hosts to iterate through
    current_test_host_index: int  # Current index in test_hosts list


def check_existing_playbook_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Check if playbook file exists and load it if enhance=True."""
    print(f"\n{'='*80} check_existing_playbook_node")
    
    from pathlib import Path
    
    # If skip_test is True, we need to validate the playbook exists
    if state.get('skip_test', False):
        filename = state.get('filename', '')
        if not filename:
            error_msg = "❌ ERROR: --skip-test requires a playbook filename, but none was specified"
            print(error_msg)
            state['error_message'] = error_msg
            state['workflow_complete'] = False
            return state
        
        file_path = Path(filename)
        if not file_path.exists():
            error_msg = f"❌ ERROR: Playbook file not found: {filename}\n   Cannot skip tests - playbook must exist when using --skip-test"
            print(error_msg)
            state['error_message'] = error_msg
            state['workflow_complete'] = False
            return state
        
        print(f"✅ Playbook file found: {filename}")
        print("📖 Loading playbook content for direct execution...")
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_content = f.read()
            state['playbook_content'] = existing_content
            state['playbook_modified'] = False  # Playbook loaded from file, not modified
            print(f"✅ Loaded playbook ({len(existing_content)} characters)")
            print("⏭️  Skipping all test-related tasks, proceeding directly to target execution")
            # Mark syntax as valid since we're skipping syntax check
            state['syntax_valid'] = True
            # Don't set workflow_complete here - let execute_on_target and analyze_output set it
            # But ensure workflow_complete is not False (which would cause routing to "end")
            # Actually, we should leave it as is (default False) and let should_continue_after_check_existing handle it
            return state
        except Exception as e:
            error_msg = f"❌ ERROR: Cannot read playbook file {filename}: {e}"
            print(error_msg)
            state['error_message'] = error_msg
            state['workflow_complete'] = False
            return state
    
    # Only check if enhance=True
    if not state.get('enhance', True):
        print("⚠️  enhance=False: Will generate new playbook (skipping existing file check)")
        return state
    
    filename = state.get('filename', '')
    if not filename:
        print("⚠️  No filename specified, proceeding with generation")
        return state
    
    file_path = Path(filename)
    if file_path.exists():
        print(f"✅ Existing playbook found: {filename}")
        print("📖 Loading existing playbook content...")
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_content = f.read()
            state['playbook_content'] = existing_content
            state['playbook_modified'] = False  # Playbook loaded from file, not modified
            print(f"✅ Loaded existing playbook ({len(existing_content)} characters)")
            print("⏭️  Skipping generation, proceeding directly to execution")
        except Exception as e:
            print(f"⚠️  Error reading existing playbook: {e}")
            print("🔄 Will generate new playbook instead")
            state['playbook_content'] = ""
            state['playbook_modified'] = True  # Will be generated, so mark as modified
    else:
        print(f"📝 Playbook file not found: {filename}")
        print("🔄 Will generate new playbook")
        state['playbook_content'] = ""
        state['playbook_modified'] = True  # Will be generated, so mark as modified
    
    return state


def generate_playbook_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Generate or enhance playbook using LLM."""
    # Check if we need to enhance (have analysis_message with issues)
    has_analysis_with_issues = False
    if state.get('analysis_message'):
        analysis_msg = state['analysis_message']
        has_issues, _ = extract_playbook_issues_from_analysis(analysis_msg)
        if has_issues:
            has_analysis_with_issues = True
    
    # Determine if this is an enhancement scenario
    is_enhancement = state.get('playbook_content') and state.get('analysis_message')
    
    # Only skip generation if:
    # 1. We have playbook_content (from existing file)
    # 2. enhance=True (check for existing files)
    # 3. AND we're NOT in an enhancement scenario (no analysis issues to fix)
    # 4. AND this is the first attempt (not a retry - retries always need regeneration)
    # 5. AND we don't have an error_message (no previous errors to fix)
    current_attempt = state.get('attempt', 1)
    has_error = bool(state.get('error_message', ''))
    should_skip = (
        state.get('playbook_content') and 
        state.get('enhance', True) and 
        not has_analysis_with_issues and
        current_attempt == 1 and
        not has_error
    )
    
    if should_skip:
        print(f"\n{'='*80} generate_playbook_node")
        print("⏭️  Skipping generation - using existing playbook")
        state['playbook_modified'] = False  # Using existing playbook, not modified
        return state
    
    print(f"\n{'='*80} generate_playbook_node")
    if is_enhancement:
        print(f"Attempt {state['attempt']}/{state['max_retries']}: Enhancing Ansible playbook...")
    else:
        print(f"Attempt {state['attempt']}/{state['max_retries']}: Generating Ansible playbook...")
    print("=" * 80)
    print(f"Objective: {state['playbook_objective']}")
    print(f"Test Host: {state['test_host']}")
    if state['test_host'] != state['target_host']:
        print(f"Target Host: {state['target_host']}")
    print(f"Become User: {state['become_user']}")
    print(f"Requirements: {len(state['requirements'])} items")
    if is_enhancement:
        print(f"Mode: Enhancement (based on existing playbook and feedback)")
    print("=" * 80)
    
    try:
        # Extract feedback from analysis_message if available
        feedback_content = None
        if state.get('analysis_message'):
            # Extract the PLAYBOOK ANALYSIS section and recommendations
            analysis_msg = state['analysis_message']
            has_issues, extracted_advice = extract_playbook_issues_from_analysis(analysis_msg)
            if has_issues and extracted_advice:
                feedback_content = extracted_advice
            elif has_issues:
                # Extract PLAYBOOK ANALYSIS section
                lines = analysis_msg.split('\n')
                feedback_lines = []
                for i, line in enumerate(lines):
                    if "PLAYBOOK ANALYSIS" in line.upper():
                        feedback_lines.append(line)
                        # Get next 20-30 lines for context
                        for j in range(i+1, min(i+30, len(lines))):
                            if lines[j].strip().startswith('- **') and 'PLAYBOOK' not in lines[j].upper() and 'DATA COLLECTION' not in lines[j].upper() and 'REMEDIATION' not in lines[j].upper():
                                break
                            feedback_lines.append(lines[j])
                        break
                feedback_content = '\n'.join(feedback_lines).strip()
        
        feedback_content = f"Error Message:\n{state['error_message']}\nAnalysis Message:\n{state['analysis_message']}\n"

        # Generate or enhance the playbook
        playbook = generate_playbook(
            playbook_objective=state['playbook_objective'],
            target_host=state['test_host'],
            become_user=state['become_user'],
            requirements=state['requirements'],
            example_output=state['example_output'],
            audit_procedure=state.get('audit_procedure', ''),
            current_playbook=state.get('playbook_content'),  # Pass current playbook for enhancement
            feedback=feedback_content  # Pass feedback for enhancement
        )
        

        # Display the generated/enhanced playbook
        if is_enhancement:
            print("\n📋 Enhanced Ansible Playbook:")
        else:
            print("\n📋 Generated Ansible Playbook:")
        print("=" * 80)
        print(playbook)
        print("=" * 80)
        
        state['playbook_content'] = playbook
        state['playbook_modified'] = True  # Playbook was generated/enhanced, mark as modified
        state['error_message'] = ""
        state['analysis_message'] = ""
        
    except Exception as e:
        state['error_message'] = str(e)
        state['playbook_content'] = ""
        state['playbook_modified'] = True  # Error occurred, but we tried to modify
        print(f"❌ Error generating playbook: {e}")
    
    return state


def increment_attempt_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Increment attempt counter for retry."""
    state['attempt'] += 1
    print(f"\n{'='*80} increment_attempt_node")
    print(f"\n🔄 Incrementing attempt counter: {state['attempt']}/{state['max_retries']}")
    return state


def save_playbook_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Save playbook to file."""
    print(f"\n{'='*80} save_playbook_node")
    # Only save if we have new content (not loaded from existing file)
    # If playbook was loaded from file, it's already saved, so skip saving again
    if state['playbook_content']:
        from pathlib import Path
        file_path = Path(state['filename'])
        # Check if file exists and content matches (to avoid unnecessary writes)
        if file_path.exists():
            try:
                with open(state['filename'], 'r', encoding='utf-8') as f:
                    existing_content = f.read()
                if existing_content == state['playbook_content']:
                    print(f"⏭️  Playbook already saved (content unchanged): {state['filename']}")
                    return state
            except Exception:
                pass  # If read fails, proceed with save
        save_playbook(state['playbook_content'], state['filename'])
    return state


def check_syntax_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Check playbook syntax."""
    print(f"\n{'='*80} check_syntax_node")
    
    # Skip syntax check if playbook hasn't been modified
    if not state.get('playbook_modified', True):
        print("⏭️  Skipping syntax check - playbook content unchanged")
        state['syntax_valid'] = True  # Assume valid if unchanged
        return state
    
    is_valid, error_msg = check_playbook_syntax(state['filename'], state['test_host'], remote_user=state['become_user'])
    
    state['syntax_valid'] = is_valid
    if not is_valid:
        #state['error_message'] = error_msg
        # Don't set should_retry here - let conditional edge decide
        
        if state['attempt'] < state['max_retries']:
            print(f"\n⚠️  Syntax check failed on attempt {state['attempt']}/{state['max_retries']}")
            print("🔄 Retrying with additional instructions to LLM...")
            print("\n📋 Error Summary:")
            error_lines = error_msg.split('\n')
            for line in error_lines[:10]:
                if line.strip():
                    print(f"   {line}")
            if len(error_lines) > 10:
                print(f"   ... ({len(error_lines) - 10} more lines)")
            
            # Add error context to requirements for next attempt
            error_msg_escaped = error_msg[:200].replace('{', '{{').replace('}', '}}')
            #state['requirements'].append(f"IMPORTANT: Previous attempt had syntax error: {error_msg_escaped}")
            state['analysis_message'] = f"IMPORTANT: Previous attempt had syntax error: {error_msg_escaped}"
    return state


def analyze_playbook_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Analyze playbook structure against requirements."""
    print(f"\n{'='*80} analyze_playbook_node")
    

    # Skip if skip_playbook_analysis is True
    if state.get('skip_playbook_analysis', False):
        return state

    # Skip if skip_test is True
    if state.get('skip_test', False):
        print("⏭️  Skipping playbook structure analysis (--skip-test flag)")
        state['playbook_structure_valid'] = True  # Assume valid when skipping
        state['playbook_structure_analysis'] = "Skipped (--skip-test flag)"
        return state
    
    # Skip if playbook hasn't been modified
    if not state.get('playbook_modified', True):
        print("⏭️  Skipping playbook structure analysis - playbook content unchanged")
        state['playbook_structure_valid'] = True  # Assume valid if unchanged
        state['playbook_structure_analysis'] = "Skipped (playbook content unchanged)"
        return state
    
    # Analyze playbook structure
    playbook_structure_passed, playbook_structure_analysis = analyze_playbook(
        requirements=state['requirements'],
        playbook_objective=state['playbook_objective'],
        playbook_content=state['playbook_content'],
        audit_procedure=state.get('audit_procedure', '')
    )
    
    state['playbook_structure_valid'] = playbook_structure_passed
    state['playbook_structure_analysis'] = playbook_structure_analysis
    
    if not playbook_structure_passed:
        if state['attempt'] < state['max_retries']:
            print(f"\n⚠️  Playbook structure analysis failed on attempt {state['attempt']}/{state['max_retries']}")
            print("🔄 Retrying with structure analysis feedback to LLM...")
            print("\n📋 Playbook Structure Analysis Details:")
            print("=" * 80)
            print(playbook_structure_analysis)
            print("=" * 80)
            
            # Add structure analysis feedback to requirements for next attempt
            analysis_escaped = playbook_structure_analysis.replace('{', '{{').replace('}', '}}')
            state['analysis_message'] = playbook_structure_analysis
            #state['requirements'].append(f"CRITICAL FIX REQUIRED: PLAYBOOK STRUCTURE ANALYSIS: FAIL\n\nAnalysis Result:\n{analysis_escaped}\n\nINSTRUCTIONS TO FIX:\n1. Review the PLAYBOOK STRUCTURE ANALYSIS feedback carefully\n2. Ensure all requirements are properly implemented in the playbook content\n3. Fix any structural issues identified in the analysis\n4. Make sure status variables are properly defined (Jinja2 expressions, not string literals)\n5. Ensure conditional execution logic matches the audit procedure")
            # Don't set analysis_message here - it will be set by analyze_output_node if needed
            # Setting it here causes duplication in error messages
        else:
            # Out of retries - print full analysis
            print(f"\n❌ Playbook structure analysis failed on final attempt {state['attempt']}/{state['max_retries']}")
            print("📋 Full Playbook Structure Analysis:")
            print("=" * 80)
            print(playbook_structure_analysis)
            print("=" * 80)
            # Don't set analysis_message here - it causes duplication in error messages
            # The playbook_structure_analysis is already stored separately and will be used for error reporting
    else:
        state['skip_playbook_analysis'] = True
    
    return state


def test_on_test_host_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Test playbook on test host."""
    test_hosts = state.get('test_hosts', [])
    current_index = state.get('current_test_host_index', 0)
    
    print("\n" + "=" * 80)
    print(f"\n{'='*80} test_on_test_host_node")
    if len(test_hosts) > 1:
        print(f"✅ PLAYBOOK STRUCTURE ANALYSIS PASS! Now testing on test host {current_index + 1}/{len(test_hosts)}: {state['test_host']}...")
    else:
        print(f"✅ PLAYBOOK STRUCTURE ANALYSIS PASS! Now testing on test host: {state['test_host']}...")
    print("=" * 80)
    
    # Execute on test host with debug tasks skipped for cleaner analysis
    test_success, test_output = test_playbook_on_server(
        state['filename'],
        state['test_host'],
        check_mode=False,
        verbose="vvv",  # Use default verbose level
        skip_debug=True,  # Skip debug tasks for cleaner output to analyze
        remote_user=state['become_user']
    )
    
    state['test_success'] = test_success
    state['test_output'] = test_output
    
    # Check if it's a connection error (cannot validate on host)
    if not test_success and test_output.startswith("CONNECTION_ERROR:"):
        print("\n" + "=" * 80)
        print("⚠️  WARNING: Cannot connect to test host for validation")
        print("=" * 80)
        print(f"\n❌ Connection Error Details:")
        print(f"   Host: {state['test_host']}")
        print(f"   Error: {test_output.replace('CONNECTION_ERROR: ', '')}")
        print(f"\n⚠️  The playbook syntax is valid, but execution validation cannot be performed.")
        print(f"   Please ensure:")
        print(f"   1. The host {state['test_host']} is reachable")
        print(f"   2. SSH access is configured correctly")
        print(f"   3. Authentication credentials are valid")
        print(f"\n✅ Playbook has been saved with valid syntax: {state['filename']}")
        print("=" * 80)
        # Set error message and mark as connection error (don't retry)
        state['error_message'] = test_output
        state['connection_error'] = True
        return state
    
    if test_success:
        print("\n" + "=" * 80)
        print(f"🎉 SUCCESS! Playbook validated on test host: {state['test_host']}!")
        print("=" * 80)
        print("\n✅ Test Execution Summary:")
        print("   1. ✅ Syntax check passed")
        print(f"   2. ✅ Test execution passed on {state['test_host']}")
        print("   3. ✅ All requirements verified")
        
        # Show test output
        print(f"\n📋 Full Test Execution Output from {state['test_host']}:")
        print("=" * 80)
        print(test_output)
        print("=" * 80)
    else:
        #state['error_message'] = test_output
        # Don't set should_retry here - let conditional edge decide
        
        if state['attempt'] < state['max_retries']:
            print(f"\n⚠️  Server test failed on attempt {state['attempt']}/{state['max_retries']}")
            print("🔄 Retrying with test failure feedback to LLM...")
            
            state['error_message'] = test_output
            # Add error feedback for retry
            #test_output_escaped = test_output[:300].replace('{', '{{').replace('}', '}}')
            #state['requirements'].append(f"IMPORTANT: Previous playbook failed testing: {test_output_escaped}")
    
    return state

def analyze_output_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Analyze playbook output against requirements."""
    print(f"\n{'='*80} analyze_output_node")
    
    # When skip_test is True, use final_output from execute_on_target_host_node
    # Otherwise, use test_output from test_on_test_host_node
    if state.get('skip_test', False):
        output_to_analyze = state.get('final_output', '')
        output_success = state.get('final_success', False)
        output_source = "target host execution"
    else:
        output_to_analyze = state.get('test_output', '')
        output_success = state.get('test_success', False)
        output_source = "test host execution"
    
    if output_success and output_to_analyze:
        # When skip_test is True, suppress the header since we're analyzing final execution output
        suppress_header = state.get('skip_test', False)
        analysis_passed, analysis_message = analyze_playbook_output(
            requirements=state['requirements'],
            playbook_objective=state['playbook_objective'],
            test_output=output_to_analyze,  # Use the appropriate output source
            audit_procedure=state.get('audit_procedure'),
            playbook_content=state.get('playbook_content'),  # Pass playbook content for analysis
            suppress_header=suppress_header
        )

        # Check for PLAYBOOK ANALYSIS: FAIL status
        has_issues, extracted_advice = extract_playbook_issues_from_analysis(analysis_message)
        
        # Verify status alignment between playbook output and AI analysis
        status_aligned, alignment_message = verify_status_alignment(output_to_analyze, analysis_message)
        analysis_statuses = extract_analysis_statuses(analysis_message)
        
        # When skip_test is True, we're analyzing final execution output, so we're done
        if state.get('skip_test', False):
            print(f"\n✅ Analysis complete for {output_source}")
            state['analysis_passed'] = analysis_passed
            state['analysis_message'] = analysis_message
            state['workflow_complete'] = True
            state['final_success'] = output_success
            return state
        
        # Proceed to target execution only when ALL criteria are met:
        # 1. DATA_COLLECTION: PASS
        # 2. REMEDIATION EXECUTION: PASS
        # 3. REMEDIATION VERIFICATION: PASS
        # NOTE: PLAYBOOK ANALYSIS is now handled separately (after syntax check, before test execution)
        data_collection_pass = analysis_statuses.get('data_collection') == 'PASS'
        remediation_execution_pass = analysis_statuses.get('remediation_execution') == 'PASS'
        remediation_verification_pass = analysis_statuses.get('remediation_verification') == 'PASS'
        
        # Check if all main sections pass
        all_main_sections_pass = (
            data_collection_pass and
            remediation_execution_pass and
            remediation_verification_pass
        )
        
        state['analysis_passed'] = all_main_sections_pass
        #state['analysis_message'] = analysis_message
        state['analysis_message'] = ""
        state['error_message'] = ""
        
        if not all_main_sections_pass:
            # Check which criteria failed
            failed_criteria = []
            if not data_collection_pass:
                failed_criteria.append("DATA COLLECTION: not PASS")
            if not remediation_execution_pass:
                failed_criteria.append("REMEDIATION EXECUTION: not PASS")
            if not remediation_verification_pass:
                failed_criteria.append("REMEDIATION VERIFICATION: not PASS")
            
            print(f"\n⚠️  AI REMEDIATION ANALYSIS criteria not met - will enhance playbook")
            print(f"   Failed criteria: {', '.join(failed_criteria)}")
            #state['error_message'] = analysis_message
            
            if state['attempt'] < state['max_retries']:
                print(f"\n⚠️  Analysis issues detected on attempt {state['attempt']}/{state['max_retries']}")
                print("🔄 Enhancing playbook with analysis feedback...")
                # Don't set workflow_complete to False when retrying - let the retry logic handle it
                
                state['analysis_message'] = analysis_message
                ## Prepare feedback message
                #if extracted_advice:
                #    # Use extracted advice if available
                #    feedback_text = extracted_advice
                #else:
                #    # Extract the PLAYBOOK ANALYSIS section and recommendations
                #    lines = analysis_message.split('\n')
                #    feedback_lines = []
                #    in_playbook_analysis = False
                #    for i, line in enumerate(lines):
                #        if "PLAYBOOK ANALYSIS" in line.upper():
                #            in_playbook_analysis = True
                #            feedback_lines.append(line)
                #            # Get next few lines for context
                #            for j in range(i+1, min(i+20, len(lines))):
                #                if lines[j].strip().startswith('- **') and 'PLAYBOOK' not in lines[j].upper():
                #                    break
                #                feedback_lines.append(lines[j])
                #            break
                #    # Also look for RECOMMENDATION or PLAYBOOK LOGIC ISSUE sections
                #    for i, line in enumerate(lines):
                #        if any(kw in line.upper() for kw in ["PLAYBOOK LOGIC ISSUE", "RECOMMENDATION", "ADVICE"]):
                #            if line not in feedback_lines:
                #                feedback_lines.append(line)
                #            # Get next 10-15 lines
                #            for j in range(i+1, min(i+15, len(lines))):
                #                if lines[j].strip().startswith('##') or (lines[j].strip().startswith('- **') and 'RECOMMENDATION' not in lines[j].upper()):
                #                    break
                #                if lines[j] not in feedback_lines:
                #                    feedback_lines.append(lines[j])


                #    feedback_text = '\n'.join(feedback_lines).strip() or analysis_message[:1000]

                #feedback_header = "CRITICAL FIX REQUIRED: PLAYBOOK ANALYSIS: FAIL - The playbook has logic issues that need to be fixed."
                #
                ## Add analysis feedback to requirements
                #analysis_escaped = feedback_text.replace('{', '{{').replace('}', '}}')
                #state['requirements'].append(f"""{feedback_header}
#
#Analysis Result:
#{analysis_escaped}
#
#INSTRUCTIONS TO FIX:
#1. Review the PLAYBOOK ANALYSIS feedback carefully
#2. Fix the playbook logic issues identified in the analysis
#3. If analysis recommends conditional execution (e.g., "when: data_1 | length > 0"), implement it
#4. If analysis identifies design flaws or logic issues, fix them according to the recommendations
#5. Ensure the playbook follows CIS procedures correctly (e.g., skip subsequent requirements when first requirement returns nothing)
#6. Update overall compliance logic to match CIS exactly
#                    7. Make sure all requirements are executed in the correct order and conditions""")
#            else:
#                # Out of retries - mark workflow as complete (failed)
#                print(f"\n❌ Analysis failed and out of retries ({state['attempt']}/{state['max_retries']})")
#                state['workflow_complete'] = False
#        else:
#            print("\n✅ PLAYBOOK ANALYSIS: PASS - Playbook logic is correct!")
#    else:
#        if state.get('skip_test', False):
#            print(f"\n⚠️  Cannot analyze output - target execution was not successful or output is missing")
#            state['error_message'] = "Target execution failed or output unavailable"
#        else:
#            print(f"\n⚠️  Cannot analyze output - test was not successful or output is missing")
#        state['analysis_passed'] = False
#        state['analysis_message'] = "Analysis skipped - execution failed or output unavailable"
#        state['workflow_complete'] = False
    
    return state


def execute_on_target_host_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Execute playbook on target host."""
    print(f"\n{'='*80} execute_on_target_host_node")
    
    # Check if execution should be skipped
    if state.get('skip_execution', False):
        print("\n" + "=" * 80)
        print("⏭️  SKIPPING EXECUTION (--skip-execution flag)")
        print("=" * 80)
        print(f"✅ Playbook generation and testing completed successfully!")
        print(f"📋 Test host(s): {', '.join(state.get('test_hosts', [state.get('test_host', 'N/A')]))}")
        print(f"🎯 Target host: {state['target_host']} (execution skipped)")
        print(f"📄 Playbook file: {state['filename']}")
        print("\n✅ Workflow complete - execution was skipped as requested.")
        print("=" * 80)
        
        # Mark workflow as complete and successful
        state['final_success'] = True
        state['final_output'] = state.get('test_output', '')
        state['workflow_complete'] = True
        state['test_success'] = True  # Test was successful on test hosts
        return state
    
    # When skip_test is True, we skip the test_host == target_host check
    # because test_output doesn't exist (tests were skipped)
    # We'll execute directly on target and let analyze_output_node handle analysis
    if not state.get('skip_test', False) and state['test_host'] == state['target_host']:
        # Same host, already executed (normal flow, not skip_test)
        state['final_success'] = True
        state['final_output'] = state['test_output']
        state['workflow_complete'] = True
        
        # Display Analysis Result for same-host execution
        print("\n" + "=" * 80)
        print(f"🎊 COMPLETE SUCCESS! Playbook executed on: {state['target_host']}!")
        print("=" * 80)
        
        # Perform full analysis (same as test host)
        print("\n" + "=" * 80)
        print(f"📊 Analysis Result for {state['target_host']}:")
        print("=" * 80)
        analysis_passed, analysis_message = analyze_playbook_output(
            requirements=state['requirements'],
            playbook_objective=state['playbook_objective'],
            test_output=state['test_output'],
            audit_procedure=state.get('audit_procedure'),
            playbook_content=state.get('playbook_content')  # Pass playbook content for analysis
        )
        print(analysis_message)
        print("=" * 80)
        
        return state
    
    print("\n" + "=" * 80)
    print(f"🚀 FINAL EXECUTION: Running playbook on target host: {state['target_host']}")
    print("=" * 80)
    print(f"\n📍 Executing on: {state['target_host']}")
    print()
    
    final_success, final_output = test_playbook_on_server(
        state['filename'],
        state['target_host'],
        check_mode=False,
        verbose="v",  # Use default verbose level to capture compliance report output
        skip_debug=True,  # Skip debug tasks on target host
        remote_user=state['become_user']
    )
    
    state['final_success'] = final_success
    state['final_output'] = final_output
    state['workflow_complete'] = True
    # When skip_test is True, we execute directly on target, so final_success indicates test success
    if state.get('skip_test', False):
        state['test_success'] = final_success
    
    if final_success:
        print("\n" + "=" * 80)
        print(f"🎊 COMPLETE SUCCESS! Playbook executed on target: {state['target_host']}!")
        print("=" * 80)
        print("\n✅ Final Execution Summary:")
        print("   1. ✅ Syntax check passed")
        print(f"   2. ✅ Test execution passed on {state['test_host']}")
        print(f"   3. ✅ Final execution passed on {state['target_host']}")
        print("   4. ✅ All requirements verified")
        
        print(f"\n📋 Full Final Execution Output from {state['target_host']}:")
        print("=" * 80)
        print(final_output)
        print("=" * 80)
        
        # Perform full analysis (same as test host)
        print("\n" + "=" * 80)
        print(f"📊 Analysis Result for {state['target_host']}:")
        print("=" * 80)
        analysis_passed, analysis_message = analyze_playbook_output(
            requirements=state['requirements'],
            playbook_objective=state['playbook_objective'],
            test_output=final_output,
            audit_procedure=state.get('audit_procedure')
        )
        print(analysis_message)
        print("=" * 80)
    else:
        print("\n" + "=" * 80)
        print(f"⚠️  Execution on target host {state['target_host']} had issues")
        print("=" * 80)
        print(f"\n📋 Full Execution Output from {state['target_host']}:")
        print("=" * 80)
        print(final_output)
        print("=" * 80)
        
        # Perform full analysis even on failure
        print("\n" + "=" * 80)
        print(f"📊 Analysis Result for {state['target_host']}:")
        print("=" * 80)
        analysis_passed, analysis_message = analyze_playbook_output(
            requirements=state['requirements'],
            playbook_objective=state['playbook_objective'],
            test_output=final_output,
            audit_procedure=state.get('audit_procedure')
        )
        print(analysis_message)
        print("=" * 80)
    
    return state


def should_continue_after_syntax(state: PlaybookGenerationState) -> Literal["analyze_playbook", "test_on_test_host", "retry", "end"]:
    """Conditional edge: Decide what to do after syntax check."""
    print(f"\n{'='*80} should_continue_after_syntax")
    if not state['syntax_valid']:
        if state['attempt'] < state['max_retries']:
            return "retry"
        else:
            return "end"
    
    # If skip_test is True, skip analyze_playbook and go directly to test_on_test_host
    # (Note: when skip_test is True, test_on_test_host will be skipped in the flow)
    if state.get('skip_test', False):
        return "test_on_test_host"
    
    # If playbook hasn't been modified, skip analyze_playbook and go directly to test_on_test_host
    if not state.get('playbook_modified', True):
        print("⏭️  Skipping analyze_playbook - playbook content unchanged")
        return "test_on_test_host"
    
    # Otherwise, analyze playbook structure first
    return "analyze_playbook"


def should_continue_after_analyze_playbook(state: PlaybookGenerationState) -> Literal["test_on_test_host", "retry", "end"]:
    """Conditional edge: Decide what to do after playbook structure analysis."""
    print(f"\n{'='*80} should_continue_after_analyze_playbook")
    if not state.get('playbook_structure_valid', True):
        if state['attempt'] < state['max_retries']:
            return "retry"
        else:
            return "end"
    return "test_on_test_host"


def should_continue_after_test(state: PlaybookGenerationState) -> Literal["analyze_output", "retry", "end"]:
    """Conditional edge: Decide what to do after test execution."""
    print(f"\n{'='*80} should_continue_after_test")
    # Check for connection errors - don't retry, just end
    if state.get('connection_error', False):
        return "end"  # Connection error - cannot validate, exit with warning
    
    if not state['test_success']:
        if state['attempt'] < state['max_retries']:
            return "retry"
        else:
            return "end"
    return "analyze_output"  # Test passed, now analyze output


def move_to_next_test_host_node(state: PlaybookGenerationState) -> PlaybookGenerationState:
    """LangGraph node: Move to next test host in the list."""
    print(f"\n{'='*80} move_to_next_test_host_node")
    
    test_hosts = state.get('test_hosts', [])
    current_index = state.get('current_test_host_index', 0)
    previous_host = state.get('test_host', '')
    
    if current_index + 1 < len(test_hosts):
        next_index = current_index + 1
        next_host = test_hosts[next_index]
        state['current_test_host_index'] = next_index
        state['test_host'] = next_host
        state['attempt'] = 1  # Reset attempt counter for new host
        state['playbook_modified'] = False  # Playbook unchanged when moving to next host
        state['playbook_structure_valid'] = False  # Reset playbook structure analysis
        state['playbook_structure_analysis'] = ""  # Clear previous playbook structure analysis
        state['analysis_passed'] = False  # Reset analysis status
        state['analysis_message'] = ""  # Clear previous analysis
        state['test_success'] = False  # Reset test status
        state['test_output'] = ""  # Clear previous test output
        state['error_message'] = ""  # Clear previous errors
        state['syntax_valid'] = False  # Reset syntax check (will re-check)
        
        print(f"✅ Test host {current_index + 1}/{len(test_hosts)} ({previous_host}) passed all analysis!")
        print(f"🔄 Moving to next test host: {next_host} (host {next_index + 1}/{len(test_hosts)})")
        print(f"🔄 Reset attempt counter to 1 for new host")
        print(f"📋 Using enhanced playbook from previous host")
    else:
        print(f"⚠️  No more test hosts to process")
    
    return state


def should_continue_after_check_existing(state: PlaybookGenerationState) -> Literal["generate", "execute_on_target", "end"]:
    """Conditional edge: Decide what to do after checking existing playbook."""
    print(f"\n{'='*80} should_continue_after_check_existing")
    
    # If skip_test is True, go directly to execute_on_target
    if state.get('skip_test', False):
        # Check if there was an error (e.g., playbook not found)
        # Only return "end" if there's an explicit error_message
        # workflow_complete may be False initially (default), which is OK - we'll set it later
        if state.get('error_message'):
            print("❌ Error detected - cannot proceed with skip_test")
            return "end"
        print("⏭️  Skipping all test tasks, proceeding directly to target execution")
        return "execute_on_target"
    
    # Normal flow: proceed to generate
    return "generate"


def should_continue_after_analysis(state: PlaybookGenerationState) -> Literal["execute_on_target", "retry", "next_test_host", "end"]:
    """Conditional edge: Decide what to do after output analysis."""
    print(f"\n{'='*80} should_continue_after_analysis")
    
    # When skip_test is True, analysis is done and workflow is complete
    if state.get('skip_test', False):
        if state.get('workflow_complete', False):
            return "end"
        else:
            # Analysis failed, but we can't retry when skip_test is True
            return "end"
    
    # Check if we have multiple test hosts
    test_hosts = state.get('test_hosts', [])
    current_index = state.get('current_test_host_index', 0)
    
    # Only regenerate if PLAYBOOK ANALYSIS: FAIL
    # The state['analysis_passed'] is already set based on PLAYBOOK ANALYSIS status
    if not state['analysis_passed']:
        if state['attempt'] < state['max_retries']:
            return "retry"
        else:
            return "end"
    
    # Analysis passed - check if we have more test hosts
    if len(test_hosts) > 1 and current_index + 1 < len(test_hosts):
        # Move to next test host
        return "next_test_host"
    
    # All test hosts passed, proceed to target
    # Note: execute_on_target_host_node() will check skip_execution and handle it appropriately
    return "execute_on_target"


def should_continue_after_final(state: PlaybookGenerationState) -> Literal["analyze_output", "end"]:
    """Conditional edge: After final execution, analyze if skip_test, else end."""
    print(f"\n{'='*80} should_continue_after_final")
    
    # If skip_test is True, we need to analyze the output from target execution
    if state.get('skip_test', False):
        print("⏭️  skip_test=True: End")
        return "end"
    
    return "end"


def create_playbook_workflow() -> StateGraph:
    """Create the LangGraph workflow for playbook generation."""
    
    # Create workflow graph
    workflow = StateGraph(PlaybookGenerationState)
    
    # Add nodes
    workflow.add_node("check_existing_playbook", check_existing_playbook_node)
    workflow.add_node("generate", generate_playbook_node)
    workflow.add_node("save", save_playbook_node)
    workflow.add_node("check_syntax", check_syntax_node)
    workflow.add_node("analyze_playbook", analyze_playbook_node)  # New node for playbook structure analysis
    workflow.add_node("test_on_test_host", test_on_test_host_node)
    workflow.add_node("analyze_output", analyze_output_node)  # New analysis node
    workflow.add_node("execute_on_target", execute_on_target_host_node)
    workflow.add_node("increment_attempt", increment_attempt_node)  # Increment counter before retry
    workflow.add_node("move_to_next_test_host", move_to_next_test_host_node)  # Move to next test host
    
    # Define edges
    workflow.set_entry_point("check_existing_playbook")
    # Conditional edge from check_existing_playbook: route to generate or execute_on_target
    workflow.add_conditional_edges(
        "check_existing_playbook",
        should_continue_after_check_existing,
        {
            "generate": "generate",
            "execute_on_target": "execute_on_target",
            "end": END
        }
    )
    workflow.add_edge("generate", "save")
    workflow.add_edge("save", "check_syntax")
    workflow.add_edge("increment_attempt", "generate")  # After incrementing, regenerate
    
    # Conditional edges
    workflow.add_conditional_edges(
        "check_syntax",
        should_continue_after_syntax,
        {
            "analyze_playbook": "analyze_playbook",
            "test_on_test_host": "test_on_test_host",
            "retry": "increment_attempt",  # Go to increment node first
            "end": END
        }
    )
    
    # Conditional edge from analyze_playbook
    workflow.add_conditional_edges(
        "analyze_playbook",
        should_continue_after_analyze_playbook,
        {
            "test_on_test_host": "test_on_test_host",
            "retry": "increment_attempt",  # Go to increment node first
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "test_on_test_host",
        should_continue_after_test,
        {
            "analyze_output": "analyze_output",  # Test passed -> Analyze
            "retry": "increment_attempt",  # Go to increment node first
            "end": END
        }
    )
    
    workflow.add_conditional_edges(
        "analyze_output",
        should_continue_after_analysis,
        {
            "execute_on_target": "execute_on_target",  # Analysis passed -> Execute on target
            "next_test_host": "move_to_next_test_host",  # Analysis passed -> Move to next test host
            "retry": "increment_attempt",  # Go to increment node first
            "end": END
        }
    )
    
    # After moving to next test host, go back to syntax check (playbook is already saved)
    workflow.add_edge("move_to_next_test_host", "check_syntax")
    
    workflow.add_conditional_edges(
        "execute_on_target",
        should_continue_after_final,
        {
            "analyze_output": "analyze_output",  # When skip_test, analyze target output
            "end": END
        }
    )
    
    # When skip_test is True, after execute_on_target, analyze the output
    # Add conditional edge: if skip_test, route to analyze_output, else end
    # Actually, we'll handle this in should_continue_after_final
    # But we need to route execute_on_target -> analyze_output when skip_test is True
    # Let's create a new conditional function for this
    
    return workflow.compile()


def _is_verbose_level(verbose: str, min_level: str = "v") -> bool:
    """
    Check if verbose level meets minimum requirement.
    
    Args:
        verbose: Current verbose level ("v", "vv", "vvv", or empty string for silent)
        min_level: Minimum required level ("v", "vv", or "vvv")
        
    Returns:
        bool: True if verbose level meets or exceeds minimum
    """
    verbose_levels = {"": 0, "v": 1, "vv": 2, "vvv": 3}
    current_level = verbose_levels.get(verbose.lower(), 1)
    required_level = verbose_levels.get(min_level.lower(), 1)
    return current_level >= required_level


def generate_playbook_workflow(
    objective: str,
    requirements: list,
    target_host: str = "master-1",
    test_host: str = None,
    become_user: str = "root",
    filename: str = "generated_playbook.yml",
    example_output: str = "",
    audit_procedure: str = None,
    max_retries: int = None,
    verbose: str = "v",
    enhance: bool = True,
    skip_execution: bool = False,
    skip_test: bool = False,
    skip_playbook_analysis: bool = False
) -> dict:
    """
    Generate and execute an Ansible playbook using LangGraph workflow.
    
    This is the programmatic API that can be called from other Python scripts.
    
    Args:
        objective: Playbook objective description
        requirements: List of requirement strings
        target_host: Target host for execution
        test_host: Test host for validation (defaults to target_host)
        become_user: User to become when executing tasks
        filename: Output filename for generated playbook
        example_output: Example command output for context
        audit_procedure: CIS Benchmark audit procedure (optional)
        max_retries: Maximum retry attempts (auto-calculated if None)
        verbose: Verbose level - "v" (default, basic info), "vv" (detailed), "vvv" (very detailed), "" (silent)
        enhance: If True, check for existing playbook and skip generation if found (default: True)
        
    Returns:
        dict: Final workflow state with results
        
    Raises:
        Exception: If workflow fails
    """
    import sys
    
    # Normalize verbose level (handle legacy bool values for backward compatibility)
    if isinstance(verbose, bool):
        verbose = "v" if verbose else ""
    elif verbose not in ["", "v", "vv", "vvv"]:
        verbose = "v"  # Default to "v" if invalid value
    
    # Parse comma-separated test hosts
    if test_host is None:
        test_host = target_host
    
    # Split test_host by comma to support multiple hosts
    test_hosts = [h.strip() for h in test_host.split(',') if h.strip()]
    if not test_hosts:
        test_hosts = [target_host]
    
    # Use first test host as the initial test_host
    initial_test_host = test_hosts[0]
    
    if max_retries is None:
        max_retries = int(len(requirements) * 1.5)
        if _is_verbose_level(verbose, "v"):
            print(f"\n💡 Auto-calculated max retries: {max_retries} (1.5x {len(requirements)} requirements)")
    
    # Display configuration
    if _is_verbose_level(verbose, "v"):
        print("\n" + "=" * 80)
        print("🎯 CONFIGURATION (LangGraph Workflow)")
        print("=" * 80)
        if len(test_hosts) > 1:
            print(f"Test Hosts:     {', '.join(test_hosts)} ({len(test_hosts)} hosts)")
            print(f"Target Host:    {target_host}")
            print("\n📋 Execution Strategy:")
            for idx, host in enumerate(test_hosts, 1):
                print(f"   {idx}. Test on: {host} (validate and enhance until pass)")
            print(f"   {len(test_hosts) + 1}. Execute on: {target_host} (after all test hosts pass)")
        else:
            print(f"Test Host:      {initial_test_host}")
            if initial_test_host != target_host:
                print(f"Target Host:    {target_host}")
            print("\n📋 Execution Strategy:")
            print(f"   1. Test on: {initial_test_host} (validation)")
            if initial_test_host != target_host:
                print(f"   2. Execute on: {target_host} (if test succeeds)")
        print(f"Become User:    {become_user}")
        print(f"Max Retries:    {max_retries}")
        print(f"Objective:      {objective[:60]}{'...' if len(objective) > 60 else ''}")
        print(f"Requirements:   {len(requirements)} items")
        if audit_procedure:
            print(f"Audit Proc:     {len(audit_procedure)} chars (CIS Benchmark audit procedure provided)")
        print(f"Filename:       {filename}")
        print(f"Enhance:        {enhance} (check for existing playbook)")
        if skip_execution:
            print(f"Skip Execution: {skip_execution} (will NOT execute on target host)")
        if skip_test:
            print(f"Skip Test:      {skip_test} (will skip all test tasks, execute directly on target)")
        print("=" * 80)
    
    # Initialize state
    initial_state: PlaybookGenerationState = {
        "playbook_objective": objective,
        "target_host": target_host,
        "test_host": initial_test_host,  # First test host
        "become_user": become_user,
        "requirements": requirements.copy(),
        "example_output": example_output,
        "filename": filename,
        "max_retries": max_retries,
        "audit_procedure": audit_procedure or "",
        "attempt": 1,
        "playbook_content": "",
        "playbook_modified": True,  # Assume modified initially (will be set correctly by nodes)
        "syntax_valid": False,
        "playbook_structure_valid": False,  # New field for playbook structure analysis
        "playbook_structure_analysis": "",  # New field for playbook structure analysis message
        "test_success": False,
        "analysis_passed": False,
        "analysis_message": "",
        "final_success": False,
        "error_message": "",
        "test_output": "",
        "final_output": "",
        "connection_error": False,
        "should_retry": False,
        "workflow_complete": False,
        "enhance": enhance,
        "skip_execution": skip_execution,  # Skip execution on target host if True
        "skip_test": skip_test,  # Skip all test-related tasks if True
        "skip_playbook_analysis": skip_playbook_analysis,
        "test_hosts": test_hosts,  # List of all test hosts
        "current_test_host_index": 0,  # Start with first host
    }
    
    # Create and run workflow
    try:
        if _is_verbose_level(verbose, "v"):
            print("\n🔄 Starting LangGraph workflow...")
        workflow = create_playbook_workflow()
        
        # Execute workflow with increased recursion limit
        recursion_limit = max(100, max_retries * 6)
        final_state = workflow.invoke(
            initial_state,
            {"recursion_limit": recursion_limit}
        )
        
        # Check results
        # Handle connection errors separately
        if final_state.get('connection_error', False):
            if _is_verbose_level(verbose, "v"):
                print("\n" + "="*80)
                print("⚠️  WORKFLOW TERMINATED: Connection Error")
                print("="*80)
                print(f"   The playbook syntax is valid but cannot be validated on the host.")
                print(f"   Playbook file: {final_state['filename']}")
                print("="*80)
            # Return state but mark as incomplete due to connection error
            final_state['workflow_complete'] = False
            return final_state
        
        # Check for success: workflow_complete AND (test_success OR skip_execution OR skip_test)
        # When skip_execution is True, we still need test_success from test hosts
        # When skip_test is True, we execute directly on target, so final_success indicates success
        is_success = (
            final_state['workflow_complete'] and 
            (
                final_state['test_success'] or 
                final_state.get('skip_execution', False) or 
                final_state.get('skip_test', False) or
                final_state.get('final_success', False)
            )
        )
        
        if is_success:
            if _is_verbose_level(verbose, "v"):
                print("\n" + "="*80)
                print("📊 EXECUTION SUMMARY (LangGraph)")
                print("="*80)
                print(f"✅ Workflow completed successfully!")
                print(f"   Total attempts: {final_state['attempt']}")
                print(f"   Playbook file: {final_state['filename']}")
                if final_state.get('skip_execution', False):
                    print(f"   ⏭️  Execution on target host was skipped (--skip-execution flag)")
                if final_state.get('skip_test', False):
                    print(f"   ⏭️  Test tasks were skipped (--skip-test flag) - executed directly on target")
                print("="*80)
            return final_state
        else:
            if _is_verbose_level(verbose, "v"):
                print("\n" + "="*80)
                print("📊 EXECUTION SUMMARY (LangGraph)")
                print("="*80)
                print(f"❌ Workflow failed")
                print(f"   Total attempts: {final_state['attempt']}/{max_retries}")
                print(f"   workflow_complete: {final_state.get('workflow_complete', False)}")
                print(f"   test_success: {final_state.get('test_success', False)}")
                print(f"   final_success: {final_state.get('final_success', False)}")
                print(f"   skip_execution: {final_state.get('skip_execution', False)}")
                print(f"   skip_test: {final_state.get('skip_test', False)}")
                print(f"   syntax_valid: {final_state.get('syntax_valid', False)}")
                print(f"   playbook_structure_valid: {final_state.get('playbook_structure_valid', True)}")
                print(f"   analysis_passed: {final_state.get('analysis_passed', False)}")
                print(f"   attempt: {final_state.get('attempt', 0)}/{final_state.get('max_retries', 0)}")
                print(f"   Last error: {final_state['error_message'][:500] if final_state.get('error_message') else 'No error message'}")
                if final_state.get('playbook_structure_analysis'):
                    print(f"\n   Playbook Structure Analysis:")
                    print("   " + "="*76)
                    # Print key lines from playbook structure analysis
                    analysis_lines = final_state['playbook_structure_analysis'].split('\n')
                    for line in analysis_lines[:20]:  # Show first 20 lines
                        if line.strip():
                            print(f"   {line}")
                    if len(analysis_lines) > 20:
                        print(f"   ... ({len(analysis_lines) - 20} more lines)")
                    print("   " + "="*76)
                if final_state.get('analysis_message'):
                    print(f"\n   Analysis Message Preview:")
                    print(f"   {final_state['analysis_message'][:500]}...")
                print("="*80)
            error_msg = final_state.get('error_message', '')
            if not error_msg:
                # Build a more descriptive error message based on state
                if not final_state.get('workflow_complete', False):
                    # Check what specific condition failed
                    failure_reasons = []
                    failure_details = []
                    
                    if not final_state.get('syntax_valid', True):
                        failure_reasons.append("syntax check failed")
                    
                    if not final_state.get('playbook_structure_valid', True):
                        failure_reasons.append("playbook structure analysis failed")
                        # Include playbook structure analysis details if available
                        playbook_structure_analysis = final_state.get('playbook_structure_analysis', '')
                        if playbook_structure_analysis:
                            # Extract key failure points from analysis (avoid duplicates)
                            analysis_lines = playbook_structure_analysis.split('\n')
                            key_lines = []
                            seen_lines = set()
                            for line in analysis_lines:
                                line_stripped = line.strip()
                                # Skip empty lines and already seen lines
                                if not line_stripped or line_stripped in seen_lines:
                                    continue
                                # Look for key failure indicators
                                if any(keyword in line_stripped.upper() for keyword in ['FAIL', 'MISSING', 'WRONG', 'INCORRECT', 'ERROR', 'REQUIREMENT']):
                                    # Avoid adding the same content multiple times
                                    if line_stripped not in seen_lines:
                                        key_lines.append(line_stripped)
                                        seen_lines.add(line_stripped)
                                        if len(key_lines) >= 3:  # Limit to 3 key lines to avoid duplication
                                            break
                            if key_lines:
                                failure_details.append(f"Playbook structure: {key_lines[0][:150]}")
                    
                    if not final_state.get('test_success', False) and not final_state.get('skip_test', False):
                        failure_reasons.append("test execution failed")
                        # Include test output error if available
                        test_output = final_state.get('test_output', '')
                        if test_output:
                            # Extract error from test output
                            error_keywords = ['ERROR', 'FAILED', 'PLAYBOOK BUG', 'undefined', 'syntax error']
                            output_lines = test_output.split('\n')
                            for line in output_lines:
                                if any(keyword in line.upper() for keyword in error_keywords):
                                    failure_details.append(f"Test error: {line.strip()[:150]}")
                                    break
                    
                    if not final_state.get('analysis_passed', True):
                        failure_reasons.append("analysis failed")
                        # Include analysis message details if available (only if different from playbook_structure_analysis)
                        analysis_message = final_state.get('analysis_message', '')
                        playbook_structure_analysis = final_state.get('playbook_structure_analysis', '')
                        # Check if analysis_message is substantially different from playbook_structure_analysis
                        # (they might be the same if playbook structure analysis was copied to analysis_message)
                        is_different = False
                        if analysis_message and playbook_structure_analysis:
                            # Check if they're the same or if one is a substring of the other
                            if analysis_message != playbook_structure_analysis:
                                # Check if they share less than 80% of their content
                                shorter = min(len(analysis_message), len(playbook_structure_analysis))
                                longer = max(len(analysis_message), len(playbook_structure_analysis))
                                if shorter > 0 and longer > 0:
                                    # Simple similarity check: if one is not mostly contained in the other
                                    if analysis_message not in playbook_structure_analysis and playbook_structure_analysis not in analysis_message:
                                        is_different = True
                                    elif shorter / longer < 0.8:  # Less than 80% overlap
                                        is_different = True
                        elif analysis_message and not playbook_structure_analysis:
                            is_different = True
                        
                        if is_different:
                            # Extract key failure points from analysis (avoid duplicates with playbook structure)
                            analysis_lines = analysis_message.split('\n')
                            key_lines = []
                            seen_lines = set()
                            for line in analysis_lines:
                                line_stripped = line.strip()
                                # Skip empty lines and already seen lines
                                if not line_stripped or line_stripped in seen_lines:
                                    continue
                                # Skip if this line is already in playbook structure analysis
                                if playbook_structure_analysis and line_stripped in playbook_structure_analysis:
                                    continue
                                # Look for key failure indicators (focus on different sections)
                                if any(keyword in line_stripped.upper() for keyword in ['DATA COLLECTION', 'REMEDIATION EXECUTION', 'REMEDIATION VERIFICATION', 'PLAYBOOK ANALYSIS', 'INSUFFICIENT', 'MISALIGNMENT']):
                                    if line_stripped not in seen_lines:
                                        key_lines.append(line_stripped)
                                        seen_lines.add(line_stripped)
                                        if len(key_lines) >= 2:  # Limit to 2 key lines to avoid duplication
                                            break
                            if key_lines:
                                failure_details.append(f"Analysis: {key_lines[0][:150]}")
                    
                    if not final_state.get('test_output'):
                        failure_reasons.append("test output missing")
                    
                    if failure_reasons:
                        error_msg = f"Workflow did not complete successfully. Failed conditions: {', '.join(failure_reasons)}"
                        if failure_details:
                            error_msg += f". Details: {' | '.join(failure_details)}"
                    else:
                        error_msg = "Workflow did not complete successfully (workflow_complete=False but no specific failure reason identified)"
                elif not (final_state.get('test_success', False) or 
                         final_state.get('skip_execution', False) or 
                         final_state.get('skip_test', False) or
                         final_state.get('final_success', False)):
                    # Workflow completed but didn't meet success criteria
                    missing_criteria = []
                    if not final_state.get('test_success', False) and not final_state.get('skip_test', False):
                        missing_criteria.append("test_success")
                    if not final_state.get('skip_execution', False) and not final_state.get('skip_test', False):
                        missing_criteria.append("skip_execution")
                    if not final_state.get('final_success', False):
                        missing_criteria.append("final_success")
                    error_msg = f"Workflow completed but success criteria not met. Missing: {', '.join(missing_criteria)}"
                else:
                    error_msg = "Unknown workflow failure"
            
            # Include additional context in error message
            context_info = []
            if final_state.get('attempt'):
                context_info.append(f"attempt {final_state['attempt']}/{final_state.get('max_retries', '?')}")
            
            # Add analysis message preview if not already included in error_msg
            if final_state.get('analysis_message') and 'Analysis issues' not in error_msg:
                analysis_preview = final_state['analysis_message'][:300]
                context_info.append(f"analysis preview: {analysis_preview}...")
            
            if context_info:
                error_msg = f"{error_msg} (Context: {', '.join(context_info)})"
            
            raise Exception(f"Workflow failed: {error_msg}")
            
    except Exception as e:
        if _is_verbose_level(verbose, "v"):
            print(f"\n❌ Error in LangGraph workflow: {str(e)}")
            import traceback
            traceback.print_exc()
        raise


def main():
    """Main execution function using LangGraph workflow."""
    
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(
        description='Generate and execute Ansible playbooks using AI with LangGraph',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use all defaults
  python3 langgraph_deepseek_generate_playbook.py
  
  # Specify custom target host
  python3 langgraph_deepseek_generate_playbook.py --target-host worker-1
  
  # Two-stage execution
  python3 langgraph_deepseek_generate_playbook.py \\
    --test-host 192.168.122.16 \\
    --target-host 192.168.122.17
  
  # Multiple test hosts (comma-separated)
  python3 langgraph_deepseek_generate_playbook.py \\
    --test-host 192.168.122.16,192.168.122.17 \\
    --target-host 192.168.122.18
"""
    )
    
    parser.add_argument('--target-host', '-t', type=str, default='master-1',
                        help='Target host to execute the playbook on')
    parser.add_argument('--test-host', type=str, default=None,
                        help='Test host(s) for validation before target execution (comma-separated for multiple hosts)')
    parser.add_argument('--become-user', '-u', type=str, default='root',
                        help='User to become when executing tasks')
    parser.add_argument('--max-retries', '-r', type=int, default=None,
                        help='Maximum number of retry attempts')
    parser.add_argument('--objective', '-o', type=str,
                        default="Create an Ansible playbook that finds and kills processes that have 'packet_recvmsg' in their stack trace.",
                        help='Playbook objective')
    parser.add_argument('--requirement', action='append', dest='requirements',
                        help='Add a requirement (can be used multiple times)')
    parser.add_argument('--example-output', '-e', type=str,
                        default="""[root@master-1 ~]# egrep packet_recvmsg /proc/*/stack
/proc/2290657/stack:[<0>] packet_recvmsg+0x6e/0x4f0
grep: /proc/2290657/stack: No such file or directory

[root@master-1 ~]# ps -ef | grep -i 2290657
root     2290657 2526847  0 12:13 ?        00:00:00 ./bpfdoor
root     2822221 2819327  0 13:07 pts/1    00:00:00 grep --color=auto -i 2290657

[root@master-1 ~]# kill -9 2290657""",
                        help='Example command output')
    parser.add_argument('--filename', '-f', type=str,
                        default='kill_packet_recvmsg_process.yml',
                        help='Output filename for the generated playbook')
    parser.add_argument('--audit-procedure', type=str, default=None,
                        help='CIS Benchmark audit procedure (shell script or commands)')
    parser.add_argument('--no-enhance', dest='enhance', action='store_false',
                        help='Disable enhance mode (always generate new playbook). Default: enhance=True (check for existing playbook)')
    parser.add_argument('--generate', action='store_true',
                        help='Force playbook generation regardless of whether playbook exists (equivalent to --no-enhance)')
    parser.add_argument('--skip-execution', dest='skip_execution', action='store_true',
                        help='Skip execution on target host (only test on test hosts)')
    parser.add_argument('--skip-test', dest='skip_test', action='store_true',
                        help='Skip all test-related tasks and execute directly on target host (playbook must exist)')
    parser.add_argument('-v', '--verbose', action='count', default=1,
                        help='Verbose level: -v (default, basic info), -vv (detailed), -vvv (very detailed). Use --quiet for silent mode.')
    parser.add_argument('--quiet', '-q', action='store_const', const=0, dest='verbose',
                        help='Quiet mode (no verbose output)')
    
    args = parser.parse_args()
    
    # Convert count to string level: 0="", 1="v", 2="vv", 3="vvv"
    verbose_level = ""
    if args.verbose == 1:
        verbose_level = "v"
    elif args.verbose == 2:
        verbose_level = "vv"
    elif args.verbose >= 3:
        verbose_level = "vvv"
    
    # If --generate is specified, set enhance=False
    if args.generate:
        args.enhance = False
    
    # Set default enhance=True if not explicitly set via --no-enhance or --generate
    if not hasattr(args, 'enhance') or args.enhance is None:
        args.enhance = True
    
    # Prepare parameters
    target_host = args.target_host
    test_host = args.test_host if args.test_host else target_host
    become_user = args.become_user
    playbook_objective = args.objective
    example_output = args.example_output
    filename = args.filename
    audit_procedure = args.audit_procedure
    
    if args.requirements:
        requirements = args.requirements
    else:
        requirements = [
            "Search for 'packet_recvmsg' keyword in /proc/*/stack",
            "Extract the process ID from the path",
            "Kill the identified process(es) using 'kill -9'",
            "Handle cases where: No matching processes found, Multiple processes found, Process disappears",
            "Display useful information: Show processes found, Show process details, Confirm termination"
        ]
    
    # Call generate_playbook_workflow function (handles all workflow logic)
    try:
        final_state = generate_playbook_workflow(
            objective=playbook_objective,
            requirements=requirements,
            target_host=target_host,
            test_host=test_host,
            become_user=become_user,
            filename=filename,
            example_output=example_output,
            audit_procedure=audit_procedure,
            max_retries=args.max_retries,
            verbose=verbose_level,
            enhance=args.enhance,
            skip_execution=getattr(args, 'skip_execution', False),
            skip_test=getattr(args, 'skip_test', False)
        )
        
        # Check if successful (generate_playbook_workflow raises exception on failure)
        # If we get here, it means workflow completed successfully
        print("\n" + "="*80)
        print("📊 EXECUTION SUMMARY (LangGraph)")
        print("="*80)
        print(f"✅ Workflow completed successfully!")
        print(f"   Total attempts: {final_state['attempt']}")
        print(f"   Playbook file: {final_state['filename']}")
        if final_state.get('skip_execution', False):
            print(f"   ⏭️  Execution on target host was skipped (--skip-execution flag)")
        if final_state.get('skip_test', False):
            print(f"   ⏭️  Test tasks were skipped (--skip-test flag) - executed directly on target")
        print("="*80)
            
    except Exception as e:
        print(f"\n❌ Error in LangGraph workflow: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
