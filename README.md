# Article Reference Analyzer

Analyzes how an article is referenced and discussed online. For arXiv papers, academic citations are fetched additionally via Semantic Scholar.

## Usage

### CLI (recommended)

```bash
python src/processing.py <URL> [--output text|json|both] [--save FILE]
```

**Examples:**

```bash
# Text report to stdout
python src/processing.py https://arxiv.org/abs/2001.08361

# Export both formats
python src/processing.py https://arxiv.org/abs/2001.08361 --output both --save report_2001.08361

# JSON only
python src/processing.py https://arxiv.org/abs/2001.08361 --output json --save report_2001.08361.json
```

### Script with fixed URL

Set the URL and output mode in `src/main.py` and run:

```bash
python src/main.py
```

The report is saved automatically as `.txt` and `.json` with a timestamped filename (e.g. `report_2001.08361_20260409_204321.txt`).

## Dependencies

No required external dependencies — all APIs are queried using the Python standard library.

**Optional:** The `anthropic` package enables LLM-based classification (step 3). Without it, only regex classification is used.

```bash
pip install anthropic
```

## Methodology

### 1. Metadata Extraction

**For arXiv URLs**, two APIs are queried:
- **arXiv API** (`export.arxiv.org`) — title, abstract, authors, publication year
- **Semantic Scholar API** — citation counts (total & influential), fields of study

**For all other URLs**, the HTML page is scraped (title tag, OG tags, meta description).

### 2. Reference Search

#### Academic citations — arXiv only (Semantic Scholar)
Returns up to 100 citing papers with title, authors, year, and abstract. Each paper is recorded with its arXiv, DOI, or Semantic Scholar URL.

#### Hacker News (Algolia API)
Three queries:
- Full-text search by title
- Full-text search by arXiv ID *(arXiv only)*
- URL-based search for the direct link *(arXiv only)*

Snippets include the thread title, score, and comment count.

#### Reddit (JSON API)
Three queries:
- Full-text search by title
- Full-text search by arXiv ID *(arXiv only)*
- URL-based search (`url:...`) for the direct link *(arXiv only)*

Snippets include title, upvotes, comment count, and post body where available.

#### Wikipedia (MediaWiki API)
Two queries:
- Full-text search by title
- Full-text search by arXiv ID *(arXiv only)*

Returns Wikipedia articles mentioning the search term, with a highlighted snippet.

#### News (Google News RSS)
Two queries:
- Full-text search by title
- Full-text search by arXiv ID *(arXiv only)*

Returns recent news articles with title, source, and excerpt. Well-known outlets (BBC, Wired, NYT, Nature, MIT Tech Review, etc.) are detected as their own platform.

### 3. Usage-Type Classification

Classification runs in two stages:

**Stage 1 — Regex:** Each result is classified immediately on ingestion via pattern matching. If no pattern matches, a platform-based fallback is applied.

**Stage 2 — LLM (optional):** All non-academic results are then sent in a single batch request to Claude (`claude-opus-4-6`). The model is given the paper title and classifies each snippet using the same category schema. LLM classifications override the regex result. If the `anthropic` package is not installed, stage 1 is the final result.

| Category | Signals |
|---|---|
| **Critical discussion** | criticism, doubt, contradiction |
| **Reuse of ideas / derivative** | own work based on the paper |
| **Summary / paraphrase** | summary, TL;DR, key findings |
| **Direct quote / citation** | direct citation, "the authors", "they find" |
| **Positive endorsement** | recommendation, praise, "must-read", "seminal" |
| **Question / Help request** | "has anyone", "how do I", "don't understand" |
| **News mention** | mention in a news context |
| **General discussion** | opinions, thoughts, general discussion |
| **Contextual reference** | passing mention, "see also" |
| **Academic citation** | academic paper / DOI  |
| **General mention** | no pattern matched |

### 4. Export

- **`.txt`** — Human-readable report with distribution charts by platform and usage type
- **`.json`** — Structured output with metadata, summary, and all individual references
