#!/usr/bin/env python3

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

"""## CIS RHEL 8 Security Benchmark RAG System"""

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

# Configuration
VECTOR_STORE_DIR = Path(__file__).parent / "CIS_RHEL8_DATA"
PDF_PATH = "resources/CIS_Red_Hat_Enterprise_Linux_8_Benchmark_v4.0.0.pdf"

embeddings = OpenAIEmbeddings(model="text-embedding-3-large")

def load_or_create_vector_store():
    """Load existing vector store or create new one from PDF."""
    
    # Check if vector store already exists
    if (VECTOR_STORE_DIR / "chroma.sqlite3").exists():
        print(f"Loading existing vector store from {VECTOR_STORE_DIR}...")
        vector_store = Chroma(
            persist_directory=str(VECTOR_STORE_DIR),
            embedding_function=embeddings
        )
        print(f"Vector store loaded with {vector_store._collection.count()} documents")
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

# Load or create the vector store
vector_store = load_or_create_vector_store()
print("Vector store ready")

"""## CIS Security Expert RAG Agent"""

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

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

llm = ChatOpenAI(model="gpt-5-nano", temperature=0)

system_prompt = """You are a CIS (Center for Internet Security) RHEL 8 security expert assistant.

Your role is to help system administrators and security professionals understand and implement 
CIS Benchmark controls for Red Hat Enterprise Linux 8.

When a user asks about a specific CIS control (e.g., "1.1.1.1 Ensure cramfs kernel module is not available"):

1. **Search** the CIS benchmark document using the search tool
2. **Explain** the control's purpose and security rationale
3. **Provide** the audit procedure to check current system compliance
4. **List** the remediation steps if the system is not compliant
5. **Note** the profile applicability (Level 1 or Level 2, Server or Workstation)

Always provide practical, actionable information that administrators can use to:
- Audit their systems for compliance
- Remediate any findings
- Understand the security implications

Format your responses clearly with sections for Audit, Remediation, and Rationale when applicable."""

agent = create_react_agent(
    model=llm,
    tools=[search_cis_benchmark],
    prompt=system_prompt
)

from langchain_core.messages import HumanMessage

# Example query for a CIS control
query = "1.1.1.1 Ensure cramfs kernel module is not available (Automated)"

print(f"\n{'='*60}")
print(f"Query: {query}")
print('='*60)

response = agent.invoke(
    {"messages": [HumanMessage(content=f"Provide the audit and remediation information for CIS control: {query}")]}
)

# Print the final response
print("\nCIS Security Expert Response:")
print("-" * 40)
print(response["messages"][-1].content)

