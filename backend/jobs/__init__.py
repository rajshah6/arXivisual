"""
Jobs package for ArXiviz.

Provides background job processing for paper processing pipeline.
"""

from .worker import process_paper_job

__all__ = ["process_paper_job"]
