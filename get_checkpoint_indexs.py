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

load_dotenv()

# =============================================================================
# Vector Store Setup
# =============================================================================

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

# Configuration - Use same directory as cis_checkpoint_to_playbook.py
VECTOR_STORE_DIR = Path(__file__).parent / "CIS_RHEL8_DATA_DEEPSEEK"
PDF_PATH = "resources/CIS_Red_Hat_Enterprise_Linux_8_Benchmark_v4.0.0.pdf"

# Use HuggingFace embeddings
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
    
    # Increased chunk size and overlap to better handle long scripts
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=2000, chunk_overlap=500, add_start_index=True
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
# CIS Checkpoint Index Extraction - Using Agent-based RAG
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
        # Increase k to 10 to ensure we get enough context
        results = vector_store.similarity_search(query, k=10)
        # Combine top results for more comprehensive context
        combined_content = "\n\n---\n\n".join([doc.page_content for doc in results])
        return combined_content
    
    return search_cis_benchmark


def get_all_cis_checkpoint_indices(vector_store, verbose: bool = False) -> list:
    """
    Extract all CIS checkpoint indices from the CIS RHEL 8 Benchmark document.
    Returns a list of checkpoint strings in the same sequence as they appear in the document.
    
    This function uses an agent-based RAG approach similar to get_checkpoint_info_with_agent
    in cis_checkpoint_to_playbook.py.
    
    Args:
        vector_store: The Chroma vector store
        verbose: If True, print debug information
        
    Returns:
        list: List of checkpoint strings like:
            [
                "1.1.1.1 Ensure cramfs kernel module is not available (Automated)",
                "1.2.1.3 Ensure repo_gpgcheck is globally activated (Manual)",
                ...
            ]
    """
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    
    # Create the search tool
    search_tool = create_cis_search_tool(vector_store)
    
    # Create the LLM - Use deepseek-chat for agentic tool use
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        temperature=0
    )
    
    # Create agent with system prompt optimized for extracting checkpoint indices
    system_prompt = """You are a CIS RHEL 8 security expert. Your task is to find and extract ALL CIS checkpoint indices from the benchmark document.

When asked to list all checkpoints:
1. Use the search tool multiple times to search comprehensively:
   - Search for "CIS checkpoint" or "checkpoint" to find checkpoint sections
   - Search for different checkpoint number ranges (e.g., "1.1", "1.2", "2.1", "3.1", "4.1", "5.1")
   - Search for "Ensure" to find checkpoint titles
   - Search for "Profile Applicability" sections which often list checkpoints
   - Search for checkpoint tables or lists in the document
2. Extract checkpoint information in the EXACT format:
   - Checkpoint ID (digits and dots only, e.g., "1.1.1.1", "1.8.3")
   - Title (the "Ensure..." description)
   - Automation status: "(Automated)" or "(Manual)"
3. Maintain the sequence as they appear in the document (by checkpoint ID order).
4. Return a comprehensive list of ALL checkpoints found.

Be thorough and search multiple times to ensure you capture all checkpoints. Search systematically through all major sections."""

    agent = create_agent(
        model=llm,
        tools=[search_tool],
        system_prompt=system_prompt
    )
    
    # Query the agent for all checkpoint indices
    query = """Find and extract ALL CIS checkpoint indices from the CIS RHEL 8 Benchmark document.

I need a complete list of all checkpoints in the format:
"<checkpoint_id> <title> (<Automated|Manual>)"

For example:
- "1.1.1.1 Ensure cramfs kernel module is not available (Automated)"
- "1.2.1.3 Ensure repo_gpgcheck is globally activated (Manual)"
- "1.6.6 Ensure system wide crypto policy disables EtM for ssh (Manual)"
- "1.8.3 Ensure GDM screen lock is configured (Automated)"
- "3.3.2.7 Ensure net.ipv6.conf.all.accept_ra is configured (Automated)"
- "5.1.1 Ensure sshd crypto_policy is not set (Automated)"
- "5.3.3.1.3 Ensure password failed attempts lockout includes root account (Automated)"

**Requirements:**
1. Extract ALL checkpoints from the document - be comprehensive
2. Maintain the sequence as they appear (ordered by checkpoint ID)
3. Include the checkpoint ID (digits and dots only, e.g., "1.1.1.1" or "1.8.3")
4. Include the full title (the "Ensure..." description)
5. Include the automation status: (Automated) or (Manual)
6. Use the search tool multiple times to ensure comprehensive coverage:
   - Search for different sections (1.1, 1.2, 2.1, 3.1, 4.1, 5.1, etc.)
   - Search for "Profile Applicability" sections
   - Search for checkpoint tables or lists
   - Search for "Ensure" to find all checkpoint titles
   - Search systematically through all major sections of the document

Return the list in the exact format shown above, one checkpoint per line. Ensure you capture ALL checkpoints from the entire document."""

    if verbose:
        print(f"🔍 DEBUG: Querying agent for all CIS checkpoint indices...")
        print("This may take several minutes as the agent searches comprehensively...")
    
    response = agent.invoke(
        {"messages": [HumanMessage(content=query)]}
    )
    
    # Get the agent's response
    agent_response = response["messages"][-1].content
    
    if verbose:
        print(f"🔍 DEBUG: Agent response length: {len(agent_response)} characters")
        print("\n" + "-"*50 + " AGENT RESPONSE PREVIEW " + "-"*50)
        print(agent_response[:5000] if len(agent_response) > 5000 else agent_response)
        print("-"*120 + "\n")
    
    # Parse the agent response to extract checkpoint indices
    checkpoint_list = []
    
    # Pattern to match checkpoint lines:
    # Format: "1.1.1.1 Ensure something (Automated)" or "1.8.3 Ensure something (Manual)"
    # The checkpoint must START with digit and dot combination, and END with (Automated) or (Manual)
    # Pattern: starts with digit, then dot, then more digits/dots, space, title, ends with (Automated|Manual)
    pattern = r'(?:^|\n)(\d+\.\d+[\d\.]*)\s+(.+?)\s*\((Automated|Manual)\)'
    
    matches = re.findall(pattern, agent_response, re.MULTILINE | re.IGNORECASE)
    
    for match in matches:
        checkpoint_id = match[0].strip()
        title = match[1].strip()
        automation = match[2].strip()
        # Validate: checkpoint_id must start with digit and contain dots
        if re.match(r'^\d+\.', checkpoint_id):
            checkpoint_str = f"{checkpoint_id} {title} ({automation})"
            checkpoint_list.append(checkpoint_str)
    
    # If regex didn't find matches, try alternative patterns
    if not checkpoint_list:
        # Alternative pattern: more flexible, but still requires start with digit+dot and end with (Automated|Manual)
        alt_pattern = r'(?:^|\s)(\d+\.\d+[\d\.]*)\s+(.+?)\s*\((Automated|Manual)\)'
        matches = re.findall(alt_pattern, agent_response, re.MULTILINE | re.IGNORECASE)
        for match in matches:
            checkpoint_id = match[0].strip()
            title = match[1].strip()
            automation = match[2].strip()
            # Validate: checkpoint_id must start with digit and contain dots
            if re.match(r'^\d+\.', checkpoint_id):
                checkpoint_str = f"{checkpoint_id} {title} ({automation})"
                checkpoint_list.append(checkpoint_str)
    
    # If still no matches, try to extract from markdown lists or numbered lists
    if not checkpoint_list:
        # Pattern for markdown or numbered list format
        # Still requires start with digit+dot and end with (Automated|Manual)
        list_pattern = r'(?:^|\n)[\d\.\-\*]+\s*(\d+\.\d+[\d\.]*)\s+(.+?)\s*\((Automated|Manual)\)'
        matches = re.findall(list_pattern, agent_response, re.MULTILINE | re.IGNORECASE)
        for match in matches:
            checkpoint_id = match[0].strip()
            title = match[1].strip()
            automation = match[2].strip()
            # Validate: checkpoint_id must start with digit and contain dots
            if re.match(r'^\d+\.', checkpoint_id):
                checkpoint_str = f"{checkpoint_id} {title} ({automation})"
                checkpoint_list.append(checkpoint_str)
    
    # Remove duplicates while preserving order
    # Only keep checkpoints that start with digit+dot and end with (Automated) or (Manual)
    seen = set()
    unique_checkpoints = []
    for cp in checkpoint_list:
        # Validate format: must start with digit+dot and end with (Automated) or (Manual)
        if not re.match(r'^\d+\.', cp):
            continue
        if not re.search(r'\((Automated|Manual)\)$', cp):
            continue
        
        # Use checkpoint ID as the key for deduplication
        cp_id_match = re.match(r'(\d+\.\d+[\d\.]*)', cp)
        if cp_id_match:
            cp_id = cp_id_match.group(1)
            if cp_id not in seen:
                seen.add(cp_id)
                unique_checkpoints.append(cp)
    
    # Sort by checkpoint ID to maintain document order
    def sort_key(cp):
        # Extract numeric parts of checkpoint ID for proper sorting
        # Must start with digit+dot
        cp_id_match = re.match(r'(\d+\.\d+[\d\.]*)', cp)
        if cp_id_match:
            cp_id = cp_id_match.group(1)
            # Convert to tuple of integers for proper numeric sorting
            # Handle variable number of parts (e.g., "1.1.1.1" vs "1.8.3")
            parts = [int(x) for x in cp_id.split('.')]
            return tuple(parts)
        return (9999,)  # Put unmatched at end
    
    unique_checkpoints.sort(key=sort_key)
    
    if verbose:
        print(f"✅ Extracted {len(unique_checkpoints)} unique checkpoints")
        if unique_checkpoints:
            print(f"   First few: {unique_checkpoints[:3]}")
            print(f"   Last few: {unique_checkpoints[-3:]}")
    
    return unique_checkpoints


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Extract all CIS RHEL 8 checkpoint indices from the benchmark document',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract all checkpoints and print to stdout
  python3 get_checkpoint_indexs.py
  
  # Save to file
  python3 get_checkpoint_indexs.py --output checkpoints.txt
  
  # Verbose mode for debugging
  python3 get_checkpoint_indexs.py --verbose
"""
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help='Output file path (default: print to stdout)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show verbose output including debug information'
    )
    
    args = parser.parse_args()
    
    try:
        # Load vector store
        print("\n" + "="*100)
        print("🔧 Initializing CIS RHEL 8 Benchmark Vector Store")
        print("="*100)
        
        vector_store = load_or_create_vector_store()
        print("✅ Vector store ready")
        
        # Extract all checkpoint indices
        print("\n" + "="*100)
        print("🔍 Extracting All CIS Checkpoint Indices")
        print("="*100)
        print("This may take several minutes as the agent searches comprehensively...")
        print()
        
        checkpoints = get_all_cis_checkpoint_indices(vector_store, verbose=args.verbose)
        
        # Output results
        print("\n" + "="*100)
        print("📋 CIS Checkpoint Indices")
        print("="*100)
        print(f"Found {len(checkpoints)} checkpoints\n")
        
        if args.output:
            # Write to file
            with open(args.output, 'w') as f:
                for cp in checkpoints:
                    f.write(cp + '\n')
            print(f"✅ Checkpoints saved to: {args.output}")
        else:
            # Print to stdout
            for cp in checkpoints:
                print(cp)
        
        print("\n" + "="*100)
        print("✅ Extraction complete")
        print("="*100)
        
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

