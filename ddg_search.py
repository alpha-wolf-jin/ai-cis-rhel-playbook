#!/usr/bin/env python3
"""
DuckDuckGo Search Utility (Alternative to Google)

This is a more reliable alternative that doesn't require API keys.
Uses DuckDuckGo search which is less likely to block requests.

Usage:
    python3 ddg_search.py "your search keywords"
    python3 ddg_search.py "ansible playbook examples" --num-results 10
"""

import sys
import json
import argparse
from typing import List, Dict


def ddg_search(query: str, num_results: int = 10) -> List[Dict[str, str]]:
    """
    Perform DuckDuckGo search using ddgs library.
    
    Args:
        query: Search keywords
        num_results: Number of results to return (default: 10)
        
    Returns:
        List of dictionaries with 'url', 'title', 'snippet' keys
        
    Note:
        Install with: pip install ddgs
    """
    try:
        from ddgs import DDGS
        
        print(f"🔍 Searching DuckDuckGo for: '{query}'")
        print(f"Requesting {num_results} results...")
        
        results = []
        
        try:
            ddgs = DDGS()
            search_results = list(ddgs.text(query, max_results=num_results))
            
            for result in search_results:
                url = result.get('href', result.get('link', ''))
                title = result.get('title', 'Untitled')
                snippet = result.get('body', result.get('snippet', ''))
                
                if url:  # Only add if we have a URL
                    results.append({
                        'url': url,
                        'title': title,
                        'snippet': snippet
                    })
                    print(f"   Found: {title}")
        except Exception as search_error:
            print(f"⚠️  Search error: {str(search_error)}")
            print("   Try adjusting your query or reducing --num-results")
        
        if not results:
            print("\n⚠️  No results found.")
            print("   This could be due to:")
            print("   - Network connectivity issues")
            print("   - Query too specific or returned no matches")
            print("   - Temporary service issues")
        
        return results
        
    except ImportError:
        print("❌ Error: 'ddgs' library not installed.")
        print("Install with: pip install ddgs")
        print("(Old package 'duckduckgo-search' has been renamed to 'ddgs')")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error during search: {str(e)}")
        import traceback
        traceback.print_exc()
        return []


def display_results(results: List[Dict[str, str]], verbose: bool = False):
    """Display search results in a user-friendly format."""
    if not results:
        print("\n❌ No results found.")
        return
    
    print("\n" + "="*100)
    print(f"SEARCH RESULTS: Found {len(results)} URLs")
    print("="*100)
    
    for idx, result in enumerate(results, 1):
        print(f"\n[{idx}] {'-'*95}")
        print(f"Title: {result.get('title', 'N/A')}")
        print(f"URL:   {result['url']}")
        
        if verbose and result.get('snippet'):
            print(f"Snippet: {result['snippet']}")
    
    print("\n" + "="*100)
    print(f"Total Results: {len(results)}")
    print("="*100 + "\n")


def save_results(results: List[Dict[str, str]], filename: str):
    """Save search results to a JSON file."""
    try:
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"✅ Results saved to: {filename}")
    except Exception as e:
        print(f"❌ Error saving results: {str(e)}")


def main():
    """Main execution function."""
    
    parser = argparse.ArgumentParser(
        description='Perform DuckDuckGo searches and retrieve related URLs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simple search
  python3 ddg_search.py "ansible playbook examples"
  
  # Search with specific number of results
  python3 ddg_search.py "python automation" --num-results 20
  
  # Save results to file
  python3 ddg_search.py "devops tools" --output results.json
  
  # Verbose output with snippets
  python3 ddg_search.py "machine learning" --verbose

Installation:
  pip install ddgs
"""
    )
    
    parser.add_argument(
        'query',
        type=str,
        help='Search keywords/query'
    )
    
    parser.add_argument(
        '--num-results', '-n',
        type=int,
        default=10,
        help='Number of results to return (default: 10)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Save results to JSON file'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output with snippets'
    )
    
    args = parser.parse_args()
    
    try:
        # Perform search
        results = ddg_search(args.query, args.num_results)
        
        # Display results
        display_results(results, verbose=args.verbose)
        
        # Save to file if requested
        if args.output:
            save_results(results, args.output)
        
        return results
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# Programmatic API
def search_ddg(query: str, num_results: int = 10) -> List[Dict[str, str]]:
    """
    Programmatic interface for DuckDuckGo search.
    
    Example:
        from ddg_search import search_ddg
        
        results = search_ddg("ansible tutorials", num_results=5)
        for result in results:
            print(result['url'])
    """
    return ddg_search(query, num_results)


if __name__ == "__main__":
    main()

