#!/usr/bin/env python3
"""
KCS to Ansible Playbook Generator

This script:
1. Searches Red Hat KCS for articles matching a query
2. Extracts ENVIRONMENT information from the top result
3. Uses DeepSeek AI to generate playbook requirements and objectives
4. Generates an Ansible playbook to verify the environment
5. Executes the playbook on the target host

Usage:
    python3 kcs_to_playbook.py
    python3 kcs_to_playbook.py --search "kernel panic" --target-host 192.168.122.16
"""

import os
import sys
import json
import argparse
import subprocess
import webbrowser
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek
from langchain_core.prompts import ChatPromptTemplate

# Import functions from kcsv2.py
from kcsv2 import (
    get_red_hat_access_token,
    search_v2_kcs,
    strip_html
)

# Load environment variables
load_dotenv()

# Initialize LLM model
model = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2
)

# Initialize LLM model
reasoner_model = ChatDeepSeek(
    model="deepseek-reasoner",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2
)

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


def generate_playbook_requirements_from_environment(environment_info):
    """
    Use DeepSeek AI to generate playbook requirements and objectives
    based on the KCS environment information.
    
    This function generates requirements for SERVER INFORMATION COLLECTION
    (not compliance verification). The collected information will be used
    by AI to determine if the server environment is similar to the KCS article.
    
    Args:
        environment_info: Dict containing environment, issue, resolution, etc.
        
    Returns:
        dict: {
            'objective': str,
            'requirements': list[str]
        }
    """
    environment_text = environment_info.get('environment', '')
    issue_text = environment_info.get('issue', '')
    resolution_text = environment_info.get('resolution', '')
    title = environment_info.get('title', '')
    
    ## Truncate if too long
    #if len(environment_text) > 2000:
    #    environment_text = environment_text[:2000] + "..."
    #if len(issue_text) > 1000:
    #    issue_text = issue_text[:1000] + "..."
    #if len(resolution_text) > 2000:
    #    resolution_text = resolution_text[:2000] + "..."
    
    prompt_template = """You are an expert system administrator analyzing Red Hat KCS articles.

Based on the following KCS article information, generate:
1. A clear playbook objective (one sentence) focused on DATA COLLECTION
2. A list of 5-10 specific requirements for an Ansible playbook that will COLLECT SERVER INFORMATION

**IMPORTANT: This is for a SERVER INFORMATION COLLECTION playbook that:**
- COLLECTS information about the server environment (OS, packages, services, configurations, etc.)
- Does NOT determine compliance or make judgments
- Gathers raw data that will be analyzed by AI afterward
- Never fails - always completes with collected data
- Reports what was found (or error messages if data cannot be collected)

**The collected information will be used to:**
- Compare server environment against KCS article environment
- Determine if server matches the scenario described in the KCS
- Identify similarities and differences
- Justify whether the KCS article solution applies to this server

**KCS Article Title:**
{title}

**Environment Information:**
{environment}

**Issue/Problem:**
{issue}

**Resolution:**
{resolution}

**Task:**
Generate an Ansible playbook objective and requirements that will COLLECT information about:
- OS version, distribution, kernel version
- Installed packages and their versions (especially those mentioned in KCS)
- Service status and configurations (especially those mentioned in KCS)
- System configurations, settings, and parameters
- File contents, directory structures (if mentioned in KCS)
- Network settings, firewall rules (if mentioned in KCS)
- Any other relevant system information mentioned in the KCS environment

**Output Format:**
Return ONLY a valid JSON object with this exact structure (no markdown, no code blocks):
{{
  "objective": "Collect server information to compare against <KCS environment description>",
  "requirements": [
    "Collect OS distribution, version, and kernel information",
    "Collect installed version of package X (or report if not installed)",
    "Collect status and configuration of service Y",
    "Collect content/settings from configuration file Z",
    "Collect system parameter W value",
    ...
  ]
}}

**Important Guidelines:**
- Frame each requirement as "Collect...", "Gather...", or "Retrieve..." (NOT "Verify...", "Check...", or "Validate...")
- Focus on INFORMATION GATHERING, not compliance checking
- If something doesn't exist (package not installed, file not found), that's valid data to collect
- Requirements should gather facts that can be compared to the KCS environment
- Include all key components mentioned in the KCS environment section

Generate the JSON now:"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    #chain = prompt | reasoner_model
    chain = prompt | model
    
    print("\n" + "="*100)
    print("🤖 Generating playbook requirements using DeepSeek AI...")
    print("="*100)
    
    response = chain.invoke({
        'title': title,
        'environment': environment_text if environment_text else 'Not specified',
        'issue': issue_text if issue_text else 'Not specified',
        'resolution': resolution_text if resolution_text else 'Not specified'
    })
    
    response_text = response.content.strip()
    
    # Clean up response - remove markdown code blocks if present
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()
    
    # Parse JSON
    try:
        result = json.loads(response_text)
        return result
    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse JSON response: {e}")
        print(f"Response was: {response_text[:500]}")
        # Fallback to a simple structure
        return {
            'objective': f"Verify environment for: {title[:100]}",
            'requirements': [
                "Check system environment",
                "Verify package versions",
                "Check configuration files",
                "Verify system state"
            ]
        }


def run_playbook_generation(objective, requirements, target_host, test_host, become_user, filename, skip_execution=True):
    """
    Call langgraph_deepseek_generate_playbook.py to generate and execute the playbook.
    
    Args:
        objective: Playbook objective string
        requirements: List of requirement strings
        target_host: Target host to run on
        test_host: Test host for validation
        become_user: User to become
        filename: Output filename for playbook
        skip_execution: If True, only generate playbook without execution
        
    Returns:
        tuple: (success, output)
    """
    print("\n" + "="*100)
    if skip_execution:
        print("🔧 Calling langgraph_deepseek_generate_playbook.py to GENERATE playbook (no execution)...")
    else:
        print("🚀 Calling langgraph_deepseek_generate_playbook.py to generate and execute playbook...")
    print("="*100)
    
    # Calculate max retries based on number of requirements
    max_retries = max(len(requirements), 3)  # At least 3, or number of requirements
    print(f"Max retries: {max_retries} (based on {len(requirements)} requirements)")
    
    # Build command
    cmd = [
        'python3',
        'langgraph_deepseek_generate_playbook.py',
        '--objective', objective,
        '--target-host', target_host,
        '--become-user', become_user,
        '--filename', filename,
        '--max-retries', str(max_retries)
    ]
    
    # Add test host if different from target
    if test_host and test_host != target_host:
        cmd.extend(['--test-host', test_host])
    
    # Add requirements
    for req in requirements:
        cmd.extend(['--requirement', req])
    
    # Display full command
    print(f"\n📍 Full Command:")
    print("="*100)
    print("python3 langgraph_deepseek_generate_playbook.py \\")
    print(f"  --objective '{objective}' \\")
    print(f"  --target-host {target_host} \\")
    if test_host and test_host != target_host:
        print(f"  --test-host {test_host} \\")
    print(f"  --become-user {become_user} \\")
    print(f"  --filename {filename} \\")
    print(f"  --max-retries {max_retries} \\")
    for idx, req in enumerate(requirements, 1):
        if idx < len(requirements):
            print(f"  --requirement '{req}' \\")
        else:
            print(f"  --requirement '{req}'")
        ## Truncate very long requirements for display
        #req_display = req if len(req) <= 80 else req[:77] + "..."
        #if idx < len(requirements):
        #    print(f"  --requirement '{req_display}' \\")
        #else:
        #    print(f"  --requirement '{req_display}'")
    print("="*100)
    print()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=False,  # Show output in real-time
            text=True,
            timeout=600  # 10 minutes timeout
        )
        
        return result.returncode == 0, "Playbook generation completed"
        
    except subprocess.TimeoutExpired:
        return False, "Playbook generation timed out after 10 minutes"
    except Exception as e:
        return False, f"Error running playbook generation: {str(e)}"


def main():
    """Main execution function."""
    
    parser = argparse.ArgumentParser(
        description='Generate Ansible verification playbooks from Red Hat KCS articles',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for a KCS article and generate verification playbook
  python3 kcs_to_playbook.py --search "kernel panic"
  
  # Specify custom target host
  python3 kcs_to_playbook.py --search "systemd failed" --target-host 192.168.122.16
  
  # Custom filename
  python3 kcs_to_playbook.py --search "network timeout" --filename verify_network.yml
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
    
    parser.add_argument(
        '--filename', '-f',
        type=str,
        default='kcs_verification.yml',
        help='Output filename for the generated playbook (default: kcs_verification.yml)'
    )
    
    parser.add_argument(
        '--num-results',
        type=int,
        default=1,
        help='Number of KCS articles to retrieve (default: 1, uses first result)'
    )
    
    parser.add_argument(
        '--show-kcs',
        action='store_true',
        help='Enable debug mode to show additional KCS metadata and statistics'
    )
    
    parser.add_argument(
        '--skip-execution',
        action='store_true',
        help='Generate playbook but skip execution (useful for OS version mismatches)'
    )
    
    parser.add_argument(
        '--no-interactive',
        action='store_true',
        help='Skip interactive requirement review (auto-accept generated requirements)'
    )
    
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='Do not automatically open KCS article in web browser'
    )
    
    args = parser.parse_args()
    
    try:
        # Step 1: Get Red Hat offline token from environment
        print("\n" + "="*100)
        print("STEP 1: Authentication")
        print("="*100)
        
        offline_token = os.environ.get('REDHAT_OFFLINE_TOKEN')
        if not offline_token:
            print("❌ Error: REDHAT_OFFLINE_TOKEN environment variable not set.")
            print("Please set it in your .env file:")
            print("  REDHAT_OFFLINE_TOKEN=your_token_here")
            sys.exit(1)
        
        print("Authenticating with Red Hat API...")
        access_token = get_red_hat_access_token(offline_token)
        print("✅ Authentication successful!")
        
        # Step 2: Search KCS
        print("\n" + "="*100)
        print(f"STEP 2: Searching KCS for: '{args.search}'")
        print("="*100)
        
        kcs_results = search_v2_kcs(access_token, args.search, args.num_results)
        
        if isinstance(kcs_results, str):
            print(f"❌ KCS search failed: {kcs_results}")
            sys.exit(1)
        
        num_found = kcs_results.get('response', {}).get('numFound', 0)
        print(f"✅ Found {num_found} KCS articles")
        
        # Step 3: Extract environment information
        print("\n" + "="*100)
        print("STEP 3: Extracting environment information from top result")
        print("="*100)
        
        env_info = extract_environment_from_kcs(kcs_results)
        
        if not env_info:
            print("❌ Failed to extract environment information")
            sys.exit(1)
        
        print(f"📄 KCS Article: {env_info['title']}")
        print(f"🔗 URL: {env_info['url']}")
        print(f"🆔 ID: {env_info['doc_id']}")
        
        # Open URL in browser for human reference (unless --no-browser)
        if not args.no_browser:
            print(f"\n🌐 Opening KCS article in web browser...")
            try:
                # Try to open in browser
                # webbrowser will try Firefox, Chrome, and other browsers in order
                webbrowser.open(env_info['url'])
                print("   ✅ Browser opened successfully")
            except Exception as e:
                print(f"   ⚠️  Could not open browser automatically: {e}")
                print(f"   Please manually open: {env_info['url']}")
        else:
            print("   ℹ️  Browser opening disabled (--no-browser flag)")
        
        # Always print detailed KCS information
        print("\n" + "-"*100)
        print("📋 KCS ARTICLE DETAILS:")
        print("-"*100)
        
        # Title
        print(f"\n📌 TITLE:")
        print(f"   {env_info['title']}")
        
        # Environment information
        print("\n" + "-"*100)
        print("🖥️  ENVIRONMENT:")
        print("-"*100)
        if env_info['environment']:
            # Truncate if too long for initial display
            env_display = env_info['environment']
            if len(env_display) > 2000:
                print(env_display[:2000])
                print(f"\n... (truncated, {len(env_display)} total characters)")
                print(f"Full details at: {env_info['url']}")
            else:
                print(env_display)
        else:
            print("⚠️  No environment information found in this KCS article")
        
        # Issue/Problem
        print("\n" + "-"*100)
        print("💡 ISSUE/PROBLEM:")
        print("-"*100)
        if env_info['issue']:
            issue_display = env_info['issue']
            if len(issue_display) > 2000:
                print(issue_display[:2000])
                print(f"\n... (truncated, {len(issue_display)} total characters)")
            else:
                print(issue_display)
        else:
            print("Not specified in this KCS article")
        
        # Resolution/Solution
        print("\n" + "-"*100)
        print("✅ RESOLUTION/SOLUTION:")
        print("-"*100)
        if env_info['resolution']:
            resolution_display = env_info['resolution']
            if len(resolution_display) > 2000:
                print(resolution_display[:2000])
                print(f"\n... (truncated, {len(resolution_display)} total characters)")
            else:
                print(resolution_display)
        else:
            print("Not specified in this KCS article")
        
        print("-"*100)
        
        # Show additional details if --show-kcs flag is used (for debugging)
        if args.show_kcs:
            print("\n" + "="*100)
            print("🔍 DEBUG MODE - Additional KCS Details")
            print("="*100)
            print(f"Full URL: {env_info['url']}")
            print(f"Document ID: {env_info['doc_id']}")
            print(f"Environment length: {len(env_info['environment'])} characters")
            print(f"Issue length: {len(env_info['issue'])} characters")
            print(f"Resolution length: {len(env_info['resolution'])} characters")
            print("="*100)
        
        if not env_info.get('environment'):
            print("⚠️  Warning: No environment information found in this KCS article")
            print("Will proceed with available information...")
        
        # Step 4: Generate playbook requirements using AI
        print("\n" + "="*100)
        print("STEP 4: Generating playbook requirements using DeepSeek AI")
        print("="*100)
        
        playbook_spec = generate_playbook_requirements_from_environment(env_info)
        
        objective = playbook_spec.get('objective', '')
        requirements = playbook_spec.get('requirements', [])
        
        print("\n📋 Generated Playbook Specification:")
        print("-"*100)
        print(f"Objective: {objective}")
        print(f"\nRequirements ({len(requirements)} items):")
        for idx, req in enumerate(requirements, 1):
            print(f"  {idx}. {req}")
        print("-"*100)
        
        # Collect human feedback to update requirements (unless --no-interactive)
        if not args.no_interactive:
            print("\n" + "="*100)
            print("📝 REQUIREMENT REVIEW AND FEEDBACK")
            print("="*100)
            print("Please review the generated requirements above.")
            print("\nOptions:")
            print("  1. Press ENTER to finalize and continue")
            print("  2. Type 'add' to add new requirements")
            print("  3. Type 'edit N' to edit requirement N (e.g., 'edit 3')")
            print("  4. Type 'delete N' to delete requirement N (e.g., 'delete 2')")
            print("  5. Type 'done' to show updated requirements and review again")
            print("="*100)
            
            while True:
                user_input = input("\n👤 Your action (press ENTER to accept, or command): ").strip()
                
                # Empty input - finalize and continue
                if not user_input:
                    print("\n✅ Requirements finalized! Proceeding to playbook generation...")
                    break
                
                # 'done' - show updated requirements and continue loop
                elif user_input.lower() == 'done':
                    print("\n📋 Updated Requirements ({} items):".format(len(requirements)))
                    print("-"*100)
                    for idx, req in enumerate(requirements, 1):
                        print(f"  {idx}. {req}")
                    print("-"*100)
                    print("\n💡 Press ENTER to accept these requirements, or continue making changes...")
                    continue
                
                # Add new requirement
                elif user_input.lower() == 'add':
                    new_req = input("   Enter new requirement: ").strip()
                    if new_req:
                        requirements.append(new_req)
                        print(f"   ✅ Added requirement {len(requirements)}: {new_req}")
                    else:
                        print("   ⚠️  Empty requirement not added")
                
                # Edit existing requirement
                elif user_input.lower().startswith('edit '):
                    try:
                        req_num = int(user_input.split()[1])
                        if 1 <= req_num <= len(requirements):
                            print(f"   Current: {requirements[req_num-1]}")
                            new_text = input("   New text: ").strip()
                            if new_text:
                                requirements[req_num-1] = new_text
                                print(f"   ✅ Updated requirement {req_num}")
                            else:
                                print("   ⚠️  Empty text, requirement not changed")
                        else:
                            print(f"   ❌ Invalid requirement number. Must be between 1 and {len(requirements)}")
                    except (ValueError, IndexError):
                        print("   ❌ Invalid format. Use: edit N (e.g., 'edit 3')")
                
                # Delete requirement
                elif user_input.lower().startswith('delete '):
                    try:
                        req_num = int(user_input.split()[1])
                        if 1 <= req_num <= len(requirements):
                            deleted = requirements.pop(req_num-1)
                            print(f"   ✅ Deleted requirement {req_num}: {deleted}")
                        else:
                            print(f"   ❌ Invalid requirement number. Must be between 1 and {len(requirements)}")
                    except (ValueError, IndexError):
                        print("   ❌ Invalid format. Use: delete N (e.g., 'delete 2')")
                
                # Show current requirements
                elif user_input.lower() == 'show':
                    print("\n📋 Current Requirements:")
                    print("-"*100)
                    for idx, req in enumerate(requirements, 1):
                        print(f"  {idx}. {req}")
                    print("-"*100)
                
                # Help
                elif user_input.lower() == 'help':
                    print("\n📖 Available commands:")
                    print("  ENTER           - Finalize and continue to playbook generation")
                    print("  done            - Show updated requirements and continue reviewing")
                    print("  add             - Add a new requirement")
                    print("  edit N          - Edit requirement number N")
                    print("  delete N        - Delete requirement number N")
                    print("  show            - Display current requirements")
                    print("  help            - Show this help message")
                
                else:
                    print("   ❌ Unknown command. Type 'help' for available commands.")
            
            # Display final requirements
            print("\n📋 Final Requirements ({} items):".format(len(requirements)))
            print("-"*100)
            for idx, req in enumerate(requirements, 1):
                print(f"  {idx}. {req}")
            print("-"*100)
        else:
            print("\n⚠️  Non-interactive mode: Auto-accepting generated requirements")
        
        # Add KCS reference to requirements
        requirements.append(f"Add comment in playbook referencing KCS article: {env_info['url']}")
        
        # Add data collection reporting requirement
        requirements.append("Generate a final DATA COLLECTION REPORT showing: the collected data/information for each requirement. If data collection fails, report the error message.")
        requirements.append("CRITICAL: Use ignore_errors: true and failed_when: false on all data collection tasks so the playbook always completes successfully and captures all available data")
        
        # Check if environment mentions a specific OS version
        env_text = env_info.get('environment', '').lower()
        if env_text:
            for version in ['rhel 6', 'rhel 7', 'rhel 8', 'rhel 9', 
                           'red hat enterprise linux 6', 'red hat enterprise linux 7',
                           'red hat enterprise linux 8', 'red hat enterprise linux 9']:
                if version in env_text:
                    print(f"\n⚠️  NOTICE: KCS article mentions '{version.upper()}' in environment")
                    print(f"   Your target host: {args.target_host}")
                    print("   Please verify your target host OS matches the KCS requirements")
                    if not args.skip_execution:
                        print("   TIP: Use --skip-execution to generate playbook without running it")
                    break
        
        # Step 5: Generate and execute playbook
        print("\n" + "="*100)
        print("STEP 5: Generating Ansible playbook")
        print("="*100)
        
        # Determine test_host
        test_host = args.test_host if args.test_host else args.target_host
        
        if test_host != args.target_host:
            print(f"Test Host:      {test_host}")
            print(f"Target Host:    {args.target_host}")
            print("\n📋 Two-Stage Execution:")
            print(f"   1. Test on: {test_host} (validation)")
            print(f"   2. Execute on: {args.target_host} (if test succeeds)")
        else:
            print(f"Target Host:    {args.target_host}")
        
        print(f"Become User:    {args.become_user}")
        print(f"Output File:    {args.filename}")
        
        if args.skip_execution:
            print("⚠️  Execution will be SKIPPED (--skip-execution flag)")
            print("   Only playbook generation and syntax validation will be performed")
        
        success, output = run_playbook_generation(
            objective=objective,
            requirements=requirements,
            target_host=args.target_host,
            test_host=test_host,
            become_user=args.become_user,
            filename=args.filename,
            skip_execution=args.skip_execution
        )
        
        # Step 6: Summary
        print("\n" + "="*100)
        print("📊 EXECUTION SUMMARY")
        print("="*100)
        
        if success:
            print("✅ Successfully generated and executed verification playbook!")
            print(f"\n📄 KCS Article: {env_info['title']}")
            print(f"🔗 URL: {env_info['url']}")
            print(f"📋 Playbook: {args.filename}")
            print(f"🎯 Target: {args.target_host}")
            print("\n✅ All steps completed successfully!")
        else:
            print("❌ Playbook generation or execution failed")
            print(f"Error: {output}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

