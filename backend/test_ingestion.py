#!/usr/bin/env python3
"""
Test script for the paper ingestion pipeline.

Tests with three papers per the spec:
1. 1706.03762 - "Attention Is All You Need" (well-structured, demo paper)
2. 2301.07041 - Newer paper for robustness testing
3. 1312.6114 - VAE paper (heavy math, tests equation extraction)

Usage:
    # From project root:
    python -m backend.test_ingestion                    # Test all papers
    python -m backend.test_ingestion 1706.03762        # Test specific paper
    python -m backend.test_ingestion --pdf-only        # Force PDF parsing
    python -m backend.test_ingestion --json            # Output as JSON
    
    # Or from backend/ directory:
    cd backend && python test_ingestion.py
"""

import argparse
import asyncio
import json
import logging
import os
import sys

# Handle imports for both running as module and as standalone script
# When run as `python -m backend.test_ingestion` from project root
# or as `python test_ingestion.py` from backend/
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)

# Add both project root and backend to path
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

# Try different import strategies
try:
    # When running as `python -m backend.test_ingestion` from project root
    from backend.ingestion import clear_cache, ingest_paper
    from backend.models.paper import StructuredPaper
except ImportError:
    try:
        # When running as `python test_ingestion.py` from backend/
        from ingestion import clear_cache, ingest_paper
        from models.paper import StructuredPaper
    except ImportError as e:
        print(f"Import error: {e}")
        print("\nPlease run this script in one of these ways:")
        print("  1. From project root: python -m backend.test_ingestion")
        print("  2. From backend dir:  cd backend && python test_ingestion.py")
        sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Test papers from the spec
TEST_PAPERS = [
    {
        'arxiv_id': '1706.03762',
        'expected_title': 'Attention Is All You Need',
        'description': 'Transformer paper - well structured, our demo paper'
    },
    {
        'arxiv_id': '2301.07041',
        'expected_title': None,  # Will verify it parses
        'description': 'Newer paper - robustness testing'
    },
    {
        'arxiv_id': '1312.6114',
        'expected_title': 'Auto-Encoding Variational Bayes',
        'description': 'VAE paper - heavy math, tests equation extraction'
    },
]


async def test_paper(
    arxiv_id: str,
    prefer_pdf: bool = False,
    output_json: bool = False
) -> bool:
    """
    Test ingestion of a single paper.
    
    Returns True if test passed, False otherwise.
    """
    print(f"\n{'='*60}")
    print(f"Testing paper: {arxiv_id}")
    print(f"{'='*60}")
    
    try:
        # Clear cache to ensure fresh fetch
        clear_cache()
        
        # Ingest the paper
        paper = await ingest_paper(arxiv_id, force_refresh=True, prefer_pdf=prefer_pdf)
        
        # Print summary
        print_paper_summary(paper)
        
        # Output JSON if requested
        if output_json:
            print("\n--- JSON Output ---")
            print(json.dumps(paper.to_dict(), indent=2, default=str))
        
        # Validate result
        validation_passed = validate_paper(paper, arxiv_id)
        
        if validation_passed:
            print(f"\n✓ Paper {arxiv_id} passed validation")
        else:
            print(f"\n✗ Paper {arxiv_id} failed validation")
        
        return validation_passed
        
    except Exception as e:
        logger.exception(f"Error testing paper {arxiv_id}")
        print(f"\n✗ Error: {e}")
        return False


def print_paper_summary(paper: StructuredPaper):
    """Print a summary of the parsed paper."""
    print(f"\nTitle: {paper.meta.title}")
    print(f"Authors: {', '.join(paper.meta.authors[:3])}{'...' if len(paper.meta.authors) > 3 else ''}")
    print(f"Categories: {', '.join(paper.meta.categories)}")
    print(f"PDF URL: {paper.meta.pdf_url}")
    print(f"HTML URL: {paper.meta.html_url or 'Not available'}")
    
    print(f"\nSections: {len(paper.sections)}")
    total_equations = sum(len(s.equations) for s in paper.sections)
    total_figures = sum(len(s.figures) for s in paper.sections)
    total_tables = sum(len(s.tables) for s in paper.sections)
    print(f"Total equations: {total_equations}")
    print(f"Total figures: {total_figures}")
    print(f"Total tables: {total_tables}")
    
    print("\n--- Section Structure ---")
    for section in paper.sections:
        indent = "  " * (section.level - 1)
        eq_count = len(section.equations)
        fig_count = len(section.figures)
        table_count = len(section.tables)
        
        extras = []
        if eq_count:
            extras.append(f"{eq_count} eq")
        if fig_count:
            extras.append(f"{fig_count} fig")
        if table_count:
            extras.append(f"{table_count} tbl")
        
        extra_str = f" ({', '.join(extras)})" if extras else ""
        content_preview = section.content[:50].replace('\n', ' ') + "..." if len(section.content) > 50 else section.content.replace('\n', ' ')
        
        print(f"{indent}[{section.level}] {section.title}{extra_str}")
        print(f"{indent}    Content: {len(section.content)} chars - \"{content_preview}\"")


def validate_paper(paper: StructuredPaper, arxiv_id: str) -> bool:
    """
    Validate that a paper was parsed correctly.
    
    Returns True if all checks pass.
    """
    checks = []
    
    # Check 1: Has metadata
    if paper.meta.arxiv_id:
        checks.append(('Has arxiv_id', True))
    else:
        checks.append(('Has arxiv_id', False))
    
    if paper.meta.title:
        checks.append(('Has title', True))
    else:
        checks.append(('Has title', False))
    
    if paper.meta.abstract:
        checks.append(('Has abstract', True))
    else:
        checks.append(('Has abstract', False))
    
    if paper.meta.authors:
        checks.append(('Has authors', True))
    else:
        checks.append(('Has authors', False))
    
    # Check 2: Has sections
    if len(paper.sections) >= 3:
        checks.append(('Has 3+ sections', True))
    else:
        checks.append(('Has 3+ sections', False))
    
    # Check 3: Sections have content
    sections_with_content = sum(1 for s in paper.sections if len(s.content) > 50)
    if sections_with_content >= 2:
        checks.append(('Sections have content', True))
    else:
        checks.append(('Sections have content', False))
    
    # Check 4: No References section (we filter these)
    has_refs = any(
        'reference' in s.title.lower() or 'bibliography' in s.title.lower()
        for s in paper.sections
    )
    if not has_refs:
        checks.append(('References filtered out', True))
    else:
        checks.append(('References filtered out', False))
    
    # Print check results
    print("\n--- Validation Checks ---")
    all_passed = True
    for check_name, passed in checks:
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")
        if not passed:
            all_passed = False
    
    return all_passed


async def run_all_tests(prefer_pdf: bool = False, output_json: bool = False):
    """Run tests on all test papers."""
    print("\n" + "="*60)
    print("ARXIVIZ INGESTION PIPELINE - TEST SUITE")
    print("="*60)
    
    results = []
    
    for test_case in TEST_PAPERS:
        arxiv_id = test_case['arxiv_id']
        description = test_case['description']
        
        print(f"\n>>> {description}")
        
        passed = await test_paper(arxiv_id, prefer_pdf=prefer_pdf, output_json=output_json)
        results.append({
            'arxiv_id': arxiv_id,
            'description': description,
            'passed': passed
        })
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed_count = sum(1 for r in results if r['passed'])
    total_count = len(results)
    
    for result in results:
        status = "✓ PASS" if result['passed'] else "✗ FAIL"
        print(f"  {status}: {result['arxiv_id']} - {result['description']}")
    
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    return passed_count == total_count


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test the ArXiviz paper ingestion pipeline"
    )
    parser.add_argument(
        'arxiv_id',
        nargs='?',
        help='Specific arXiv ID to test (default: test all)'
    )
    parser.add_argument(
        '--pdf-only',
        action='store_true',
        help='Force PDF parsing even if HTML is available'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output parsed paper as JSON'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.arxiv_id:
        # Test specific paper
        success = asyncio.run(
            test_paper(args.arxiv_id, prefer_pdf=args.pdf_only, output_json=args.json)
        )
    else:
        # Test all papers
        success = asyncio.run(
            run_all_tests(prefer_pdf=args.pdf_only, output_json=args.json)
        )
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
