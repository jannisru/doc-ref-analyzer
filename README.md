# doc-ref-analyzer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)

Analyze how an academic paper or article is discussed across the web — Hacker News, Reddit, Wikipedia, Google News, and academic citations — in a single CLI call.

For arXiv papers, academic citations are fetched additionally via the Semantic Scholar API.

## Example

```bash
python src/processing.py https://arxiv.org/abs/2001.08361
```

```
[doc-ref-analyzer] Fetching metadata...
[doc-ref-analyzer] Searching Hacker News, Reddit, Wikipedia, News, Semantic Scholar...
[doc-ref-analyzer] Classifying 47 references...

=== Scaling Laws for Neural Language Models ===
Kaplan et al. (2020)  ·  8,912 citations (Semantic Scholar)

Platform breakdown:
  Hacker News     12 threads   (summary: 6 · endorsement: 4 · discussion: 2)
  Reddit          18 posts     (summary: 7 · question: 5 · discussion: 6)
  Wikipedia        3 articles
  News             8 articles  (BBC, Wired, MIT Tech Review)
  Academic        47 papers    (14 influential)

Report saved: report_2001.08361_20260409_204321.txt
```

## Installation

No required dependencies — all APIs use the Python standard library.

Optional: install `anthropic` to enable LLM-based reference classification.

```bash
pip install anthropic   # optional
```

## Usage

```bash
# Text report to stdout
python src/processing.py https://arxiv.org/abs/2001.08361

# Export both formats
python src/processing.py https://arxiv.org/abs/2001.08361 --output both --save report_2001.08361

# JSON only
python src/processing.py https://arxiv.org/abs/2001.08361 --output json --save report.json
```

## How it works

### 1. Metadata extraction

For arXiv URLs: queries the arXiv API (title, abstract, authors) and Semantic Scholar (citation counts, fields of study).  
For all other URLs: scrapes the HTML page (title, OG tags, meta description).

### 2. Reference search

Searches five platforms in parallel:

| Platform | Method |
|---|---|
| Semantic Scholar | Up to 100 citing papers with title, authors, year, abstract |
| Hacker News | Algolia API — by title, arXiv ID, and direct URL |
| Reddit | JSON API — by title, arXiv ID, and direct URL |
| Wikipedia | MediaWiki API — by title and arXiv ID |
| Google News RSS | By title and arXiv ID |

### 3. Usage-type classification

Two-stage classification pipeline:

**Stage 1 — Regex:** pattern matching on ingestion, with platform-based fallback.  
**Stage 2 — LLM (optional):** all non-academic results are sent in a single batch request to Claude. LLM classifications override regex results.

| Category | Signals |
|---|---|
| Critical discussion | criticism, doubt, contradiction |
| Reuse / derivative work | "based on", "building on" |
| Summary / paraphrase | "TL;DR", "key findings" |
| Positive endorsement | "must-read", "seminal" |
| Question / help request | "has anyone", "how do I" |
| Academic citation | DOI, citing paper |

### 4. Export

- `.txt` — human-readable report with distribution charts by platform and usage type
- `.json` — structured output with metadata, summary, and all individual references

## Stack

Python (stdlib) · Semantic Scholar API · Anthropic API (optional)
