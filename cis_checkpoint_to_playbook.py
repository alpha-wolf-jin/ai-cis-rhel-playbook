#!/usr/bin/env python3
"""
CIS Checkpoint to Ansible Playbook Generator

This script:
1. Queries the CIS RHEL 8 Benchmark using RAG to get checkpoint audit info
2. Uses DeepSeek AI to generate playbook requirements based on the checkpoint
3. Generates an Ansible playbook to audit the CIS checkpoint
4. Optionally executes the playbook on the target host

Usage:
    python3 cis_checkpoint_to_playbook.py --checkpoint "1.1.1.1"
    python3 cis_checkpoint_to_playbook.py --checkpoint "1.1.1.1 Ensure cramfs kernel module is not available" --target-host 192.168.122.16
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Vector Store Setup (from cis_rhel8_rag_deepseek.py)
# =============================================================================

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# Configuration - Use same directory as cis_rhel8_rag_deepseek.py
VECTOR_STORE_DIR = Path(__file__).parent / "CIS_RHEL8_DATA_DEEPSEEK"
PDF_PATH = "resources/CIS_Red_Hat_Enterprise_Linux_8_Benchmark_v4.0.0.pdf"

# Use HuggingFace embeddings (same as cis_rhel8_rag_deepseek.py)
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={'device': 'cpu'},
    encode_kwargs={'normalize_embeddings': True}
)

def load_or_create_vector_store():
    """Load existing vector store or create new one from PDF."""
    
    if (VECTOR_STORE_DIR / "chroma.sqlite3").exists():
        print(f"Loading existing vector store from {VECTOR_STORE_DIR}...")
        vector_store = Chroma(
            persist_directory=str(VECTOR_STORE_DIR),
            embedding_function=embeddings
        )
        doc_count = vector_store._collection.count()
        print(f"Vector store loaded with {doc_count} documents")
        
        if doc_count == 0:
            print("⚠️  WARNING: Vector store exists but has 0 documents!")
            print("    Deleting empty vector store and recreating...")
            import shutil
            shutil.rmtree(VECTOR_STORE_DIR)
            VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
        else:
            # Test search to verify it works
            try:
                test_results = vector_store.similarity_search("CIS benchmark", k=1)
                if test_results:
                    print(f"✅ Vector store verified - test search returned results")
                else:
                    print("⚠️  WARNING: Test search returned no results")
            except Exception as e:
                print(f"⚠️  WARNING: Test search failed: {e}")
            return vector_store
    
    # Create new vector store from PDF
    print("No existing vector store found. Creating from PDF...")
    
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    
    print(f"Loading CIS RHEL 8 Benchmark PDF from {PDF_PATH}...")
    loader = PyPDFLoader(PDF_PATH)
    data = loader.load()
    print(f"Loaded {len(data)} pages from CIS benchmark document")
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500, chunk_overlap=300, add_start_index=True
    )
    all_splits = text_splitter.split_documents(data)
    print(f"Created {len(all_splits)} document chunks")
    
    print(f"Building and persisting vector store to {VECTOR_STORE_DIR}...")
    vector_store = Chroma.from_documents(
        documents=all_splits,
        embedding=embeddings,
        persist_directory=str(VECTOR_STORE_DIR)
    )
    print("Vector store created and saved")
    
    return vector_store


# =============================================================================
# CIS Checkpoint Search - Using Agent-based RAG (like cis_rhel8_rag_deepseek.py)
# =============================================================================

def create_cis_search_tool(vector_store):
    """Create a search tool for the CIS benchmark vector store."""
    from langchain_core.tools import tool
    
    @tool
    def search_cis_benchmark(query: str) -> str:
        """Search the CIS RHEL 8 Benchmark document for security control information.
        
        Use this tool to find:
        - Audit procedures for specific CIS controls
        - Remediation steps for security configurations
        - Profile applicability (Level 1/Level 2, Server/Workstation)
        - Rationale for security recommendations
        
        Args:
            query: The CIS control number (e.g., '1.1.1.1') or description to search for
        """
        results = vector_store.similarity_search(query, k=4)
        # Combine top results for more comprehensive context
        combined_content = "\n\n---\n\n".join([doc.page_content for doc in results])
        return combined_content
    
    return search_cis_benchmark


def get_checkpoint_info_with_agent(vector_store, checkpoint: str, verbose: bool = False) -> dict:
    """
    Use an agent-based RAG approach to get checkpoint information.
    This mirrors the approach in cis_rhel8_rag_deepseek.py which works better.
    
    Args:
        vector_store: The Chroma vector store
        checkpoint: The CIS checkpoint ID/description
        verbose: If True, print debug information
        
    Returns:
        dict: Structured checkpoint information
    """
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    
    # Create the search tool
    search_tool = create_cis_search_tool(vector_store)
    
    # Create the LLM
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        temperature=0
    )
    
    # Create agent with system prompt optimized for extracting structured info
    system_prompt = """You are a CIS RHEL 8 security expert. Your task is to find and extract detailed information about a specific CIS checkpoint.

When asked about a checkpoint:
1. Use the search tool to find information about the checkpoint
2. Search multiple times if needed - try different queries like:
   - The checkpoint number (e.g., "1.1.1.2")
   - The checkpoint with "Ensure" (e.g., "1.1.1.2 Ensure")
   - Keywords from the checkpoint (e.g., "freevxfs kernel module")
3. Extract ALL relevant information including:
   - Profile Applicability (Level 1/Level 2, Server/Workstation)
   - Description
   - Rationale
   - Audit procedure (exact commands)
   - Remediation procedure (exact commands)
   - Impact
   - Default Value

Be thorough and search multiple times to find complete information."""

    agent = create_agent(
        model=llm,
        tools=[search_tool],
        system_prompt=system_prompt
    )
    
    # Query the agent for checkpoint information
    query = f"""Find and extract ALL information about CIS checkpoint {checkpoint}.

I need the following in your response (use the search tool multiple times if needed):
1. Checkpoint ID (exact number like 1.1.1.2)
2. Title (e.g., "Ensure freevxfs kernel module is not available")
3. Profile Applicability (Level 1 or Level 2, Server or Workstation)
4. Description (what this control does)
5. Rationale (why this is important for security)
6. COMPLETE Audit procedure (include ALL shell commands exactly as shown)
7. COMPLETE Remediation procedure (include ALL shell commands exactly as shown)
8. Impact (if any)
9. Default Value (if mentioned)

Search for "{checkpoint}" and related terms to find all the details."""

    if verbose:
        print(f"🔍 DEBUG: Querying agent for checkpoint: {checkpoint}")
    
    response = agent.invoke(
        {"messages": [HumanMessage(content=query)]}
    )
    
    # Get the agent's response
    agent_response = response["messages"][-1].content
    
    if verbose:
        print(f"🔍 DEBUG: Agent response length: {len(agent_response)} characters")
        print("\n" + "-"*50 + " AGENT RESPONSE " + "-"*50)
        print(agent_response[:3000] if len(agent_response) > 3000 else agent_response)
        print("-"*120 + "\n")
    
    return agent_response


def search_cis_checkpoint(vector_store, checkpoint: str, verbose: bool = False) -> str:
    """
    Search the CIS RHEL 8 Benchmark for checkpoint information.
    Falls back to direct search if agent approach fails.
    
    Args:
        vector_store: The Chroma vector store
        checkpoint: The CIS control number or description
        verbose: If True, print raw search results for debugging
        
    Returns:
        str: Combined content from relevant documents
    """
    import re
    
    # Extract checkpoint ID if present (e.g., "1.1.1.1" from "1.1.1.1 Ensure cramfs...")
    checkpoint_id_match = re.match(r'^(\d+\.\d+\.\d+\.?\d*)', checkpoint)
    checkpoint_id = checkpoint_id_match.group(1) if checkpoint_id_match else checkpoint
    
    # Build multiple search queries for better coverage
    enhanced_queries = []
    
    # Primary queries - most specific
    if checkpoint_id_match:
        enhanced_queries.extend([
            f"{checkpoint_id} Ensure",
            f"checkpoint {checkpoint_id}",
            f"{checkpoint_id} kernel module",
            f"{checkpoint_id} freevxfs",  # Common for 1.1.1.x
            f"{checkpoint_id} Audit",
            f"{checkpoint_id} Remediation",
        ])
    
    # Add the original query
    enhanced_queries.append(checkpoint)
    
    # Generic CIS-related queries
    enhanced_queries.extend([
        f"CIS {checkpoint_id}" if checkpoint_id_match else f"CIS {checkpoint}",
        f"Profile Applicability {checkpoint_id}" if checkpoint_id_match else checkpoint,
    ])
    
    # Remove duplicates while preserving order
    seen = set()
    unique_queries = []
    for q in enhanced_queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)
    
    if verbose:
        print(f"\n🔍 DEBUG: Checkpoint ID extracted: {checkpoint_id}")
        print(f"🔍 DEBUG: Search queries to try: {unique_queries}")
    
    # Collect results from multiple queries
    all_results = []
    seen_content = set()
    
    for query in unique_queries:
        try:
            results = vector_store.similarity_search(query, k=4)
            if verbose:
                print(f"🔍 DEBUG: Query '{query}' returned {len(results)} results")
            for doc in results:
                # Deduplicate by content hash (use more of the content for better dedup)
                content_hash = hash(doc.page_content[:500])
                if content_hash not in seen_content:
                    seen_content.add(content_hash)
                    all_results.append(doc)
        except Exception as e:
            if verbose:
                print(f"🔍 DEBUG: Query '{query}' failed: {e}")
    
    # Sort results by relevance to checkpoint_id (if found in content)
    def relevance_score(doc):
        content = doc.page_content.lower()
        score = 0
        if checkpoint_id.lower() in content:
            score += 10
        if "ensure" in content and checkpoint_id.lower() in content:
            score += 5
        if "audit" in content:
            score += 2
        if "remediation" in content:
            score += 2
        return -score  # Negative for descending sort
    
    all_results.sort(key=relevance_score)
    
    # Limit to top 10 unique results
    all_results = all_results[:10]
    
    combined_content = "\n\n---\n\n".join([doc.page_content for doc in all_results])
    
    if verbose:
        print(f"\n🔍 DEBUG: Total unique document chunks found: {len(all_results)}")
        print(f"🔍 DEBUG: Combined content length: {len(combined_content)} characters")
        print("\n" + "-"*50 + " RAW CONTENT PREVIEW " + "-"*50)
        # Show full content in verbose mode
        print(combined_content[:5000] if len(combined_content) > 5000 else combined_content)
        print("-"*120 + "\n")
    
    # Always show a warning if no content found
    if len(combined_content) < 100:
        print("⚠️  WARNING: Very little content retrieved from vector store!")
        print("    Make sure CIS_RHEL8_DATA_DEEPSEEK directory has the vector database.")
        print("    You may need to run cis_rhel8_rag_deepseek.py first to create the vector store.")
    
    return combined_content


def parse_agent_response_to_checkpoint_info(checkpoint: str, agent_response: str) -> dict:
    """
    Parse the agent's natural language response into a structured dictionary.
    
    Args:
        checkpoint: The original checkpoint query
        agent_response: The agent's response text
        
    Returns:
        dict: Structured checkpoint information
    """
    import re
    
    # Initialize with defaults
    info = {
        'checkpoint_id': checkpoint,
        'title': '',
        'profile_applicability': '',
        'description': '',
        'rationale': '',
        'audit_procedure': '',
        'remediation_procedure': '',
        'impact': '',
        'default_value': '',
        'references': ''
    }
    
    # Extract checkpoint ID from response
    id_match = re.search(r'(\d+\.\d+\.\d+\.?\d*)', agent_response)
    if id_match:
        info['checkpoint_id'] = id_match.group(1)
    
    # Helper function to extract section content
    def extract_section(text, section_names, next_sections=None):
        """Extract content between section header and next section."""
        for name in section_names:
            # Try different patterns
            patterns = [
                rf'\*\*{name}\*\*[:\s]*\n?(.*?)(?=\*\*[A-Z]|\n\n\n|$)',
                rf'{name}[:\s]*\n(.*?)(?=\n[A-Z][a-z]+:|$)',
                rf'#{1,3}\s*{name}[:\s]*\n?(.*?)(?=#{1,3}|$)',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if match and match.group(1).strip():
                    return match.group(1).strip()
        return ''
    
    # Extract title
    title_patterns = [
        rf'{info["checkpoint_id"]}[:\s]*(Ensure[^\n]+)',
        r'\*\*Title\*\*[:\s]*([^\n]+)',
        r'Title[:\s]*([^\n]+)',
    ]
    for pattern in title_patterns:
        match = re.search(pattern, agent_response, re.IGNORECASE)
        if match:
            info['title'] = match.group(1).strip()
            break
    
    # If no title found, try to extract from first line mentioning "Ensure"
    if not info['title']:
        ensure_match = re.search(r'(Ensure[^\n\.]+)', agent_response)
        if ensure_match:
            info['title'] = ensure_match.group(1).strip()
    
    # Extract other sections
    info['profile_applicability'] = extract_section(
        agent_response, 
        ['Profile Applicability', 'Profile', 'Applicability']
    )
    
    info['description'] = extract_section(
        agent_response,
        ['Description']
    )
    
    info['rationale'] = extract_section(
        agent_response,
        ['Rationale', 'Why', 'Security Rationale']
    )
    
    info['audit_procedure'] = extract_section(
        agent_response,
        ['Audit', 'Audit Procedure', 'How to Audit', 'Audit Commands']
    )
    
    info['remediation_procedure'] = extract_section(
        agent_response,
        ['Remediation', 'Remediation Procedure', 'How to Remediate', 'Fix']
    )
    
    info['impact'] = extract_section(
        agent_response,
        ['Impact']
    )
    
    info['default_value'] = extract_section(
        agent_response,
        ['Default Value', 'Default']
    )
    
    # If critical fields are empty, store the full agent response
    if not info['audit_procedure'] or not info['title']:
        info['raw_agent_response'] = agent_response
    
    return info


def get_checkpoint_info_with_ai(checkpoint: str, raw_content: str) -> dict:
    """
    Use DeepSeek AI to extract structured checkpoint information.
    
    Args:
        checkpoint: The CIS checkpoint ID/description
        raw_content: Raw content from vector search
        
    Returns:
        dict: Structured checkpoint information
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        temperature=0
    )
    
    prompt_template = """You are a CIS RHEL 8 security expert. Analyze the following content extracted from the CIS Benchmark PDF document and extract structured information about the requested checkpoint.

**Requested Checkpoint:** {checkpoint}

**Raw Content from CIS Benchmark (may contain multiple document chunks):**
{raw_content}

**Task:** 
Carefully read through ALL the raw content above. The information may be split across multiple chunks separated by "---". Look for:
- The checkpoint number (e.g., "1.1.1.1")
- Title starting with "Ensure" or similar
- Sections labeled "Profile Applicability", "Description", "Rationale", "Audit", "Remediation", "Impact", "Default Value", "References"
- Shell commands in the Audit and Remediation sections

Extract and return a JSON object with this structure:
{{
    "checkpoint_id": "The exact checkpoint ID (e.g., 1.1.1.1)",
    "title": "The full title (e.g., 'Ensure cramfs kernel module is not available')",
    "profile_applicability": "Level 1 or Level 2, Server/Workstation (look for 'Profile Applicability' section)",
    "description": "Brief description of what this control does",
    "rationale": "Why this control is important for security (look for 'Rationale' section)",
    "audit_procedure": "The COMPLETE audit commands/steps - include ALL shell commands exactly as shown",
    "remediation_procedure": "The COMPLETE remediation commands/steps - include ALL shell commands exactly as shown",
    "impact": "Any potential impact (look for 'Impact' section)",
    "default_value": "The default system value (look for 'Default Value' section)",
    "references": "Any CIS or other references"
}}

**Critical Instructions:**
1. Search through ALL chunks in the raw content - the information may be spread across multiple sections
2. For audit_procedure and remediation_procedure, include the COMPLETE shell commands exactly as written
3. Look for patterns like "Run the following command" or "# " prefix for commands
4. If a section says "None" or is empty, use that value
5. If information truly cannot be found in any chunk, use "Not found in provided content"
6. Return ONLY valid JSON, no markdown code blocks

Generate the JSON now:"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm
    
    response = chain.invoke({
        'checkpoint': checkpoint,
        'raw_content': raw_content
    })
    
    response_text = response.content.strip()
    
    # Clean up response - remove markdown code blocks if present
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()
    
    try:
        result = json.loads(response_text)
        # Check if AI couldn't find the info - fall back to raw content
        not_found_indicators = ['not found', 'not specified', 'unable to find', 'no information']
        fields_not_found = sum(1 for v in result.values() 
                               if isinstance(v, str) and any(ind in v.lower() for ind in not_found_indicators))
        
        if fields_not_found >= 5:  # Most fields not found
            print("⚠️  AI extraction found limited information. Using raw content as fallback.")
            print("    TIP: Try with full checkpoint description for better results.")
            result['raw_content_preview'] = raw_content[:3000]
            # Try to extract basic info from raw content directly
            import re
            # Look for checkpoint title pattern
            title_match = re.search(rf'{re.escape(checkpoint)}[^\n]*Ensure[^\n]+', raw_content, re.IGNORECASE)
            if title_match:
                result['title'] = title_match.group(0).strip()
            # Look for audit section
            audit_match = re.search(r'Audit[:\s]*\n(.*?)(?=Remediation|$)', raw_content, re.DOTALL | re.IGNORECASE)
            if audit_match:
                result['audit_procedure'] = audit_match.group(1).strip()[:2000]
            # Look for remediation section
            remed_match = re.search(r'Remediation[:\s]*\n(.*?)(?=Impact|Default|References|$)', raw_content, re.DOTALL | re.IGNORECASE)
            if remed_match:
                result['remediation_procedure'] = remed_match.group(1).strip()[:2000]
        return result
    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse JSON response: {e}")
        print(f"Response was: {response_text[:500]}...")
        return {
            'checkpoint_id': checkpoint,
            'title': 'Unable to parse AI response',
            'audit_procedure': raw_content[:2000],
            'remediation_procedure': 'See raw content above',
            'raw_content_preview': raw_content[:3000]
        }


# =============================================================================
# Playbook Requirements Generation (adapted from kcs_to_playbook.py)
# =============================================================================

def generate_playbook_requirements_from_checkpoint(checkpoint_info: dict) -> dict:
    """
    Use DeepSeek AI to generate playbook requirements based on CIS checkpoint info.
    
    Args:
        checkpoint_info: Dict containing checkpoint details
        
    Returns:
        dict: {
            'objective': str,
            'requirements': list[str]
        }
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.prompts import ChatPromptTemplate
    
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        temperature=0
    )
    
    # Get raw agent response if available (this contains the full details from agent search)
    raw_agent_response = checkpoint_info.get('raw_agent_response', '')
    
    # Build the prompt - include raw agent response if we have it
    additional_context = ""
    if raw_agent_response:
        additional_context = f"""
**Full Agent Response (contains complete checkpoint details):**
{raw_agent_response[:6000]}
"""
    
    prompt_template = """You are an expert system administrator creating Ansible playbooks for CIS benchmark compliance auditing.

Based on the following CIS checkpoint information, generate:
1. A clear playbook objective (one sentence) focused on AUDITING this security control
2. A list of 3-8 specific requirements for an Ansible playbook

**CIS Checkpoint Information:**
- Checkpoint ID: {checkpoint_id}
- Title: {title}
- Profile Applicability: {profile_applicability}
- Description: {description}
- Rationale: {rationale}

**Audit Procedure from CIS Benchmark:**
{audit_procedure}

**Remediation Procedure from CIS Benchmark:**
{remediation_procedure}
{additional_context}
**Task:**
Generate Ansible playbook requirements that will:
1. AUDIT the system to check if it complies with this CIS checkpoint
2. COLLECT the current system state/configuration
3. COMPARE against the expected values from CIS benchmark
4. REPORT compliance status (PASS/FAIL) with details

**Output Format:**
Return ONLY a valid JSON object with this exact structure (no markdown, no code blocks):
{{
    "objective": "Audit CIS checkpoint {checkpoint_id}: {title}",
    "requirements": [
        "Check <condition> using command: `<command>`. Rationale: PASS when <expected result>, FAIL when <failure condition>",
        "Verify <setting> with command: `<command>`. Rationale: PASS when <expected>, FAIL otherwise",
        ...
    ]
}}

**Important Guidelines:**
- Base requirements DIRECTLY on the audit procedure commands from the checkpoint information
- Include the exact commands from the CIS benchmark audit procedure
- Focus on AUDITING (checking compliance), not remediation
- Each requirement should map to a specific audit step
- CRITICAL: Each requirement MUST end with "Rationale: PASS when <condition>, FAIL when <condition>" explaining the pass/fail logic
- Include expected values/outputs for comparison
- If the Full Agent Response is provided, extract the audit commands from there

Generate the JSON now:"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm
    
    response = chain.invoke({
        'checkpoint_id': checkpoint_info.get('checkpoint_id', 'Unknown'),
        'title': checkpoint_info.get('title', '') or 'Unknown',
        'profile_applicability': checkpoint_info.get('profile_applicability', '') or 'Not specified',
        'description': checkpoint_info.get('description', '') or 'Not specified',
        'additional_context': additional_context,
        'rationale': checkpoint_info.get('rationale', '') or 'See Full Agent Response above',
        'audit_procedure': checkpoint_info.get('audit_procedure', '') or 'See Full Agent Response above',
        'remediation_procedure': checkpoint_info.get('remediation_procedure', '') or 'See Full Agent Response above'
    })
    
    response_text = response.content.strip()
    
    # Clean up response
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()
    
    try:
        result = json.loads(response_text)
        return result
    except json.JSONDecodeError as e:
        print(f"Warning: Failed to parse JSON response: {e}")
        return {
            'objective': f"Audit CIS checkpoint: {checkpoint_info.get('checkpoint_id', 'Unknown')}",
            'requirements': [
                "Check system configuration",
                "Verify compliance with CIS benchmark",
                "Report PASS or FAIL status"
            ]
        }


def run_playbook_generation(objective, requirements, target_host, test_host, become_user, filename, skip_execution=True):
    """
    Call langgraph_deepseek_generate_playbook.py to generate and execute the playbook.
    """
    print("\n" + "="*100)
    if skip_execution:
        print("🔧 Calling langgraph_deepseek_generate_playbook.py to GENERATE playbook (no execution)...")
    else:
        print("🚀 Calling langgraph_deepseek_generate_playbook.py to generate and execute playbook...")
    print("="*100)
    
    max_retries = max(len(requirements), 3)
    print(f"Max retries: {max_retries} (based on {len(requirements)} requirements)")
    
    cmd = [
        'python3',
        'langgraph_deepseek_generate_playbook.py',
        '--objective', objective,
        '--target-host', target_host,
        '--become-user', become_user,
        '--filename', filename,
        '--max-retries', str(max_retries)
    ]
    
    if test_host and test_host != target_host:
        cmd.extend(['--test-host', test_host])
    
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
    print("="*100)
    print()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=False,
            text=True,
            timeout=600
        )
        
        return result.returncode == 0, "Playbook generation completed"
        
    except subprocess.TimeoutExpired:
        return False, "Playbook generation timed out after 10 minutes"
    except Exception as e:
        return False, f"Error running playbook generation: {str(e)}"


# =============================================================================
# Interactive Mode
# =============================================================================

def interactive_mode(vector_store, args):
    """Interactive mode to query CIS checkpoints and generate playbooks."""
    print("\n" + "="*70)
    print("CIS RHEL 8 Checkpoint to Ansible Playbook Generator")
    print("="*70)
    print("\nEnter CIS checkpoint IDs to generate audit playbooks.")
    print("Examples:")
    print("  - 1.1.1.1")
    print("  - 1.1.1.1 Ensure cramfs kernel module is not available")
    print("  - 5.2.1 Ensure permissions on /etc/ssh/sshd_config are configured")
    print("\nType 'quit' or 'exit' to stop.\n")
    
    while True:
        try:
            checkpoint = input("Enter checkpoint (or 'quit'): ").strip()
            
            if not checkpoint:
                continue
            
            if checkpoint.lower() in ['quit', 'exit', 'q']:
                print("\nGoodbye!")
                break
            
            process_checkpoint(vector_store, checkpoint, args)
            
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


def process_checkpoint(vector_store, checkpoint: str, args):
    """Process a single CIS checkpoint and generate playbook."""
    
    verbose = getattr(args, 'verbose', False)
    
    # Step 1 & 2 Combined: Use Agent-based RAG to get checkpoint info (like cis_rhel8_rag_deepseek.py)
    print("\n" + "="*100)
    print(f"STEP 1: Querying CIS RHEL 8 Benchmark using Agent RAG for: '{checkpoint}'")
    print("="*100)
    print("Using agent-based search (same approach as cis_rhel8_rag_deepseek.py)...")
    
    # Use agent to get checkpoint info - this works better than direct search
    agent_response = get_checkpoint_info_with_agent(vector_store, checkpoint, verbose=verbose)
    
    # Step 2: Parse the agent response into structured format
    print("\n" + "="*100)
    print("STEP 2: Parsing checkpoint information from agent response")
    print("="*100)
    
    checkpoint_info = parse_agent_response_to_checkpoint_info(checkpoint, agent_response)
    
    print(f"\n📋 CIS Checkpoint Details:")
    print("-"*100)
    print(f"ID: {checkpoint_info.get('checkpoint_id', 'N/A')}")
    print(f"Title: {checkpoint_info.get('title', 'N/A') or 'See agent response below'}")
    print(f"Profile: {checkpoint_info.get('profile_applicability', 'N/A') or 'See agent response below'}")
    print(f"\nDescription: {checkpoint_info.get('description', 'N/A') or 'See agent response below'}")
    print(f"\nRationale: {checkpoint_info.get('rationale', 'N/A') or 'See agent response below'}")
    
    # Check if we have parsed audit procedure or need to show raw response
    audit_proc = checkpoint_info.get('audit_procedure', '')
    remed_proc = checkpoint_info.get('remediation_procedure', '')
    raw_response = checkpoint_info.get('raw_agent_response', '')
    
    if audit_proc:
        print("\n" + "-"*100)
        print("🔍 AUDIT PROCEDURE:")
        print("-"*100)
        if len(audit_proc) > 2000:
            print(audit_proc[:2000] + "\n... (truncated)")
        else:
            print(audit_proc)
    
    if remed_proc:
        print("\n" + "-"*100)
        print("🔧 REMEDIATION PROCEDURE:")
        print("-"*100)
        if len(remed_proc) > 2000:
            print(remed_proc[:2000] + "\n... (truncated)")
        else:
            print(remed_proc)
    
    # If parsing didn't extract key fields, show the full agent response
    if raw_response or (not audit_proc and not remed_proc):
        print("\n" + "-"*100)
        print("📝 FULL AGENT RESPONSE (use this for requirements):")
        print("-"*100)
        response_to_show = raw_response or agent_response
        if len(response_to_show) > 4000:
            print(response_to_show[:4000] + "\n... (truncated)")
        else:
            print(response_to_show)
        # Store the agent response in checkpoint_info for use in requirements generation
        checkpoint_info['raw_agent_response'] = response_to_show
    print("-"*100)
    
    # Step 3: Generate playbook requirements
    print("\n" + "="*100)
    print("STEP 3: Generating playbook requirements using DeepSeek AI")
    print("="*100)
    
    playbook_spec = generate_playbook_requirements_from_checkpoint(checkpoint_info)
    
    objective = playbook_spec.get('objective', '')
    requirements = playbook_spec.get('requirements', [])
    
    print(f"\n📋 Generated Playbook Specification:")
    print("-"*100)
    print(f"Objective: {objective}")
    print(f"\nRequirements ({len(requirements)} items):")
    for idx, req in enumerate(requirements, 1):
        print(f"  {idx}. {req}")
    print("-"*100)
    
    # Interactive requirement review (unless --no-interactive)
    if not args.no_interactive:
        print("\n" + "="*100)
        print("📝 REQUIREMENT REVIEW AND FEEDBACK")
        print("="*100)
        print("Options:")
        print("  1. Press ENTER to generate playbook")
        print("  2. Type 'add' to add new requirements")
        print("  3. Type 'edit N' to edit requirement N")
        print("  4. Type 'delete N' to delete requirement N")
        print("  5. Type 'skip' to skip playbook generation")
        print("  6. Type 'help' for more commands")
        print("="*100)
        
        while True:
            user_input = input("\n👤 Your action (ENTER to generate, 'skip' to skip): ").strip()
            
            if not user_input:
                print("\n✅ Generating playbook...")
                break
            
            if user_input.lower() == 'skip':
                print("\n⏭️  Skipping playbook generation for this checkpoint")
                return
            
            if user_input.lower() == 'done':
                print("\n📋 Updated Requirements ({} items):".format(len(requirements)))
                for idx, req in enumerate(requirements, 1):
                    print(f"  {idx}. {req}")
                continue
            
            if user_input.lower() == 'add':
                new_req = input("   Enter new requirement: ").strip()
                if new_req:
                    requirements.append(new_req)
                    print(f"   ✅ Added requirement {len(requirements)}: {new_req}")
                continue
            
            if user_input.lower().startswith('edit '):
                try:
                    req_num = int(user_input.split()[1])
                    if 1 <= req_num <= len(requirements):
                        print(f"   Current: {requirements[req_num-1]}")
                        new_text = input("   New text: ").strip()
                        if new_text:
                            requirements[req_num-1] = new_text
                            print(f"   ✅ Updated requirement {req_num}")
                    else:
                        print(f"   ❌ Invalid number. Must be 1-{len(requirements)}")
                except (ValueError, IndexError):
                    print("   ❌ Invalid format. Use: edit N")
                continue
            
            if user_input.lower().startswith('delete '):
                try:
                    req_num = int(user_input.split()[1])
                    if 1 <= req_num <= len(requirements):
                        deleted = requirements.pop(req_num-1)
                        print(f"   ✅ Deleted: {deleted}")
                    else:
                        print(f"   ❌ Invalid number. Must be 1-{len(requirements)}")
                except (ValueError, IndexError):
                    print("   ❌ Invalid format. Use: delete N")
                continue
            
            if user_input.lower() == 'help':
                print("\n📖 Commands: ENTER (generate), skip, add, edit N, delete N, done (show reqs)")
                continue
            
            print("   ❌ Unknown command. Type 'help' for options.")
    
    # Add CIS reference to requirements
    checkpoint_id = checkpoint_info.get('checkpoint_id', checkpoint)
    requirements.append(f"Add comment referencing CIS RHEL 8 Benchmark v4.0.0, checkpoint {checkpoint_id}")
    requirements.append(f"""Create a task named 'Generate compliance report' that displays a debug msg with this EXACT format:
========================================================
        COMPLIANCE REPORT - CIS {checkpoint_id}
========================================================
Reference: CIS RHEL 8 Benchmark v4.0.0 checkpoint {checkpoint_id}
========================================================

REQUIREMENT 1 - <requirement description>:
  Task: <task name>
  Command: <command executed>
  Exit code: <exit code>
  Data: <command output>
  Status: PASS or FAIL
  Rationale: <why PASS or FAIL based on the requirement's rationale>

(repeat for each requirement)

========================================================
OVERALL COMPLIANCE:
  Result: PASS or FAIL
  Rationale: <overall pass/fail logic explanation>
========================================================

Each requirement MUST have Status and Rationale lines. The OVERALL COMPLIANCE section is REQUIRED at the end.""")
    requirements.append("CRITICAL: Use ignore_errors: true and failed_when: false on all audit tasks so all checks complete and report status")
    
    # Step 4: Generate playbook filename
    safe_checkpoint_id = checkpoint_id.replace('.', '_').replace(' ', '_')[:20]
    filename = args.filename if args.filename else f"cis_audit_{safe_checkpoint_id}.yml"
    
    # Step 5: Generate and optionally execute playbook
    print("\n" + "="*100)
    print("STEP 4: Generating Ansible Playbook")
    print("="*100)
    print(f"Target Host:    {args.target_host}")
    print(f"Become User:    {args.become_user}")
    print(f"Output File:    {filename}")
    
    if args.skip_execution:
        print("⚠️  Execution will be SKIPPED (--skip-execution flag)")
    
    success, output = run_playbook_generation(
        objective=objective,
        requirements=requirements,
        target_host=args.target_host,
        test_host=args.test_host if args.test_host else args.target_host,
        become_user=args.become_user,
        filename=filename,
        skip_execution=args.skip_execution
    )
    
    # Summary
    print("\n" + "="*100)
    print("📊 SUMMARY")
    print("="*100)
    
    if success:
        print(f"✅ Successfully generated audit playbook!")
        print(f"\n📋 CIS Checkpoint: {checkpoint_info.get('checkpoint_id', checkpoint)}")
        print(f"📄 Title: {checkpoint_info.get('title', 'N/A')}")
        print(f"📁 Playbook: {filename}")
        print(f"🎯 Target: {args.target_host}")
    else:
        print(f"❌ Playbook generation failed: {output}")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Generate Ansible audit playbooks from CIS RHEL 8 checkpoints',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  python3 cis_checkpoint_to_playbook.py
  
  # Single checkpoint
  python3 cis_checkpoint_to_playbook.py --checkpoint "1.1.1.1"
  
  # With custom target host
  python3 cis_checkpoint_to_playbook.py --checkpoint "1.1.1.1" --target-host 192.168.122.16
  
  # Skip execution (generate only)
  python3 cis_checkpoint_to_playbook.py --checkpoint "5.2.4" --skip-execution
"""
    )
    
    parser.add_argument(
        '--checkpoint', '-c',
        type=str,
        default=None,
        help='CIS checkpoint ID or description (e.g., "1.1.1.1" or "Ensure cramfs kernel module is not available")'
    )
    
    parser.add_argument(
        '--target-host', '-t',
        type=str,
        default='192.168.122.16',
        help='Target host for playbook execution (default: 192.168.122.16)'
    )
    
    parser.add_argument(
        '--test-host',
        type=str,
        default=None,
        help='Test host for validation before target execution'
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
        default=None,
        help='Output filename for the generated playbook (default: cis_audit_<checkpoint>.yml)'
    )
    
    parser.add_argument(
        '--skip-execution',
        action='store_true',
        help='Generate playbook but skip execution'
    )
    
    parser.add_argument(
        '--no-interactive',
        action='store_true',
        help='Skip interactive requirement review'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show verbose output including raw search results for debugging'
    )
    
    args = parser.parse_args()
    
    try:
        # Load vector store
        print("\n" + "="*100)
        print("🔧 Initializing CIS RHEL 8 Benchmark Vector Store")
        print("="*100)
        
        vector_store = load_or_create_vector_store()
        print("✅ Vector store ready")
        
        if args.checkpoint:
            # Single checkpoint mode
            process_checkpoint(vector_store, args.checkpoint, args)
        else:
            # Interactive mode
            interactive_mode(vector_store, args)
            
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

