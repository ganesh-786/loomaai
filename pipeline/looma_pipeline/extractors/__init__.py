"""Text extractors, one module per source: database records, PDF (with OCR), captions and HTML.

Each extractor is a pure function of its input (a record or a file path) and returns plain text pieces; the F3 stage
decides which extractor to call for an item and records failures.
"""
