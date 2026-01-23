#!/usr/bin/env python3
"""
Google Search Utility

This script performs Google searches and returns related URLs based on keywords.

Two implementations provided:
1. Simple googlesearch library (no API key needed)
2. Google Custom Search API (requires API key, more reliable)

Usage:
    python3 google_search.py "your search keywords"
    python3 google_search.py "ansible playbook examples" --num-results 10
"""

import os
import sys
import json
import argparse
from typing import List, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def google_search_simple(query: str, num_results: int = 10) -> List[Dict[str, str]]:
    """
    Perform Google search using googlesearch-python library.
    
    This is a simple approach that doesn't require API keys but may have rate limits.
    
    Args:
        query: Search keywords
        num_results: Number of results to return (default: 10)
        
    Returns:
        List of dictionaries with 'url' and 'title' keys
        
    Note:
        Install with: pip install googlesearch-python
    """
    try:
        from googlesearch import search
        
        print(f"🔍 Searching Google for: '{query}'")
        print(f"Requesting {num_results} results...")
        
        results = []
        try:
            # Add sleep parameter to avoid rate limiting
            for url in search(query, num_results=num_results, lang='en', safe='off', sleep_interval=2):
                results.append({
                    'url': url,
                    'title': url.split('/')[2] if '/' in url else url  # Extract domain as title
                })
                print(f"   Found: {url}")
        except Exception as search_error:
            print(f"⚠️  Search error: {str(search_error)}")
            print("   This often happens due to rate limiting or network issues.")
            print("   Try:")
            print("   1. Wait a few minutes and try again")
            print("   2. Use --method api instead (requires Google API credentials)")
            print("   3. Reduce --num-results to a smaller number")
        
        if not results:
            print("\n⚠️  No results found. This could be due to:")
            print("   - Rate limiting by Google")
            print("   - Network connectivity issues")
            print("   - The query returned no matches")
            print("\n💡 Try using the API method: --method api")
        
        return results
        
    except ImportError:
        print("❌ Error: 'googlesearch-python' library not installed.")
        print("Install with: pip install googlesearch-python")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error during search: {str(e)}")
        return []


def google_search_api(query: str, num_results: int = 10) -> List[Dict[str, str]]:
    """
    Perform Google search using Google Custom Search API.
    
    This is a more reliable approach but requires:
    1. Google Custom Search API key (GOOGLE_API_KEY in .env)
    2. Custom Search Engine ID (GOOGLE_CSE_ID in .env)
    
    Get your credentials at: https://developers.google.com/custom-search/v1/introduction
    
    Args:
        query: Search keywords
        num_results: Number of results to return (default: 10, max: 100)
        
    Returns:
        List of dictionaries with 'url', 'title', 'snippet' keys
    """
    try:
        import requests
        
        # Get API credentials from environment
        api_key = os.environ.get('GOOGLE_API_KEY')
        cse_id = os.environ.get('GOOGLE_CSE_ID')
        
        if not api_key or not cse_id:
            print("❌ Error: Google API credentials not found.")
            print("Please set in .env file:")
            print("  GOOGLE_API_KEY=your_api_key")
            print("  GOOGLE_CSE_ID=your_custom_search_engine_id")
            print("\nGet credentials at: https://developers.google.com/custom-search/v1/introduction")
            sys.exit(1)
        
        print(f"🔍 Searching Google for: '{query}'")
        print(f"Requesting {num_results} results...")
        
        results = []
        
        # Google Custom Search API returns max 10 results per request
        # So we need to paginate for more results
        for start_index in range(1, min(num_results + 1, 101), 10):
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                'key': api_key,
                'cx': cse_id,
                'q': query,
                'start': start_index,
                'num': min(10, num_results - len(results))
            }
            
            response = requests.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'items' in data:
                    for item in data['items']:
                        results.append({
                            'url': item.get('link', ''),
                            'title': item.get('title', ''),
                            'snippet': item.get('snippet', '')
                        })
                        
                        if len(results) >= num_results:
                            break
                else:
                    print("⚠️  No more results found")
                    break
            else:
                print(f"❌ API Error: {response.status_code} - {response.text}")
                break
            
            if len(results) >= num_results:
                break
        
        return results
        
    except ImportError:
        print("❌ Error: 'requests' library not installed.")
        print("Install with: pip install requests")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error during API search: {str(e)}")
        return []


def display_results(results: List[Dict[str, str]], verbose: bool = False):
    """
    Display search results in a user-friendly format.
    
    Args:
        results: List of search result dictionaries
        verbose: If True, show snippets (if available)
    """
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
        
        if verbose and 'snippet' in result and result['snippet']:
            print(f"Snippet: {result['snippet']}")
    
    print("\n" + "="*100)
    print(f"Total Results: {len(results)}")
    print("="*100 + "\n")


def save_results(results: List[Dict[str, str]], filename: str):
    """
    Save search results to a JSON file.
    
    Args:
        results: List of search result dictionaries
        filename: Output filename
    """
    try:
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"✅ Results saved to: {filename}")
    except Exception as e:
        print(f"❌ Error saving results: {str(e)}")


def main():
    """Main execution function."""
    
    parser = argparse.ArgumentParser(
        description='Perform Google searches and retrieve related URLs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simple search with default settings
  python3 google_search.py "ansible playbook examples"
  
  # Search with specific number of results
  python3 google_search.py "python automation" --num-results 20
  
  # Use API method (requires credentials in .env)
  python3 google_search.py "kubernetes tutorial" --method api
  
  # Save results to file
  python3 google_search.py "devops tools" --output results.json
  
  # Verbose output with snippets
  python3 google_search.py "machine learning" --verbose

Environment Variables (for API method):
  GOOGLE_API_KEY    - Your Google Custom Search API key
  GOOGLE_CSE_ID     - Your Custom Search Engine ID
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
        '--method', '-m',
        type=str,
        choices=['simple', 'api'],
        default='simple',
        help='Search method: simple (no API key) or api (requires credentials)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Save results to JSON file'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output with snippets (API method only)'
    )
    
    args = parser.parse_args()
    
    try:
        # Perform search based on selected method
        if args.method == 'simple':
            results = google_search_simple(args.query, args.num_results)
        else:
            results = google_search_api(args.query, args.num_results)
        
        # Display results
        display_results(results, verbose=args.verbose)
        
        # Save to file if requested
        if args.output:
            save_results(results, args.output)
        
        # Return results for programmatic use
        return results
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# Programmatic API for use in other scripts
def search_google(query: str, num_results: int = 10, method: str = 'simple') -> List[Dict[str, str]]:
    """
    Programmatic interface for Google search.
    
    Args:
        query: Search keywords
        num_results: Number of results to return
        method: 'simple' or 'api'
        
    Returns:
        List of dictionaries with search results
        
    Example:
        from google_search import search_google
        
        results = search_google("ansible tutorials", num_results=5)
        for result in results:
            print(result['url'])
    """
    if method == 'simple':
        return google_search_simple(query, num_results)
    else:
        return google_search_api(query, num_results)


if __name__ == "__main__":
    main()

