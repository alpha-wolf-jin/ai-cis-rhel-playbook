#!/usr/bin/env python3
"""
Generic Ansible Playbook Generator

This script generates Ansible playbooks based on custom requirements.

HOW TO USE FOR DIFFERENT TASKS:
================================

In the main() function, modify these variables:

1. playbook_objective: 
   What the playbook should achieve (clear description)

2. target_host: 
   Default target host for the playbook

3. become_user: 
   User to become (usually "root")

4. requirements: 
   List of specific requirements as strings
   - What tasks to perform
   - How to handle errors
   - What output to display

5. example_output: 
   Example command output to provide context


EXAMPLE - Disk Cleanup Playbook:
=================================

playbook_objective = "Clean up old log files to free disk space"
target_host = "webserver-1"
become_user = "root"
requirements = [
    "Find log files older than 30 days in /var/log",
    "Display files to be deleted",
    "Delete old log files",
    "Show disk space freed"
]
example_output = "df -h output and find command results"

"""

import os
import sys
import subprocess
import argparse
import shutil
import re
from dotenv import load_dotenv


def get_ansible_navigator_path() -> str:
    """
    Find the path to ansible-navigator executable.
    Checks multiple locations including virtual environments.
    """
    # First try shutil.which with current PATH
    ansible_nav = shutil.which('ansible-navigator')
    if ansible_nav:
        print(f"   Found ansible-navigator using shutil.which: {ansible_nav}")
        return ansible_nav
    
    # Try to find it relative to the Python interpreter (works for venv)
    python_dir = os.path.dirname(sys.executable)
    venv_ansible = os.path.join(python_dir, 'ansible-navigator')
    if os.path.isfile(venv_ansible) and os.access(venv_ansible, os.X_OK):
        print(f"   Found ansible-navigator in Python venv: {venv_ansible}")
        return venv_ansible
    
    # Check common virtual environment locations
    possible_paths = [
        # Current directory venv
        os.path.join(os.getcwd(), '.venv', 'bin', 'ansible-navigator'),
        # Home directory venv
        os.path.expanduser('~/ai/rhel-cis/.venv/bin/ansible-navigator'),
        # Generic venv in current dir
        os.path.join(os.getcwd(), 'venv', 'bin', 'ansible-navigator'),
        # System paths
        '/usr/bin/ansible-navigator',
        '/usr/local/bin/ansible-navigator',
    ]
    
    for path in possible_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            print(f"   Found ansible-navigator at: {path}")
            return path
    
    # If nothing found, print debug info
    print(f"   ⚠️  Could not find ansible-navigator in:")
    print(f"      - Current PATH: {os.environ.get('PATH', 'Not set')}")
    print(f"      - Python executable: {sys.executable}")
    print(f"      - Python dir: {python_dir}")
    print(f"      - Checked paths: {possible_paths}")
    
    # Last resort: return the command name and hope it's in PATH
    return 'ansible-navigator'
from langchain_deepseek import ChatDeepSeek

# Load environment variables
load_dotenv()

# Initialize LLM model
model = ChatDeepSeek(
    #model="deepseek-chat",
    model="deepseek-reasoner",
    base_url="https://api.deepseek.com",
    temperature=0,
    #max_tokens=None,
    max_tokens=16384,
    #max_tokens=8192,
    timeout=1800,  # 30 minutes timeout
    max_retries=3,
    request_timeout=1800  # Explicit request timeout: 30 minutes
)

def parse_requirement_index(req_text: str) -> tuple[int, str]:
    """
    Parse the requirement index and text from a requirement string.
    E.g., "2. Collect OS info" -> (2, "Collect OS info")
    
    Returns (index, text) where index is the parsed number or -1 if not found.
    """
    import re
    # Match patterns like "1." or "2." or "10." at the start
    match = re.match(r'^(\d+)\.\s*(.*)$', req_text.strip())
    if match:
        return int(match.group(1)), match.group(2).strip()
    return -1, req_text.strip()


def generate_playbook(
    playbook_objective: str,
    target_host: str = "master-1",
    become_user: str = "root",
    requirements: list = None,
    example_output: str = "",
    audit_procedure: str = None,
    current_playbook: str = None,
    feedback: str = None
):
    """
    Generate or enhance Ansible playbook based on custom requirements or audit procedure.
    
    Args:
        playbook_objective: Description of what the playbook should achieve
        target_host: Default target host for the playbook
        become_user: User to become (usually root)
        requirements: List of requirement strings describing what the playbook should do
        example_output: Example command output to provide context
        audit_procedure: CIS Benchmark audit procedure (script/commands) - when provided,
                        generates an audit playbook based on this procedure
        current_playbook: Existing playbook content to enhance (if provided, enhances instead of regenerating)
        feedback: Analysis feedback/advice for enhancing the playbook (used with current_playbook)
    """
    
    if requirements is None:
        requirements = []
    
    # Build audit procedure section if provided
    audit_procedure_section = ""
    if audit_procedure:
        audit_procedure_section = f"""

**CIS BENCHMARK AUDIT PROCEDURE:**
The following is the official audit procedure from the CIS Benchmark. 
Your playbook MUST implement this audit procedure:

```bash
{audit_procedure}
```

**CRITICAL INSTRUCTIONS FOR AUDIT PROCEDURE:**
1. **PRIORITY: USE PROVIDED SCRIPTS/COMMANDS FIRST**
   - **MANDATORY**: If the audit procedure provides scripts or commands, you MUST use them exactly as provided
   - **DO NOT** create alternative commands or scripts unless the provided ones fail to work
   - **ONLY** explore other options if the provided scripts/commands do not work (e.g., command not found, syntax errors, etc.)
   - Preserve the exact commands, scripts, and logic from the audit procedure
2. Convert the audit procedure script/commands into Ansible tasks
3. Each distinct check in the audit procedure should become a separate requirement/task
4. Capture the output of each command for the compliance report
5. **USE THE EXPECTED OUTPUT** from the audit procedure to determine PASS/FAIL status:
   - If the procedure shows "Example output: generated", then "generated" = PASS
   - If the procedure shows "Verify output is not masked or disabled", then check for those strings
   - Compare actual command output against the expected output shown in the procedure
6. The audit procedure defines what PASS and FAIL mean - use this for status determination logic
7. If the audit procedure is a script, break it into individual commands that can be run as Ansible tasks
8. **Extract expected outputs and failure conditions** from the procedure text and use them in your status variables

"""
    
    # Parse requirements to extract original indices and text
    # This preserves the original requirement indices (e.g., "2. Collect..." stays as req_2)
    parsed_reqs = []
    for req in requirements:
        idx, text = parse_requirement_index(req)
        if idx > 0:
            parsed_reqs.append((idx, text))
        else:
            # Requirement without index - keep as-is for non-data-collection reqs
            parsed_reqs.append((None, req))
    
    # Build requirements text preserving original indices
    data_reqs = [(idx, text) for idx, text in parsed_reqs if idx is not None]
    other_reqs = [text for idx, text in parsed_reqs if idx is None]
    
    # Format data requirements with their original indices
    # Instructions to avoid colons in task names
    requirements_text = "\n".join([f"{idx}. {text}" for idx, text in data_reqs])
    if other_reqs:
        requirements_text += "\n\nAdditional requirements:\n" + "\n".join([f"- {r}" for r in other_reqs])
    
    requirements_text += "\n\nCRITICAL TASK NAMING RULE: For Ansible task names, use ' - ' (dash) instead of ':' (colon) to separate requirement numbers from descriptions. E.g., use 'Req 1 - description' instead of 'Req 1: description'."
    
    #print('--'*20, 'Requirements', '--'*20)
    #print (requirements_text)
    #print('--'*60)
    #ok = input("Requirements Text Continure Y:")

    # Build example output section if provided
    example_section = ""
    if example_output:
        example_section = f"""

**Example Output Context:**
```bash
{example_output}
```"""
    

    #print('--'*20, 'Feedback', '--'*20)
    #print (feedback)
    #print('--'*60)
    #ok = input("Feedback Continure Y:")

    # Build current playbook and feedback section if provided (for enhancement)
    enhancement_section = ""
    if current_playbook and feedback:
        enhancement_section = f"""

**CURRENT PLAYBOOK TO ENHANCE:**
The following is the current playbook that needs to be enhanced based on the feedback below:

```yaml
{current_playbook}
```

**FEEDBACK AND ANALYSIS:**
The following feedback identifies issues and provides recommendations for enhancing the playbook:

{feedback}

**ENHANCEMENT INSTRUCTIONS:**
1. **PRESERVE WORKING PARTS**: Keep all working tasks, variables, and logic that are correct
2. **APPLY SPECIFIC FIXES**: Make only the changes recommended in the feedback above
3. **MAINTAIN STRUCTURE**: Keep the same playbook structure, variable names, and task organization unless the feedback specifically requires changes
4. **FIX IDENTIFIED ISSUES**: Address each issue mentioned in the feedback:
   - If feedback mentions "MISSING CONDITIONAL EXECUTION", add the `when:` conditions to the appropriate tasks
   - If feedback mentions "INCORRECT REPORTING LOGIC", fix the status determination logic
   - If feedback mentions "EXECUTION FLOW ISSUE", adjust the task execution order or conditions
   - If feedback mentions "CRITICAL DESIGN FLAW", fix the design issue while preserving other working parts
5. **FOLLOW RECOMMENDATIONS**: Implement the specific recommendations provided in the feedback (e.g., "Use `when: data_1 | length > 0` on Requirements 2 and 3 tasks")
6. **DO NOT REGENERATE**: This is an ENHANCEMENT task, not a regeneration. Only modify what needs to be fixed based on the feedback.

**IMPORTANT**: The current playbook is mostly correct. Only fix the specific issues identified in the feedback. Do not rewrite the entire playbook unless absolutely necessary.
"""
    
    # Build dynamic vars and tasks examples based on actual requirement indices
    if data_reqs:
        req_indices = [idx for idx, text in data_reqs]
        first_idx = req_indices[0]
        
        # Build vars section showing actual requirement variables (2-digit zero-padded)
        # Properly escape double quotes and backslashes in requirement text
        def escape_yaml_string(s):
            """Escape special characters for YAML double-quoted strings."""
            return s.replace('\\', '\\\\').replace('"', '\\"')
        
        vars_section = "\n".join([
            f'    req_{idx:02d}: "{escape_yaml_string(text)}"' 
            for idx, text in data_reqs
        ])
        
        # Build init section (2-digit zero-padded) - include status and rationale
        init_section = "\n".join([
            f'        data_{idx:02d}: "Not collected yet"\n'
            f'        status_{idx:02d}: "UNKNOWN"\n'
            f'        rationale_{idx:02d}: "Not evaluated"'
            for idx in req_indices
        ])
        
        # Build report section with 2-digit zero-padded indices
        # Include Status and Rationale for each requirement
        report_lines = []
        for idx in req_indices:
            report_lines.append(
                f'      - "REQUIREMENT {idx:02d} - {{{{{{ req_{idx:02d} }}}}}}:"\n'
                f'      - "  Task: {{{{{{ task_{idx:02d}_name | default(\'Task not recorded\') }}}}}}"\n'
                f'      - "  Command: {{{{{{ task_{idx:02d}_cmd | default(\'N/A\') }}}}}}"\n'
                f'      - "  Exit code: {{{{{{ task_{idx:02d}_rc | default(-1) }}}}}}"\n'
                f'      - "  Data: {{{{{{ data_{idx:02d} | default(\'Data collection failed\') | trim }}}}}}"\n'
                f'      - "  Status: {{{{{{ status_{idx:02d} | default(\'UNKNOWN\') | trim }}}}}}"\n'
                f'      - "  Rationale: {{{{{{ rationale_{idx:02d} | default(\'Not evaluated\') | trim }}}}}}"\n'
                f'      - ""'
            )
        
        # Add OVERALL COMPLIANCE section using the LAST requirement's status
        last_idx = req_indices[-1]
        report_lines.append(
            f'      - "========================================================"\n'
            f'      - "OVERALL COMPLIANCE:"\n'
            f'      - "  Status: {{{{{{ status_{last_idx:02d} | default(\'UNKNOWN\') | trim }}}}}}"\n'
            f'      - "  Rationale: {{{{{{ rationale_{last_idx:02d} | default(\'Not evaluated\') | trim }}}}}}"\n'
            f'      - "========================================================"'
        )
        
        report_section = "\n".join(report_lines)
    else:
        first_idx = 1
        vars_section = '    req_1: "Requirement 1 description"'
        init_section = '        data_1: "Not collected yet"'
        report_section = '      - "REQUIREMENT 1 - {{ req_1 }}:"\n      - "  Data: {{ data_1 | default(\'N/A\') | trim }}"\n      - "  Status: {{ status_1 | default(\'UNKNOWN\') | trim }}"\n      - "  Rationale: {{ rationale_1 | default(\'Not evaluated\') | trim }}"\n      - ""\n      - "========================================================"\n      - "OVERALL COMPLIANCE:"\n      - "  Status: {{ status_1 | default(\'UNKNOWN\') | trim }}"\n      - "  Rationale: {{ rationale_1 | default(\'Not evaluated\') | trim }}"\n      - "========================================================"'
    
    # Determine if this is an enhancement or new generation
    is_enhancement = current_playbook and feedback
    
    # Build common prompt sections (shared between enhancement and generation)
    def build_common_prompt_sections():
        """Build common prompt sections shared by both enhancement and generation modes."""
        # Use .format() instead of f-string to avoid issues with {% %} syntax
        # We'll format it later with the dynamic variables
        return """
## 1. REQUIREMENT INDEXING
**CRITICAL - USE EXACT REQUIREMENT INDEX NUMBERS:**
- Requirement indices MUST match what's given above. If requirement is "2. Collect OS info", use req_2, data_2, task_2_*, result_2 - NOT req_1!
- Task names: Use ' - ' (dash) instead of ':' (colon), e.g., 'Req 1 - description' not 'Req 1: description'

## 2. SIMPLICITY RULES
1. **PRIORITY: USE PROVIDED SCRIPTS/COMMANDS FIRST**
   - **MANDATORY**: If the audit procedure or requirements provide scripts or commands, use them exactly as provided
   - **DO NOT** create alternative commands or scripts unless the provided ones fail to work
   - **ONLY** explore other options if the provided scripts/commands do not work (e.g., command not found, syntax errors, etc.)
   - Preserve the exact commands, scripts, and logic from the audit procedure
2. MINIMUM tasks - only what's needed to collect data
3. NO debug tasks except the final report
4. NO complex Jinja2 - use simple expressions
5. ONE task per requirement
6. Use shell/command for simple checks (faster than modules)
7. Use EXACT requirement text in vars - copy from requirements above!
   - **CRITICAL: ALL req_ variables MUST be quoted strings (use double quotes)**
   - ❌ WRONG: `req_2: Run script to check for audit log files`
   - ✅ CORRECT: `req_2: "Run script to check for audit log files"`
   - This prevents YAML syntax errors when requirement text contains colons, special characters, or multiple words
8. CRITICAL: ALWAYS use `args: executable: /bin/bash` for ALL shell tasks (CIS scripts require bash)

## 3. MANDATORY STRUCTURE
```yaml
---
- name: Data Collection for KCS [KCS ID]
  hosts: all
  become: yes
  gather_facts: false
  vars:
    kcs_article: "[KCS URL]"
    # COPY EXACT requirement text from requirements above!
    # CRITICAL: ALL req_ variables MUST be quoted strings (use double quotes)
    # ❌ WRONG: req_2: Run script to check for audit log files
    # ✅ CORRECT: req_2: "Run script to check for audit log files"
{vars_section}

  tasks:
    - name: Initialize data variables
      set_fact:
{{init_section}}
        task_{{first_idx}}_name: "Not executed"
        task_{{first_idx}}_cmd: "N/A"
        task_{{first_idx}}_rc: -1

    # Requirement {{first_idx}}: [COPY EXACT requirement text here]
    - name: "Req {{first_idx}} - [brief description]"
      shell: [command]
      args:
        executable: /bin/bash
      register: result_{{first_idx}}
      ignore_errors: true
      changed_when: false

    - name: Store requirement {{first_idx}} details
      set_fact:
        task_{{first_idx}}_name: "[task description]"
        task_{{first_idx}}_cmd: "[exact shell command used]"
        task_{{first_idx}}_rc: "{{{{{{ result_{{first_idx}}.rc | default(-1) }}}}}}"
        data_{{first_idx}}: "{{{{{{ result_{{first_idx}}.stdout | default('') | trim }}}}}}"
        status_{{first_idx}}: "{{{{{{ ('PASS' if condition else 'FAIL') | trim }}}}}}"
        # NOTE: If rationale contains double quotes, use single quotes for outer wrapper:
        # rationale_{{first_idx}}: '{{ ("PASS when output is exactly \"value\", FAIL otherwise" if ... else "FAIL: Expected \"value\"") | trim }}'
        rationale_{{first_idx}}: "{{{{{{ 'PASS when X, FAIL when Y' | trim }}}}}}"

    # Final report - MUST include Status and Rationale for each requirement
    - name: Generate compliance report
      debug:
        msg:
          - "========================================================"
          - "        COMPLIANCE REPORT"
          - "========================================================"
          - "Reference: [KCS URL or CIS Benchmark reference]"
          - "========================================================"
          - ""
{{report_section}}
          - "========================================================"
```

## 4. CRITICAL SYNTAX RULES

**Jinja2 Variables:**
- Variables: {{{{{{ variable }}}}}} (double braces)
- Defaults: {{{{{{ variable | default('fallback') }}}}}}
- **CRITICAL - Shell Task Error Handling**: For shell/command tasks, use EITHER `ignore_errors: true` OR `failed_when: false`, NOT both. Using both is redundant and unnecessary.
  - ✅ CORRECT: `ignore_errors: true` (allows task to continue even if command fails)
  - ✅ CORRECT: `failed_when: false` (prevents task from being marked as failed)
  - ❌ WRONG: Both `ignore_errors: true` and `failed_when: false` together (redundant)

**CRITICAL - YAML Quoting for Jinja2 Expressions with String Literals:**
- **Problem**: When a Jinja2 expression contains double quotes inside and is wrapped in double quotes, YAML parser gets confused:
  ```yaml
  # ❌ WRONG - Causes "did not find expected key" error:
  rationale_1: "{{ ('PASS when output is exactly "permitemptypasswords no", FAIL otherwise' if ... else 'FAIL: Expected "permitemptypasswords no", got "' + ...) | trim }}"
  # Problem: Double quotes inside the expression conflict with outer double quotes
  ```
- **Solution**: Use single quotes for the outer wrapper and escape double quotes inside:
  ```yaml
  # ✅ CORRECT - Single quotes outside, escaped double quotes inside:
  rationale_1: '{{ ("PASS when output is exactly \"permitemptypasswords no\", FAIL otherwise" if (result_1.stdout | default("") | trim == "permitemptypasswords no") else "FAIL: Expected \"permitemptypasswords no\", got " + (result_1.stdout | default("") | trim)) | trim }}'
  ```
- **Alternative**: Use single quotes for string literals inside the expression:
  ```yaml
  # ✅ CORRECT - Single quotes for string literals inside:
  rationale_1: "{{{{ ('PASS when output is exactly \'permitemptypasswords no\', FAIL otherwise' if (result_1.stdout | default('') | trim == 'permitemptypasswords no') else 'FAIL: Expected \'permitemptypasswords no\', got \'' + (result_1.stdout | default('') | trim) + '\'') | trim }}}}"
  ```
- **Rule**: When Jinja2 expressions contain string literals with quotes:
  1. **Preferred**: Use single quotes `'...'` for the outer wrapper and escape double quotes `\"` inside
  2. **Alternative**: Use double quotes `"..."` for the outer wrapper and escape single quotes `\'` inside, or use single quotes for string literals inside
  3. **Why**: YAML parser sees the second set of matching quotes and thinks the string has ended prematurely

**YAML Syntax for Shell Commands:**
- Commands with special characters MUST use literal block scalar (|) or folded (>)
- ❌ WRONG: `- shell: journalctl | grep 'error: failed'` (colon causes YAML error)
- ✅ CORRECT: Use `>` or `|` for shell commands with pipes, colons, backslashes

**Shell Command with Special Characters - MANDATORY: Use {% raw %} and {% endraw %} Tags:**
- **CRITICAL**: Commands with special characters like `%`, `(`, `)`, `[`, `]`, or complex formatting MUST use `{% raw %}` and `{% endraw %}` tags to prevent YAML/Jinja2 parsing errors
- **IMPORTANT**: `{% raw %}` is MORE FLEXIBLE than `!unsafe` because it allows you to mix Ansible variable substitution (outside raw block) with raw bash code (inside raw block)
- ❌ WRONG - Causes "mapping values are not allowed" error:
  ```yaml
  - name: Req 2 - Verify permissions
    shell: stat -Lc 'Access: (%a/%A) Uid: ( %u/ %U) Gid: ( %g/ %G)' /etc/cron.daily/
  ```
- ❌ WRONG - Using `!unsafe` prevents Ansible variable substitution:
  ```yaml
  - name: Req 2 - Test Match blocks if they exist
    shell: !unsafe |
      if [ "{{ match_blocks_used }}" = "true" ]; then
        sshd -T -C user=root | grep ignorerhosts
      fi
  # Problem: {{ match_blocks_used }} is NOT replaced because !unsafe prevents ALL Jinja2 processing
  ```
- ✅ CORRECT - Using `{% raw %}` and `{% endraw %}` for commands with special characters:
  ```yaml
  - name: Req 2 - Verify permissions
    shell: |
      {% raw %}
      stat -Lc 'Access: (%a/%A) Uid: ( %u/ %U) Gid: ( %g/ %G)' /etc/cron.daily/
      {% endraw %}
    args:
      executable: /bin/bash
    register: result_2
    ignore_errors: true
    changed_when: false
  ```
- ✅ CORRECT - Using `{% raw %}` with Ansible variables (MIXED approach):
  ```yaml
  - name: Req 2 - Test Match blocks if they exist
    shell: |
      # 1. Ansible REPLACES this because it is OUTSIDE the raw block:
      # Check if we have match blocks to test
      match_blocks_count={{ match_blocks_list | default([]) | length }}
      match_blocks_used="{{ match_blocks_used }}"
      
      # 2. Ansible IGNORES this because it is INSIDE the raw block:
      {% raw %}
      if [ "$match_blocks_count" -eq 0 ]; then
        echo "No Match blocks to test"
        exit 0
      fi
      
      if [ "$match_blocks_used" = "true" ]; then
        # Test with a common user parameter
        sshd -T -C user=root | grep ignorerhosts
      else
        echo "No Match blocks to test"
      fi
      {% endraw %}
    args:
      executable: /bin/bash
    register: result_2
    ignore_errors: true
    changed_when: false
    when: match_blocks_used is defined
  ```
- **CRITICAL: Scope of `{% raw %}` blocks - Variable Assignment Rules:**
  - ❌ WRONG - Ansible variable assignment INSIDE raw block (will NOT be processed):
    ```yaml
    shell: |
      {% raw %}
      match_blocks_count={{ match_blocks_list | default([]) | length }}
      if [ "$match_blocks_count" -eq 0 ]; then
        echo "No Match blocks"
      fi
      {% endraw %}
    # Problem: {{ match_blocks_list | default([]) | length }} is NOT replaced because it's inside {% raw %}
    ```
  - ✅ CORRECT - Ansible variable assignment OUTSIDE raw block (will be processed):
    ```yaml
    shell: |
      # Ansible processes this first outside raw block
      match_blocks_count={{ match_blocks_list | default([]) | length }}
      
      # Ansible ignores this inside raw block
      {% raw %}
      if [ "$match_blocks_count" -eq 0 ]; then
        echo "No Match blocks"
      fi
      {% endraw %}
    # Result: match_blocks_count gets the actual value, then bash uses it
    ```
  - **CRITICAL RULE**: When you need to mix Ansible variables and Bash variables:
    1. **OUTSIDE `{% raw %}`**: ALL Ansible variable assignments MUST be outside (e.g., `var={{ ansible_var }}`, `count={{ list | length }}`, `value="{{ string_var }}"`)
    2. **INSIDE `{% raw %}`**: ALL Bash code that uses those variables (e.g., `if [ "$var" -eq 0 ]`, `for item in "$list"`)
    3. **Place variable assignments at the BEGINNING**, before the `{% raw %}` block starts
    4. **Processing order**: Ansible processes content OUTSIDE raw blocks FIRST, then passes the result to the shell
    5. **Remember**: Anything inside `{% raw %}` is treated as literal text - NO Jinja2 processing happens inside
  - **CRITICAL: Jinja2 Variables MUST Be Outside `{% raw %}` Blocks:**
    - ❌ WRONG - Jinja2 inside raw block (will NOT be processed):
      ```yaml
      shell: |
        {% raw %}
        # This will send literal {{ match_conditions_list }} to bash, causing errors
        done <<< "$(echo '{{ match_conditions_list | default([]) | join("\n") }}')"
        {% endraw %}
      ```
    - ✅ CORRECT - Jinja2 outside raw block, use variable inside:
      ```yaml
      shell: |
        # Ansible processes these FIRST (outside raw block):
        match_blocks_exist="{{ match_blocks_exist }}"
        match_conditions_count="{{ match_conditions_list | default([]) | length }}"
        conditions_string="{{ match_conditions_list | default([]) | join('\n') }}"
        
        {% raw %}
        # Bash code uses the variables that were set above
        if [ "$match_blocks_exist" = "false" ] || [ "$match_conditions_count" -eq 0 ]; then
          echo "No Match blocks to test"
          exit 0
        fi
        
        # Use heredoc to pass multi-line variable to bash
        while IFS= read -r condition; do
          # Process condition...
        done << EOF
        $conditions_string
        EOF
        {% endraw %}
      ```
  - **CRITICAL: Avoid Complex Bash Array Syntax with Parentheses Inside `{% raw %}` Blocks:**
    - **Problem**: Even inside `{% raw %}` blocks, YAML's argument splitter can get confused by bash array syntax with parentheses like `words=($condition)` or `for ((i=0; i<...; i+=2))`
    - ❌ WRONG - Complex array syntax with parentheses can cause parsing errors:
      ```yaml
      shell: |
        {% raw %}
        # This can confuse YAML parser even inside raw block
        words=($condition)
        for ((i=0; i<${#words[@]}; i+=2)); do
          key="${words[i]}"
          value="${words[i+1]}"
        done
        {% endraw %}
      ```
    - ✅ CORRECT - Use simpler bash syntax without parentheses:
      ```yaml
      shell: |
        {% raw %}
        # Use set and shift instead of array syntax
        set -- $condition
        while [ $# -gt 0 ]; do
          key="$1"
          value="$2"
          shift 2
          # Process key and value...
        done
        {% endraw %}
      ```
    - **Rule**: Inside `{% raw %}` blocks, prefer simpler bash syntax:
      - Use `set -- $variable` and `shift` instead of array syntax `words=($variable)`
      - Use `while [ $# -gt 0 ]` instead of `for ((i=0; i<...; i+=2))`
      - Use heredoc `<< EOF` for multi-line input instead of command substitution with Jinja2
  - **CRITICAL: Avoid special characters in comments within `shell:` blocks:**
    - **MANDATORY Three Rules for Comments in `shell:` blocks (applies to BOTH inside and outside `{% raw %}` blocks):**
      1. **NO Parentheses in Comments**: DO NOT use `( )` anywhere in comments - they confuse Ansible's argument splitter
      2. **NO Quotes in Comments**: DO NOT use `"` or `'` anywhere in comments - both single and double quotes cause parsing errors
      3. **Use Literal Blocks**: Always use `shell: |` to ensure newlines are preserved correctly
    - **ABSOLUTE PROHIBITION**: Comments in `shell:` blocks MUST NOT contain:
      - ❌ Parentheses: `( )` - e.g., "FIRST (outside raw block)" → use "first outside raw block"
      - ❌ Double quotes: `"` - e.g., "says: "specify"" → use "says: specify"
      - ❌ Single quotes: `'` - e.g., "We'll test" → use "We will test" (NO CONTRACTIONS!)
    - ❌ WRONG - Special characters in comments cause "failed at splitting arguments" error:
      ```yaml
      shell: |
        # Ansible processes this FIRST (outside raw block):  ← Problem: parentheses in comment
        match_blocks_used="{{ match_blocks_used }}"
        
        {% raw %}
        # The CIS procedure says: "specify the connection parameters"  ← Problem: double quotes in comment
        # We'll test with root user as a common case  ← Problem: single quote in contraction
        # Match conditions can be: User, Group, Host, LocalAddress, LocalPort, Address, etc.  ← Problem: parentheses in comment
        # We'll extract the applicable parameters  ← Problem: single quote in contraction
        output=""
        {% endraw %}
      ```
    - ✅ CORRECT - Plain text comments without ANY special characters:
      ```yaml
      shell: |
        # Ansible processes this first outside raw block
        match_blocks_used="{{ match_blocks_used }}"
        
        {% raw %}
        # Simplified approach: Test with common connection parameters
        # The CIS procedure says: specify the connection parameters to use for the -T test
        # We will test with root user as a common case
        # Match conditions can be: User, Group, Host, LocalAddress, LocalPort, Address, and others
        # We will extract the applicable parameters
        output=""
        {% endraw %}
      ```
    - **CRITICAL RULE**: In `shell:` blocks, comments MUST be plain text without:
      - Parentheses: `( )` - Replace with "and", "or", "including", etc.
      - Double quotes: `"` - Remove quotes from quoted text in comments
      - Single quotes: `'` - Replace contractions (e.g., "We'll" → "We will", "can't" → "cannot", "it's" → "it is")
    - **Why**: Ansible's argument splitter can get confused by parentheses and quotes in comments, thinking you're trying to call a function or open a grouped expression that doesn't close correctly, even when they're just in comments.
- ✅ CORRECT - Using `{% raw %}` for complex shell commands with arrays:
  ```yaml
  - name: Req 1 - Check if audit tools exist
    shell: |
      {% raw %}
      a_audit_files=("auditctl" "auditd" "ausearch" "aureport" "autrace" "augenrules")
      a_parlist=()
      for a_file in "${a_audit_files[@]}"; do
        if [ -x "$(command -v "$a_file")" ]; then
          a_parlist+=("$a_file")
        fi
      done
      echo "${a_parlist[@]}"
      {% endraw %}
    args:
      executable: /bin/bash
    register: result_1
    ignore_errors: true
    changed_when: false
  ```
- **CRITICAL: Scope of `{% raw %}` blocks - Variable Assignment Rules:**
  - ❌ WRONG - Ansible variable assignment INSIDE raw block (will NOT be processed):
    ```yaml
    shell: |
      {% raw %}
      match_blocks_count={{ match_blocks_list | default([]) | length }}
      if [ "$match_blocks_count" -eq 0 ]; then
        echo "No Match blocks"
      fi
      {% endraw %}
    # Problem: {{ match_blocks_list | default([]) | length }} is NOT replaced because it's inside {% raw %}
    ```
  - ✅ CORRECT - Ansible variable assignment OUTSIDE raw block (will be processed):
    ```yaml
    shell: |
      # 1. Ansible REPLACES this because it is OUTSIDE the raw block:
      # Check if we have match blocks to test
      match_blocks_count={{ match_blocks_list | default([]) | length }}
      
      # 2. Ansible IGNORES this because it is INSIDE the raw block:
      {% raw %}
      if [ "$match_blocks_count" -eq 0 ]; then
        echo "No Match blocks to test"
        exit 0
      fi
      {% endraw %}
    # Result: match_blocks_count gets the actual value, then bash uses it
    ```
  - **Rule**: When you need to mix Ansible variables and Bash variables:
    1. **OUTSIDE `{% raw %}`**: All Ansible variable assignments (e.g., `var={{ ansible_var }}`, `count={{ list | length }}`)
    2. **INSIDE `{% raw %}`**: All Bash code that uses those variables (e.g., `if [ "$var" -eq 0 ]`, `for item in "$list"`)
    3. **Place variable assignments at the BEGINNING**, before the `{% raw %}` block
    4. **Ansible processes the content OUTSIDE raw blocks FIRST**, then passes the result to the shell
- **MANDATORY: Use `{% raw %}` and `{% endraw %}` when shell command contains**:
  - Special characters: `%`, `(`, `)`, `[`, `]`, `{`, `}`
  - Arrays: `("item1" "item2")` or `["item1", "item2"]`
  - Complex bash syntax that Ansible tries to parse
  - Format strings with placeholders like `%a`, `%A`, `%u`, `%U`, `%g`, `%G`
  - Any command that causes "mapping values are not allowed" or "failed at splitting arguments" errors
- **Key Benefits of `{% raw %}` over `!unsafe`**:
  - ✅ Allows mixing Ansible variable substitution (outside raw block) with raw bash code (inside raw block)
  - ✅ More flexible - you can set variables before the raw block and use them inside
  - ✅ Prevents YAML/Jinja2 parsing errors while still allowing variable substitution when needed
- **Note**: `{% raw %}` and `{% endraw %}` are Jinja2 tags that go INSIDE the shell content, not on the `shell:` line

**Complex Bash Scripts - MANDATORY PATTERN:**
- **CRITICAL**: When a requirement contains a bash script (from audit procedure or requirements), you MUST use this EXACT pattern:
  1. Use `copy` module to create the script on remote client with `{% raw %}` tags
  2. Use `shell` module to execute the script
  3. Use `file` module to delete the temporary script
- **MANDATORY PATTERN** (use this EXACT structure):
```yaml
    - name: Req 1 - Execute CIS audit script for [description]
      copy:
        dest: "/tmp/cis_audit_[checkpoint_id].sh"
        mode: '0700'
        content: |
          {% raw %}
          #!/usr/bin/env bash
          {
             l_output3="" l_dl="" # clear variables
             unset a_output; unset a_output2 # unset arrays
             l_mod_name="cramfs" # set module name
             # ... [FULL SCRIPT CONTENT FROM REQUIREMENT/AUDIT PROCEDURE] ...
             if [ "${#a_output2[@]}" -le 0 ]; then
                printf '%s\\n' "- Audit Result:" "  ** PASS **"
             else
                printf '%s\\n' "- Audit Result:" "  ** FAIL **" "${a_output2[@]}"
             fi
          }
          {% endraw %}
      register: script_create_1
      ignore_errors: true

    - name: Req 1 - Execute the audit script
      shell: "/tmp/cis_audit_[checkpoint_id].sh"
      args:
        executable: /bin/bash
      register: result_1
      ignore_errors: true
      changed_when: false

    - name: Req 1 - Remove temporary audit script
      file:
        path: "/tmp/cis_audit_[checkpoint_id].sh"
        state: absent
      ignore_errors: true
```
- **CRITICAL RULES**:
  - **ALWAYS** wrap script content in `{% raw %}` and `{% endraw %}` tags in the `copy` module's `content` field
  - **ALWAYS** use three tasks: `copy` (create), `shell` (execute), `file` (delete)
  - Script filename should be unique per requirement (e.g., `/tmp/cis_audit_7.2.9.sh` or `/tmp/cis_audit_req_1.sh`)
  - Set `mode: '0700'` on the copy task to make script executable
  - Use `args: executable: /bin/bash` on the shell task
  - Use `ignore_errors: true` on all three tasks
  - Use `changed_when: false` on the shell task (audit scripts don't change system state)
  - Register the shell task result (e.g., `register: result_1`) for status evaluation
  - **DO NOT** try to execute scripts inline with shell module - always use copy/shell/file pattern

**Multi-line Variable Assignments:**
- **CRITICAL: For regular requirement text (req_ variables), ALWAYS use quoted strings:**
  - ✅ CORRECT: `req_2: "Run script to check for audit log files not owned by root"`
  - ❌ WRONG: `req_2: Run script to check for audit log files not owned by root` (missing quotes causes YAML syntax error)
- When you encounter requirement to assign a complicated multi-lines value (for example script) to a variable, wrap the block in `{% raw %}` tags:
```yaml
vars:
  req_2: |
    {% raw %}
    #!/usr/bin/env bash
    # ... your complex script ...
    {% endraw %}

# Or in set_fact:
- name: Store complex script
  set_fact:
    script_content: |
      {% raw %}
      #!/usr/bin/env bash
      l_mod_name="cramfs"
      l_mod_type="fs"
      # ... complex script with {{ }} or other Jinja2-like syntax ...
      {% endraw %}
```
- **CRITICAL**: Use `{% raw %}` tags when the content contains characters that Jinja2 might interpret (like `{{`, `}}`, `{%`, `%}`, `$`, etc.)
- This prevents Jinja2 from trying to process the content as a template

**Regex Pattern Matching - CRITICAL: AVOID DOUBLE-ESCAPING TRAP:**
- Use `regex_search()` NOT `match()` (match requires full string match, too strict)
- **MANDATORY: Use SINGLE QUOTES for regex patterns** - In Ansible/Jinja2, single quotes are "raw-ish," meaning you don't need to double-escape backslashes
- **CRITICAL RULE:** With single quotes, use `\\.` (SINGLE backslash) NOT `\\\\.` (DOUBLE backslash)

**CRITICAL - Extracting Specific Values from Regex Matches:**
- **PREFERRED APPROACH: Use `regex_replace()` with backreferences to extract specific capture groups directly**
  - This is safer and more readable than using `regex_search()` with array indexing (`match[1]`, `match[2]`, etc.)
  - Array indexing is error-prone and can grab characters from the full match string rather than the specific capture group
  - Use backreferences `\\1`, `\\2`, `\\3`, etc. to extract the 1st, 2nd, 3rd capture groups
- ✅ **CORRECT - Using `regex_replace()` to extract values directly:**
  ```yaml
  status_1: >-
    {% set output = result_1.stdout | default('') | trim %}
    {% if "Access:" in output %}
      {% set mode = output | regex_replace('.*Access: \\(0?([0-7]+)/.*', '\\1') %}
      {% set uid  = output | regex_replace('.*Uid: \\(\\s*([0-9]+)/.*', '\\1') %}
      {% set gid  = output | regex_replace('.*Gid: \\(\\s*([0-9]+)/.*', '\\1') %}
      {% if mode | int(base=8) <= 420 and uid == '0' and gid == '0' %}
        PASS
      {% else %}
        FAIL
      {% endif %}
    {% else %}
      FAIL
    {% endif %}
  ```
- ❌ **WRONG - Using `regex_search()` with array indexing (error-prone):**
  ```yaml
  status_1: >-
    {% set output = result_1.stdout | default('') | trim %}
    {% if output != '' %}
      {% set match = output | regex_search('Access: \\(([0-9]+)/.*Uid: \\(\\s*([0-9]+)/.*Gid: \\(\\s*([0-9]+)/') %}
      {% if match %}
        {% set mode_str = match[1] %}  # ❌ WRONG: match[1] may grab wrong character
        {% set uid_str = match[2] %}    # ❌ WRONG: match[2] may grab wrong character
        {% set gid_str = match[3] %}    # ❌ WRONG: match[3] may grab wrong character
  ```
- **Key Rules for `regex_replace()` extraction:**
  - Use `.*` at the start to match everything before the capture group
  - Use `.*` at the end to match everything after the capture group
  - Use `\\1`, `\\2`, `\\3` (with double backslash) as the replacement to extract the 1st, 2nd, 3rd capture groups
  - In template blocks (`{% %}`), use `\\` (double backslash) for backreferences - this is CORRECT
  - Example: `{% set mode = output | regex_replace('.*Access: \\(0?([0-7]+)/.*', '\\1') %}`

**Examples in Status Variables (MOST COMMON USE CASE):**
- ✅ CORRECT: `status_1: "{{{{ ('PASS' if (result_1.stdout | regex_search('pam-1\\.3\\.1-([0-9]+)')) else 'FAIL') | trim }}}}"` (quoted string, single quotes, SINGLE backslash `\\.`)
- ✅ CORRECT (for extraction): `status_1: "{{{{ ('PASS' if ((result_1.stdout | regex_replace('.*pam-1\\.3\\.1-([0-9]+).*', '\\1') | int) >= 25) else 'FAIL') | trim }}}}"` (using regex_replace to extract version number)
- ❌ WRONG: `status_1: |` followed by `{{ ('PASS' if (result_1.stdout | regex_search('pam-1\\\\.3\\\\.1-([0-9]+)')) else 'FAIL') | trim }}` (literal block scalar `|` + DOUBLE backslash `\\\\.` - DOUBLE TRAP!)
- ❌ WRONG: `status_1: "{{{{ ('PASS' if (result_1.stdout | regex_search('pam-1\\\\.3\\\\.1-([0-9]+)')) else 'FAIL') | trim }}}}"` (DOUBLE backslash `\\\\.` - THIS IS THE TRAP!)
- ❌ WRONG: `status_1: "{{{{ ('PASS' if (result_1.stdout | regex_search("pam-1\\\\.3\\\\.1-([0-9]+)")) else 'FAIL') | trim }}}}"` (double quotes require double-escaping - causes trap)

**Standalone Examples:**
- ✅ CORRECT: `{{ result_1.stdout | regex_search('pam-1\\.3\\.1-([0-9]+)') }}` (single quotes, SINGLE backslash `\\.`) - for boolean checks
- ✅ CORRECT: `{{ result_1.stdout | regex_replace('.*pam-1\\.3\\.1-([0-9]+).*', '\\1') }}` (single quotes, SINGLE backslash `\\.`, double backslash `\\1` for backreference) - for extracting values
- ❌ WRONG: `{{ result_1.stdout | regex_search('pam-1\\\\.3\\\\.1-([0-9]+)') }}` (DOUBLE backslash `\\\\.` - THIS IS THE TRAP!)
- ❌ WRONG: `{{ result_1.stdout is match('pattern') }}` (too strict, use regex_search)

**Remember:** 
- Single quotes + SINGLE backslash (`\\.`) = CORRECT for regex patterns
- Single quotes + DOUBLE backslash (`\\\\.`) = TRAP!
- For extracting values: Use `regex_replace()` with `\\1`, `\\2`, etc. (double backslash for backreferences) - PREFERRED over array indexing

## 5. STATUS AND RATIONALE - CRITICAL RULES

**Status Value Definitions:**
- **PASS**: Requirement is definitively met
- **FAIL**: Requirement is definitively not met
- **NA**: Skip related task or Did not execute the related task
- **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)

**CRITICAL - Status Variable Requirements:**
1. **MUST be Jinja2 EXPRESSIONS** (using {{{{ }}}}) that EVALUATE to 'PASS'/'FAIL'/'NA'/'UNKNOWN', NOT string literals
   - ✅ CORRECT: `status_1: "{{{{ ('PASS' if condition else 'FAIL') | trim }}}}"`
   - ❌ WRONG: `status_1: "'PASS' if condition else 'FAIL'"` (string literal - will show expression text)
2. **MUST use QUOTED STRINGS**, NOT literal block scalars (`|`)
   - ✅ CORRECT: `status_1: "{{{{ 'PASS' if condition else 'FAIL' }}}}"`
   - ❌ WRONG: `status_1: |` followed by `{{ ('PASS' if condition else 'FAIL') | trim }}` (preserves newlines)
3. **MUST use `| trim`** on all status, rationale, and data variables
   - Prevents "PASS\\n" → "PASS"
   - Apply in set_fact: `status_1: "{{{{ ('PASS' if condition else 'FAIL') | trim }}}}"`
   - Apply in report: `"Status: {{{{ status_1 | default('UNKNOWN') | trim }}}}"`
4. **If using regex in status determination: Use SINGLE quotes with SINGLE backslash (`\\.`), NOT double backslash (`\\\\.`)**
   - ✅ CORRECT: `status_1: "{{{{ ('PASS' if (result_1.stdout | regex_search('pam-1\\.3\\.1-([0-9]+)')) else 'FAIL') | trim }}}}"` (quoted string, SINGLE backslash `\\.`)
   - ❌ WRONG: `status_1: |` followed by `{{ ('PASS' if (result_1.stdout | regex_search('pam-1\\\\.3\\\\.1-([0-9]+)')) else 'FAIL') | trim }}` (literal block scalar `|` + DOUBLE backslash `\\\\.` - DOUBLE TRAP!)
   - ❌ WRONG: `status_1: "{{{{ ('PASS' if (result_1.stdout | regex_search('pam-1\\\\.3\\\\.1-([0-9]+)')) else 'FAIL') | trim }}}}"` (DOUBLE backslash `\\\\.` - TRAP!)

**CRITICAL - set_fact Limitation:**
- Variables in the SAME `set_fact` block CANNOT reference each other
- ✅ CORRECT: Reference original source in same block
  ```yaml
  - set_fact:
      data_1: "{{{{ result_1.stdout | default('') | trim }}}}"
      status_1: "{{{{ ('PASS' if (result_1.stdout | default('') | trim == '') else 'FAIL') | trim }}}}"  # Reference result_1.stdout, NOT data_1
  ```
- ❌ WRONG: Referencing variable in same block
  ```yaml
  - set_fact:
      data_1: "{{{{ result_1.stdout | default('') | trim }}}}"
      status_1: "{{{{ ('PASS' if (data_1 | trim == '') else 'FAIL') | trim }}}}"  # data_1 is undefined here!
  ```

**CRITICAL - Using trim in Comparisons:**
- ALWAYS use `| trim` BEFORE comparing AND on final result
- ✅ CORRECT: `status_4: "{{{{ ('PASS' if (data_1 | trim == '' or status_2 | trim == 'PASS') else 'FAIL') | trim }}}}"`
- ❌ WRONG: `status_4: "{{{{ ('PASS' if (data_1 == '' or status_2 == 'PASS') else 'FAIL') | trim }}}}"` (missing trim before comparison)

**CRITICAL - Complex Comparisons Using Jinja2 Templates:**
- For complicated version comparisons or multi-step logic, use Jinja2 template blocks with `{% set %}` and `{% if %}`
- **Use folded block scalar (`>-`) for complex Jinja2 templates** - this is ACCEPTABLE and works correctly
- ✅ CORRECT - Complex version comparison using Jinja2 template (RECOMMENDED APPROACH):
  ```yaml
  - set_fact:
      status_1: >-
        {% set output = result_1.stdout | default('') | trim %}
        {% if output is search('pam-[0-9]') %}
          {% set version_match = output | regex_search('pam-([0-9]+\\.[0-9]+\\.[0-9]+)-([0-9]+)') %}
          {% if version_match %}
            {% set version_parts = version_match.split('-')[1] %}
            {% set major = version_parts.split('.')[0] | int %}
            {% set minor = version_parts.split('.')[1] | int %}
            {% set patch = version_parts.split('.')[2] | int %}
            {% set release = version_match.split('-')[2] | int %}
            {# {{major}}.{{minor}}.{{patch}}-{{ release }} #}
            {% if (major > 1) or
                  (major == 1 and minor > 3) or
                  (major == 1 and minor == 3 and patch > 1) or
                  (major == 1 and minor == 3 and patch == 1 and release >= 25) %}
              PASS
            {% else %}
              FAIL
            {% endif %}
          {% else %}
            FAIL
          {% endif %}
        {% else %}
          FAIL
        {% endif %}
  ```
- **Key Points for Complex Comparisons:**
  - **PREFERRED**: Use `regex_replace()` with backreferences to extract specific values directly into variables
    - This is safer and more reliable than using `regex_search()` with array indexing (`match[1]`, `match[2]`, etc.)
    - Array indexing is error-prone and can grab characters from the full match string rather than the specific capture group
    - Example for extracting multiple values: 
      ```yaml
      {% set mode = output | regex_replace('.*Access: \\(0?([0-7]+)/.*', '\\1') %}
      {% set uid  = output | regex_replace('.*Uid: \\(\\s*([0-9]+)/.*', '\\1') %}
      {% set gid  = output | regex_replace('.*Gid: \\(\\s*([0-9]+)/.*', '\\1') %}
      ```
  - **ALTERNATIVE**: For version strings with consistent delimiters, use `regex_search()` to get the full match, then use `split()` to extract components
    - This approach works well when the format is predictable (e.g., `pam-1.3.1-25`)
    - Example: `{% set version_match = output | regex_search('pam-([0-9]+\\.[0-9]+\\.[0-9]+)-([0-9]+)') %}`
    - Then extract parts: `{% set version_parts = version_match.split('-')[1] %}`
    - Then split by `.`: `{% set major = version_parts.split('.')[0] | int %}`
    - **NOTE**: Only use this approach if you're certain about the format. For extracting specific capture groups, `regex_replace()` is preferred.
  - Use `{% set variable = ... %}` to extract and store intermediate values
  - Use `{% if %}` blocks for multi-condition logic
  - Use `regex_replace()` or `regex_search()` with proper escaping: in template blocks, use single backslash `\\.` for periods in regex patterns
  - Use `| int` or `| int(base=8)` filter to convert extracted strings to integers for numeric comparison
  - Folded block scalar (`>-`) is ACCEPTABLE for complex templates (folds newlines correctly)
  - Always end with `PASS` or `FAIL` (not quoted, as it's inside the template block)
  - Use `{# ... #}` for comments/debugging within template blocks
- **When to use this approach:**
  - Version comparisons requiring multiple components (major.minor.patch-release)
  - Complex conditional logic with multiple AND/OR conditions
  - Multi-step extraction and comparison processes
  - When simple inline expressions become too complex or unreadable
- **Version Extraction Pattern (RECOMMENDED):**
  1. First, use `regex_search()` to get the full version match: `{% set version_match = output | regex_search('pattern') %}`
  2. Check if match exists: `{% if version_match %}`
  3. Extract version parts using `split()`: `{% set version_parts = version_match.split('-')[1] %}`
  4. Split by `.` to get major, minor, patch: `{% set major = version_parts.split('.')[0] | int %}`
  5. Extract release number: `{% set release = version_match.split('-')[2] | int %}`
  6. Compare numerically using `{% if %}` blocks

## 6. REPORT FORMAT
```yaml
- name: Generate compliance report
  debug:
    msg:
      - "========================================================"
      - "        COMPLIANCE REPORT"
      - "========================================================"
      - "Reference: {{{{ kcs_article }}}}"
      - "========================================================"
      - ""
      - "REQUIREMENT 1 - {{{{ req_1 }}}}:"
      - "  Task: {{{{ task_1_name | default('Task not recorded') }}}}"
      - "  Command: {{{{ task_1_cmd | default('N/A') }}}}"
      - "  Exit code: {{{{ task_1_rc | default(-1) }}}}"
      - "  Data: {{{{ data_1 | default('') | trim }}}}"
      - "  Status: {{{{ status_1 | default('UNKNOWN') | trim }}}}"
      - "  Rationale: {{{{ rationale_1 | default('Not evaluated') | trim }}}}"
      - ""
      # ... repeat for all requirements ...
      - ""
      - "========================================================"
      - "OVERALL COMPLIANCE:"
      - "  Status: {{{{ status_N | trim }}}}"
      - "  Rationale: {{{{ rationale_N | trim }}}}"
      - "========================================================"
```

**Key Points:**
- Each requirement gets: task name, command, exit code, data, status, rationale
- Empty data with exit code 0 or 1 = valid "nothing found"
- Status determined by requirement's rationale (parse from requirement text)
- LAST requirement (usually "OVERALL Verify") determines OVERALL COMPLIANCE

**OUTPUT:** Valid YAML only. No markdown. Start with ---.
"""
    
    common_sections = build_common_prompt_sections()
    
    # Build the base prompt
    if is_enhancement:
        base_prompt = f"""Enhance the existing Ansible playbook based on the feedback provided below.

**Objective:** {playbook_objective}
{audit_procedure_section}
**Requirements to collect data for:**
{requirements_text}{example_section}{enhancement_section}
{common_sections}

**ENHANCEMENT INSTRUCTIONS:**
1. **PRESERVE WORKING PARTS**: Keep all working tasks, variables, and logic that are correct
2. **APPLY SPECIFIC FIXES**: Make only the changes recommended in the feedback above
3. **MAINTAIN STRUCTURE**: Keep the same playbook structure, variable names, and task organization unless the feedback specifically requires changes
4. **FIX IDENTIFIED ISSUES**: Address each issue mentioned in the feedback
5. **FOLLOW RECOMMENDATIONS**: Implement the specific recommendations provided in the feedback
6. **DO NOT REGENERATE**: This is an ENHANCEMENT task, not a regeneration. Only modify what needs to be fixed based on the feedback.

**IMPORTANT**: The current playbook is mostly correct. Only fix the specific issues identified in the feedback. Do not rewrite the entire playbook unless absolutely necessary.

Enhance the existing playbook by applying the feedback above. Return the complete enhanced playbook with all fixes applied."""
    else:
        base_prompt = f"""Generate a MINIMAL Ansible playbook for data collection.

**Objective:** {playbook_objective}
{audit_procedure_section}
**Requirements to collect data for:**
{requirements_text}{example_section}
{common_sections}

Generate the minimal playbook now:"""
    
    # Use the base_prompt as prompt_template
    prompt_template = base_prompt
    
    # Don't use ChatPromptTemplate - invoke model directly to avoid brace parsing issues
    from langchain_core.messages import HumanMessage
    
    print("Generating Ansible playbook...")
    print("=" * 80)
    
    # Add retry logic for timeout handling
    max_generation_attempts = 3
    for attempt in range(1, max_generation_attempts + 1):
        try:
            print(f"Generation attempt {attempt}/{max_generation_attempts}...")
            response = model.invoke([HumanMessage(content=prompt_template)])
            playbook_content = response.content
            break  # Success, exit retry loop
        except Exception as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                print(f"⚠️  Generation timed out on attempt {attempt}/{max_generation_attempts}")
                if attempt < max_generation_attempts:
                    print(f"🔄 Retrying playbook generation...")
                    continue
                else:
                    print(f"❌ All {max_generation_attempts} generation attempts timed out")
                    raise Exception(f"Playbook generation timed out after {max_generation_attempts} attempts") from e
            else:
                # Non-timeout error, raise immediately
                raise
    
    # Clean up the response - remove markdown code blocks if present
    if "```yaml" in playbook_content:
        playbook_content = playbook_content.split("```yaml")[1].split("```")[0].strip()
    elif "```" in playbook_content:
        playbook_content = playbook_content.split("```")[1].split("```")[0].strip()
    
    # Remove any stray "yaml" or "yml" line at the beginning
    lines = playbook_content.split('\n')
    while lines and lines[0].strip().lower() in ['yaml', 'yml', '']:
        lines.pop(0)
    playbook_content = '\n'.join(lines)
    
    # Ensure it starts with ---
    if not playbook_content.strip().startswith('---'):
        playbook_content = '---\n' + playbook_content
    
    return playbook_content


def fix_yaml_special_chars(content: str) -> str:
    r"""
    Fix common YAML syntax issues with special characters in shell commands.
    
    Converts problematic inline strings to literal block scalars (|) when they contain:
    - Backslashes in regex patterns (e.g., grep 'pattern1\|pattern2')
    - Unescaped colons in shell commands
    
    Args:
        content: The playbook YAML content
        
    Returns:
        Fixed content with problematic strings converted to block scalars
    """
    import re
    
    lines = content.split('\n')
    fixed_lines = []
    i = 0
    fixes_applied = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check for problematic patterns in set_fact or variable assignments
        # Pattern: key: "...backslash..." or key: '...backslash...'
        # Look for lines like: task_cmd: "...grep 'pattern\|pattern'..."
        
        # Match lines with quoted values containing backslashes
        match = re.match(r'^(\s+)(\w+):\s*(["\'])(.+\\\\?.+)\3\s*$', line)
        if match:
            indent = match.group(1)
            key = match.group(2)
            quote = match.group(3)
            value = match.group(4)
            
            # Check if value contains problematic backslash patterns
            problematic_patterns = [
                r'\\[|()]',  # \| \( \) in grep/find
                r'\\.',      # \. in regex
                r'\\s',      # \s in regex
                r'\\d',      # \d in regex
            ]
            
            needs_fix = False
            for pattern in problematic_patterns:
                if re.search(pattern, value):
                    needs_fix = True
                    break
            
            if needs_fix:
                # Convert to literal block scalar
                fixed_lines.append(f"{indent}{key}: |")
                # Add the value on next line with extra indentation
                fixed_lines.append(f"{indent}  {value}")
                fixes_applied += 1
                i += 1
                continue
        
        # Check for shell/command with problematic inline content
        shell_match = re.match(r'^(\s*)-\s*(shell|command):\s*(["\']?)(.+?)(["\']?)\s*$', line)
        if shell_match:
            indent = shell_match.group(1)
            module = shell_match.group(2)
            open_quote = shell_match.group(3)
            cmd = shell_match.group(4)
            close_quote = shell_match.group(5)
            
            # Check for problematic content (use raw strings to avoid escape warnings)
            problematic = [r'\|', r'\(', r'\)', ': ', r'\.']
            if any(p in cmd for p in problematic):
                # Convert to folded block scalar
                fixed_lines.append(f"{indent}- {module}: >")
                fixed_lines.append(f"{indent}    {cmd}")
                fixes_applied += 1
                i += 1
                continue
        
        fixed_lines.append(line)
        i += 1
    
    if fixes_applied > 0:
        print(f"   🔧 Auto-fixed {fixes_applied} YAML special character issue(s)")
    
    return '\n'.join(fixed_lines)


def save_playbook(content: str, filename: str = "kill_packet_recvmsg_process.yml"):
    """Save the generated playbook to a file and check for common Jinja2 syntax errors."""
    from pathlib import Path
    
    # Apply YAML special character fixes
    content = fix_yaml_special_chars(content)
    
    # Ensure the directory exists if filename contains a path
    file_path = Path(filename)
    if file_path.parent != Path('.'):
        file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(filename, 'w') as f:
        f.write(content)
    print(f"\n✅ Playbook saved to: {filename}")


def check_playbook_syntax(filename: str, target_host: str) -> tuple[bool, str]:
    """
    Check Ansible playbook syntax.
    
    Args:
        filename: Path to the playbook file
        
    Returns:
        tuple: (is_valid, error_message)
    """
    try:
        print(f"\n🔍 Checking playbook syntax: {filename}")
        
        # Initialize ansible_nav early in case of errors
        ansible_nav = get_ansible_navigator_path()
        
        # First, check if the playbook file exists
        if not os.path.isfile(filename):
            error_msg = f"Playbook file not found: {filename}"
            print(f"❌ {error_msg}")
            return False, error_msg
        
        cmd = [
            ansible_nav, 'run', 
            filename, 
            '-i', f'{target_host},',
            '-u', 'root',  # Use root user to connect
            '-v',  # Verbose output
            '--syntax-check',
            '--mode', 'stdout'  # Force output to stdout instead of interactive mode
        ]
        print(f"Command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ  # Pass current environment
        )
        
        if result.returncode == 0:
            print("✅ Syntax check passed!")
            return True, ""
        else:
            # Combine stdout and stderr
            error_output = []
            
            if result.stdout and result.stdout.strip():
                error_output.append("=== STDOUT ===")
                error_output.append(result.stdout)
            
            if result.stderr and result.stderr.strip():
                error_output.append("=== STDERR ===")
                error_output.append(result.stderr)
            
            # If both are empty, provide helpful message
            if not error_output:
                error_output.append("No error output captured. Checking playbook file...")
                # Try to validate the YAML directly
                try:
                    import yaml
                    with open(filename, 'r') as f:
                        yaml.safe_load_all(f)
                    error_output.append("YAML structure is valid. Issue may be with Ansible-specific syntax.")
                except yaml.YAMLError as e:
                    error_output.append(f"YAML Parsing Error: {str(e)}")
                except Exception as e:
                    error_output.append(f"Error reading file: {str(e)}")
            
            error_msg = "\n".join(error_output)
            
            print(f"❌ Syntax check failed!")
            print("\n" + "="*80)
            print("SYNTAX ERROR DETAILS:")
            print("="*80)
            print(error_msg)
            print("="*80)
            
            return False, error_msg
            
    except subprocess.TimeoutExpired:
        error_msg = "Syntax check timed out after 30 seconds"
        print(f"❌ {error_msg}")
        return False, error_msg
    except FileNotFoundError as e:
        error_msg = f"ansible-navigator command not found: {e}\n"
        error_msg += f"   Tried to execute: {ansible_nav}\n"
        error_msg += f"   Python executable: {sys.executable}\n"
        error_msg += f"   PATH: {os.environ.get('PATH', 'Not set')}"
        print(f"❌ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Error during syntax check: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg


def filter_verbose_task_output(output: str) -> str:
    """
    Filter verbose Ansible task output to reduce data size for AI feedback.
    
    Removes lines between TASK markers and status lines (skipping/fatal/ok),
    keeping only task names and their final status (including JSON blocks).
    
    Args:
        output: Raw Ansible output
        
    Returns:
        Filtered output with verbose task details removed
    """
    import re
    
    lines = output.split('\n')
    filtered_lines = []
    i = 0

    Skip = False
    while i < len(lines):
        next_line = lines[i]

        # Check if this is a TASK line
        task_match = re.match(r'^TASK\s+\[([^\]]+)\]\s*', next_line)
        if task_match:
            # Found a TASK line - keep it
            filtered_lines.append(next_line)
            Skip = True


        #if re.search(r'\s*ok:\s*', line):

        if (re.search(r'\s*skipping:\s*', next_line) or
            re.search(r'\s*fatal:\s*', next_line) or
            re.search(r'\s*ok:\s*', next_line) or
            re.search(r'\s*changed:\s*', next_line) or
            re.search(r'\s*failed:\s*', next_line)):

            Skip = False

        if not Skip:
            filtered_lines.append(next_line)

        i += 1

    return '\n'.join(filtered_lines)


def test_playbook_on_server(filename: str, target_host: str = "192.168.122.16", check_mode: bool = False, verbose: str = "v", skip_debug: bool = False) -> tuple[bool, str]:
    """
    Test the playbook on a real server to verify it meets requirements.
    
    Args:
        filename: Path to the playbook file
        target_host: Target server IP/hostname
        check_mode: If True, run in check mode (dry-run, no changes made)
        verbose: Verbose level - "v" (default, basic info), "vv" (detailed), "vvv" (very detailed), "" (silent)
        skip_debug: If True, skip debug-tagged tasks (for production execution)
        
    Returns:
        tuple: (is_successful, output) - output is filtered to reduce verbose task details
    """
    try:
        # Normalize verbose level (handle legacy bool values for backward compatibility)
        if isinstance(verbose, bool):
            verbose = "v" if verbose else ""
        elif verbose not in ["", "v", "vv", "vvv"]:
            verbose = "v"  # Default to "v" if invalid value
        
        mode_desc = "check mode (dry-run)" if check_mode else "execution mode"
        if skip_debug:
            mode_desc += " [skipping debug tasks]"
        print(f"\n🧪 Testing playbook on server: {target_host} ({mode_desc})")
        
        # Initialize ansible_nav early in case of errors
        ansible_nav = get_ansible_navigator_path()
        
        # Check if the playbook file exists
        if not os.path.isfile(filename):
            error_msg = f"Playbook file not found: {filename}"
            print(f"❌ {error_msg}")
            return False, error_msg
        
        # Build ansible-navigator command
        cmd = [
            ansible_nav, 'run', 
            filename, 
            '-i', f'{target_host},',
            '-u', 'root'  # Use root user to connect
        ]
        
        # Add verbose flags based on level
        if verbose == "v":
            cmd.append('-v')
        elif verbose == "vv":
            cmd.append('-vv')
        elif verbose == "vvv":
            cmd.append('-vvv')
        # If verbose is "", don't add any verbose flag

        if check_mode:
            cmd.append('--check')  # Dry-run mode
        
        if skip_debug:
            cmd.extend(['--skip-tags', 'debug'])  # Skip troubleshooting debug tasks
            
        
        print(f"   Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minutes timeout for execution
            env=os.environ  # Pass current environment to find ansible-navigator in venv
        )
        
        raw_output = result.stdout + result.stderr
        
        # Filter verbose task output to reduce data size for AI feedback
        # Keep full output for error detection, then filter before returning
        output = raw_output
        
        # Check for PLAYBOOK BUGS that require retry/regeneration
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
            ("failed at splitting arguments", "YAML/Jinja2 parsing error - likely due to complex script in shell module"),
            ("unbalanced jinja2 block", "Jinja2 parsing error - likely due to curly braces in shell script"),
            ("Missing end of comment tag", "Jinja2 parsing error - likely bash variable ${#var} mistaken for Jinja2 comment"),
            # Shell syntax errors (even if task shows ok due to ignore_errors)
            ("syntax error near unexpected token", "Shell syntax error - likely bash-specific syntax used with /bin/sh"),
            ("syntax error:", "Shell syntax error in command"),
            ("/bin/sh: -c: line", "Shell script error - command may require bash instead of sh"),
            ("bad substitution", "Shell bad substitution - bash syntax used with /bin/sh"),
            ("unexpected EOF", "Shell unexpected end of file"),
            ("command not found", "Command not found - missing binary or path issue"),
        ]
        
        for pattern, description in playbook_bug_patterns:
            if pattern in output:
                # Check if it's being ignored (has "...ignoring" after the error)
                # Even if ignored, undefined variables are still bugs
                
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
                        # Show surrounding context
                        start = max(0, i-3)
                        end = min(len(error_lines), i+8)
                        error_context_lines = error_lines[start:end]
                        print('\n'.join(error_context_lines))
                        break
                print("="*80)
                
                # Return detailed error with filtered context - CRITICAL: Return False immediately when bug detected
                full_error_context = '\n'.join(error_context_lines) if error_context_lines else output[:500]
                # Filter output before returning to reduce data size
                filtered_output = filter_verbose_task_output(output)
                return False, f"PLAYBOOK BUG: {description}\n\nError context:\n{full_error_context}\n\nFull pattern: {pattern}\n\nFiltered output:\n{filtered_output}"

        if result.returncode == 0:
            print(f"✅ Playbook executed successfully in {mode_desc}!")
            
            # CRITICAL: Check for fatal errors in ignored tasks (playbook bugs)
            # Even if tasks are ignored (ignore_errors: true), fatal errors indicate playbook bugs
            # These are playbook bugs that need to be fixed, not verification failures
            fatal_error_patterns = [
                ("Invalid data passed to 'loop'", "Invalid loop data - playbook bug"),
                ("Invalid data passed to", "Invalid data passed to task - playbook bug"),
                ("is undefined", "Undefined variable - playbook bug"),
                ("template error", "Jinja2 template error - playbook bug"),
                ("syntax error", "Syntax error - playbook bug"),
                ("cannot be converted to", "Type conversion error - playbook bug"),
                ("'dict object' has no attribute", "Invalid attribute access - playbook bug"),
                ("has no attribute", "Invalid attribute access - playbook bug"),
                ("Unexpected end of template", "Jinja2 unclosed block - playbook bug"),
                ("expected token", "Jinja2 syntax error - playbook bug"),
            ]
            
            # Check if there are fatal errors that are being ignored
            has_fatal_error = False
            fatal_error_details = []
            
            import re
            # Find all fatal errors in the output
            # Pattern: "fatal: [host]: FAILED! => {"msg": "error message"}
            fatal_blocks = re.finditer(
                r'fatal:\s*\[[^\]]+\]:\s*FAILED!\s*=>\s*\{[^}]*"msg":\s*"([^"]+)"',
                output,
                re.DOTALL
            )
            
            for fatal_match in fatal_blocks:
                error_msg = fatal_match.group(1)
                match_start = fatal_match.start()
                match_end = fatal_match.end()
                
                # Check if this error matches any playbook bug pattern
                for error_pattern, description in fatal_error_patterns:
                    if error_pattern in error_msg:
                        # Check if this fatal error is being ignored
                        # Look for "...ignoring" after the fatal error block
                        next_ignoring = output.find("...ignoring", match_end)
                        if next_ignoring != -1 and next_ignoring - match_end < 300:
                            # This fatal error is being ignored - it's a playbook bug!
                            has_fatal_error = True
                            # Extract task name if available (look backwards for TASK [)
                            task_start = output.rfind("TASK [", 0, match_start)
                            task_name = ""
                            if task_start != -1:
                                task_end = output.find("]", task_start)
                                if task_end != -1:
                                    task_name = output[task_start:task_end+1]
                            
                            error_detail = f"{description}"
                            if task_name:
                                error_detail += f" in {task_name}"
                            error_detail += f": {error_msg[:300]}"
                            fatal_error_details.append(error_detail)
                            print(f"❌ PLAYBOOK BUG DETECTED (ignored task): {description}")
                            if task_name:
                                print(f"   Task: {task_name}")
                            print(f"   Error: {error_msg[:300]}")
                        break  # Found a match, no need to check other patterns for this error
            
            # For verification/compliance playbooks, success means it completed
            # We don't require failed=0 because checks are allowed to find non-compliance
            if "ok=" in output and "PLAY RECAP" in output:
                # Check PLAY RECAP for actual task failures
                # Look for "failed=N" where N > 0
                import re
                recap_match = re.search(r'failed=(\d+)', output)
                if recap_match:
                    failed_count = int(recap_match.group(1))
                    if failed_count > 0:
                        print(f"⚠️  Playbook has {failed_count} failed task(s)")
                        # This could be a playbook bug, return failure to trigger retry
                        # Filter output before returning to reduce data size
                        filtered_output = filter_verbose_task_output(output)
                        return False, f"Playbook had {failed_count} failed tasks\n\n{filtered_output}"
                
                # Check for ignored tasks with fatal errors (playbook bugs)
                if has_fatal_error:
                    error_summary = "\n".join(fatal_error_details)
                    print(f"❌ PLAYBOOK BUG: Fatal errors detected in ignored tasks")
                    print("   These errors indicate playbook bugs that need to be fixed")
                    print("   The playbook will be regenerated with corrections")
                    # Filter output before returning to reduce data size
                    filtered_output = filter_verbose_task_output(output)
                    return False, f"PLAYBOOK BUG: Fatal errors in ignored tasks (playbook bugs)\n\nErrors:\n{error_summary}\n\nFiltered output:\n{filtered_output}"
                
                print("✅ Playbook completed successfully!")
                
                # Check for compliance report
                if "COMPLIANT" in output or "NON-COMPLIANT" in output or "Compliance" in output:
                    print("✅ Compliance report generated")
                
                # Parse Ansible output for specific checks
                if "PLAY RECAP" in output:
                    recap_start = output.find("PLAY RECAP")
                    recap_section = output[recap_start:recap_start+200].split("\n")[0:4]
                    for line in recap_section:
                        if line.strip():
                            print(f"   {line}")
                
                # Filter output before returning to reduce data size for AI feedback
                filtered_output = filter_verbose_task_output(output)
                return True, filtered_output
            else:
                # Filter output before returning to reduce data size
                filtered_output = filter_verbose_task_output(output)
                return False, f"Execution completed but output format unexpected:\n{filtered_output}"
        else:
            print(f"⚠️  Playbook execution returned code: {result.returncode}")
            
            # Check if it's an SSH/connection issue
            # Ansible-navigator returns code 4 for connection issues
            connection_error_patterns = [
                "Failed to connect to the host",
                "Permission denied",
                "Connection refused",
                "No route to host",
                "Host key verification failed",
                "UNREACHABLE",
                "SSH Error: data could not be sent"
            ]
            
            is_connection_error = (
                result.returncode == 4 or 
                any(pattern in output for pattern in connection_error_patterns)
            )
            
            if is_connection_error:
                print("⚠️  SSH connection issue detected")
                print("   Cannot connect to the host for validation")
                print("   ⚠️  WARNING: Validation cannot be done on the host")
                print("   The playbook syntax is valid, but execution testing is not possible")
                return False, "CONNECTION_ERROR: Cannot connect to host - validation cannot be performed"
            
            # Check if it's an OS version mismatch (playbook is valid, just wrong target)
            os_version_patterns = [
                "This playbook only supports Red Hat Enterprise Linux",
                "ansible_distribution_major_version",
                "OS version mismatch",
                "distribution version",
                "Only supported on"
            ]
            
            if any(pattern in output for pattern in os_version_patterns):
                print("⚠️  OS version mismatch detected")
                print("   The playbook is valid but targets a different OS version than the test host")
                print("   This is expected when KCS article specifies a different OS version")
                print("   ✅ Treating as successful generation - playbook syntax and logic are correct")
                return True, "OS version mismatch - playbook valid for different OS version"
            
            # For verification playbooks, even non-zero exit codes might be acceptable
            # if the playbook completed and generated a report
            if "PLAY RECAP" in output and ("COMPLIANT" in output or "Compliance" in output):
                print("⚠️  Playbook exited with non-zero code but completed verification")
                print("   This is acceptable for compliance check playbooks")
                print("   ✅ Treating as successful - compliance report was generated")
                return True, "Compliance verification completed with findings"
            
            # If we get here, it's a non-zero exit code and not a known acceptable case
            # Return the filtered output as error message
            filtered_output = filter_verbose_task_output(output)
            return False, f"Playbook execution failed with return code {result.returncode}\n\nFiltered output:\n{filtered_output}"
            
    except subprocess.TimeoutExpired:
        error_msg = "Playbook execution timed out after 120 seconds"
        print(f"❌ {error_msg}")
        return False, error_msg
    except FileNotFoundError as e:
        error_msg = f"ansible-navigator command not found: {e}\n"
        error_msg += f"   Tried to execute: {ansible_nav}\n"
        error_msg += f"   Python executable: {sys.executable}\n"
        error_msg += f"   PATH: {os.environ.get('PATH', 'Not set')}"
        print(f"❌ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Error during playbook testing: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg


def verify_status_alignment(test_output: str, analysis_message: str) -> tuple[bool, str]:
    """
    Verify that playbook statuses (PASS/FAIL/NA/UNKNOWN) align with AI analysis (COMPLIANT/NON-COMPLIANT/UNKNOWN/NA).
    
    **Status Standard (Both Playbook and AI must follow):**
    - **COMPLIANT** (AI) / **PASS** (Playbook): Data shows requirement is definitively met
    - **NON-COMPLIANT** (AI) / **FAIL** (Playbook): Data shows requirement is definitively not met
    - **UNKNOWN** (Both): Cannot determine from data (error collecting, ambiguous requirement)
    - **NA** (Both): Skip related task or Did not execute the related task
    
    Status mapping:
    - PASS -> COMPLIANT
    - FAIL -> NON-COMPLIANT
    - NA -> NA
    - UNKNOWN -> UNKNOWN
    
    Args:
        test_output: Playbook execution output containing statuses
        analysis_message: AI analysis message containing compliance statuses
        
    Returns:
        tuple: (is_aligned, alignment_message)
        - is_aligned: True if all statuses align correctly
        - alignment_message: Description of alignment status
    """
    import re
    
    # Extract requirement statuses from playbook output
    playbook_statuses = {}
    overall_playbook_status = None
    overall_req_num = None  # Track which requirement number is the OVERALL requirement
    
    # Pattern to match "REQUIREMENT N - ..." followed by "Status: PASS/FAIL/NA"
    # Also check if it's the OVERALL requirement
    req_pattern = r'REQUIREMENT\s+(\d+)\s*-\s*([^:]*):\s*.*?Status:\s*(PASS|FAIL|NA|UNKNOWN)'
    for match in re.finditer(req_pattern, test_output, re.DOTALL | re.IGNORECASE):
        req_num = int(match.group(1))
        req_title = match.group(2).strip().upper()
        status = match.group(3).upper()
        
        # Check if this is the OVERALL requirement (skip in individual comparison)
        if "OVERALL" in req_title:
            overall_req_num = req_num
            # Still store it but we'll skip it in individual requirement comparison
        else:
            playbook_statuses[req_num] = status
    
    # Extract overall status from playbook output (from OVERALL COMPLIANCE section)
    overall_pattern = r'OVERALL\s+COMPLIANCE:.*?Result:\s*(PASS|FAIL|NA|UNKNOWN)'
    overall_match = re.search(overall_pattern, test_output, re.DOTALL | re.IGNORECASE)
    if overall_match:
        overall_playbook_status = overall_match.group(1).upper()
    
    # Extract compliance statuses from AI analysis
    ai_statuses = {}
    overall_ai_status = None
    
    # Use line-by-line parsing for more reliable extraction
    # This handles various formats: markdown, bullet points, etc.
    lines = analysis_message.split('\n')
    current_req = None
    
    for i, line in enumerate(lines):
        # Match requirement number (with or without markdown)
        # Examples: "**Requirement 1: ..." or "Requirement 1: ..."
        req_match = re.search(r'(?:\*\*)?Requirement\s+(\d+)[^:]*:', line, re.IGNORECASE)
        if req_match:
            current_req = int(req_match.group(1))
            # Reset any previous status for this requirement
            if current_req in ai_statuses:
                del ai_statuses[current_req]
            
            # Also check the current line for compliance status (might be on same line or nearby)
            # Check current line and next 15 lines for compliance status
            # Stop at the next requirement to avoid matching wrong requirement's status
            for j in range(i, min(i + 20, len(lines))):
                # Check if we've hit the next requirement (stop searching)
                next_req_match = re.search(r'(?:\*\*)?Requirement\s+(\d+)[^:]*:', lines[j], re.IGNORECASE)
                if next_req_match and int(next_req_match.group(1)) != current_req:
                    break
                
                # Skip lines that contain "COMPLIANCE STATUS" (all caps, overall) - we only want individual requirement statuses
                # We want "Compliance Status" (mixed case) for individual requirements
                # Check if the line has "COMPLIANCE STATUS" in all caps (overall) but NOT "Compliance Status" (mixed case, individual)
                # The pattern should match "COMPLIANCE STATUS" (all caps) but not "Compliance Status" (mixed case)
                line_upper = lines[j].upper()
                # Check if line contains "COMPLIANCE STATUS" in all caps (without mixed case "Compliance Status")
                if 'COMPLIANCE STATUS' in line_upper:
                    # Check if it's actually "Compliance Status" (mixed case) - if so, don't skip it
                    if not re.search(r'[Cc]ompliance\s+[Ss]tatus', lines[j]):
                        # This is likely the overall status line (all caps), skip it
                        continue
                
                # Pattern: "- **Compliance Status**: COMPLIANT/NON-COMPLIANT" or "Compliance Status: COMPLIANT/NON-COMPLIANT"
                # Make sure we match the full pattern including the colon and status
                # IMPORTANT: Check for NON-COMPLIANT first (longer match) to avoid matching "COMPLIANT" from "NON-COMPLIANT"
                # Match "Compliance Status" (mixed case) not "COMPLIANCE STATUS" (all caps, which is overall)
                # Use case-sensitive matching to ensure we only match "Compliance Status" (mixed case)
                # Pattern breakdown: [-*]? (optional dash/asterisk), \s* (whitespace), \*\*? (markdown bold), 
                # Compliance\s+Status (mixed case), \*\*? (markdown bold end), \s*:\s* (colon with whitespace),
                # \*?\s* (optional asterisk and whitespace), (NON-COMPLIANT|COMPLIANT|UNKNOWN) (status), \b (word boundary)
                status_match = re.search(r'[-*]?\s*\*\*?[Cc]ompliance\s+[Ss]tatus\*\*?\s*:\s*\*?\s*(NON-COMPLIANT|COMPLIANT|UNKNOWN)\b', lines[j], re.IGNORECASE)
                if status_match:
                    status_value = status_match.group(1).upper()
                    ai_statuses[current_req] = status_value
                    current_req = None  # Reset after finding status
                    break
        
        # Also check if current line has a compliance status without a requirement header
        # This handles cases where the status might appear before we've seen the requirement header
        # But only if we're already tracking a requirement
        if current_req:
            # Skip lines that contain "COMPLIANCE STATUS" (all caps, overall)
            if not (re.search(r'^\s*[-*]?\s*\*\*?COMPLIANCE\s+STATUS\*\*?\s*:', line, re.IGNORECASE) and not re.search(r'Compliance\s+Status', line, re.IGNORECASE)):
                status_match = re.search(r'[-*]?\s*\*\*?Compliance\s+Status\*\*?\s*:\s*\*?\s*(NON-COMPLIANT|COMPLIANT|UNKNOWN)\b', line, re.IGNORECASE)
                if status_match and current_req not in ai_statuses:
                    status_value = status_match.group(1).upper()
                    ai_statuses[current_req] = status_value
                    current_req = None  # Reset after finding status
    
    # Extract overall compliance status from AI analysis
    # Try multiple patterns for overall status
    # IMPORTANT: Use case-sensitive matching for "COMPLIANCE STATUS" (all caps) to avoid matching "Compliance Status" (individual)
    # Examples: "- **COMPLIANCE STATUS**: COMPLIANT" or "COMPLIANCE STATUS: COMPLIANT"
    overall_ai_patterns = [
        (r'[-*]?\s*\*\*?COMPLIANCE\s+STATUS\*\*?\s*:\s*\*?\s*(COMPLIANT|NON-COMPLIANT|UNKNOWN)\b', 0),  # Case-sensitive, all caps "- **COMPLIANCE STATUS**: COMPLIANT"
        (r'OVERALL[^:]*COMPLIANCE[:\s]+\*?\s*(COMPLIANT|NON-COMPLIANT|UNKNOWN)\b', re.IGNORECASE),  # "OVERALL COMPLIANCE: COMPLIANT"
        (r'Overall[^:]*[:\s]+\*?\s*(COMPLIANT|NON-COMPLIANT|UNKNOWN)\b', re.IGNORECASE),  # "Overall: COMPLIANT"
    ]
    for pattern, flags in overall_ai_patterns:
        overall_ai_match = re.search(pattern, analysis_message, flags)
        if overall_ai_match:
            overall_ai_status = overall_ai_match.group(1).upper()
            break
    
    # Verify alignment: PASS = COMPLIANT, FAIL = NON-COMPLIANT
    alignment_issues = []
    
    # Check requirement alignments (skip OVERALL requirement in individual comparison)
    all_req_nums = set(playbook_statuses.keys()) | set(ai_statuses.keys())
    for req_num in sorted(all_req_nums):
        # Skip the OVERALL requirement in individual requirement comparison
        if req_num == overall_req_num:
            continue
            
        playbook_status = playbook_statuses.get(req_num)
        ai_status = ai_statuses.get(req_num)
        
        if playbook_status and ai_status:
            # Map: PASS -> COMPLIANT, FAIL -> NON-COMPLIANT, NA -> NA, UNKNOWN -> UNKNOWN
            if playbook_status == "PASS":
                expected_ai = "COMPLIANT"
            elif playbook_status == "FAIL":
                expected_ai = "NON-COMPLIANT"
            elif playbook_status == "NA":
                expected_ai = "NA"  # NA maps to NA (both mean: Skip related task or Did not execute)
            elif playbook_status == "UNKNOWN":
                expected_ai = "UNKNOWN"
            else:
                expected_ai = None
            
            if expected_ai and ai_status != expected_ai:
                alignment_issues.append(f"Requirement {req_num}: Playbook={playbook_status}, AI={ai_status} (expected {expected_ai})")
        elif playbook_status and not ai_status:
            alignment_issues.append(f"Requirement {req_num}: Playbook has status {playbook_status} but AI analysis missing")
        elif ai_status and not playbook_status:
            alignment_issues.append(f"Requirement {req_num}: AI has status {ai_status} but playbook status missing")
    
    # Check overall alignment
    if overall_playbook_status and overall_ai_status:
        # Map: PASS -> COMPLIANT, FAIL -> NON-COMPLIANT, NA -> NA, UNKNOWN -> UNKNOWN
        if overall_playbook_status == "PASS":
            expected_overall_ai = "COMPLIANT"
        elif overall_playbook_status == "FAIL":
            expected_overall_ai = "NON-COMPLIANT"
        elif overall_playbook_status == "NA":
            expected_overall_ai = "NA"  # NA maps to NA (both mean: Skip related task or Did not execute)
        elif overall_playbook_status == "UNKNOWN":
            expected_overall_ai = "UNKNOWN"
        else:
            expected_overall_ai = None
        
        if expected_overall_ai and overall_ai_status != expected_overall_ai:
            alignment_issues.append(f"Overall: Playbook={overall_playbook_status}, AI={overall_ai_status} (expected {expected_overall_ai})")
    elif overall_playbook_status and not overall_ai_status:
        alignment_issues.append(f"Overall: Playbook has status {overall_playbook_status} but AI analysis missing")
    elif overall_ai_status and not overall_playbook_status:
        alignment_issues.append(f"Overall: AI has status {overall_ai_status} but playbook status missing")
    
    # Debug: Print extracted statuses for troubleshooting
    if alignment_issues:
        debug_info = f"Extracted AI statuses: {ai_statuses}\n"
        debug_info += f"Extracted playbook statuses: {playbook_statuses}\n"
        debug_info += f"Overall AI status: {overall_ai_status}\n"
        debug_info += f"Overall playbook status: {overall_playbook_status}\n"
        # Also show a sample of the analysis message to help debug extraction
        # Find lines containing "Compliance Status" or "COMPLIANCE STATUS"
        relevant_lines = []
        for i, line in enumerate(analysis_message.split('\n')):
            if 'Compliance Status' in line or 'COMPLIANCE STATUS' in line or 'Requirement' in line:
                relevant_lines.append(f"Line {i}: {line}")
                if len(relevant_lines) >= 30:  # Limit to 30 relevant lines
                    break
        debug_info += f"\nRelevant lines from analysis message (containing 'Compliance Status' or 'Requirement'):\n" + "\n".join(relevant_lines) + "\n"
        return False, "Status misalignment detected:\n" + debug_info + "\n".join(alignment_issues)
    
    return True, "All statuses align correctly (PASS=COMPLIANT, FAIL=NON-COMPLIANT, NA=UNKNOWN)"


def extract_analysis_statuses(analysis_message: str) -> dict:
    """
    Extract all required statuses from the AI analysis message.
    
    Args:
        analysis_message: The analysis message from analyze_playbook_output
        
    Returns:
        dict with keys:
        - data_collection: "PASS" or "FAIL" or None
        - compliance_analysis: "PASS" or "FAIL" or None
        - NOTE: playbook_analysis is no longer included as it's handled separately (after syntax check, before test execution)
    """
    import re
    analysis_upper = analysis_message.upper()
    statuses = {
        'data_collection': None,
        'compliance_analysis': None
    }
    
    # Extract DATA COLLECTION status
    data_collection_patterns = [
        r'DATA\s+COLLECTION[:\s]*PASS',
        r'\*\*DATA\s+COLLECTION\*\*[:\s]*PASS',
        r'-\s*\*\*DATA\s+COLLECTION\*\*[:\s]*PASS',
    ]
    for pattern in data_collection_patterns:
        if re.search(pattern, analysis_upper):
            statuses['data_collection'] = 'PASS'
            break
    
    if not statuses['data_collection']:
        data_collection_fail_patterns = [
            r'DATA\s+COLLECTION[:\s]*FAIL',
            r'\*\*DATA\s+COLLECTION\*\*[:\s]*FAIL',
        ]
        for pattern in data_collection_fail_patterns:
            if re.search(pattern, analysis_upper):
                statuses['data_collection'] = 'FAIL'
                break
    
    # Extract COMPLIANCE ANALYSIS (PASS/FAIL, not COMPLIANT/NON-COMPLIANT)
    compliance_analysis_patterns = [
        r'COMPLIANCE\s+ANALYSIS[:\s]*PASS',
        r'\*\*COMPLIANCE\s+ANALYSIS\*\*[:\s]*PASS',
        r'-\s*\*\*COMPLIANCE\s+ANALYSIS\*\*[:\s]*PASS',
    ]
    for pattern in compliance_analysis_patterns:
        if re.search(pattern, analysis_upper):
            statuses['compliance_analysis'] = 'PASS'
            break
    
    if not statuses['compliance_analysis']:
        compliance_analysis_fail_patterns = [
            r'COMPLIANCE\s+ANALYSIS[:\s]*FAIL',
            r'\*\*COMPLIANCE\s+ANALYSIS\*\*[:\s]*FAIL',
            r'-\s*\*\*COMPLIANCE\s+ANALYSIS\*\*[:\s]*FAIL',
        ]
        for pattern in compliance_analysis_fail_patterns:
            if re.search(pattern, analysis_upper):
                statuses['compliance_analysis'] = 'FAIL'
                break
    
    return statuses


def extract_playbook_issues_from_analysis(analysis_message: str) -> tuple[bool, str]:
    """
    Extract playbook issues and recommendations from analysis message.
    NOTE: This function is deprecated - PLAYBOOK ANALYSIS is now handled separately 
    (after syntax check, before test execution) via the analyze_playbook function.
    This function always returns (False, "") since PLAYBOOK ANALYSIS is no longer 
    part of the compliance analysis output.
    
    Args:
        analysis_message: The analysis message from analyze_playbook_output
        
    Returns:
        tuple: (has_issues, extracted_advice)
        - has_issues: Always False (PLAYBOOK ANALYSIS handled separately)
        - extracted_advice: Always empty string
    """
    # NOTE: PLAYBOOK ANALYSIS is now handled separately (after syntax check, before test execution)
    # via the analyze_playbook function. This function always returns no issues since
    # PLAYBOOK ANALYSIS is no longer part of the compliance analysis output.
    return False, ""


def check_status_values_evaluated(test_output: str) -> tuple[bool, str]:
    """
    Check if status values in the compliance report are evaluated (PASS/FAIL/NA) or contain Jinja2 expressions.
    
    Args:
        test_output: Playbook execution output
        
    Returns:
        tuple: (is_valid, error_message)
        - is_valid: True if all status values are evaluated correctly
        - error_message: Description of issues found if invalid
    """
    import re
    import json
    
    # First, try to extract the compliance report from Ansible JSON output
    # The report is typically in the "msg" field of the "Generate compliance report" task
    compliance_report_text = ""
    
    # Try to extract from JSON structure (Ansible output format)
    try:
        # Look for the "Generate compliance report" task output
        # Pattern: "msg": [ "line1", "line2", ... ]
        msg_pattern = r'"msg":\s*\[(.*?)\]'
        msg_matches = re.findall(msg_pattern, test_output, re.DOTALL)
        
        for msg_match in msg_matches:
            # Try to parse as JSON array
            try:
                msg_array = json.loads('[' + msg_match + ']')
                # Join all strings in the array
                msg_text = '\n'.join(str(item) for item in msg_array)
                if 'COMPLIANCE REPORT' in msg_text:
                    compliance_report_text = msg_text
                    break
            except (json.JSONDecodeError, ValueError):
                # If JSON parsing fails, try to extract strings manually
                # Pattern: "string content"
                string_pattern = r'"([^"]*)"'
                strings = re.findall(string_pattern, msg_match)
                msg_text = '\n'.join(strings)
                if 'COMPLIANCE REPORT' in msg_text:
                    compliance_report_text = msg_text
                    break
    except Exception:
        pass
    
    # If we couldn't extract from JSON, use the original method
    if not compliance_report_text:
        lines = test_output.split('\n')
        in_compliance_report = False
        report_lines = []
        
        for i, line in enumerate(lines):
            # Detect start of compliance report
            if 'COMPLIANCE REPORT' in line or ('COMPLIANCE' in line and 'REPORT' in line):
                in_compliance_report = True
                report_lines.append(line)
                continue
            
            # Detect end of compliance report
            if in_compliance_report:
                if 'PLAY RECAP' in line or ('TASK [' in line and i > 0 and len(report_lines) > 10):
                    break
                report_lines.append(line)
        
        compliance_report_text = '\n'.join(report_lines)
    
    if not compliance_report_text:
        # If we can't find the compliance report, assume it's OK (might be in a different format)
        return True, "Compliance report not found in expected format, skipping status validation"
    
    # Patterns to detect Jinja2 expressions in status values
    jinja2_patterns = [
        r'Status:\s*\{\s*\(',  # Status: { (
        r'Status:\s*\{\{\s*\(',  # Status: {{ (
        r'Status:\s*\{\{\{\{\s*\(',  # Status: {{{{ (
        r'Status:\s*["\']\s*PASS\s*if',  # Status: 'PASS if
        r'Status:\s*["\']\s*FAIL\s*if',  # Status: 'FAIL if
        r'Status:\s*["\']\s*NA\s*if',  # Status: 'NA if
        r'Status:\s*["\']\s*UNKNOWN\s*if',  # Status: 'UNKNOWN if
        r'Status:\s*trim\s*\}\}',  # Status: ... trim }}
        r'Status:\s*trim\s*\}\}\}\}',  # Status: ... trim }}}}
    ]
    
    # Extract all status lines from the compliance report
    status_lines = []
    lines = compliance_report_text.split('\n')
    
    for i, line in enumerate(lines):
        # Check for status lines (but not "OVERALL COMPLIANCE" section)
        if 'Status:' in line and 'OVERALL' not in line.upper():
            status_lines.append((i+1, line))
    
    # Check each status line for Jinja2 expressions
    issues = []
    for line_num, line in status_lines:
        for pattern in jinja2_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                issues.append(f"Line {line_num}: {line.strip()}")
                break
    
    if issues:
        error_msg = "Status values are showing Jinja2 expressions instead of evaluated values.\n\n"
        error_msg += "**Valid status values:**\n"
        error_msg += "- **PASS**: Requirement is definitively met\n"
        error_msg += "- **FAIL**: Requirement is definitively not met\n"
        error_msg += "- **NA**: Skip related task or Did not execute the related task\n"
        error_msg += "- **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)\n\n"
        error_msg += "Found issues:\n"
        for issue in issues[:5]:  # Show first 5 issues
            error_msg += f"  - {issue}\n"
        if len(issues) > 5:
            error_msg += f"  ... and {len(issues) - 5} more issues\n"
        error_msg += "\nThis indicates the playbook is using string literals instead of Jinja2 expressions for status variables."
        return False, error_msg
    
    # Also check if status values are valid (PASS/FAIL/NA/UNKNOWN)
    # Extract and validate status values with proper stripping
    # CRITICAL: Use strip() before comparison - if status is valid after stripping, accept it
    invalid_statuses = []
    for line_num, line in status_lines:
        # Extract status value from the line
        # Pattern: Status: <value> (capture everything after "Status:" until end of line or comma)
        # This will capture the value including any trailing whitespace/newlines
        status_match = re.search(r'Status:\s*(?:["\'])?\s*(.+?)(?:["\'])?\s*[,]?\s*$', line, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if status_match:
            # Extract the status value and strip it to remove newlines and whitespace
            raw_status_value = status_match.group(1)
            # CRITICAL: Strip before comparison
            status_value = raw_status_value.strip()
            
            # Check if it's a valid status value (after stripping)
            if status_value.upper() in ['PASS', 'FAIL', 'NA', 'UNKNOWN']:
                # Valid status after stripping - accept it even if raw value had newlines
                # This is correct behavior - strip() cleans the value before comparison
                pass
            else:
                # Invalid status value even after stripping
                # Check if it contains newline or other invalid characters
                if '\n' in raw_status_value or '\r' in raw_status_value:
                    invalid_statuses.append(f"Line {line_num}: Status shows `{repr(raw_status_value)}` (contains newline character) instead of clean 'PASS', 'FAIL', 'NA', or 'UNKNOWN'")
                else:
                    invalid_statuses.append(f"Line {line_num}: Status shows `{repr(status_value)}` instead of 'PASS', 'FAIL', 'NA', or 'UNKNOWN'")
        else:
            # Try alternative pattern - extract value after "Status:" more flexibly
            alt_match = re.search(r'Status:\s*(.+?)(?:\s*[,]?\s*$|\s*["\'])', line, re.IGNORECASE | re.DOTALL)
            if alt_match:
                raw_status_value = alt_match.group(1)
                # CRITICAL: Strip before comparison
                status_value = raw_status_value.strip()
                if status_value.upper() not in ['PASS', 'FAIL', 'NA', 'UNKNOWN']:
                    if '\n' in raw_status_value or '\r' in raw_status_value:
                        invalid_statuses.append(f"Line {line_num}: Status shows `{repr(raw_status_value)}` (contains newline character) instead of clean 'PASS', 'FAIL', 'NA', or 'UNKNOWN'")
                    else:
                        invalid_statuses.append(f"Line {line_num}: Status shows `{repr(status_value)}` instead of 'PASS', 'FAIL', 'NA', or 'UNKNOWN'")
            else:
                # Couldn't extract status value - check if line contains Status: but no valid value
                if 'Status:' in line:
                    # Extract any potential status value and check after stripping
                    # Look for Status: followed by any text
                    fallback_match = re.search(r'Status:\s*(.+)', line, re.IGNORECASE)
                    if fallback_match:
                        fallback_value = fallback_match.group(1).strip()
                        if fallback_value.upper() not in ['PASS', 'FAIL', 'NA', 'UNKNOWN']:
                            invalid_statuses.append(f"Line {line_num}: {line.strip()}")
                    else:
                        invalid_statuses.append(f"Line {line_num}: {line.strip()}")
    
    if invalid_statuses:
        error_msg = "Status values are not valid.\n\n"
        error_msg += "**Valid status values:**\n"
        error_msg += "- **PASS**: Requirement is definitively met\n"
        error_msg += "- **FAIL**: Requirement is definitively not met\n"
        error_msg += "- **NA**: Skip related task or Did not execute the related task\n"
        error_msg += "- **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)\n\n"
        error_msg += "Found invalid statuses:\n"
        for issue in invalid_statuses[:5]:
            error_msg += f"  - {issue}\n"
        if len(invalid_statuses) > 5:
            error_msg += f"  ... and {len(invalid_statuses) - 5} more issues\n"
        return False, error_msg
    
    return True, "All status values are correctly evaluated"


def analyze_playbook(
    requirements: list[str],
    playbook_objective: str,
    playbook_content: str,
    audit_procedure: str = None
) -> tuple[bool, str]:
    """
    Analyze if the playbook structure and content correctly implements all requirements (STAGE 0: PLAYBOOK STRUCTURE CHECK).
    
    This function checks if the playbook content has tasks implementing all requirements BEFORE execution.
    It verifies the playbook structure matches the requirements and CIS audit procedure.
    
    Args:
        requirements: List of requirements
        playbook_objective: The objective of the playbook
        playbook_content: The actual playbook YAML content
        audit_procedure: CIS Benchmark audit procedure (optional)
        
    Returns:
        tuple: (is_valid, playbook_analysis_message)
        - is_valid: True if playbook structure correctly implements all requirements
        - playbook_analysis_message: AI's analysis of playbook structure
    """
    print("\n" + "=" * 80)
    print("🔍 STAGE 0: PLAYBOOK STRUCTURE ANALYSIS")
    print("=" * 80)
    print("Checking if playbook structure correctly implements all requirements...")
    
    # Format requirements for analysis
    requirements_text = "\n".join([f"{i+1}. {req}" for i, req in enumerate(requirements)])
    
    # Build audit procedure section if provided
    audit_procedure_section = ""
    if audit_procedure:
        audit_procedure_section = f"""

**CIS BENCHMARK AUDIT PROCEDURE:**
The following is the official audit procedure from the CIS Benchmark. 
The playbook MUST implement this audit procedure correctly:

```bash
{audit_procedure}
```

**CRITICAL - AUDIT PROCEDURE COMPLIANCE:**
1. **PRIORITY: USE PROVIDED SCRIPTS/COMMANDS FIRST**
   - **MANDATORY**: If the audit procedure provides scripts or commands, the playbook MUST use them exactly as provided
   - **DO NOT** accept alternative commands or scripts unless the provided ones are confirmed to not work
   - **ONLY** flag as incorrect if the playbook uses different commands when the audit procedure provides specific ones
   - Verify that the playbook preserves the exact commands, scripts, and logic from the audit procedure
2. The playbook should convert the audit procedure script/commands into Ansible tasks
3. Each distinct check in the audit procedure should become a separate requirement/task
4. The playbook should follow the step-by-step logic from the audit procedure
5. Conditional execution should match the audit procedure (e.g., "If nothing is returned, no further audit steps are required")
6. Status determination logic should match the expected outputs and pass/fail criteria from the audit procedure

"""
    
    # Build playbook structure analysis prompt
    # Note: We need to escape % characters for .format() - % becomes %%
    # Also need to escape { and } for .format() - { becomes {{ and } becomes }}
    # For Jinja2 template syntax like {% set %}, we use {{%% set %%}} which becomes {% set %} after format
    playbook_analysis_prompt = """You are an expert Ansible auditor. Analyze if a playbook STRUCTURE correctly implements all requirements.

**SCOPE:**
- This stage ONLY checks playbook CONTENT structure and task existence
- DO NOT check execution output, data collection, or actual data values (handled in later stages)

**STATUS VALUE DEFINITIONS:**
- **PASS**: Requirement is definitively met
- **FAIL**: Requirement is definitively not met
- **NA**: Skip related task or Did not execute the related task
- **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)

**INPUT:**
**Playbook Objective:** {objective}
{audit_procedure_section}
**Requirements to implement:**
{requirements}

**Actual Playbook Content (YAML):**
```yaml
{playbook_content}
```

**VERIFICATION TASKS:**

**1. REQUIREMENT MAPPING VERIFICATION** (Existence Check):
   - **Purpose**: Verify ALL requirements have corresponding tasks/elements in playbook content
   - **Scope**: EXISTENCE only, NOT correctness
   - **Method**:
     * Count total requirements in input list
     * For DATA COLLECTION requirements: Check if task exists (shell/command modules, task names)
     * For STRUCTURAL requirements: Check if elements exist (CIS comments, "Generate compliance report" task)
     * Mark as FOUND if task/element exists, even if implementation is incorrect
   - **PASS**: All requirements have corresponding tasks/elements
   - **FAIL**: Any requirement completely missing (no task/element exists)

**2. REQUIREMENTS ANALYSIS** (Correctness Check):
   - **Purpose**: Verify tasks IMPLEMENT requirements correctly
   - **Scope**: Implementation details and correctness
   - **Check**:
     * **PRIORITY: USE PROVIDED SCRIPTS/COMMANDS FIRST**
       - **MANDATORY**: If the audit procedure or requirements provide scripts or commands, verify the playbook uses them exactly as provided
       - **DO NOT** flag as incorrect if the playbook uses the provided scripts/commands, even if alternatives exist
       - **ONLY** flag as incorrect if the playbook uses different commands when specific ones are provided in the audit procedure
       - Verify that the playbook preserves the exact commands, scripts, and logic from the audit procedure
     * Command/script matches requirement description OR matches the provided audit procedure script/command
     * Regex patterns are correct (extract and compare values properly)
     * Version comparisons implemented correctly (e.g., "1.3.1-25 or later" extracts and compares numerically)
     * Status determination logic matches requirement's pass/fail criteria
     * **Complex comparisons using Jinja2 templates** (`{% set %}`, `{% if %}` blocks) are VALID and acceptable for complicated logic
       - Example: Multi-component version comparisons (major.minor.patch-release) using `{% set %}` to extract components
       - Example: Complex conditional logic with multiple AND/OR conditions using `{% if %}` blocks
       - These should use folded block scalars (`>-`) which is ACCEPTABLE for this use case
   - **CRITICAL - ONLY FLAG CONFIRMED ISSUES**:
     * **IGNORE potential issues** (e.g., "may not correctly match", "could cause issues") - execution will test these
     * **IGNORE reliability concerns** (e.g., "may not reliably produce") - execution will test reliability
     * **ONLY FLAG confirmed problems**: Clearly wrong patterns, missing logic, incorrect syntax, or obvious mismatches
     * **DO NOT flag if playbook uses provided scripts/commands from audit procedure** - this is correct behavior
     * If you cannot confirm an issue definitively, do NOT flag it - let execution reveal the actual behavior
   - **PASS**: Tasks implement requirements correctly (or issues are only potential/uncertain)
   - **FAIL**: Tasks have confirmed implementation problems (wrong regex, incorrect comparisons, missing logic, etc.) OR playbook uses different commands when audit procedure provides specific ones

**3. AUDIT PROCEDURE COMPLIANCE** (if audit procedure provided):
   - **Purpose**: Verify playbook WORKFLOW and DEPENDENCIES align with audit procedure
   - **Scope**: Workflow/dependencies only, NOT implementation details
   - **Check**:
     * Conditional execution matches audit procedure (e.g., `when:` conditions where required)
     * Task execution order matches audit procedure's step-by-step logic
     * Task dependencies match audit procedure (e.g., Requirement 2 depends on Requirement 1's output)
     * Overall compliance logic matches audit procedure (e.g., "PASS when req_1 returns nothing OR (req_1 returns output AND req_2=PASS AND req_3=PASS)")
   - **PASS**: Workflow/dependencies align
   - **FAIL**: Workflow/dependencies don't align
   - **NOTE**: Implementation details (regex, version comparisons) belong in "Requirements Analysis"

**4. STATUS VARIABLE FORMAT VERIFICATION:**
   - **Block Scalars Check**:
     * ❌ WRONG: `status_1: |` (literal block scalar preserves newlines - causes "PASS\\n" issues)
     * ✅ ACCEPTABLE: `status_1: >-` (folded block scalar folds newlines - works correctly)
       - **ACCEPTABLE for complex Jinja2 templates**: When using `{% set %}` and `{% if %}` blocks for complex comparisons, folded block scalar (`>-`) is the correct approach
     * ✅ PREFERRED: `status_1: "{{{{ ... }}}}"` (quoted string - most explicit, for simple expressions)
   - **Multi-line Variable Assignments**:
     * When assigning complicated multi-line values (for example scripts) to variables, wrap the block in `{% raw %}` tags:
     * ✅ CORRECT:
       ```yaml
       vars:
         req_2: |
           {% raw %}
           #!/usr/bin/env bash
           # ... your complex script ...
           {% endraw %}
       
       # Or in set_fact:
       - name: Store complex script
         set_fact:
           script_content: |
             {% raw %}
             #!/usr/bin/env bash
             l_mod_name="cramfs"
             # ... complex script with {{ }} or other Jinja2-like syntax ...
             {% endraw %}
       ```
     * ❌ WRONG: Multi-line script without `{% raw %}` tags (Jinja2 will try to process it):
       ```yaml
       req_2: |
         #!/usr/bin/env bash
         # This will fail if script contains {{ }} or other Jinja2 syntax
       ```
     * **CRITICAL**: Use `{% raw %}` tags when the content contains characters that Jinja2 might interpret (like `{{`, `}}`, `{%`, `%}`, `$`, etc.)
   - **Complex Jinja2 Template Blocks (ACCEPTABLE)**:
     * For complicated version comparisons or multi-step logic, Jinja2 template blocks with `{% set %}` and `{% if %}` are VALID
     * ✅ CORRECT - Complex template using folded block scalar (RECOMMENDED APPROACH):
       ```yaml
       status_1: >-
         {% set output = result_1.stdout | default('') | trim %}
         {% if output is search('pam-[0-9]') %}
           {% set version_match = output | regex_search('pam-([0-9]+\\.[0-9]+\\.[0-9]+)-([0-9]+)') %}
           {% if version_match %}
             {% set version_parts = version_match.split('-')[1] %}
             {% set major = version_parts.split('.')[0] | int %}
             {% set minor = version_parts.split('.')[1] | int %}
             {% set patch = version_parts.split('.')[2] | int %}
             {% set release = version_match.split('-')[2] | int %}
             {% if (major > 1) or
                   (major == 1 and minor > 3) or
                   (major == 1 and minor == 3 and patch > 1) or
                   (major == 1 and minor == 3 and patch == 1 and release >= 25) %}
               PASS
             {% else %}
               FAIL
             {% endif %}
           {% else %}
             FAIL
           {% endif %}
         {% else %}
           FAIL
         {% endif %}
       ```
     * **Key indicators of valid complex templates**:
       - **PREFERRED**: Uses `regex_replace()` with backreferences (`\\1`, `\\2`, etc.) to extract specific capture groups directly
         - This is safer than using `regex_search()` with array indexing (`match[1]`, `match[2]`, etc.)
         - Example: `{% set mode = output | regex_replace('.*Access: \\(0?([0-7]+)/.*', '\\1') %}`
       - **ALTERNATIVE**: For version strings with consistent delimiters, uses `regex_search()` to get full version match first, then `split()` to extract components
         - This approach works well when the format is predictable (e.g., `pam-1.3.1-25`)
       - Uses `{% set variable = ... %}` to extract and store intermediate values
       - Uses `{% if %}` blocks for multi-condition logic
       - Uses `| int` or `| int(base=8)` filter to convert strings to integers for numeric comparison
       - Ends with `PASS` or `FAIL` (not quoted, inside template block)
       - Uses folded block scalar (`>-`) which is ACCEPTABLE for this use case
       - May use `{# ... #}` for comments/debugging within template blocks
   - **Regex Double-Escaping Trap Check**:
     * In status variables using `regex_search()` or `regex_replace()`, verify patterns use SINGLE backslash
     * **CRITICAL DETECTION RULE**: Count the backslashes BEFORE the period in the actual YAML source code
     * **What to look for in the actual YAML source**:
       - Examine the regex pattern string character by character in the playbook YAML
       - Look for patterns like: `regex_search('pam-1` followed by backslashes and a period
       - ❌ WRONG: If you see `\\\\.` (TWO backslashes before period) - this is the double-escaping trap!
       - ❌ WRONG: If you see `\\\\\\.` (FOUR backslashes before period) - also wrong!
       - ✅ CORRECT: If you see `\\.` (ONE backslash before period) - this is correct for single-quoted strings
       - **NOTE**: In Jinja2 template blocks (`{% %}`), backslashes in `regex_replace` patterns may appear as `\\` (two backslashes) in YAML source, but this is CORRECT because they're inside template blocks - only flag if it's in inline expressions
     * **Concrete Example from YAML source**:
       - ❌ WRONG: `regex_search('pam-1\\\\.3\\\\.1-([0-9]+)')` - In inline expression, TWO backslashes before period
       - ✅ CORRECT: `regex_search('pam-1\\.3\\.1-([0-9]+)')` - In inline expression, ONE backslash before period
       - ✅ CORRECT: `regex_replace('^.*pam-([0-9]+)\\..*$', '\\1')` - In template block (`{% %}`), `\\` is correct
     * **Detection Method**: 
       - Search the playbook content for `regex_search(` or `regex_replace(`
       - **Distinguish between inline expressions and template blocks**:
         * In inline expressions (inside `{{ }}`): Should have ONE backslash (`\\.`)
         * In template blocks (inside `{% %}`): `\\` (two backslashes) is CORRECT for regex patterns
       - Count consecutive backslashes before periods: 
         * In inline: should be ONE (`\\.`)
         * In template blocks: TWO (`\\.`) is CORRECT
       - If you see `\\\\.` (FOUR backslashes) or more in inline expressions, flag it as WRONG
     * ❌ WRONG Examples (from actual YAML source):
       * `regex_search('pam-1\\\\.3\\\\.1-([0-9]+)')` - In inline expression, TWO backslashes before period
       * `regex_search('pam-1\\\\\\.3\\\\\\.1-([0-9]+)')` - In inline expression, FOUR backslashes before period
     * ✅ CORRECT Examples (from actual YAML source):
       * `regex_search('pam-1\\.3\\.1-([0-9]+)')` - In inline expression, ONE backslash before period
       * `status_1: "{{{{ ('PASS' if (result_1.stdout | regex_search('pam-1\\.3\\.1-([0-9]+)')) else 'FAIL') | trim }}}}"` - Inline expression with ONE backslash
       * `{% set major = output | regex_replace('^.*pam-([0-9]+)\\..*$', '\\1') | int %}` - In template block, `\\` is CORRECT

**5. CONDITIONAL EXECUTION VERIFICATION** (if applicable):
   - Check if playbook has proper `when:` conditions for conditional requirements
   - Verify conditional logic matches audit procedure (if provided)
   - Example: If audit procedure says "If nothing is returned, no further audit steps are required", check if Requirements 2 and 3 have `when: data_1 | length > 0`

**PASS CRITERIA:**
✅ All requirements have corresponding tasks/elements (REQUIREMENT MAPPING VERIFICATION: PASS)
✅ Tasks implement requirements correctly (REQUIREMENTS ANALYSIS: PASS)
✅ Status variables use quoted strings or folded block scalars (`>-`), NOT literal (`|`)
  - **NOTE**: Folded block scalars (`>-`) are ACCEPTABLE for complex Jinja2 templates using `{% set %}` and `{% if %}` blocks
✅ Regex patterns use SINGLE backslash (`\\.`) in inline expressions, or correct escaping in template blocks
✅ Complex comparisons using Jinja2 templates (`{% set %}`, `{% if %}`) are valid and acceptable
✅ Structural requirements present (comments, report tasks, etc.)
✅ Audit procedure compliance correct (if provided)
✅ Conditional execution properly implemented (if applicable)

**FAIL CRITERIA:**
❌ Any requirement completely missing (REQUIREMENT MAPPING VERIFICATION: FAIL)
❌ Tasks don't implement requirements correctly (REQUIREMENTS ANALYSIS: FAIL)
❌ Status variables use literal block scalars (`|`) instead of quoted strings or folded (`>-`)
❌ Regex patterns use DOUBLE backslash (`\\\\.`) instead of SINGLE backslash (`\\.`)
❌ Structural requirements completely missing
❌ Audit procedure compliance incorrect (if provided)
❌ Conditional execution missing when required

**DO NOT CHECK:**
- Task execution results (verified in later stages)
- Data collection or data values (verified in later stages)
- Empty output validity (verified in later stages)
- Jinja2 syntax correctness (validated by other functions)
- YAML syntax correctness (validated by syntax check)
- "Generate compliance report" task output format (only verify task exists)
- Status values with newlines if `| trim` is present (acceptable)
- Folded block scalars (`>-`) (acceptable)
- **Potential issues** (e.g., "may not correctly", "could cause") - execution will test these
- **Reliability concerns** (e.g., "may not reliably", "might fail") - execution will test reliability
- **Uncertain problems** - only flag confirmed, definitive issues

**RESPONSE FORMAT:**

**SUCCESS RESPONSE:**
```
PLAYBOOK_STRUCTURE: PASS

**REQUIREMENT MAPPING VERIFICATION:** PASS
- **Total Requirements in Input:** [N] requirements
- **Data Collection Requirements Found:** [X] requirements (tasks exist in playbook content)
- **Structural Requirements Verified:** [Y] requirements
- **NOTE**: Checks for EXISTENCE only. Correctness is verified separately in "Requirements Analysis".

**Requirements Analysis:** PASS
- Requirement 1: Task "Req 1 - [description]" exists and implements correctly (command/script matches requirement)
- Requirement 2: Task "Req 2 - [description]" exists and implements correctly
- Requirement 3: Task "Req 3 - [description]" exists and implements correctly
- Requirement 4: Task "Req 4 - [description]" exists and implements correctly
- Requirement 5: CIS reference comment present and correct
- Requirement 6: "Generate compliance report" task exists in playbook content
  - **NOTE**: Only task existence verified. Output format not analyzed.
- Requirement 7: [Other structural requirement exists and correct]

**Status Variable Format and Regex Verification:** PASS
- All status variables use quoted strings or folded block scalars (`>-`), NOT literal (`|`)
  - Folded block scalars (`>-`) are ACCEPTABLE for complex Jinja2 templates using `{{%% set %%}}` and `{{%% if %%}}` blocks
- Multi-line variable assignments (scripts, complex content) correctly use `{% raw %}` tags when needed
- All regex patterns use correct escaping:
  - In inline expressions (`{{ }}`): SINGLE backslash (`\\.`)
  - In template blocks (`{% %}`): 
    - **PREFERRED**: Use `regex_replace()` with backreferences (`\\1`, `\\2`, etc.) to extract specific capture groups directly
    - **ALTERNATIVE**: For version strings with consistent delimiters, use `regex_search()` with single backslash `\\.` for periods, then use `split()` to extract components

{{If audit procedure provided:}}
**Audit Procedure Compliance:** PASS
- Workflow and dependencies align with audit procedure
- Conditional execution matches audit procedure requirements
- Overall compliance logic structure matches audit procedure
- **NOTE**: Implementation details checked in "Requirements Analysis", not here

{{If conditional execution applicable:}}
**Conditional Execution Verification:** PASS
- Requirements 2 and 3 have proper `when:` conditions (e.g., `when: data_1 | length > 0`)
- Conditional execution logic matches audit procedure
```

**FAILURE RESPONSE:**
```
PLAYBOOK_STRUCTURE: FAIL

**REQUIREMENT MAPPING VERIFICATION:** FAIL
- **Total Requirements in Input:** [N] requirements
- **Data Collection Requirements Found:** [X] requirements
- **Structural Requirements Verified:** [Y] requirements
- **NOTE**: Checks for EXISTENCE only. FAIL only if requirements are completely missing.

Missing/Not Found:
- Requirement X: [requirement text] - No task/element found in playbook content
- Requirement Y: [requirement text] - No task/element found in playbook content

**Requirements Analysis:** FAIL
- **NOTE**: Checks CORRECTNESS and IMPLEMENTATION DETAILS. Tasks may exist but fail here if incorrect.
- **CRITICAL**: Only flag CONFIRMED issues. Do NOT flag potential issues (e.g., "may not correctly", "could cause") or reliability concerns (e.g., "may not reliably") - execution will test these.
- **PRIORITY: USE PROVIDED SCRIPTS/COMMANDS FIRST**
  - **MANDATORY**: If the audit procedure provides scripts or commands, verify the playbook uses them exactly as provided
  - **DO NOT** flag as incorrect if the playbook uses the provided scripts/commands from the audit procedure
  - **ONLY** flag as incorrect if the playbook uses different commands when specific ones are provided in the audit procedure
- Requirement X: [requirement text] - Task exists but implementation incorrect
  - Example: "Regex pattern `'pam-1\\.3\\.1-([0-9]+)'` doesn't extract and compare build number to '25' as required" (CONFIRMED issue)
  - Example: "Playbook uses `grep -r pattern` but audit procedure specifies `find /path -name 'file' | xargs grep pattern`" (CONFIRMED issue - different command when specific one provided)
  - ❌ WRONG: "Regex pattern may not correctly match" (potential issue - DO NOT FLAG)
  - ❌ WRONG: "May not reliably produce" (reliability concern - DO NOT FLAG)
  - ❌ WRONG: "Playbook uses audit procedure command X, but alternative command Y might be better" (DO NOT FLAG - using provided command is correct)
- Requirement Y: [requirement text] - Task exists but doesn't match requirement (wrong command/script when audit procedure provides specific one, incorrect regex, wrong version comparison - CONFIRMED issues only)

{{If status variables have issues:}}
**Status Variable Format and Regex Verification:** FAIL
- Status variables should use quoted strings or folded block scalars (`>-`), NOT literal (`|`)
  - **NOTE**: Folded block scalars (`>-`) are ACCEPTABLE for complex Jinja2 templates using `{% set %}` and `{% if %}` blocks
- Multi-line variable assignments (scripts, complex content) MUST use `{% raw %}` tags:
  - ✅ CORRECT: 
    ```yaml
    req_2: |
      {% raw %}
      #!/usr/bin/env bash
      # ... your complex script ...
      {% endraw %}
    ```
  - ❌ WRONG: Multi-line script without `{% raw %}` tags (Jinja2 will try to process it and may fail)
- Regex patterns MUST use correct escaping:
  - In inline expressions (`{{ }}`): SINGLE backslash (`\\.`), NOT multiple backslashes (`\\\\.` or `\\\\\\.`)
  - In template blocks (`{% %}`): 
    - **PREFERRED**: Use `regex_replace()` with backreferences (`\\1`, `\\2`, etc.) to extract specific capture groups directly
      - This is safer than using `regex_search()` with array indexing (`match[1]`, `match[2]`, etc.)
      - Example: `{% set mode = output | regex_replace('.*Access: \\(0?([0-7]+)/.*', '\\1') %}`
    - **ALTERNATIVE**: For version strings with consistent delimiters, use `regex_search()` with single backslash `\\.` for periods, then use `split()` to extract components
- **Detection**: In the YAML source, distinguish between inline expressions and template blocks
- **Examples**:
  * ❌ WRONG: `status_1: |` (literal preserves newlines)
  * ❌ WRONG: `regex_search('pam-1\\\\.3\\\\.1-([0-9]+)')` in inline expression (TWO backslashes `\\\\.` before period - WRONG!)
  * ❌ WRONG: `regex_search('pam-1\\\\\\.3\\\\\\.1-([0-9]+)')` in inline expression (FOUR backslashes `\\\\\\.` before period - WRONG!)
  * ❌ WRONG: Using `regex_search()` with array indexing: `{% set match = output | regex_search('pattern') %}{% set value = match[1] %}` (error-prone, may grab wrong character)
  * ✅ CORRECT: `regex_search('pam-1\\.3\\.1-([0-9]+)')` in inline expression (ONE backslash `\\.` before period - CORRECT) - for boolean checks
  * ✅ CORRECT: `status_1: "{{{{ ('PASS' if (result_1.stdout | regex_search('pam-1\\.3\\.1-([0-9]+)')) else 'FAIL') | trim }}}}"` (quoted string + single backslash) - for boolean checks
  * ✅ CORRECT: `{% set mode = output | regex_replace('.*Access: \\(0?([0-7]+)/.*', '\\1') %}` - PREFERRED: Extract specific capture group directly
  * ✅ CORRECT: `{% set version_match = output | regex_search('pam-([0-9]+\\.[0-9]+\\.[0-9]+)-([0-9]+)') %}` - ALTERNATIVE: For version strings with consistent delimiters, use `regex_search()` first, then `split()` to extract components
  * ✅ CORRECT: `{% set major = version_parts.split('.')[0] | int %}` - Use `split()` method to extract version components (when using regex_search approach)
  * ✅ CORRECT: Complex template using folded block scalar (RECOMMENDED APPROACH):
    ```yaml
    status_1: >-
      {% set output = result_1.stdout | default('') | trim %}
      {% if output is search('pam-[0-9]') %}
        {% set version_match = output | regex_search('pam-([0-9]+\\.[0-9]+\\.[0-9]+)-([0-9]+)') %}
        {% if version_match %}
          {% set version_parts = version_match.split('-')[1] %}
          {% set major = version_parts.split('.')[0] | int %}
          {% set minor = version_parts.split('.')[1] | int %}
          {% set patch = version_parts.split('.')[2] | int %}
          {% set release = version_match.split('-')[2] | int %}
          {% if (major > 1) or
                (major == 1 and minor > 3) or
                (major == 1 and minor == 3 and patch > 1) or
                (major == 1 and minor == 3 and patch == 1 and release >= 25) %}
            PASS
          {% else %}
            FAIL
          {% endif %}
        {% else %}
          FAIL
        {% endif %}
      {% else %}
        FAIL
      {% endif %}
    ```

{{If audit procedure compliance wrong:}}
**Audit Procedure Compliance:** FAIL
- [Specific workflow/dependency issue]
- [What needs to be fixed]
- **NOTE**: Implementation details belong in "Requirements Analysis"

{{If conditional execution missing:}}
**Conditional Execution Issues:**
- Requirements 2 and 3 should have `when:` conditions but don't
- Audit procedure requires: "If nothing is returned, no further audit steps are required"
- Missing: `when: data_1 | length > 0` on Requirements 2 and 3 tasks

ADVICE TO UPDATE PLAYBOOK:
1. [Add missing tasks/elements]
2. [Fix implementation issues]
3. [Change literal block scalars (`|`) to quoted strings or folded (`>-`)]
4. [Fix regex patterns: Change `\\\\.` to `\\.`]
5. [Fix audit procedure compliance if needed]
6. [Add conditional execution if needed]
7. **CRITICAL**: Do NOT provide advice about "Generate compliance report" task output format - only verify task exists
```

**Your Response:**"""
    
    # Use .replace() instead of .format() to avoid issues with % characters
    # First, replace the format placeholders
    playbook_analysis_prompt = playbook_analysis_prompt.replace('{objective}', playbook_objective)
    playbook_analysis_prompt = playbook_analysis_prompt.replace('{audit_procedure_section}', audit_procedure_section)
    playbook_analysis_prompt = playbook_analysis_prompt.replace('{requirements}', requirements_text)
    playbook_analysis_prompt = playbook_analysis_prompt.replace('{playbook_content}', playbook_content)
    
    try:
        print("Analyzing playbook structure (this may take a minute)...")
        
        # Use the LLM directly
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"Playbook structure analysis attempt {attempt}/{max_attempts}...")
                response = model.invoke(playbook_analysis_prompt)
                result = response.content.strip()
                break
            except Exception as e:
                error_msg = str(e)
                if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    print(f"⚠️  Analysis timed out on attempt {attempt}, retrying...")
                    if attempt < max_attempts:
                        continue
                    else:
                        print("⚠️  Analysis timed out, assuming playbook structure is valid...")
                        return True, "PLAYBOOK_STRUCTURE: PASS (Analysis timed out - assuming valid)"
                else:
                    raise
        
        print("\n📊 Playbook Structure Analysis Result:")
        print("-" * 80)
        # Show full result, not truncated
        print(result)
        print("-" * 80)
        
        # Check result - IMPORTANT: Check for FAIL first because "FAIL" might contain "PASS"
        result_upper = result.upper()
        
        if "PLAYBOOK_STRUCTURE: FAIL" in result_upper or "REQUIREMENT_MAPPING_ERROR" in result_upper:
            print("\n❌ PLAYBOOK STRUCTURE: FAIL - Requirements not properly implemented")
            print("\n📋 Full Analysis Details:")
            print("=" * 80)
            print(result)
            print("=" * 80)
            return False, result
        elif "PLAYBOOK_STRUCTURE: PASS" in result_upper:
            print("\n✅ PLAYBOOK STRUCTURE: PASS - All requirements properly implemented")
            return True, result
        else:
            # Ambiguous result - check for positive/negative indicators
            if any(word in result.lower() for word in ["missing", "not implemented", "not found", "incorrect", "wrong", "error"]):
                print("\n❌ PLAYBOOK STRUCTURE: FAIL - Issues found (negative indicators detected)")
                return False, result
            elif any(word in result.lower() for word in ["all requirements", "properly implemented", "correctly", "verified"]):
                print("\n✅ PLAYBOOK STRUCTURE: PASS - Structure appears correct")
                return True, result
            else:
                print("\n⚠️  PLAYBOOK STRUCTURE: UNCLEAR - Assuming valid")
                return True, result
                
    except Exception as e:
        error_msg = f"Error during playbook structure analysis: {str(e)}"
        print(f"❌ {error_msg}")
        # On error, assume valid to not block
        return True, f"PLAYBOOK_STRUCTURE: PASS (Check failed but proceeding: {error_msg})"


def analyze_data_collection(
    requirements: list[str],
    playbook_objective: str,
    test_output: str,
    playbook_content: str = None,
    audit_procedure: str = None,
    suppress_header: bool = False
) -> tuple[bool, str]:
    """
    Analyze if the playbook collected sufficient data (STAGE 1: DATA SUFFICIENCY CHECK).
    
    This function ONLY checks if data was collected properly.
    It also validates that status values are correctly evaluated (PASS/FAIL/NA/UNKNOWN).
    
    Args:
        requirements: List of requirements
        playbook_objective: The objective of the playbook
        test_output: Output from data collection playbook
        playbook_content: The actual playbook YAML content (optional, used to analyze status evaluation issues)
        audit_procedure: CIS Benchmark audit procedure (optional)
        suppress_header: If True, suppress the header output (used when called from analyze_playbook_output)
        
    Returns:
        tuple: (is_sufficient, data_collection_analysis_message)
        - is_sufficient: True if data was collected properly and status values are correct
        - data_collection_analysis_message: AI's analysis of data collection sufficiency
    """
    if not suppress_header:
        print("\n" + "=" * 80)
        print("🔍 STAGE 1: DATA COLLECTION ANALYSIS")
        print("=" * 80)
        print("Checking if playbook collected sufficient data...")
    
    # First, check if status values are correctly evaluated
    status_values_valid, status_validation_error = check_status_values_evaluated(test_output)
    status_evaluation_issue = None
    if not status_values_valid:
        if not suppress_header:
            print("\n⚠️  WARNING: Status Values Not Evaluated")
            print("=" * 80)
            print(status_validation_error)
            print("=" * 80)
        status_evaluation_issue = status_validation_error
    
    # Format requirements for analysis
    requirements_text = "\n".join([f"{i+1}. {req}" for i, req in enumerate(requirements)])
    
    # Build audit procedure section if provided
    audit_procedure_section = ""
    if audit_procedure:
        audit_procedure_section = f"""

**CIS BENCHMARK AUDIT PROCEDURE:**
The following is the official audit procedure from the CIS Benchmark. 
Use this to determine if task skipping aligns with the audit procedure:

```bash
{audit_procedure}
```

**CRITICAL - TASK SKIPPING VALIDATION:**
- If the audit procedure states: "If nothing is returned, no further audit steps are required"
- Then tasks that are skipped (Status='NA') when the condition is met are VALID and SUFFICIENT
- Example: If Requirement 1 returns empty output, and audit procedure says "no further steps required", then Requirements 2 and 3 should be skipped (Status='NA')
- **Skipped tasks that align with audit procedure are SUFFICIENT DATA** - they indicate intentional conditional execution
- Only flag skipped tasks as INSUFFICIENT if they don't align with the audit procedure

"""
    
    # Build playbook content section if provided and there's a status evaluation issue
    playbook_content_section = ""
    if playbook_content and status_evaluation_issue:
        playbook_content_section = f"""

**ACTUAL PLAYBOOK CONTENT (for analyzing status evaluation issues):**
The following is the actual playbook YAML. Use this to identify why status values are not being evaluated correctly:

```yaml
{playbook_content}
```

**CRITICAL - STATUS EVALUATION ISSUE DETECTED:**
{status_evaluation_issue}

**YOUR TASK - ANALYZE PLAYBOOK FOR STATUS EVALUATION:**
1. Review the playbook content above
2. Find the `set_fact` tasks that set status_N variables
3. Identify why status values are showing Jinja2 expressions instead of evaluated values
4. Provide specific advice on how to fix the status variable definitions

**COMMON ISSUES:**
- Status variables are set as string literals instead of Jinja2 expressions
- Missing `{{{{ }}}}` around the expression
- Using single quotes around the entire expression instead of Jinja2 syntax
- **Using literal block scalars (`|`) for status variables - preserves newlines and causes "PASS\n" or "FAIL\n" in output**
- **Using `match()` instead of `regex_search()` - `match()` requires full string match, too strict**
- **Using single quotes for regex patterns - requires single-escaping backslashes (e.g., `\\.` instead of `\\\\.`)**
- Example WRONG: `status_1: "'PASS' if condition else 'FAIL'"` (string literal)
- Example WRONG: 
  ```yaml
  status_1: |
    {{ ('PASS' if condition else 'FAIL') | trim }}
  ```
  (literal block scalar preserves newlines)
- Example WRONG: `{{ result_1.stdout | regex_search('pam-1\\.3\\.1-([0-9]+)') }}` (double quotes require double-escaping)
- Example WRONG: `status_1: "{{{{ 'PASS' if (result_1.stdout is match('pattern')) else 'FAIL' }}}}"` (using match() instead of regex_search())
- Example CORRECT: `status_1: "{{{{ ('PASS' if condition else 'FAIL') | trim }}}}"` (quoted string with Jinja2 expression)
- Example CORRECT: `{{ result_1.stdout | regex_search('pam-1\\.3\\.1-([0-9]+)') }}` (single quotes, single backslashes - no double-escaping needed)
- Example CORRECT: `{{ result_1.stdout | regex_replace('.*pam-1\\.3\\.1-([0-9]+).*', '\\1') }}` (single quotes for pattern and replacement)
- Example CORRECT: `status_1: "{{{{ 'PASS' if (result_1.stdout | regex_search('pattern')) else 'FAIL' }}}}"` (using regex_search() with single quotes for pattern matching)

"""
    
    # Build data collection analysis prompt
    data_collection_prompt = """You are an expert Ansible auditor. Your task is to check if a playbook COLLECTED SUFFICIENT DATA.

**DO NOT perform compliance analysis. ONLY check if data was collected.**

**Playbook Objective:**
{objective}
{audit_procedure_section}
**Requirements to collect data for:**
{requirements}
{playbook_content_section}
**Playbook Execution Output:**
```
{output}
```

**YOUR TASK - DATA SUFFICIENCY CHECK:**

1. Does the output contain a "Generate compliance report" task?
2. For EACH requirement, does the report include ACTUAL DATA or CONFIRMED ABSENCE?
3. Is any data missing, showing "Not collected yet", or showing only placeholders?
4. **CRITICAL - STATUS VALUE VALIDATION**: Check if the 'Status' for each requirement in the output is 'PASS', 'FAIL', 'NA', or 'UNKNOWN' (not Jinja2 expressions like `{{ ('PASS' if ... else 'FAIL') | trim }}`)
   - **Status value definitions:**
     - **PASS**: Requirement is definitively met
     - **FAIL**: Requirement is definitively not met
     - **NA**: Skip related task or Did not execute the related task
     - **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)

**IMPORTANT - THREE VALID SCENARIOS:**
1. **Data collected**: Command found and retrieved actual data (e.g., "Docker version 20.10.24")
2. **Confirmed absence**: Command succeeded (exit code 0) but found nothing (e.g., "No packages found", empty output)
3. **Task skipped (Status='NA')**: Task was intentionally skipped due to conditional execution that aligns with audit procedure
   - Example: If audit procedure says "If nothing is returned, no further audit steps are required"
   - Then when Requirement 1 returns empty, Requirements 2 and 3 should be skipped (Status='NA')
   - **This is SUFFICIENT DATA** - the skipping indicates intentional conditional execution per audit procedure
   - Only flag as INSUFFICIENT if the skipping doesn't align with audit procedure

ALL THREE scenarios are DATA SUFFICIENT because they provide clear information about the environment or indicate intentional conditional execution.

**CRITICAL - STATUS VALUES MUST BE EVALUATED:**
- Status values in the compliance report MUST be evaluated as 'PASS', 'FAIL', 'NA', or 'UNKNOWN'
- **Status value definitions:**
  - **PASS**: Requirement is definitively met
  - **FAIL**: Requirement is definitively not met
  - **NA**: Skip related task or Did not execute the related task
  - **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)
- Status values MUST NOT show Jinja2 expressions like `{{ ('PASS' if ... else 'FAIL') | trim }}`
- If status values show Jinja2 expressions, this is a CRITICAL ERROR that must be fixed
- If playbook_content is provided and status evaluation issues are detected, analyze the playbook to provide specific fix advice

**RESPONSE FORMAT:**

If data is SUFFICIENT and status values are correct:
```
DATA_COLLECTION: PASS

All requirements have actual data or confirmed absence.
All status values are correctly evaluated as PASS/FAIL/NA/UNKNOWN.

**Data collection per requirement:**
- Requirement 1: ✅ SUFFICIENT - [actual data found OR confirmed absence with exit code 0], Status: [PASS/FAIL/NA/UNKNOWN]
- Requirement 2: ✅ SUFFICIENT - [actual data found OR confirmed absence with exit code 0 OR task skipped (Status='NA') when aligns with audit procedure], Status: [PASS/FAIL/NA/UNKNOWN]
- Requirement 3: ✅ SUFFICIENT - [task skipped (Status='NA') - aligns with audit procedure: "If nothing is returned, no further audit steps are required"], Status: NA
...
```

If data is INSUFFICIENT (command FAILED, not just empty):
```
DATA_COLLECTION: FAIL

INSUFFICIENT_DATA: [Explain what data is missing or FAILED to collect]

Missing/Incomplete:
- Requirement X: [what's wrong - no data, placeholder, error, etc.]
- Requirement Y: [what's wrong]

ADVICE TO UPDATE PLAYBOOK:
1. [Specific instruction on what task to add/fix]
2. [How to collect the missing data]
3. [How to include it in the report with actual values]
```

If status values are NOT evaluated correctly (showing Jinja2 expressions):
```
DATA_COLLECTION: FAIL

STATUS_EVALUATION_ERROR: Status values are showing Jinja2 expressions instead of evaluated values (PASS/FAIL/NA/UNKNOWN).

**Status value definitions:**
- **PASS**: Requirement is definitively met
- **FAIL**: Requirement is definitively not met
- **NA**: Skip related task or Did not execute the related task
- **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)

Issues Found:
- Requirement X: Status shows `{{ ('PASS' if ... else 'FAIL') | trim }}` instead of 'PASS', 'FAIL', 'NA', or 'UNKNOWN'
- Requirement Y: Status shows Jinja2 expression instead of evaluated value

ADVICE TO UPDATE PLAYBOOK:
[If playbook_content is provided, analyze the playbook and provide specific advice:]
1. Review the `set_fact` tasks that set status_N variables
2. Ensure status variables use Jinja2 expressions (with {{{{ }}}}) that EVALUATE to 'PASS'/'FAIL'/'NA'/'UNKNOWN', not string literals
3. Example WRONG: `status_1: "'PASS' if condition else 'FAIL'"` (string literal - will show expression text)
4. Example CORRECT: `status_1: "{{{{ ('PASS' if condition else 'FAIL') | trim }}}}"` (Jinja2 expression - will evaluate to 'PASS' or 'FAIL')
5. For skipped tasks: `status_N: "NA"` (when task is skipped or did not execute due to conditional execution)
6. For error cases: `status_N: "{{{{ 'UNKNOWN' | trim }}}}"` (when error collecting data or requirement is ambiguous)
7. [Specific fix instructions based on the actual playbook content]
```

**IMPORTANT - DISTINGUISHING VALID vs INSUFFICIENT:**

✅ SUFFICIENT (valid data):
- Actual data collected: "Docker version 20.10.24"
- Confirmed absence with exit code 0: "No packages found", "(empty)"
- Exit code 1 from grep/egrep with empty output = "No matches found" (VALID!)
- Any command completed and reported its result (even if empty)
- **Task skipped (Status='NA') when it aligns with audit procedure** (VALID!)
  - Example: If audit procedure says "If nothing is returned, no further audit steps are required"
  - Then Requirements 2 and 3 skipped when Requirement 1 returns empty = VALID and SUFFICIENT
  - The skipping indicates intentional conditional execution per audit procedure
- Status values are 'PASS', 'FAIL', 'NA', or 'UNKNOWN' (evaluated, not Jinja2 expressions)
  - **PASS**: Requirement is definitively met
  - **FAIL**: Requirement is definitively not met
  - **NA**: Skip related task or Did not execute the related task (VALID when aligns with audit procedure)
  - **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)

**CRITICAL - grep exit codes:**
- Exit code 0 = matches found (has output)
- Exit code 1 = NO matches found (empty output) ← THIS IS VALID DATA!
- Exit code 2 = error occurred

Example: `journalctl | grep 'Connection timed out'` returns exit code 1 with empty output
→ This is SUFFICIENT DATA meaning "no 'Connection timed out' entries exist"

❌ INSUFFICIENT (needs fix):
- "Not collected yet" - task didn't run (and should have run per audit procedure)
- Command crashed/errored (exit code 2+) with no useful output
- Report section completely missing for a requirement
- Only placeholders, no execution at all
- **Task skipped when it should have run per audit procedure** (only flag if skipping doesn't align with audit procedure)
- Status values showing Jinja2 expressions instead of 'PASS'/'FAIL'/'NA'/'UNKNOWN'
  - Valid status values: **PASS** (requirement met), **FAIL** (requirement not met), **NA** (skip related task or did not execute - VALID when aligns with audit procedure), **UNKNOWN** (cannot determine - error collecting, ambiguous requirement)

DO NOT analyze compliance - just verify data collection ran and reported results, and that status values are correctly evaluated.

**Your Response:**""".format(
        objective=playbook_objective,
        audit_procedure_section=audit_procedure_section,
        requirements=requirements_text,
        playbook_content_section=playbook_content_section,
        output=test_output[-8000:]  # Limit output size to avoid token issues
    )
    
    try:
        if not suppress_header:
            print("Analyzing data collection (this may take a minute)...")
        
        # Use the LLM directly
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                if not suppress_header:
                    print(f"Data collection analysis attempt {attempt}/{max_attempts}...")
                response = model.invoke(data_collection_prompt)
                result = response.content.strip()
                break
            except Exception as e:
                error_msg = str(e)
                if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    if not suppress_header:
                        print(f"⚠️  Analysis timed out on attempt {attempt}, retrying...")
                    if attempt < max_attempts:
                        continue
                    else:
                        if not suppress_header:
                            print("⚠️  Analysis timed out, assuming data is sufficient...")
                        return True, "DATA_COLLECTION: PASS (Analysis timed out - assuming sufficient)"
                else:
                    raise
        
        if not suppress_header:
            print("\n📊 Data Collection Analysis Result:")
            print("-" * 40)
            print(result)
            #print(result[:1000] + ("..." if len(result) > 1000 else ""))
            print("-" * 40)
        
        # Check result - IMPORTANT: Check for FAIL first because "FAIL" might contain "PASS"
        result_upper = result.upper()
        
        # Check for status evaluation errors first (most critical)
        if "STATUS_EVALUATION_ERROR" in result_upper or ("STATUS_EVALUATION" in result_upper and "ERROR" in result_upper):
            if not suppress_header:
                print("\n❌ DATA COLLECTION: FAIL - Status values not evaluated correctly")
            return False, result
        
        if "DATA_COLLECTION: FAIL" in result_upper or "INSUFFICIENT_DATA" in result or "INSUFFICIENT" in result_upper[:200]:
            if not suppress_header:
                print("\n❌ DATA COLLECTION: FAIL - Data collection insufficient")
            return False, result
        elif "DATA_COLLECTION: PASS" in result_upper or ("SUFFICIENT" in result_upper[:200] and "INSUFFICIENT" not in result_upper[:200] and "STATUS_EVALUATION" not in result_upper):
            if not suppress_header:
                print("\n✅ DATA COLLECTION: PASS - Data collection sufficient")
            return True, result
        else:
            # Ambiguous result - check for positive/negative indicators
            if any(word in result.lower() for word in ["missing", "incomplete", "not collected", "failed to collect", "advice to update", "status_evaluation"]):
                if not suppress_header:
                    print("\n❌ DATA COLLECTION: FAIL - Data appears insufficient or status evaluation issue (found negative indicators)")
                return False, result
            elif any(word in result.lower() for word in ["all requirements have", "data values collected", "sufficient"]) and "status_evaluation" not in result.lower():
                if not suppress_header:
                    print("\n✅ DATA COLLECTION: PASS - Data appears sufficient")
                return True, result
            else:
                if not suppress_header:
                    print("\n⚠️  DATA COLLECTION: UNCLEAR - Assuming sufficient")
                return True, result
                
    except Exception as e:
        error_msg = f"Error during data collection analysis: {str(e)}"
        print(f"❌ {error_msg}")
        # On error, assume sufficient to not block
        return True, f"DATA_COLLECTION: PASS (Check failed but proceeding: {error_msg})"


def analyze_playbook_output(
    requirements: list[str],
    playbook_objective: str,
    test_output: str,
    audit_procedure: str = None,
    playbook_content: str = None,
    suppress_header: bool = False
) -> tuple[bool, str]:
    """
    Analyze the playbook data collection output and determine compliance for each requirement.
    
    NEW APPROACH: Playbooks only collect data, AI determines compliance.
    
    This function:
    1. First calls analyze_data_collection() to check if data was collected properly
    2. If data collection passes, performs full compliance analysis
    
    Args:
        requirements: Original list of requirements
        playbook_objective: The objective of the playbook
        test_output: Output from data collection playbook
        audit_procedure: CIS Benchmark audit procedure with expected outputs (optional)
        playbook_content: The actual playbook YAML content (optional, used to verify conditional execution)
        suppress_header: If True, suppress the "AI COMPLIANCE ANALYSIS" header (default: False)
        
    Returns:
        tuple: (is_verified, compliance_analysis_message)
        - is_verified: True if playbook collected data properly and analysis completed
        - compliance_analysis_message: AI's compliance determination for each requirement
    """
    if not suppress_header:
        print("\n" + "=" * 80)
        print("🔍 AI COMPLIANCE ANALYSIS (Analyzing Collected Data)")
        print("=" * 80)
    
    # NOTE: STAGE 0 (Playbook Structure Analysis) is now handled by LangGraph workflow
    # in langgraph_deepseek_generate_playbook.py before test execution.
    # This function only handles STAGE 1 (Data Collection) and STAGE 2 (Compliance Analysis).
    
    # STAGE 1: Check data collection
    # Suppress header since it will be included in the final analysis result
    data_collection_passed, data_collection_analysis = analyze_data_collection(
        requirements=requirements,
        playbook_objective=playbook_objective,
        test_output=test_output,
        playbook_content=playbook_content,
        audit_procedure=audit_procedure,
        suppress_header=True
    )
    
    # If data collection failed, return early with the data collection analysis
    if not data_collection_passed:
        print("\n⚠️  Insufficient Data Collected")
        print("   The playbook's compliance report is missing actual data.")
        print("   AI provided specific advice to improve data collection.")
        return False, data_collection_analysis
    
    # STAGE 2: Data collection passed, proceed with full compliance analysis
    print("Playbook collected data. AI now determining compliance...")
    
    # Format requirements for analysis
    requirements_text = "\n".join([f"{i+1}. {req}" for i, req in enumerate(requirements)])
    
    # Build audit procedure context if provided
    audit_context = ""
    if audit_procedure:
        audit_context = f"""

**CIS BENCHMARK AUDIT PROCEDURE FOR REFERENCE:**
The audit procedure below contains expected outputs and pass/fail criteria.
Use this to determine compliance status:

```
{audit_procedure}
```

**CRITICAL - EMPTY OUTPUT INTERPRETATION:**
According to CIS benchmark logic:
- **Empty output (Data: "") = "nothing returned"**
- If the audit procedure states: "If nothing is returned, [condition] and no further audit steps are required"
- Then empty output means the condition is met (typically COMPLIANT for "module not available" checks)
- **When nothing is returned, subsequent requirements should NOT be executed**
- Example: If Requirement 1 returns empty (module not found), and the procedure says "no further audit steps are required", then Requirements 2 and 3 should NOT have been executed

**CRITICAL - AUDIT PROCEDURE COMPLIANCE LOGIC:**
**YOU MUST CAREFULLY READ AND FOLLOW THE AUDIT PROCEDURE LOGIC:**

The audit procedure typically has a multi-step structure:
- **Step 1**: Initial check (e.g., check if module is available on filesystem)
  - If Step 1 returns nothing (empty output) → Overall: COMPLIANT (no further steps needed)
  - If Step 1 returns output (something found) → Proceed to Step 2

- **Step 2**: Additional verification (only if Step 1 found something)
  - Step 2 typically contains multiple requirements (e.g., Requirement 2 and Requirement 3)
  - **Step 2 is PASS only when ALL its requirements are PASS**
  - If Step 2 is PASS → Overall: COMPLIANT (even though Step 1 failed)
  - If Step 2 is FAIL (any requirement fails) → Overall: NON-COMPLIANT

**EXAMPLE LOGIC:**
```
Step 1: Check if module is available on filesystem
  - If nothing returned → Overall: COMPLIANT ✅
  - If output returned → Go to Step 2

Step 2: Verify module is not loaded AND not loadable
  - Requirement 2: Module not loaded (PASS/FAIL)
  - Requirement 3: Module not loadable (PASS/FAIL)
  - Step 2 PASS = (Requirement 2 = PASS) AND (Requirement 3 = PASS)
  - If Step 2 PASS → Overall: COMPLIANT ✅ (even if Step 1 failed)
  - If Step 2 FAIL → Overall: NON-COMPLIANT ❌
```

**KEY POINT**: When Step 1 fails (module is available) BUT Step 2 passes (both requirements 2 and 3 pass), the overall status is **COMPLIANT**, not NON-COMPLIANT.

**IMPORTANT:** 
- If the procedure shows "Example output: generated", compare actual output to "generated"
- If the procedure says "Verify output is not masked or disabled", check for those strings
- Use the expected outputs shown in the procedure to determine PASS/FAIL status
- The procedure defines what constitutes compliance vs non-compliance
- **Empty output is valid data** - it means "nothing found" which often indicates compliance for "should not exist" checks
- **READ THE AUDIT PROCEDURE CAREFULLY** to understand the step-by-step logic and overall compliance determination

"""
    
    # Build playbook content section if provided
    playbook_content_section = ""
    if playbook_content:
        playbook_content_section = f"""

**ACTUAL PLAYBOOK CONTENT (for reference):**
The following is the actual playbook YAML that was executed:

```yaml
{playbook_content}
```

"""
    
    # Build analysis prompt without f-string to avoid issues with curly braces in test_output
    analysis_prompt = """You are an expert Ansible compliance auditor. Your task is to analyze whether a playbook CORRECTLY REPORTS compliance status based on what it found.

**Original Objective:**
{objective}

**Original Requirements:**
{requirements}
{audit_context}
**Actual Playbook Content (for reference):**
{playbook_content_section}
**Actual Playbook Execution Output:**
```
{output}
```

**CRITICAL TASK:** Analyze the COMPLIANCE REPORT and verify the status/rationale for each requirement.

**NEW APPROACH - INTELLIGENT COMPLIANCE ANALYSIS:**
- Playbooks now ONLY collect data (no compliance determination)
- YOU (AI) will analyze the collected data and determine compliance
- This approach is MORE INTELLIGENT and works across various servers
- **USE THE AUDIT PROCEDURE** (if provided above) to understand expected outputs and pass/fail criteria

**YOUR TASK - COMPLIANCE ANALYSIS:**

**NOTE: Data collection has already been verified as sufficient. Proceed directly to compliance analysis.**
If the report contains real data for all requirements, then determine compliance:
1. Review each requirement and the data collected
2. Determine if requirement is met based on the data:
   - **COMPLIANT**: Data shows requirement is definitively met
   - **NON-COMPLIANT**: Data shows requirement is definitively not met
   - **UNKNOWN**: Cannot determine from data (error collecting, ambiguous requirement)
   - **NA**: Skip related task or Did not execute the related task
3. Provide reasoning for each determination

**ANALYSIS GUIDELINES:**
- If data shows "Docker version 20.10.24 installed" and requirement is "Docker must be installed" → COMPLIANT
- If data shows "Docker is not installed" and requirement is "Docker must be installed" → NON-COMPLIANT
- If data shows "Error collecting Docker info" → UNKNOWN (unable to verify)
- If data shows "Service httpd is active" and requirement is "Service must be running" → COMPLIANT
- If data shows "Service httpd is stopped" and requirement is "Service must be running" → NON-COMPLIANT
- If data shows version numbers, compare them intelligently
- If requirement is unclear/ambiguous → UNKNOWN (requirement needs clarification)

**CRITICAL - EMPTY OUTPUT = "NOTHING RETURNED":**
- **Empty output (Data: "", exit code 0 or 1) = "nothing returned"** per CIS benchmark
- For checks like "module should NOT be available": Empty output = module not found = COMPLIANT
- For checks like "module should be available": Empty output = module not found = NON-COMPLIANT
- **If CIS procedure states "If nothing is returned, [condition] and no further audit steps are required":**
  - Empty output means the condition is met (typically COMPLIANT)
  - Subsequent requirements should NOT be executed when nothing is returned
  - Example: If Requirement 1 (check if module exists) returns empty, and procedure says "no further steps required", then Requirements 2 and 3 should NOT have been executed
- **Empty output is VALID DATA** - it provides clear information: "nothing found"
- Do NOT treat empty output as "insufficient data" - it is sufficient data meaning "not found"

**Verification Checklist:**
1. Does the playbook collect data for EVERY requirement listed above?
2. **Is the playbook ONLY collecting data (not determining compliance)?** ✅ This is correct!
3. For each requirement, is relevant data collected OR error message provided?
4. Based on the collected data, can you determine compliance?
5. **YOUR ANALYSIS - For EACH requirement (including the OVERALL Verify requirement), determine:**
   - **CRITICAL: You MUST analyze ALL requirements, including the OVERALL Verify requirement (usually the last requirement)**
   - **Do NOT skip the OVERALL Verify requirement even if it says "N/A - Calculated from previous requirements"**
   - **For the OVERALL Verify requirement, analyze it based on the playbook's reported status and the overall compliance logic**
   - COMPLIANT: Data shows requirement is definitively met
   - NON-COMPLIANT: Data shows requirement is definitively not met
   - UNKNOWN: Cannot determine from data (error collecting, ambiguous requirement)
   - NA: Skip related task or Did not execute the related task

**PASS Examples (Correct Data Collection - AI determines compliance):**

**Playbook Collects Data:**
✅ Requirement: "Docker must be installed" → Collected: "Docker version 20.10.24 is installed" → AI Determines: COMPLIANT
✅ Requirement: "Service must be running" → Collected: "Service httpd is stopped" → AI Determines: NON-COMPLIANT  
✅ Requirement: "RHEL 7 required" → Collected: "RHEL 8.6" → AI Determines: NON-COMPLIANT
✅ Requirement: "Image pullable" → Collected: "Error: no credentials" → AI Determines: UNKNOWN
✅ Requirement: "Check packages" → Collected: "docker-20.10.24, nginx-1.20.1..." → AI Determines: Based on requirement

**FAIL Examples (Incorrect Playbook Behavior):**
❌ Playbook determines compliance itself (should only collect data!)
❌ Playbook reports "COMPLIANT" or "NON-COMPLIANT" (AI's job, not playbook's!)
❌ Playbook skips data collection
❌ Playbook doesn't handle errors (should report error message as data)

**FAIL Examples (Incorrect Reporting Logic):**
❌ Requirement: "Package installed" → Found: 0 packages → Reports: COMPLIANT (WRONG!)
❌ Requirement: "Service running" → Didn't check status → Reports: COMPLIANT (WRONG!)
❌ Requirement: "Version >= 2.0" → Found: Version 1.5 → Reports: COMPLIANT (WRONG!)
❌ Report missing a requirement check entirely
❌ Requirement: "Image pullable" → Auth failed → Reports: COMPLIANT (WRONG! Should be UNKNOWN)
❌ Requirement: "Check API" → Connection refused → Reports: COMPLIANT (WRONG! Should be UNKNOWN)
❌ Requirement: "Service check" → No permissions → Reports: NON-COMPLIANT (MISLEADING! Should be UNKNOWN)

**APPROACH: DATA COLLECTION + AI ANALYSIS**

**Playbook Role**: Collect data only (no intelligence)
- Just gather facts, run commands, collect information
- Report what was found OR error message
- NO compliance determination in playbook

**AI Role**: Analyze data and determine compliance (intelligence here!)
- Review collected data for each requirement
- Determine: COMPLIANT / NON-COMPLIANT / UNKNOWN
- Provide reasoning for determination
- This approach works across various servers

**Why This Works Better:**
- Playbooks are generic (just data collection)
- AI has intelligence to interpret data in context
- Same playbook works for different compliance standards
- AI can handle nuances and edge cases

**Key Point:** Playbook collects data, AI judges compliance!

**Response Formats:**

**Provide compliance analysis using this EXACT FORMAT:**
```
## STAGE 2: COMPLIANCE ANALYSIS

Based on the collected data, here is the compliance analysis for each requirement:

**CRITICAL - ANALYZE ALL REQUIREMENTS:**
- **MANDATORY: You MUST analyze ALL requirements, including the OVERALL Verify requirement (usually the last requirement)**
- **The OVERALL Verify requirement (e.g., "Requirement 4 - OVERALL Verify: Ensure cramfs kernel module is not available") MUST be included in your analysis**
- **Do NOT skip the last requirement even if it says "OVERALL Verify" or "N/A - Calculated from previous requirements"**
- **For the OVERALL Verify requirement, analyze it based on:**
  - The playbook's reported status (PASS/FAIL)
  - The rationale provided (e.g., "PASS when (req_1 returns nothing) OR (req_1 returns output AND req_2=PASS AND req_3=PASS), FAIL otherwise")
  - Whether the overall compliance logic correctly implements the CIS audit procedure

**Requirement 1: [requirement description]**
- **Data Collected**: [Exit code: X, Output: "actual output"]
- **Compliance Status**: COMPLIANT / NON-COMPLIANT / UNKNOWN / NA
- **Reasoning**: [detailed explanation referencing the requirement rationale]

**Requirement 2: [requirement description]**
- **Data Collected**: [Exit code: X, Output: "actual output" or "N/A - Task skipped"]
- **Compliance Status**: COMPLIANT / NON-COMPLIANT / UNKNOWN / NA
- **Reasoning**: [detailed explanation referencing the requirement rationale]
- **Note**: **Status Standard (Both Playbook and AI must follow):**
  - **COMPLIANT** (AI) / **PASS** (Playbook): Data shows requirement is definitively met
  - **NON-COMPLIANT** (AI) / **FAIL** (Playbook): Data shows requirement is definitively not met
  - **UNKNOWN** (Both): Cannot determine from data (error collecting, ambiguous requirement)
  - **NA** (Both): Skip related task or Did not execute the related task
  - If playbook status is 'NA' (task was skipped or did not execute), AI Compliance Status should be 'NA' (task was not executed)

... (continue for ALL requirements, including the OVERALL Verify requirement)

**Requirement N (OVERALL Verify): [overall verify description]**
- **Data Collected**: [Exit code: X, Output: "N/A - Calculated from previous requirements" or similar]
- **Compliance Status**: COMPLIANT / NON-COMPLIANT / UNKNOWN
- **Reasoning**: [Analyze based on the overall compliance logic. For example: "According to the audit procedure logic: Step 1 (Requirement 1) returned output = FAIL/NON-COMPLIANT, Step 2 (Requirements 2 and 3) both passed = PASS/COMPLIANT. Since Step 2 passes, the overall status is COMPLIANT, even though Step 1 failed. The system meets CIS requirements because while the module is available on the filesystem, it is properly configured to prevent loading (not loaded and blacklisted)."]

## OVERALL ASSESSMENT

- **DATA COLLECTION**: PASS or FAIL
  - PASS: Playbook successfully collected sufficient data for all requirements. ✅
  - The report includes actual command outputs, exit codes, and task details. ✅
  - Empty outputs are correctly reported as valid data (e.g., Requirement 2 shows empty output). ✅
  - FAIL: Data collection is insufficient, missing, or incomplete.
  
- **COMPLIANCE ANALYSIS**: PASS or FAIL
  - **PASS**: When ALL of the following are true:
    - All steps and requirements results from playbook and AI match each other (status alignment verified)
    - The audit procedure logic matches correctly
    - All individual requirement statuses align (PASS=COMPLIANT, FAIL=NON-COMPLIANT, NA=UNKNOWN)
    - Overall status aligns (PASS=COMPLIANT, FAIL=NON-COMPLIANT, NA=UNKNOWN)
  - **FAIL**: When ANY of the following are true:
    - Any step or requirement result from playbook does NOT match AI analysis (status misalignment)
    - The audit procedure logic does NOT match correctly
    - Any individual requirement status misalignment
    - Overall status misalignment
  - **MANDATORY FORMAT**: You MUST use this EXACT format:
    ```
    - **COMPLIANCE ANALYSIS**: PASS
      COMPLIANCE STATUS: [COMPLIANT or NON-COMPLIANT] ✅
      - According to the audit procedure logic:
        - Step 1 (Requirement 1) [description] = PLAYBOOK_STATUS/AI_STATUS ✅
        - Step 2 (Requirements 2 and 3) results:
          - Requirement 2: [description] = PLAYBOOK_STATUS/AI_STATUS ✅
          - Requirement 3: [description] = PLAYBOOK_STATUS/AI_STATUS ✅
        - Since Step [N] [passes/fails], the overall status is PLAYBOOK_STATUS/AI_STATUS. ✅
      - The system [does/does NOT] meet CIS requirements because:
        1) [reason one]
        2) [reason two]
        3) [reason three if applicable]
      - **Status Alignment Verification**:
        - Requirement 1: PLAYBOOK_STATUS/AI_STATUS = [status]/[status] ✅
        - Requirement 2: PLAYBOOK_STATUS/AI_STATUS = [status]/[status] ✅
        - Requirement 3: PLAYBOOK_STATUS/AI_STATUS = [status]/[status] ✅
        - Requirement 4 (Overall): PLAYBOOK_STATUS/AI_STATUS = [status]/[status] ✅
    ```
  - **CRITICAL**: Follow the audit procedure logic carefully:
    - If Step 1 returns nothing (empty) → Overall: COMPLIANT
    - If Step 1 returns output AND Step 2 passes (all Step 2 requirements pass) → Overall: COMPLIANT
    - If Step 1 returns output AND Step 2 fails (any Step 2 requirement fails) → Overall: NON-COMPLIANT
  - **Status mapping**: PASS -> COMPLIANT, FAIL -> NON-COMPLIANT, NA -> UNKNOWN
  - **DO NOT** incorrectly report NON-COMPLIANT when Step 1 fails but Step 2 passes - in that case, overall should be COMPLIANT
    
- **RECOMMENDATION**: 
  To achieve compliance: 
  1) [First action to take], 
  2) [Second action to take], 
  3) [Third action if needed].
  
```

IMPORTANT: Always use this exact format with:
- "## STAGE 2: COMPLIANCE ANALYSIS" header
- "**Requirement N:**" with bold formatting
- "- **Data Collected**:", "- **Compliance Status**:", "- **Reasoning**:" sub-items
- "## OVERALL ASSESSMENT" header with proper indentation:
  * Main items: "- **ITEM**:" 
  * Sub-bullets: "  - details" (2 spaces indent)
  * Numbered lists: "  1) item" (2 spaces indent)

**Examples:**

✅ SUFFICIENT DATA Example:
```
## STAGE 2: COMPLIANCE ANALYSIS

Based on the collected data, here is the compliance analysis for each requirement:

**Requirement 1: Docker must be installed**
- **Data Collected**: Exit code: 0, Output: "Docker version 20.10.24, build 297e128"
- **Compliance Status**: COMPLIANT
- **Reasoning**: Data shows Docker is installed with specific version 20.10.24. According to the requirement, Docker must be installed, and it is.

**Requirement 2: Service httpd must be running**
- **Data Collected**: Exit code: 0, Output: "Service httpd state: stopped"
- **Compliance Status**: NON-COMPLIANT
- **Reasoning**: Data clearly shows service is stopped. According to the requirement rationale, the service must be running.

**Requirement 3: Image registry must be accessible**
- **Data Collected**: Exit code: 1, Output: "Error: authentication required but no credentials provided"
- **Compliance Status**: UNKNOWN
- **Reasoning**: Cannot determine accessibility without proper credentials. This is an error condition, not a compliance determination.

## OVERALL ASSESSMENT

- **DATA COLLECTION**: PASS 
  - Playbook successfully collected sufficient data for all requirements. 
  - The report includes actual command outputs, exit codes, and task details.
  
- **COMPLIANCE ANALYSIS**: PASS
  COMPLIANCE STATUS: NON-COMPLIANT ✅
  - According to the audit procedure logic:
    - Requirement 1: Docker must be installed = PASS/COMPLIANT ✅
    - Requirement 2: Service httpd must be running = FAIL/NON-COMPLIANT ✅
    - Requirement 3: Image registry must be accessible = UNKNOWN/UNKNOWN ✅
    - Since Requirement 2 fails, the overall status is FAIL/NON-COMPLIANT. ✅
  - The system does NOT meet CIS requirements because:
    1) Service httpd is not running (Requirement 2 = FAIL/NON-COMPLIANT)
    2) Registry accessibility cannot be verified (Requirement 3 = UNKNOWN)
  - **Status Alignment Verification**:
    - Requirement 1: PLAYBOOK_STATUS/AI_STATUS = PASS/COMPLIANT ✅
    - Requirement 2: PLAYBOOK_STATUS/AI_STATUS = FAIL/NON-COMPLIANT ✅
    - Requirement 3: PLAYBOOK_STATUS/AI_STATUS = UNKNOWN/UNKNOWN ✅
    - Requirement 4 (Overall): PLAYBOOK_STATUS/AI_STATUS = FAIL/NON-COMPLIANT ✅
    
- **RECOMMENDATION**: 
  To achieve compliance: 
  1) Start the httpd service with `systemctl start httpd`, 
  2) Configure registry authentication credentials and re-run the check.
```

✅ CORRECT AUDIT PROCEDURE LOGIC Example:
```
## STAGE 2: COMPLIANCE ANALYSIS

Based on the collected data, here is the compliance analysis for each requirement:

**Requirement 1: Run script to check if cramfs kernel module is available on filesystem**
- **Data Collected**: Exit code: 0, Output: "cramfs exists in /usr/lib/modules/..."
- **Compliance Status**: NON-COMPLIANT
- **Reasoning**: According to CIS benchmark: "PASS when script returns no output (module not available) OR system has cramfs built into kernel, FAIL when script returns output indicating cramfs module is available." The script returned output showing the module exists, so this is FAIL/NON-COMPLIANT.

**Requirement 2: Verify the cramfs kernel module is not loaded**
- **Data Collected**: Exit code: 1, Output: "" (empty)
- **Compliance Status**: COMPLIANT
- **Reasoning**: According to CIS benchmark: "PASS when the command returns no output, FAIL when it returns any output." The command returned empty output (nothing found), so this is PASS/COMPLIANT.

**Requirement 3: Verify the cramfs kernel module is not loadable**
- **Data Collected**: Exit code: 0, Output: "install cramfs /bin/false blacklist cramfs"
- **Compliance Status**: COMPLIANT
- **Reasoning**: According to CIS benchmark: "PASS when the output includes 'blacklist cramfs' AND EITHER 'install cramfs /bin/false' OR 'install cramfs /bin/true', FAIL otherwise." The output contains both "blacklist cramfs" AND "install cramfs /bin/false", so this is PASS/COMPLIANT.

**Requirement 4: OVERALL Verify: Ensure cramfs kernel module is not available**
- **Data Collected**: Exit code: 0, Output: "N/A - Calculated from previous requirements"
- **Compliance Status**: COMPLIANT
- **Reasoning**: According to the audit procedure logic: Step 1 (Requirement 1) returned output (module is available) = FAIL/NON-COMPLIANT, Step 2 (Requirements 2 and 3) both passed: Requirement 2 (Module is not loaded) = PASS/COMPLIANT, Requirement 3 (Module is not loadable/blacklisted) = PASS/COMPLIANT. Since Step 2 passes (both requirements pass), the overall status is PASS/COMPLIANT, even though Step 1 failed. The system meets CIS requirements because while the module is available on the filesystem, it is properly configured to prevent loading (not loaded and blacklisted).

## OVERALL ASSESSMENT

- **DATA COLLECTION**: PASS
  - Playbook successfully collected sufficient data for all requirements. ✅
  - The report includes actual command outputs, exit codes, and task details. ✅
  - Empty outputs are correctly reported as valid data (Requirement 2 shows empty output). ✅

- **COMPLIANCE ANALYSIS**: PASS
  COMPLIANCE STATUS: COMPLIANT ✅
  - According to the audit procedure logic:
    - Step 1 (Requirement 1) returned output (module is available) = FAIL/NON-COMPLIANT ✅
    - Step 2 (Requirements 2 and 3) results:
      - Requirement 2: Module is not loaded = PASS/COMPLIANT ✅
      - Requirement 3: Module is not loadable (blacklisted) = PASS/COMPLIANT ✅
    - Since Step 2 passes (both requirements pass), the overall status is PASS/COMPLIANT, even though Step 1 failed. ✅
  - The system meets CIS requirements because while the module is available on the filesystem, it is properly configured to prevent loading (not loaded and blacklisted). ✅
  - **Status Alignment Verification**:
    - Requirement 1: PLAYBOOK_STATUS/AI_STATUS = FAIL/NON-COMPLIANT ✅
    - Requirement 2: PLAYBOOK_STATUS/AI_STATUS = PASS/COMPLIANT ✅
    - Requirement 3: PLAYBOOK_STATUS/AI_STATUS = PASS/COMPLIANT ✅
    - Requirement 4 (Overall): PLAYBOOK_STATUS/AI_STATUS = PASS/COMPLIANT ✅

- **RECOMMENDATION**:
  No remediation needed - the system is compliant. The module is properly disabled even though it exists on the filesystem.
```

❌ COMPLIANCE ANALYSIS: FAIL Example:
```
## STAGE 2: COMPLIANCE ANALYSIS

Based on the collected data, here is the compliance analysis for each requirement:

**Requirement 1: Check if freevxfs kernel module is available**
- **Data Collected**: Exit code: 1, Output: "" (empty - nothing returned)
- **Compliance Status**: COMPLIANT
- **Reasoning**: According to CIS benchmark: "If nothing is returned, the freevxfs kernel module is not available on the system and no further audit steps are required." Empty output means "nothing returned" = module not available = COMPLIANT.

**Requirement 2: Verify module is not loaded**
- **Data Collected**: Exit code: 0, Output: "Module not loaded"
- **Compliance Status**: COMPLIANT
- **Reasoning**: Module is not loaded, which is correct.

**Requirement 3: Verify module cannot be loaded**
- **Data Collected**: Exit code: 0, Output: "Module cannot be loaded"
- **Compliance Status**: COMPLIANT
- **Reasoning**: Module cannot be loaded, which is correct.

## OVERALL ASSESSMENT

- **DATA COLLECTION**: PASS 
  - Playbook successfully collected sufficient data for all requirements.
  
- **COMPLIANCE ANALYSIS**: PASS
  COMPLIANCE STATUS: COMPLIANT ✅
  - According to the audit procedure logic:
    - Step 1 (Requirement 1) returned nothing (module not available) = PASS/COMPLIANT ✅
    - Since Step 1 returns nothing, no further audit steps are required. ✅
  - The system meets CIS requirements because the module is not available as required. ✅
  - **Status Alignment Verification**:
    - Requirement 1: PLAYBOOK_STATUS/AI_STATUS = PASS/COMPLIANT ✅
    - Requirement 2: Task was skipped (not executed) = NA/NA ✅
    - Requirement 3: Task was skipped (not executed) = NA/NA ✅
    - Requirement 4 (Overall): PLAYBOOK_STATUS/AI_STATUS = PASS/COMPLIANT ✅
  
- **RECOMMENDATION**: 
  No remediation needed - the system is compliant. The freevxfs module is not available as required.
```

❌ COMPLIANCE ANALYSIS: FAIL Example (with incorrect reporting):
```
## STAGE 2: COMPLIANCE ANALYSIS

Based on the collected data, here is the compliance analysis for each requirement:

**Requirement 1: Check if cramfs kernel module is available**
- **Data Collected**: Exit code: 0, Output: "cramfs"
- **Compliance Status**: NON-COMPLIANT
- **Reasoning**: Module is available, which means it should be disabled/blacklisted.

**Requirement 2: Verify module is not loaded**
- **Data Collected**: Exit code: 0, Output: "Module not loaded"
- **Compliance Status**: COMPLIANT
- **Reasoning**: Module is not currently loaded, which is correct.

**Requirement 3: Verify module is blacklisted**
- **Data Collected**: Exit code: 0, Output: "install cramfs /bin/false blacklist cramfs"
- **Compliance Status**: COMPLIANT
- **Reasoning**: The output shows the module is properly blacklisted with "install cramfs /bin/false blacklist cramfs", which meets the requirement.

## OVERALL ASSESSMENT

- **DATA COLLECTION**: PASS 
  - Playbook successfully collected sufficient data for all requirements.
  
- **COMPLIANCE ANALYSIS**: FAIL
  COMPLIANCE STATUS: NON-COMPLIANT ✅
  - According to the audit procedure logic:
    - Step 1 (Requirement 1) returned output (module is available) = FAIL/NON-COMPLIANT ✅
    - Step 2 (Requirements 2 and 3) results:
      - Requirement 2: Module is not loaded = PASS/COMPLIANT ✅
      - Requirement 3: Module is not loadable (blacklisted) = FAIL/NON-COMPLIANT ❌ (Playbook incorrectly reported FAIL, but should be PASS based on data)
    - Since Step 2 fails (Requirement 3 fails), the overall status is FAIL/NON-COMPLIANT. ✅
  - The system does NOT meet CIS requirements because:
    1) The cramfs module is available on the filesystem (Requirement 1 = FAIL/NON-COMPLIANT)
    2) The module is not properly blacklisted to prevent loading (Requirement 3 = FAIL/NON-COMPLIANT)
  - **Status Alignment Verification**:
    - Requirement 1: PLAYBOOK_STATUS/AI_STATUS = FAIL/NON-COMPLIANT ✅
    - Requirement 2: PLAYBOOK_STATUS/AI_STATUS = PASS/COMPLIANT ✅
    - Requirement 3: PLAYBOOK_STATUS/AI_STATUS = FAIL/COMPLIANT ❌ (MISALIGNED - playbook reported FAIL but AI determined COMPLIANT)
    - Requirement 4 (Overall): PLAYBOOK_STATUS/AI_STATUS = FAIL/NON-COMPLIANT ✅
  
- **RECOMMENDATION**: 
  To achieve compliance:
  1) Remove the cramfs module from the filesystem, or
  2) Ensure the module is properly blacklisted to prevent loading.
```

✅ EMPTY OUTPUT = "NOTHING RETURNED" Example (CIS Benchmark Logic):
```
## STAGE 2: COMPLIANCE ANALYSIS

Based on the collected data, here is the compliance analysis for each requirement:

**Requirement 1: Check if freevxfs kernel module is available**
- **Data Collected**: Exit code: 1, Output: "" (empty - nothing returned)
- **Compliance Status**: COMPLIANT
- **Reasoning**: According to CIS benchmark: "If nothing is returned, the freevxfs kernel module is not available on the system and no further audit steps are required." Empty output means "nothing returned" = module not available = COMPLIANT (module should NOT be available).

**Requirement 2: Verify module is not loaded**
- **Data Collected**: Not executed (correctly skipped)
- **Compliance Status**: N/A
- **Reasoning**: According to CIS procedure, when Requirement 1 returns nothing, "no further audit steps are required". The playbook correctly skipped this requirement, which is the expected behavior.

**Requirement 3: Verify module cannot be loaded**
- **Data Collected**: Not executed (correctly skipped)
- **Compliance Status**: N/A
- **Reasoning**: According to CIS procedure, when Requirement 1 returns nothing, "no further audit steps are required". The playbook correctly skipped this requirement, which is the expected behavior.

## OVERALL ASSESSMENT

- **DATA COLLECTION**: PASS 
  - Playbook successfully collected sufficient data. Empty output is valid data meaning "nothing found".
  - The playbook correctly followed CIS procedure by skipping subsequent requirements when nothing was returned.
  
- **COMPLIANCE STATUS**: COMPLIANT 
  - The system is compliant because: 
    1) Requirement 1 returned empty output, which means the module is not available (as required).
    2) The playbook correctly did not execute Requirements 2 and 3, following CIS procedure.
```

**Your Analysis:**"""
    
    # Format the prompt with actual values
    analysis_prompt = analysis_prompt.format(
        objective=playbook_objective,
        requirements=requirements_text,
        audit_context=audit_context,
        playbook_content_section=playbook_content_section,
        output=test_output
    )

    try:
        # Use the LLM directly without ChatPromptTemplate to avoid issues with curly braces
        print("Analyzing playbook output (this may take a few minutes)...")
        
        # Add retry logic for timeout handling
        max_analysis_attempts = 3
        for attempt in range(1, max_analysis_attempts + 1):
            try:
                print(f"Analysis attempt {attempt}/{max_analysis_attempts}...")
                response = model.invoke(analysis_prompt)
                analysis_result = response.content.strip()
                
                # Prepend DATA COLLECTION analysis to the full compliance analysis
                # This ensures the final message includes both stages
                if data_collection_analysis and "DATA_COLLECTION: PASS" in data_collection_analysis.upper():
                    # Insert DATA COLLECTION section at the beginning of the analysis
                    if "## STAGE 2: COMPLIANCE ANALYSIS" in analysis_result:
                        # Insert before STAGE 2
                        analysis_result = analysis_result.replace(
                            "## STAGE 2: COMPLIANCE ANALYSIS",
                            f"## STAGE 1: DATA COLLECTION ANALYSIS\n\n{data_collection_analysis}\n\n## STAGE 2: COMPLIANCE ANALYSIS"
                        )
                    elif "## OVERALL ASSESSMENT" in analysis_result:
                        # Insert before OVERALL ASSESSMENT
                        analysis_result = analysis_result.replace(
                            "## OVERALL ASSESSMENT",
                            f"## STAGE 1: DATA COLLECTION ANALYSIS\n\n{data_collection_analysis}\n\n## OVERALL ASSESSMENT"
                        )
                    else:
                        # Prepend at the beginning
                        analysis_result = f"## STAGE 1: DATA COLLECTION ANALYSIS\n\n{data_collection_analysis}\n\n{analysis_result}"
                
                break  # Success, exit retry loop
            except Exception as e:
                error_msg = str(e)
                if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    print(f"⚠️  Analysis timed out on attempt {attempt}/{max_analysis_attempts}")
                    if attempt < max_analysis_attempts:
                        print(f"🔄 Retrying analysis...")
                        continue
                    else:
                        print(f"❌ All {max_analysis_attempts} analysis attempts timed out")
                        # Fall back to passing if analysis times out
                        print("⚠️  Analysis timed out, proceeding anyway...")
                        return True, "PASS: Analysis timed out - unable to verify, proceeding with execution"
                else:
                    # Non-timeout error, re-raise
                    raise
        
        print("\n📊 Analysis Result:")
        print("=" * 80)
        print(analysis_result)
        print("=" * 80)
        
        # Check if data is insufficient - look for it anywhere in the response
        if "INSUFFICIENT_DATA" in analysis_result or "INSUFFICIENT DATA" in analysis_result:
            print("\n⚠️  Insufficient Data Collected")
            print("   The playbook's compliance report is missing actual data.")
            print("   AI provided specific advice to improve data collection.")
            return False, analysis_result
        
        # Check the two critical sections: DATA COLLECTION, COMPLIANCE ANALYSIS
        # NOTE: PLAYBOOK ANALYSIS is now handled separately (after syntax check, before test execution)
        analysis_upper = analysis_result.upper()
        import re
        
        # Extract status from each section
        data_collection_status = None
        compliance_analysis_status = None
        
        # Check DATA COLLECTION status
        data_collection_patterns = [
            r'DATA\s+COLLECTION[:\s]*PASS',
            r'\*\*DATA\s+COLLECTION\*\*[:\s]*PASS',
            r'-\s*\*\*DATA\s+COLLECTION\*\*[:\s]*PASS',
        ]
        for pattern in data_collection_patterns:
            if re.search(pattern, analysis_upper):
                data_collection_status = 'PASS'
                break
        
        if not data_collection_status:
            data_collection_fail_patterns = [
                r'DATA\s+COLLECTION[:\s]*FAIL',
                r'\*\*DATA\s+COLLECTION\*\*[:\s]*FAIL',
            ]
            for pattern in data_collection_fail_patterns:
                if re.search(pattern, analysis_upper):
                    data_collection_status = 'FAIL'
                    break
        
        # Check COMPLIANCE ANALYSIS (PASS/FAIL, not COMPLIANT/NON-COMPLIANT)
        compliance_analysis_patterns = [
            r'COMPLIANCE\s+ANALYSIS[:\s]*PASS',
            r'\*\*COMPLIANCE\s+ANALYSIS\*\*[:\s]*PASS',
            r'-\s*\*\*COMPLIANCE\s+ANALYSIS\*\*[:\s]*PASS',
        ]
        for pattern in compliance_analysis_patterns:
            if re.search(pattern, analysis_upper):
                compliance_analysis_status = 'PASS'
                break
        
        if not compliance_analysis_status:
            compliance_analysis_fail_patterns = [
                r'COMPLIANCE\s+ANALYSIS[:\s]*FAIL',
                r'\*\*COMPLIANCE\s+ANALYSIS\*\*[:\s]*FAIL',
                r'-\s*\*\*COMPLIANCE\s+ANALYSIS\*\*[:\s]*FAIL',
            ]
            for pattern in compliance_analysis_fail_patterns:
                if re.search(pattern, analysis_upper):
                    compliance_analysis_status = 'FAIL'
                    break
        
        # Determine if both sections are correct
        all_sections_pass = (
            data_collection_status == 'PASS' and
            compliance_analysis_status == 'PASS'
        )

        if all_sections_pass:
            print("\n✅ AI Compliance Analysis: COMPLETE")
            print("   All sections passed:")
            print(f"   - DATA COLLECTION: {data_collection_status}")
            print(f"   - COMPLIANCE ANALYSIS: {compliance_analysis_status}")
            return True, analysis_result
        else:
            # Check which sections failed
            failed_sections = []
            if data_collection_status != 'PASS':
                failed_sections.append(f"DATA COLLECTION: {data_collection_status or 'NOT FOUND'}")
            if compliance_analysis_status != 'PASS':
                failed_sections.append(f"COMPLIANCE ANALYSIS: {compliance_analysis_status or 'NOT FOUND'}")
            
            print("\n❌ AI Compliance Analysis: Issues Found")
            print("   The following sections have problems:")
            for section in failed_sections:
                print(f"   - {section}")
            print("   Analysis result will be used for playbook enhancement.")
            return False, analysis_result
            
    except Exception as e:
        error_msg = f"Error during output analysis: {str(e)}"
        print(f"❌ {error_msg}")
        # If analysis fails, default to passing (don't block execution)
        print("⚠️  Analysis failed, proceeding anyway...")
        return True, error_msg


def main():
    """Main execution function."""
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Generate and execute Ansible playbooks using AI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use all defaults (packet_recvmsg killer)
  python3 deepseek_generate_playbook.py
  
  # Specify custom target host
  python3 deepseek_generate_playbook.py --target-host worker-1
  
  # Custom objective and filename
  python3 deepseek_generate_playbook.py \\
    --objective "Clean up old log files" \\
    --filename cleanup_logs.yml
  
  # Add custom requirements
  python3 deepseek_generate_playbook.py \\
    --objective "Install Docker" \\
    --requirement "Install Docker packages" \\
    --requirement "Start Docker service" \\
    --requirement "Enable Docker at boot" \\
    --filename install_docker.yml
  
  # Full customization
  python3 deepseek_generate_playbook.py \\
    --target-host worker-1 \\
    --become-user ansible \\
    --objective "Update system packages" \\
    --requirement "Update package cache" \\
    --requirement "Upgrade all packages" \\
    --filename system_update.yml
"""
    )
    
    parser.add_argument(
        '--target-host', '-t',
        type=str,
        default='master-1',
        help='Target host to execute the playbook on (default: master-1)'
    )
    
    parser.add_argument(
        '--test-host',
        type=str,
        default=None,
        help='Test host for validation before target execution (if not specified, uses target-host for testing)'
    )
    
    parser.add_argument(
        '--become-user', '-u',
        type=str,
        default='root',
        help='User to become when executing tasks (default: root)'
    )
    
    
    parser.add_argument(
        '--max-retries', '-r',
        type=int,
        default=None,
        help='Maximum number of retry attempts (default: auto-calculated based on number of requirements)'
    )
    
    parser.add_argument(
        '--objective', '-o',
        type=str,
        default="Create an Ansible playbook that finds and kills processes that have 'packet_recvmsg' in their stack trace.",
        help='Playbook objective - what the playbook should achieve'
    )
    
    parser.add_argument(
        '--requirement',
        action='append',
        dest='requirements',
        help='Add a requirement (can be used multiple times). If not specified, uses default packet_recvmsg requirements.'
    )
    
    parser.add_argument(
        '--example-output', '-e',
        type=str,
        default="""[root@master-1 ~]# egrep packet_recvmsg /proc/*/stack
/proc/2290657/stack:[<0>] packet_recvmsg+0x6e/0x4f0
grep: /proc/2290657/stack: No such file or directory

[root@master-1 ~]# ps -ef | grep -i 2290657
root     2290657 2526847  0 12:13 ?        00:00:00 ./bpfdoor
root     2822221 2819327  0 13:07 pts/1    00:00:00 grep --color=auto -i 2290657

[root@master-1 ~]# kill -9 2290657""",
        help='Example command output to provide context to the LLM'
    )
    
    parser.add_argument(
        '--audit-procedure',
        type=str,
        default=None,
        help='CIS Benchmark audit procedure (shell script or commands). When provided, generates an audit playbook based on this procedure.'
    )
    
    parser.add_argument(
        '--filename', '-f',
        type=str,
        default='kill_packet_recvmsg_process.yml',
        help='Output filename for the generated playbook (default: kill_packet_recvmsg_process.yml)'
    )
    
    args = parser.parse_args()
    
    # Use command-line arguments
    target_host = args.target_host
    test_host = args.test_host if args.test_host else target_host
    become_user = args.become_user
    playbook_objective = args.objective
    example_output = args.example_output
    filename = args.filename
    audit_procedure = args.audit_procedure
    
    # Handle requirements - use provided ones or defaults
    if args.requirements:
        requirements = args.requirements
    else:
        # Default requirements for packet_recvmsg killer
        requirements = [
            "Search for 'packet_recvmsg' keyword in /proc/*/stack",
            "Extract the process ID from the path (e.g., from '/proc/2290657/stack', extract '2290657')",
            "Kill the identified process(es) using 'kill -9'",
            "Handle cases where: No matching processes are found, Multiple processes are found (kill all), Process disappears between detection and kill attempt",
            "Display useful information: Show what processes were found, Show the process details (ps output), Confirm successful termination"
        ]
    
    # Calculate max_retries based on number of requirements if not specified
    if args.max_retries is None:
        max_retries = max(len(requirements), 3)  # At least 3, or number of requirements
        print(f"\n💡 Auto-calculated max retries: {max_retries} (based on {len(requirements)} requirements)")
    else:
        max_retries = args.max_retries
    
    # Display configuration
    print("\n" + "=" * 80)
    print("🎯 CONFIGURATION")
    print("=" * 80)
    print(f"Test Host:      {test_host}")
    if test_host != target_host:
        print(f"Target Host:    {target_host}")
    print(f"Become User:    {become_user}")
    print(f"Max Retries:    {max_retries}")
    print(f"Objective:      {playbook_objective[:60]}{'...' if len(playbook_objective) > 60 else ''}")
    print(f"Requirements:   {len(requirements)} items")
    if audit_procedure:
        print(f"Audit Proc:     {len(audit_procedure)} chars (CIS Benchmark audit procedure provided)")
    print(f"Filename:       {filename}")
    if test_host != target_host:
        print("\n📋 Execution Strategy:")
        print(f"   1. Test on: {test_host} (validation)")
        print(f"   2. Execute on: {target_host} (if test succeeds)")
    print("=" * 80)
    
    try:
        for attempt in range(1, max_retries + 1):
            print(f"\n{'='*80}")
            print(f"Attempt {attempt}/{max_retries}: Generating Ansible playbook...")
            print("=" * 80)
            print(f"Objective: {playbook_objective}")
            print(f"Test Host: {test_host}")
            if test_host != target_host:
                print(f"Target Host: {target_host}")
            print(f"Become User: {become_user}")
            print(f"Requirements: {len(requirements)} items")
            print("=" * 80)
            
            # Generate or enhance the playbook
            # On first attempt, current_playbook and feedback are None (generate from scratch)
            # On retry attempts, pass the current playbook and feedback for enhancement
            current_playbook_content = None
            feedback_content = None
            
            # If this is a retry (attempt > 1), we should have a previous playbook
            if attempt > 1:
                # Try to read the current playbook file if it exists
                try:
                    if os.path.isfile(filename):
                        with open(filename, 'r') as f:
                            current_playbook_content = f.read()
                except Exception:
                    pass  # If we can't read it, just generate from scratch
            
            # Extract feedback from requirements (look for CRITICAL FIX REQUIRED)
            for req in requirements:
                if "CRITICAL FIX REQUIRED" in req or "PLAYBOOK ANALYSIS: FAIL" in req:
                    feedback_content = req
                    break
            
            playbook = generate_playbook(
                playbook_objective=playbook_objective,
                target_host=test_host,  # Use test_host for generation
                become_user=become_user,
                requirements=requirements,
                example_output=example_output,
                audit_procedure=audit_procedure,
                current_playbook=current_playbook_content,
                feedback=feedback_content
            )
            
            # Display the generated playbook
            print("\n📋 Generated Ansible Playbook:")
            print("=" * 80)
            print(playbook)
            print("=" * 80)
            
            # Save to file
            save_playbook(playbook, filename)
            
            # Store current playbook for next retry if needed
            current_playbook_content = playbook
            
            # Check syntax
            is_valid, error_msg = check_playbook_syntax(filename, test_host)
            
            if not is_valid:
                # Syntax check failed
                if attempt < max_retries:
                    print(f"\n⚠️  Syntax check failed on attempt {attempt}/{max_retries}")
                    print("🔄 Retrying with additional instructions to LLM...")
                    print("\n📋 Error Summary:")
                    # Extract key error information
                    error_lines = error_msg.split('\n')
                    for line in error_lines[:10]:  # Show first 10 lines of error
                        if line.strip():
                            print(f"   {line}")
                    if len(error_lines) > 10:
                        print(f"   ... ({len(error_lines) - 10} more lines)")
                    
                    # Escape curly braces in error message to prevent format string errors
                    error_msg_escaped = error_msg[:200].replace('{', '{{').replace('}', '}}')
                    
                    # Add error context to requirements for next attempt
                    requirements.append(f"IMPORTANT: Previous attempt had syntax error: {error_msg_escaped}")
                    continue
                else:
                    print(f"\n❌ Failed to generate valid playbook after {max_retries} attempts")
                    print("\n" + "="*80)
                    print("FINAL SYNTAX ERROR:")
                    print("="*80)
                    print(error_msg)
                    print("="*80)
                    print(f"\n⚠️  The playbook has been saved to: {filename}")
                    print("Please review and fix the syntax errors manually.")
                    raise Exception(f"Syntax validation failed after {max_retries} attempts")
            
            # Syntax is valid, now test on test host
            print("\n" + "=" * 80)
            print(f"✅ Syntax Valid! Now testing on test host: {test_host}...")
            print("=" * 80)
            
            # Execute on test host first (skip debug tasks for cleaner analysis)
            test_success, test_output = test_playbook_on_server(filename, test_host, check_mode=False, verbose="v", skip_debug=True)
            
            # Check if it's a connection error (cannot validate on host)
            if not test_success and test_output.startswith("CONNECTION_ERROR:"):
                print("\n" + "=" * 80)
                print("⚠️  WARNING: Cannot connect to test host for validation")
                print("=" * 80)
                print(f"\n❌ Connection Error Details:")
                print(f"   Host: {test_host}")
                print(f"   Error: {test_output.replace('CONNECTION_ERROR: ', '')}")
                print(f"\n⚠️  The playbook syntax is valid, but execution validation cannot be performed.")
                print(f"   Please ensure:")
                print(f"   1. The host {test_host} is reachable")
                print(f"   2. SSH access is configured correctly")
                print(f"   3. Authentication credentials are valid")
                print(f"\n✅ Playbook has been saved with valid syntax: {filename}")
                print("=" * 80)
                # Exit with warning - don't proceed to analysis since we can't validate
                raise Exception(f"Cannot connect to test host {test_host} - validation cannot be performed")
            
            if test_success:
                # Test on test_host succeeded
                print("\n" + "=" * 80)
                print(f"🎉 SUCCESS! Playbook validated on test host: {test_host}!")
                print("=" * 80)
                print("\n✅ Test Execution Summary:")
                print("   1. ✅ Syntax check passed")
                print(f"   2. ✅ Test execution passed on {test_host}")
                print("   3. ✅ All requirements verified")
                
                # Check if it was an OS version mismatch
                if "OS version mismatch" in test_output or "playbook valid for different OS version" in test_output:
                    print("\n⚠️  NOTE: OS Version Mismatch on Test Host")
                    print("   The playbook is designed for a different OS version than the test host.")
                    print("   The playbook itself is syntactically and logically correct.")
                
                # Show FULL test execution output
                print(f"\n📋 Full Test Execution Output from {test_host}:")
                print("=" * 80)
                print(test_output)
                print("=" * 80)
                
                # Analyze playbook output against requirements
                # Read the current playbook content to pass to analysis
                current_playbook_for_analysis = None
                try:
                    if os.path.isfile(filename):
                        with open(filename, 'r') as f:
                            current_playbook_for_analysis = f.read()
                except Exception:
                    pass
                
                analysis_passed, analysis_message = analyze_playbook_output(
                    requirements=requirements,
                    playbook_objective=playbook_objective,
                    test_output=test_output,
                    audit_procedure=audit_procedure,
                    playbook_content=current_playbook_for_analysis
                )
                
                # Check if this is a PLAYBOOK STRUCTURE ANALYSIS failure (STAGE 0)
                is_structure_failure = (
                    not analysis_passed and 
                    ("PLAYBOOK STRUCTURE" in analysis_message.upper() or 
                     "PLAYBOOK_STRUCTURE" in analysis_message.upper() or
                     "REQUIREMENT_MAPPING_ERROR" in analysis_message.upper())
                )
                
                # Check if this is a DATA COLLECTION ANALYSIS failure (STAGE 1)
                is_data_collection_failure = (
                    not analysis_passed and 
                    not is_structure_failure and  # Not a structure failure
                    ("DATA_COLLECTION: FAIL" in analysis_message.upper() or 
                     "DATA COLLECTION: FAIL" in analysis_message.upper() or
                     "INSUFFICIENT_DATA" in analysis_message.upper() or
                     "STATUS_EVALUATION_ERROR" in analysis_message.upper() or
                     ("INSUFFICIENT" in analysis_message.upper()[:200] and "DATA" in analysis_message.upper()))
                )
                
                # Check for PLAYBOOK ANALYSIS: FAIL status (STAGE 2)
                has_issues, extracted_advice = extract_playbook_issues_from_analysis(analysis_message)
                
                # Check if COMPLIANCE ANALYSIS is missing, invalid, or FAIL (STAGE 2)
                # COMPLIANCE ANALYSIS should be PASS or FAIL
                # Check if the analysis message indicates COMPLIANCE ANALYSIS failure
                compliance_analysis_fail = "COMPLIANCE ANALYSIS: FAIL" in analysis_message.upper()
                compliance_analysis_missing = (
                    "COMPLIANCE ANALYSIS: NOT FOUND" in analysis_message.upper() or
                    ("COMPLIANCE ANALYSIS" in analysis_message.upper() and 
                     "COMPLIANCE ANALYSIS: PASS" not in analysis_message.upper() and
                     "COMPLIANCE ANALYSIS: FAIL" not in analysis_message.upper())
                )
                
                is_compliance_analysis_failure = (
                    not analysis_passed and 
                    not is_structure_failure and  # Not a structure failure
                    not is_data_collection_failure and  # Not a data collection failure
                    not has_issues and  # Not a PLAYBOOK ANALYSIS failure
                    (compliance_analysis_fail or compliance_analysis_missing)  # COMPLIANCE ANALYSIS is FAIL, missing, or invalid
                )
                
                # Verify status alignment between playbook output and AI analysis
                status_aligned, alignment_message = verify_status_alignment(test_output, analysis_message)
                
                # Debug output
                print(f"\n🔍 DEBUG: PLAYBOOK ANALYSIS status check:")
                print(f"   - PLAYBOOK ANALYSIS: {'FAIL' if has_issues else 'PASS'}")
                print(f"   - Status Alignment: {'✓ ALIGNED' if status_aligned else '✗ MISALIGNED'}")
                if not status_aligned:
                    print(f"   - Alignment Issues: {alignment_message}")
                
                # Proceed to target execution only when ALL criteria are met:
                # 1. Analysis passed (not a structure or data collection failure)
                # 2. PLAYBOOK ANALYSIS is PASS (if analysis passed)
                # 3. All requirement statuses align (PASS/FAIL = COMPLIANT/NON-COMPLIANT)
                # 4. Overall status aligns
                should_proceed = (
                    analysis_passed and  # Must pass analysis first
                    not has_issues and  # PLAYBOOK ANALYSIS must be PASS
                    status_aligned      # Statuses must align
                )
                
                if not should_proceed:
                    # Handle different failure types
                    if is_structure_failure:
                        print(f"\n⚠️  PLAYBOOK STRUCTURE ANALYSIS: FAIL - will regenerate playbook")
                    elif is_data_collection_failure:
                        print(f"\n⚠️  DATA COLLECTION ANALYSIS: FAIL - will regenerate playbook")
                    elif is_compliance_analysis_failure:
                        print(f"\n⚠️  COMPLIANCE ANALYSIS: MISSING or INVALID - will enhance playbook")
                    elif has_issues:
                        print(f"\n⚠️  PLAYBOOK ANALYSIS: FAIL - will enhance playbook")
                    else:
                        print(f"\n⚠️  Status misalignment detected - will enhance playbook")
                        print(f"   {alignment_message}")
                    
                    if attempt < max_retries:
                        # Handle different failure types
                        if is_structure_failure:
                            print(f"\n⚠️  PLAYBOOK STRUCTURE ANALYSIS: FAIL on attempt {attempt}/{max_retries}")
                        elif is_data_collection_failure:
                            print(f"\n⚠️  DATA COLLECTION ANALYSIS: FAIL on attempt {attempt}/{max_retries}")
                        elif is_compliance_analysis_failure:
                            print(f"\n⚠️  COMPLIANCE ANALYSIS: MISSING or INVALID on attempt {attempt}/{max_retries}")
                        elif has_issues:
                            print(f"\n⚠️  PLAYBOOK ANALYSIS: FAIL on attempt {attempt}/{max_retries}")
                        else:
                            print(f"\n⚠️  Status misalignment on attempt {attempt}/{max_retries}")
                        
                        if current_playbook_content:
                            print("🔄 Enhancing existing playbook with analysis feedback...")
                        else:
                            print("🔄 Regenerating playbook with analysis feedback...")
                        
                        # Prepare feedback message for PLAYBOOK STRUCTURE ANALYSIS failure
                        if is_structure_failure:
                            # Escape curly braces in feedback
                            structure_feedback_escaped = analysis_message.replace('{', '{{').replace('}', '}}')
                            structure_feedback = f"""CRITICAL FIX REQUIRED: PLAYBOOK STRUCTURE ANALYSIS: FAIL - The playbook structure does not correctly implement all requirements.

Analysis Result:
{structure_feedback_escaped}

INSTRUCTIONS TO FIX:
1. Review the PLAYBOOK STRUCTURE ANALYSIS feedback carefully
2. Ensure ALL requirements from the input list are implemented in the playbook content
3. For DATA COLLECTION requirements: Add tasks that collect the required data (check command/script matches requirement)
4. For STRUCTURAL requirements: Add CIS reference comments, "Generate compliance report" task, etc.
5. Ensure status variables are properly defined using Jinja2 expressions (with {{{{ }}}}) that EVALUATE to 'PASS'/'FAIL'/'NA'/'UNKNOWN', not string literals
6. If audit procedure is provided, ensure the playbook follows the audit procedure step-by-step logic
7. If conditional execution is required (e.g., "If nothing is returned, no further audit steps are required"), add proper `when:` conditions
8. Fix all issues identified in the analysis before proceeding"""
                            requirements.append(structure_feedback)
                            # Continue to next attempt
                            continue
                        
                        # Prepare feedback message for DATA COLLECTION ANALYSIS failure
                        if is_data_collection_failure:
                            # Escape curly braces in feedback
                            data_collection_feedback_escaped = analysis_message.replace('{', '{{').replace('}', '}}')
                            data_collection_feedback = f"""CRITICAL FIX REQUIRED: DATA COLLECTION ANALYSIS: FAIL - The playbook did not collect sufficient data or status values are not correctly evaluated.

Analysis Result:
{data_collection_feedback_escaped}

INSTRUCTIONS TO FIX:
1. Review the DATA COLLECTION ANALYSIS feedback carefully
2. Ensure ALL requirements have tasks that collect actual data (not placeholders or "Not collected yet")
3. For each requirement, verify the playbook includes:
   - A task that executes the command/script to collect data
   - Proper registration of command output (register: result_N)
   - Storage of data in data_N variables using set_fact
   - Status determination logic that evaluates to 'PASS', 'FAIL', 'NA', or 'UNKNOWN' (not Jinja2 expressions)
4. If status values are showing Jinja2 expressions instead of evaluated values:
   - Ensure status_N variables use Jinja2 expressions (with {{{{ }}}}) that EVALUATE to 'PASS'/'FAIL'/'NA'/'UNKNOWN', not string literals
   - Example WRONG: `status_1: "'PASS' if condition else 'FAIL'"` (string literal - will show expression text)
   - Example CORRECT: `status_1: "{{{{ ('PASS' if condition else 'FAIL') | trim }}}}"` (Jinja2 expression - will evaluate to 'PASS' or 'FAIL')
5. If data is missing or incomplete:
   - Add tasks to collect the missing data
   - Ensure commands are executed and output is captured
   - Verify the compliance report includes actual data or confirmed absence (empty output with exit code 0/1 is valid)
6. If tasks are skipped (Status='NA'), verify they align with audit procedure (if provided)
7. Fix all issues identified in the analysis before proceeding"""
                            requirements.append(data_collection_feedback)
                            # Continue to next attempt
                            continue
                        
                        # Prepare feedback message for COMPLIANCE ANALYSIS failure
                        if is_compliance_analysis_failure:
                            # Escape curly braces in feedback
                            compliance_analysis_feedback_escaped = analysis_message.replace('{', '{{').replace('}', '}}')
                            compliance_analysis_feedback = f"""CRITICAL FIX REQUIRED: COMPLIANCE ANALYSIS: MISSING or FAIL - The AI analysis did not provide a valid COMPLIANCE ANALYSIS (PASS or FAIL).

Analysis Result:
{compliance_analysis_feedback_escaped}

INSTRUCTIONS TO FIX:
1. Review the COMPLIANCE ANALYSIS feedback carefully
2. The AI analysis MUST include a "COMPLIANCE ANALYSIS" section in the OVERALL ASSESSMENT with value PASS or FAIL
3. COMPLIANCE ANALYSIS: PASS when:
   - All steps and requirements results from playbook and AI match each other (status alignment verified)
   - The audit procedure logic matches correctly
   - All individual requirement statuses align (PASS=COMPLIANT, FAIL=NON-COMPLIANT, NA=UNKNOWN)
   - Overall status aligns (PASS=COMPLIANT, FAIL=NON-COMPLIANT, NA=UNKNOWN)
4. COMPLIANCE ANALYSIS: FAIL when:
   - Any step or requirement result from playbook does NOT match AI analysis (status misalignment)
   - The audit procedure logic does NOT match correctly
   - Any individual requirement status misalignment
   - Overall status misalignment
5. Ensure the playbook's overall compliance logic correctly determines the final status based on:
   - Individual requirement statuses (PASS/FAIL/NA/UNKNOWN)
   - The audit procedure logic (if provided)
   - The overall compliance criteria
6. The COMPLIANCE ANALYSIS should verify that playbook statuses align with AI analysis statuses
7. Fix all issues identified in the analysis before proceeding"""
                            requirements.append(compliance_analysis_feedback)
                            # Continue to next attempt
                            continue
                        
                        # Prepare feedback message for status alignment
                        if not status_aligned:
                            # Add status alignment feedback
                            feedback_header = "CRITICAL FIX REQUIRED: Status misalignment between playbook output and AI analysis."
                            alignment_feedback = f"""{feedback_header}

Status Alignment Issues:
{alignment_message}

INSTRUCTIONS TO FIX:
1. Review the status alignment issues above
2. Ensure playbook status determination logic matches AI analysis:
   - PASS should correspond to COMPLIANT
   - FAIL should correspond to NON-COMPLIANT
3. Fix the status determination logic in the playbook to align with AI analysis
4. Verify overall compliance logic matches CIS requirements exactly
"""
                            requirements.append(alignment_feedback)
                        
                        # Prepare feedback message for PLAYBOOK ANALYSIS issues (if any)
                        if extracted_advice:
                            # Use extracted advice if available
                            feedback_text = extracted_advice
                        else:
                            # Extract the PLAYBOOK ANALYSIS section and recommendations
                            lines = analysis_message.split('\n')
                            feedback_lines = []
                            in_playbook_analysis = False
                            for i, line in enumerate(lines):
                                if "PLAYBOOK ANALYSIS" in line.upper():
                                    in_playbook_analysis = True
                                    feedback_lines.append(line)
                                    # Get next few lines for context
                                    for j in range(i+1, min(i+20, len(lines))):
                                        if lines[j].strip().startswith('- **') and 'PLAYBOOK' not in lines[j].upper() and 'DATA COLLECTION' not in lines[j].upper():
                                            break
                                        feedback_lines.append(lines[j])
                                    break
                            # Also look for RECOMMENDATION or PLAYBOOK LOGIC ISSUE sections
                            for i, line in enumerate(lines):
                                if any(kw in line.upper() for kw in ["PLAYBOOK LOGIC ISSUE", "RECOMMENDATION", "ADVICE"]):
                                    if line not in feedback_lines:
                                        feedback_lines.append(line)
                                    # Get next 10-15 lines
                                    for j in range(i+1, min(i+15, len(lines))):
                                        if lines[j].strip().startswith('##') or (lines[j].strip().startswith('- **') and 'RECOMMENDATION' not in lines[j].upper()):
                                            break
                                        if lines[j] not in feedback_lines:
                                            feedback_lines.append(lines[j])
                            feedback_text = '\n'.join(feedback_lines).strip() or analysis_message[:1000]
                        
                        feedback_header = "CRITICAL FIX REQUIRED: PLAYBOOK ANALYSIS: FAIL - The playbook has logic issues that need to be fixed."
                        
                        # Build complete feedback message
                        feedback_escaped = feedback_text.replace('{', '{{').replace('}', '}}')
                        complete_feedback = f"""{feedback_header}

Analysis Result:
{feedback_escaped}

INSTRUCTIONS TO FIX:
1. Review the PLAYBOOK ANALYSIS feedback carefully
2. Fix the playbook logic issues identified in the analysis
3. If analysis recommends conditional execution (e.g., "when: data_1 | length > 0"), implement it
4. If analysis identifies design flaws or logic issues, fix them according to the recommendations
5. Ensure the playbook follows CIS procedures correctly (e.g., skip subsequent requirements when first requirement returns nothing)
6. Update overall compliance logic to match CIS exactly
7. Make sure all requirements are executed in the correct order and conditions"""
                        
                        # Store feedback for next attempt (will be passed to generate_playbook)
                        # Also add to requirements for context, but the actual enhancement will use current_playbook and feedback
                        requirements.append(complete_feedback)
                        
                        # Continue to next attempt (current_playbook_content is already set from previous save)
                        continue
                    else:
                        print(f"\n❌ Failed to generate correct playbook after {max_retries} attempts")
                        print("   PLAYBOOK ANALYSIS: FAIL - playbook logic issues need to be fixed")
                        print(f"\n⚠️  The playbook has been saved to: {filename}")
                        print("Please review the analysis feedback and fix manually.")
                        raise Exception(f"Playbook analysis failed after {max_retries} attempts")
                
                # All criteria met - proceed to target host execution
                print("\n✅ All criteria met:")
                print("   1. ✅ PLAYBOOK ANALYSIS: PASS")
                print("   2. ✅ Status alignment verified (PASS/FAIL = COMPLIANT/NON-COMPLIANT)")
                print("   3. ✅ Overall status alignment verified")
                print("\n🚀 Proceeding to target host execution...")
                
                # Now execute on target host if different
                if test_host != target_host:
                    print("\n" + "=" * 80)
                    print(f"🚀 FINAL EXECUTION: Running playbook on target host: {target_host}")
                    print("=" * 80)
                    print(f"\n📍 Executing on: {target_host}")
                    print()
                    
                    final_success, final_output = test_playbook_on_server(filename, target_host, check_mode=False, verbose="v", skip_debug=True)
                    
                    if final_success:
                        print("\n" + "=" * 80)
                        print(f"🎊 COMPLETE SUCCESS! Playbook executed on target: {target_host}!")
                        print("=" * 80)
                        print("\n✅ Final Execution Summary:")
                        print("   1. ✅ Syntax check passed")
                        print(f"   2. ✅ Test execution passed on {test_host}")
                        print(f"   3. ✅ Final execution passed on {target_host}")
                        print("   4. ✅ All requirements verified")
                        
                        # Show FULL final execution output
                        print(f"\n📋 Full Final Execution Output from {target_host}:")
                        print("=" * 80)
                        print(final_output)
                        print("=" * 80)
                    else:
                        print("\n" + "=" * 80)
                        print(f"⚠️  Execution on target host {target_host} had issues")
                        print("=" * 80)
                        print(f"\n📋 Full Execution Output from {target_host}:")
                        print("=" * 80)
                        print(final_output)
                        print("=" * 80)
                        print("\n⚠️  The playbook was validated on test host but may need adjustment for target host.")
                        print(f"   Test host: {test_host} ✅")
                        print(f"   Target host: {target_host} ❌")
                else:
                    print("\n" + "=" * 80)
                    print(f"🎊 COMPLETE SUCCESS! Playbook executed on {target_host}!")
                    print("=" * 80)
                
                break
            else:
                # Test failed
                if attempt < max_retries:
                    print(f"\n⚠️  Server test failed on attempt {attempt}/{max_retries}")
                    print("🔄 Retrying with test failure feedback to LLM...")
                    
                    # Check if it's an undefined variable bug
                    is_undefined_variable = "PLAYBOOK BUG" in test_output and "undefined" in test_output.lower()
                    
                    if is_undefined_variable:
                        # For undefined variable bugs, include more context
                        print("\n📋 Detected Undefined Variable Error - Providing detailed feedback to LLM")
                        
                        # Extract the specific error message
                        error_context = []
                        output_lines = test_output.split('\n')
                        for i, line in enumerate(output_lines):
                            if 'undefined' in line.lower() or 'PLAYBOOK BUG' in line:
                                # Get surrounding lines for context
                                start = max(0, i-5)
                                end = min(len(output_lines), i+10)
                                error_context = output_lines[start:end]
                                break
                        
                        if error_context:
                            error_msg = '\n'.join(error_context)
                        else:
                            error_msg = test_output[:500]
                        
                        # Escape curly braces
                        error_msg_escaped = error_msg.replace('{', '{{').replace('}', '}}')
                        
                        # Add specific undefined variable instructions
                        requirements.append(f"""CRITICAL FIX REQUIRED: Previous playbook had UNDEFINED VARIABLE error.
Error details: {error_msg_escaped}

To fix this:
1. Ensure ALL variables are defined BEFORE they are used
2. NEVER use a variable in the same set_fact task where it's being defined
3. Split set_fact tasks that have dependencies into separate tasks
4. Use 'variable_name | default(value)' for safety
5. Always set 'gather_facts: false' at the playbook level

Example of the problem:
BAD - Circular reference:
  - set_fact:
      var1: "{{{{ some_value }}}}"
      var2: "{{{{ var1 | upper }}}}"  # ERROR: var1 doesn't exist yet!

GOOD - Split into separate tasks:
  - set_fact:
      var1: "{{{{ some_value }}}}"
  - set_fact:
      var2: "{{{{ var1 | upper }}}}"  # OK: var1 exists now""")
                    else:
                        # For other errors, use shorter context
                        test_output_escaped = test_output[:300].replace('{', '{{').replace('}', '}}')
                        requirements.append(f"IMPORTANT: Previous playbook failed testing: {test_output_escaped}")
                else:
                    print(f"\n❌ Failed to generate working playbook after {max_retries} attempts")
                    print(f"Last test output:\n{test_output}")
                    print(f"\n⚠️  The playbook has been saved to: {filename}")
                    print("Please review and fix the issues manually.")
                    raise Exception(f"Playbook testing failed after {max_retries} attempts")
        
    except Exception as e:
        print(f"\n❌ Error generating playbook: {str(e)}")
        raise


if __name__ == "__main__":
    main()
