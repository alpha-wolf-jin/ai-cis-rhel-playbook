# Automating CIS RHEL 9 Compliance: From PDF Benchmark to Ansible Playbooks with AI

## Introduction

The CIS (Center for Internet Security) RHEL 9 Benchmark is a comprehensive security configuration guide containing hundreds of checkpoints that organizations must audit to ensure their Red Hat Enterprise Linux systems meet security best practices. Manually converting these checkpoints into executable audit playbooks is time-consuming, error-prone, and requires deep expertise in both security compliance and Ansible automation.

In this blog post, we'll explore how we've built an AI-powered system that automatically transforms the CIS RHEL 9 Benchmark PDF into production-ready Ansible playbooks, dramatically reducing the time and effort required for compliance auditing.

## The Challenge

The CIS RHEL 9 Benchmark PDF contains:
- **Hundreds of security checkpoints** (e.g., "1.1.1.1 Ensure cramfs kernel module is not available")
- **Complex audit procedures** with bash scripts, shell commands, and conditional logic
- **Profile-specific requirements** (Level 1/Level 2, Server/Workstation)
- **Detailed remediation steps** for non-compliant systems

Converting each checkpoint into an Ansible playbook requires:
1. **Extracting checkpoint information** from the PDF
2. **Understanding the audit procedure** (often involving complex bash scripts)
3. **Translating to Ansible tasks** while preserving exact command logic
4. **Handling edge cases** like conditional execution, error handling, and output parsing
5. **Testing and validation** to ensure playbooks work correctly

Doing this manually for hundreds of checkpoints would take weeks or months. Our solution automates this entire process.

## Solution Architecture

Our system uses a combination of **RAG (Retrieval-Augmented Generation)** and **AI-powered code generation** to transform the CIS benchmark into executable Ansible playbooks. The workflow is implemented using **LangGraph**, which provides robust state management and iterative refinement through multiple validation loops.

### High-Level Workflow

The complete workflow follows an iterative refinement pattern with multiple validation checkpoints. Each validation step can trigger automatic regeneration if issues are detected:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CIS RHEL 9 Benchmark PDF                                  │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              Step 1: PDF Processing & Vector Store                            │
│  • Load PDF with PyPDFLoader                                                 │
│  • Split into chunks (2000 chars, 500 overlap)                              │
│  • Create embeddings using HuggingFace (all-MiniLM-L6-v2)                    │
│  • Store in Chroma vector database                                           │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│         Step 2: RAG-Based Checkpoint Information Retrieval                   │
│  • Agent-based search using DeepSeek AI                                      │
│  • Semantic search across benchmark document                                │
│  • Extract: Profile, Description, Rationale, Audit/Remediation procedures  │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│        Step 3: Extract Playbook Requirements                                 │
│  • Parse audit procedures (bash scripts, commands)                           │
│  • Generate structured requirements using DeepSeek AI                        │
│  • Handle complex scripts and conditional logic                             │
│  • Create requirement list for playbook generation                           │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│          Step 4: Generate Ansible Playbook                                   │
│  • Convert requirements to Ansible YAML using DeepSeek AI                    │
│  • Handle bash scripts with {% raw %} tags                                  │
│  • Implement error handling and status determination                        │
│  • Generate compliance reports                                              │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│          Step 5: Save Playbook                                               │
│  • Write generated YAML to file                                              │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│          Step 6: Syntax Check                                                │
│  • Run: ansible-playbook --syntax-check                                     │
│  • Detect YAML syntax errors, Jinja2 template errors                        │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐            │
│  │  IF FAILED:                                                 │            │
│  │    • Increment attempt counter                              │            │
│  │    • If attempt < max_retries:                               │            │
│  │        → Return to Step 4 (Generate) with error message    │            │
│  │    • Else:                                                  │            │
│  │        → End workflow (failed)                             │            │
│  └────────────────────────────────────────────────────────────┘            │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼ (if syntax valid)
┌─────────────────────────────────────────────────────────────────────────────┐
│          Step 7: Analyze Playbook Structure                                  │
│  • AI analyzes playbook content against requirements                        │
│  • Check: Requirement mapping, implementation correctness                    │
│  • Verify: Audit procedure compliance, status variable format              │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐            │
│  │  IF FAILED:                                                 │            │
│  │    • Increment attempt counter                              │            │
│  │    • If attempt < max_retries:                               │            │
│  │        → Return to Step 4 (Generate) with analysis feedback │            │
│  │    • Else:                                                  │            │
│  │        → End workflow (failed)                             │            │
│  └────────────────────────────────────────────────────────────┘            │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼ (if structure valid)
┌─────────────────────────────────────────────────────────────────────────────┐
│          Step 8: Test Playbook on Test Host                                  │
│  • Execute playbook on test RHEL 9 system                                   │
│  • Capture execution output                                                 │
│  • Detect playbook bugs (Jinja2 errors, undefined variables, etc.)         │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐            │
│  │  IF FAILED (playbook bug detected):                        │            │
│  │    • Increment attempt counter                              │            │
│  │    • If attempt < max_retries:                               │            │
│  │        → Return to Step 4 (Generate) with error details    │            │
│  │    • Else:                                                  │            │
│  │        → End workflow (failed)                             │            │
│  │                                                            │            │
│  │  IF SUCCESS:                                               │            │
│  │    → Proceed to Step 9 (Analyze Output)                   │            │
│  └────────────────────────────────────────────────────────────┘            │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼ (if test successful)
┌─────────────────────────────────────────────────────────────────────────────┐
│          Step 9: Analyze Playbook Output                                     │
│  • Check Data Collection Sufficiency:                                        │
│    - Verify all required data was collected                                 │
│    - Check if commands executed successfully (not failed)                   │
│    - Ensure status values are correctly evaluated                          │
│                                                                              │
│  • AI Compliance Analysis:                                                   │
│    - Compare collected data against CIS benchmark requirements              │
│    - Analyze based on extracted requirements from Step 3                   │
│    - Determine compliance status (PASS/FAIL/NA/UNKNOWN)                     │
│                                                                              │
│  • Verify Status Alignment:                                                  │
│    - Check if playbook output status matches AI analysis                    │
│    - Detect discrepancies between playbook logic and AI interpretation      │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────┐            │
│  │  IF DATA COLLECTION: FAIL or COMPLIANCE ANALYSIS: FAIL:    │            │
│  │    • Increment attempt counter                              │            │
│  │    • If attempt < max_retries:                               │            │
│  │        → Return to Step 4 (Generate) with analysis feedback │            │
│  │        → Include specific issues: missing data, wrong logic  │            │
│  │    • Else:                                                  │            │
│  │        → End workflow (failed)                             │            │
│  │                                                            │            │
│  │  IF STATUS MISALIGNMENT:                                    │            │
│  │    • Playbook output doesn't match AI analysis              │            │
│  │    • Indicates playbook logic error                        │            │
│  │    → Return to Step 4 (Generate) to fix logic              │            │
│  │                                                            │            │
│  │  IF ALL PASS:                                               │            │
│  │    → Proceed to Step 10 (Execute on Target)                │            │
│  └────────────────────────────────────────────────────────────┘            │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼ (if analysis passed)
┌─────────────────────────────────────────────────────────────────────────────┐
│          Step 10: Execute Playbook on Target Host                           │
│  • Execute validated playbook on production/target RHEL 9 system           │
│  • Capture final execution output                                           │
│  • Generate compliance report                                               │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│          Step 11: Final AI Analysis                                          │
│  • Analyze final execution output                                           │
│  • Compare against CIS benchmark and requirements                           │
│  • Generate comprehensive compliance report                                 │
│  • Document any discrepancies or issues                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Features of the Workflow

1. **Iterative Refinement**: Each validation step can trigger automatic regeneration with specific error feedback
2. **Multiple Validation Layers**: Syntax → Structure → Execution → Data → Compliance
3. **Intelligent Retry Logic**: Only retries when issues are detected, with attempt limits
4. **Comprehensive Analysis**: AI analyzes both playbook structure and execution results
5. **Status Alignment Verification**: Ensures playbook logic matches AI's interpretation of CIS requirements
6. **Data Sufficiency Checks**: Verifies that all required data was collected before compliance analysis

### Workflow State Management

The workflow uses **LangGraph** for state management, tracking:
- **Attempt counter**: Prevents infinite loops
- **Playbook content**: Generated YAML
- **Validation results**: Syntax, structure, test, analysis results
- **Error messages**: Specific feedback for regeneration
- **Execution outputs**: Test and target host outputs
- **Analysis messages**: AI compliance analysis results

## Iterative Refinement Process

The workflow implements a sophisticated **iterative refinement** process where each validation step can trigger automatic regeneration with specific feedback. This ensures that generated playbooks are not just syntactically correct, but also functionally accurate and compliant with CIS requirements.

### Retry Logic and Feedback Loop

The system uses **LangGraph** to manage state and control flow, implementing retry logic at multiple checkpoints:

1. **Syntax Check Retry**: If YAML or Jinja2 syntax errors are detected, the playbook is regenerated with the specific error message
2. **Structure Analysis Retry**: If the playbook doesn't correctly implement requirements, it's regenerated with detailed feedback
3. **Execution Test Retry**: If playbook bugs are detected during test execution, regeneration occurs with execution error details
4. **Data Collection Retry**: If insufficient data is collected, the playbook is enhanced to collect missing information
5. **Compliance Analysis Retry**: If the playbook's compliance logic doesn't match AI analysis, it's regenerated to align with CIS requirements

### Example: Multi-Stage Refinement

Here's an example of how a playbook might be refined through multiple iterations:

**Attempt 1:**
- ✅ Syntax check: PASS
- ❌ Structure analysis: FAIL - Missing requirement 2 implementation
- → **Regenerate** with feedback: "Requirement 2: Check PermitEmptyPasswords in match blocks is missing"

**Attempt 2:**
- ✅ Syntax check: PASS
- ✅ Structure analysis: PASS
- ❌ Test execution: FAIL - Jinja2 template error in shell block
- → **Regenerate** with feedback: "Template error: expected token ')' at line 45 in shell task"

**Attempt 3:**
- ✅ Syntax check: PASS
- ✅ Structure analysis: PASS
- ✅ Test execution: PASS
- ❌ Data collection: FAIL - Command failed, no data collected
- → **Regenerate** with feedback: "Command 'sshd -T' failed. Add error handling or use alternative command"

**Attempt 4:**
- ✅ Syntax check: PASS
- ✅ Structure analysis: PASS
- ✅ Test execution: PASS
- ✅ Data collection: PASS
- ❌ Compliance analysis: FAIL - Status misalignment (playbook says PASS, AI says FAIL)
- → **Regenerate** with feedback: "Status logic error: Playbook evaluates as PASS but AI analysis shows FAIL based on CIS requirements"

**Attempt 5:**
- ✅ All checks: PASS
- → **Success!** Playbook is ready for production use

### Data Sufficiency and Compliance Analysis

A critical aspect of the workflow is the **two-stage analysis** after playbook execution:

#### Stage 1: Data Collection Sufficiency Check

Before analyzing compliance, the system verifies that the playbook collected sufficient data:

```python
def analyze_data_collection(playbook_output: str, requirements: list) -> tuple[bool, str]:
    """Check if playbook collected sufficient data for compliance analysis."""
    
    # AI analyzes:
    # 1. Were all required commands executed successfully?
    # 2. Is output data present (even if empty)?
    # 3. Are status values correctly evaluated?
    
    # Examples:
    # ✅ SUFFICIENT: Command executed, returned empty output → "not found" is valid data
    # ✅ SUFFICIENT: Command executed, returned data → ready for analysis
    # ❌ INSUFFICIENT: Command failed (not just empty) → missing data
```

**Key Principle**: Empty output is **sufficient data** (meaning "not found"), but command failures are **insufficient data**.

#### Stage 2: AI Compliance Analysis

Once data sufficiency is confirmed, the AI performs compliance analysis:

```python
def analyze_playbook_output(
    requirements: list,
    playbook_objective: str,
    test_output: str,
    audit_procedure: str
) -> tuple[bool, str]:
    """Analyze playbook output against CIS requirements."""
    
    # AI compares:
    # 1. Collected data vs. CIS benchmark requirements
    # 2. Playbook's status determination vs. AI's interpretation
    # 3. Overall compliance logic alignment
    
    # Returns:
    # - DATA COLLECTION: PASS/FAIL
    # - COMPLIANCE ANALYSIS: PASS/FAIL with detailed reasoning
    # - Status alignment verification
```

**Status Alignment Verification**: The system checks if the playbook's compliance status matches the AI's analysis. If they don't align, it indicates a logic error in the playbook that needs to be fixed.

## Detailed Workflow

### Step 1: Building the Knowledge Base

The first step is converting the CIS benchmark PDF into a searchable vector database:

```python
# Load PDF and create vector store
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# Load the PDF
loader = PyPDFLoader("CIS_Red_Hat_Enterprise_Linux_9_Benchmark_v2.0.0.pdf")
data = loader.load()

# Split into chunks (optimized for long scripts)
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=2000,  # Large enough for complete bash scripts
    chunk_overlap=500  # Ensure scripts aren't split mid-way
)
chunks = text_splitter.split_documents(data)

# Create embeddings and vector store
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)
vector_store = Chroma.from_documents(
    documents=chunks,
    embedding=embeddings,
    persist_directory="CIS_RHEL9_DATA_DEEPSEEK"
)
```

**Key Design Decisions:**
- **Large chunk size (2000 chars)**: Ensures complete bash scripts aren't split across chunks
- **Significant overlap (500 chars)**: Prevents losing context when scripts span chunk boundaries
- **HuggingFace embeddings**: Open-source, no API costs, good performance for technical documents

### Step 2: Intelligent Checkpoint Retrieval

Instead of simple keyword search, we use an **agent-based RAG approach** where an AI agent intelligently searches the benchmark:

```python
def get_checkpoint_info_with_agent(vector_store, checkpoint: str):
    """Use AI agent to find and extract checkpoint information."""
    
    # Create search tool
    @tool
    def search_cis_benchmark(query: str) -> str:
        """Search the CIS benchmark for security control information."""
        results = vector_store.similarity_search(query, k=10)
        return "\n\n---\n\n".join([doc.page_content for doc in results])
    
    # Create agent with specialized system prompt
    agent = create_agent(
        model=ChatOpenAI(model="deepseek-chat"),
        tools=[search_cis_benchmark],
        system_prompt="""You are a CIS RHEL 9 security expert. 
        When asked about a checkpoint:
        1. Use the search tool multiple times with different queries
        2. Extract ALL information: Profile, Description, Rationale, 
           Audit procedure, Remediation procedure
        3. CRITICAL: If audit/remediation contains bash scripts, 
           extract the ENTIRE script - missing even one line makes it useless."""
    )
    
    # Query the agent
    response = agent.invoke({
        "messages": [HumanMessage(content=f"Find all info about {checkpoint}")]
    })
    
    return response
```

**Why Agent-Based RAG?**
- **Multiple search queries**: The agent tries different search terms (checkpoint number, keywords, "Ensure" phrases)
- **Context assembly**: Combines results from multiple searches to get complete information
- **Script extraction**: Specifically instructed to extract complete bash scripts, not truncated versions

### Step 3: Parsing Audit Procedures

CIS audit procedures can be:
- **Simple commands**: `grep -E '^\s*umask\s+(0[0-7][0-7][0-7]|[0-7]{3})\s*' /etc/bashrc`
- **Complex bash scripts**: Multi-line scripts with loops, conditionals, and variable assignments
- **Conditional logic**: "If X returns nothing, then check Y, else check Z"

Our system handles all these cases:

```python
def extract_audit_steps_from_procedure(procedure: str) -> list:
    """Extract structured audit steps from procedure text."""
    
    # Detect if procedure is a complete bash script
    if procedure.strip().startswith('#!/usr/bin/env bash') or \
       (procedure.count('{') > 0 and procedure.count('}') > 0):
        # It's a script - return empty to trigger fallback
        return []
    
    # Otherwise, try to parse as structured steps
    # Use AI to extract JSON-formatted steps
    # ...
```

**Handling Bash Scripts:**
When a complete bash script is detected, we don't try to parse it into steps. Instead, we create a single requirement that instructs the playbook generator to:
1. Copy the script to the remote host
2. Execute it
3. Parse the output
4. Determine compliance status

### Step 4: Generating Playbook Requirements

The system converts audit procedures into structured requirements that guide playbook generation:

```python
def generate_playbook_requirements_from_checkpoint(checkpoint_info: dict) -> list:
    """Generate playbook requirements from checkpoint information."""
    
    requirements = []
    audit_procedure = checkpoint_info.get('audit_procedure', '')
    
    # If audit procedure is a script, create single requirement
    if is_complete_bash_script(audit_procedure):
        requirements.append(f"""
        Use the provided bash script to audit this checkpoint:
        {audit_procedure}
        
        Steps:
        1. Copy script to remote host using 'copy' module
        2. Execute script using 'shell' module
        3. Parse output to determine PASS/FAIL
        4. Clean up script using 'file' module
        """)
    else:
        # Parse into individual requirements
        steps = extract_audit_steps_from_procedure(audit_procedure)
        for step in steps:
            requirements.append(step['description'])
    
    return requirements
```

### Step 5: Ansible Playbook Generation

This is where the magic happens. We use **DeepSeek AI** with a highly detailed prompt to generate production-ready Ansible playbooks:

```python
def generate_playbook(requirements: list, checkpoint_info: dict) -> str:
    """Generate Ansible playbook from requirements."""
    
    prompt = f"""
    Generate an Ansible playbook to audit CIS checkpoint: {checkpoint_info['title']}
    
    Requirements:
    {requirements}
    
    CRITICAL RULES:
    1. For bash scripts: Use copy, shell, file modules with {% raw %} tags
    2. For shell commands with special chars: Use {% raw %} and {% endraw %}
    3. Move Jinja2 variables OUTSIDE {% raw %} blocks
    4. Avoid parentheses and quotes in comments within shell: blocks
    5. Use simpler bash syntax (set/shift) instead of array syntax inside raw blocks
    ...
    """
    
    playbook = llm.generate(prompt)
    return playbook
```

**Key Technical Challenges Solved:**

#### 1. Embedding Bash Scripts in Ansible

Bash scripts often contain characters that conflict with YAML/Jinja2 syntax (`{{`, `}}`, `$`, etc.). Our solution:

```yaml
# ✅ CORRECT: Use {% raw %} tags in copy module
- name: Copy audit script
  copy:
    content: |
      {% raw %}
      #!/usr/bin/env bash
      l_output=""
      l_output2=""
      # ... complex script with {{ }} and $ variables ...
      {% endraw %}
    dest: /tmp/audit_script.sh
    mode: '0755'

- name: Execute audit script
  shell: /tmp/audit_script.sh
  register: result

- name: Clean up script
  file:
    path: /tmp/audit_script.sh
    state: absent
```

#### 2. Mixing Ansible Variables with Bash Code

When you need Ansible variables in bash scripts:

```yaml
# ✅ CORRECT: Variables outside, bash inside
- name: Check match blocks
  shell: |
    # Ansible processes these FIRST (outside raw block)
    match_blocks_exist="{{ match_blocks_exist }}"
    conditions_string="{{ match_conditions_list | default([]) | join('\n') }}"
    
    {% raw %}
    # Bash code uses variables set above
    if [ "$match_blocks_exist" = "false" ]; then
      echo "No match blocks"
      exit 0
    fi
    
    while IFS= read -r condition; do
      # Process condition...
    done << EOF
    $conditions_string
    EOF
    {% endraw %}
```

#### 3. Avoiding YAML Parser Errors

Even inside `{% raw %}` blocks, complex bash array syntax can confuse YAML parsers:

```yaml
# ❌ WRONG: Complex array syntax causes parsing errors
{% raw %}
words=($condition)
for ((i=0; i<${#words[@]}; i+=2)); do
  key="${words[i]}"
  value="${words[i+1]}"
done
{% endraw %}

# ✅ CORRECT: Simpler syntax
{% raw %}
set -- $condition
while [ $# -gt 0 ]; do
  key="$1"
  value="$2"
  shift 2
  # Process key and value...
done
{% endraw %}
```

#### 4. Comments in Shell Blocks

Special characters in comments can break YAML parsing:

```yaml
# ❌ WRONG: Parentheses and quotes in comments
shell: |
  # Ansible processes this FIRST (outside raw block):  ← Problem!
  # The CIS procedure says: "specify parameters"  ← Problem!
  # We'll test with root user  ← Problem! (contraction)

# ✅ CORRECT: Plain text comments
shell: |
  # Ansible processes this first outside raw block
  # The CIS procedure says: specify parameters
  # We will test with root user
```

### Step 6: Multi-Stage Validation and Testing

Generated playbooks go through a comprehensive multi-stage validation process:

#### Stage 1: Syntax Validation

```python
def check_playbook_syntax(playbook_path: str) -> tuple[bool, str]:
    """Check YAML and Jinja2 syntax."""
    result = subprocess.run(
        ['ansible-playbook', '--syntax-check', playbook_path],
        capture_output=True
    )
    if result.returncode != 0:
        return False, result.stderr.decode()
    return True, "Syntax valid"
```

**Detects:**
- YAML syntax errors
- Jinja2 template syntax errors
- Invalid Ansible task structure

**On Failure**: Regenerate playbook with syntax error details

#### Stage 2: Playbook Structure Analysis

```python
def analyze_playbook(requirements: list, playbook_content: str) -> tuple[bool, str]:
    """AI analyzes playbook structure against requirements."""
    
    # AI checks:
    # 1. Requirement mapping: All requirements have corresponding tasks
    # 2. Implementation correctness: Tasks implement requirements correctly
    # 3. Audit procedure compliance: Workflow matches CIS procedure
    # 4. Status variable format: Correct YAML format (folded vs literal)
    
    analysis_result = llm.analyze(requirements, playbook_content)
    has_issues = extract_issues(analysis_result)
    
    return not has_issues, analysis_result
```

**Detects:**
- Missing requirement implementations
- Incorrect command/script usage
- Workflow logic misalignment with CIS procedures
- Status variable format issues

**On Failure**: Regenerate playbook with structure analysis feedback

#### Stage 3: Test Execution on Test Host

```python
def test_playbook_on_server(playbook_path: str, test_host: str) -> tuple[bool, str]:
    """Execute playbook on test RHEL 9 system."""
    
    result = subprocess.run(
        ['ansible-navigator', 'run', playbook_path, '-i', f'{test_host},'],
        capture_output=True,
        timeout=120
    )
    
    output = result.stdout + result.stderr
    
    # Detect playbook bugs (not compliance failures)
    playbook_bug_patterns = [
        ("template error while templating", "Jinja2 template error"),
        ("failed at splitting arguments", "YAML/Jinja2 parsing error"),
        ("undefined variable", "Undefined variable error"),
        ("Invalid data passed to 'loop'", "Invalid loop data"),
        # ... more patterns
    ]
    
    for pattern, description in playbook_bug_patterns:
        if pattern in output:
            return False, f"Playbook bug: {description}"
    
    # Check for fatal errors in ignored tasks
    if "fatal:" in output and "...ignoring" in output:
        return False, "Fatal error in ignored task - playbook bug"
    
    return True, output
```

**Detects:**
- Jinja2 template errors during execution
- YAML parsing errors
- Undefined variables
- Fatal errors in ignored tasks (indicates playbook bug)

**On Failure**: Regenerate playbook with execution error details

#### Stage 4: Data Collection Sufficiency Check

```python
def analyze_data_collection(playbook_output: str, requirements: list) -> tuple[bool, str]:
    """Check if playbook collected sufficient data."""
    
    # AI analyzes:
    # 1. Were all required commands executed successfully?
    # 2. Is output data present (even if empty)?
    # 3. Are status values correctly evaluated?
    
    analysis_prompt = f"""
    Check if the playbook collected sufficient data:
    
    Requirements: {requirements}
    Playbook Output: {playbook_output}
    
    Determine:
    - DATA_COLLECTION: PASS if all commands executed and data collected
    - DATA_COLLECTION: FAIL if commands failed or data is missing
    """
    
    result = llm.analyze(analysis_prompt)
    
    if "DATA_COLLECTION: FAIL" in result:
        return False, result
    return True, result
```

**Key Principle**: Empty output is **sufficient data** (meaning "not found"), but command failures are **insufficient data**.

**On Failure**: Regenerate playbook to fix data collection issues

#### Stage 5: AI Compliance Analysis

```python
def analyze_playbook_output(
    requirements: list,
    playbook_objective: str,
    test_output: str,
    audit_procedure: str
) -> tuple[bool, str]:
    """AI analyzes compliance based on CIS benchmark and requirements."""
    
    analysis_prompt = f"""
    Analyze playbook output for CIS compliance:
    
    Objective: {playbook_objective}
    Requirements: {requirements}
    Audit Procedure: {audit_procedure}
    Playbook Output: {test_output}
    
    Provide:
    1. DATA COLLECTION: PASS/FAIL
    2. COMPLIANCE ANALYSIS: PASS/FAIL with detailed reasoning
    3. Status alignment verification
    """
    
    analysis_result = llm.analyze(analysis_prompt)
    
    # Extract statuses
    data_collection_pass = "DATA_COLLECTION: PASS" in analysis_result
    compliance_pass = "COMPLIANCE_ANALYSIS: PASS" in analysis_result
    
    # Verify status alignment
    status_aligned = verify_status_alignment(test_output, analysis_result)
    
    all_pass = data_collection_pass and compliance_pass and status_aligned
    
    return all_pass, analysis_result
```

**Analyzes:**
- Collected data vs. CIS benchmark requirements
- Playbook's status determination vs. AI's interpretation
- Overall compliance logic alignment

**On Failure**: Regenerate playbook to align with CIS requirements and AI analysis

#### Stage 6: Final Execution on Target Host

Once all validations pass on the test host, the playbook is executed on the target/production host and analyzed one final time.

**Complete Validation Flow:**
1. ✅ Syntax check → If fail: Regenerate
2. ✅ Structure analysis → If fail: Regenerate
3. ✅ Test execution → If fail: Regenerate
4. ✅ Data sufficiency → If fail: Regenerate
5. ✅ Compliance analysis → If fail: Regenerate
6. ✅ Final execution → Success!

## Automation: Processing All Checkpoints

For organizations needing to audit all CIS checkpoints, we provide an automated script:

```python
# auto_rhel9_cis_playbook.py
def main():
    # 1. Extract all checkpoint indices from PDF
    checkpoints = extract_checkpoint_indices(PDF_PATH)
    
    # 2. Process each checkpoint
    for checkpoint in checkpoints:
        try:
            # Get checkpoint info via RAG
            checkpoint_info = get_checkpoint_info_with_agent(
                vector_store, checkpoint
            )
            
            # Generate requirements
            requirements = generate_playbook_requirements_from_checkpoint(
                checkpoint_info
            )
            
            # Generate playbook
            playbook_path = run_playbook_generation(
                requirements, checkpoint_info
            )
            
            # Test playbook
            success, output = test_playbook_on_server(
                playbook_path, target_host
            )
            
            if not success:
                # Retry with error message
                playbook_path = run_playbook_generation(
                    requirements, checkpoint_info, 
                    previous_error=output
                )
                
        except Exception as e:
            log_failed_checkpoint(checkpoint, str(e))
            continue
```

## Results and Benefits

### Time Savings
- **Manual approach**: 2-4 hours per checkpoint × 300+ checkpoints = **600-1200 hours**
- **Automated approach**: ~5 minutes per checkpoint (including testing) = **~25 hours**
- **Time saved**: **95%+ reduction**

### Quality Improvements
- **Consistency**: All playbooks follow the same structure and best practices
- **Completeness**: No missed checkpoints or incomplete audit procedures
- **Error handling**: Standardized error handling and status determination
- **Documentation**: Each playbook includes CIS checkpoint metadata

### Maintainability
- **Version control**: All generated playbooks are version-controlled
- **Regeneration**: Easy to regenerate playbooks when benchmark is updated
- **Customization**: Generated playbooks can be customized for specific environments

## Technical Stack

- **Python 3.9+**: Core language
- **LangChain**: RAG framework and agent orchestration
- **Chroma**: Vector database for embeddings
- **HuggingFace**: Embeddings model (all-MiniLM-L6-v2)
- **DeepSeek AI**: LLM for checkpoint extraction and playbook generation
- **Ansible**: Target automation framework
- **PyPDFLoader**: PDF document loading

## Challenges and Solutions

### Challenge 1: Incomplete Script Extraction
**Problem**: Bash scripts in the PDF sometimes span multiple chunks, leading to incomplete extraction.

**Solution**: 
- Increased chunk size to 2000 characters
- Added 500-character overlap
- Agent searches multiple times and combines results
- Explicit instructions to extract complete scripts

### Challenge 2: YAML/Jinja2 Syntax Conflicts
**Problem**: Bash scripts contain `{{`, `}}`, `$`, and other characters that conflict with YAML/Jinja2.

**Solution**:
- Use `{% raw %}` and `{% endraw %}` tags
- Move Ansible variable assignments outside raw blocks
- Use simpler bash syntax inside raw blocks
- Avoid special characters in comments

### Challenge 3: Complex Conditional Logic
**Problem**: Some audit procedures have complex conditional logic (e.g., "If X is empty, check Y; else if Z matches pattern, check W").

**Solution**:
- Detailed prompt engineering with examples
- Use Jinja2 `{% set %}` and `{% if %}` blocks for complex logic
- Folded block scalars (`>-`) for multi-line Jinja2 expressions

### Challenge 4: Playbook Bug Detection
**Problem**: Distinguishing between playbook bugs (syntax errors) and compliance failures (system not compliant).

**Solution**:
- Pattern matching for known playbook bug indicators
- Separate handling for fatal errors in ignored tasks
- Automatic regeneration with error context

## Future Enhancements

1. **Remediation Playbooks**: Generate remediation playbooks in addition to audit playbooks
2. **Profile-Specific Generation**: Generate different playbooks for Level 1 vs Level 2, Server vs Workstation
3. **Compliance Reporting**: Enhanced reporting with trend analysis and compliance dashboards
4. **Multi-OS Support**: Extend to other CIS benchmarks (Ubuntu, Windows, etc.)
5. **Integration**: Integrate with compliance management platforms (OpenSCAP, InSpec, etc.)

## Conclusion

By combining RAG, AI-powered code generation, and careful prompt engineering, we've created a system that dramatically reduces the effort required to convert CIS benchmarks into executable Ansible playbooks. The system handles complex bash scripts, conditional logic, and edge cases that would be difficult to address manually.

The generated playbooks are production-ready, tested, and follow Ansible best practices. Organizations can now focus on running audits and addressing compliance issues rather than spending weeks writing playbooks.

## Getting Started

If you're interested in using this system:

1. **Clone the repository**: [Repository URL]
2. **Install dependencies**: `pip install -r requirements.txt`
3. **Set up environment variables**: Create `.env` with `DEEPSEEK_API_KEY`
4. **Run for a single checkpoint**:
   ```bash
   python3 single_rhel9_cis_checkpoint_to_playbook.py --checkpoint "1.1.1.1"
   ```
5. **Run for all checkpoints**:
   ```bash
   python3 auto_rhel9_cis_playbook.py --output-dir ./playbooks
   ```

## References

- [CIS RHEL 9 Benchmark](https://www.cisecurity.org/benchmark/red_hat_linux)
- [Ansible Documentation](https://docs.ansible.com/)
- [LangChain Documentation](https://python.langchain.com/)
- [DeepSeek AI](https://www.deepseek.com/)

---

*This blog post was written to document the technical approach and implementation details of our CIS RHEL 9 playbook generation system. For questions or contributions, please open an issue or pull request.*

