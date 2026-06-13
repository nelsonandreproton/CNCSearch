"""Ingestion utilities (text cleaning, OCR helpers).

This package is a pure leaf: it must not import the database, web, or any
heavy/IO dependency. It is safe to call from every import path and from the
manual-edit write boundary.
"""
