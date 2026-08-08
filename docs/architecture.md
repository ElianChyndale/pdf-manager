# Architecture

## Frontend

The frontend provides PDF upload, reading, comparison, and tool workflows.

## Rust API

The Rust API exposes job creation, status, artifacts, and PDF tool routes.

## Python Processing Layer

The processing layer handles OCR/provider integration, translation, rendering, and supporting document operations.

## Research Layer

The research layer evaluates extraction quality, layout preservation, chunking strategies, retrieval behavior, and failure modes.

## Main Interface

- Input: PDF document and processing mode.
- Output: structured text blocks, page metadata, extraction artifacts, rendered outputs, and evaluation records.
