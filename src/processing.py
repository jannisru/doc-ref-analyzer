import sys
import argparse
import re
import json
import time
import ssl
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from html.parser import HTMLParser

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._chunks.append(data)

    def get_text(self):
        return " ".join(self._chunks)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return re.sub(r"\s+", " ", extractor.get_text()).strip()


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ArticleReferenceAnalyzer/1.0; "
        "+https://github.com/example/article-reference-analyzer)"
    )
}


def fetch(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except Exception as exc:
        print(f"  [WARN] Could not fetch {url}: {exc}")
        return ""


def _get_json(url: str, timeout: int = 15) -> dict | list | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [WARN] API error {e.code} for {url}")
        return None
    except Exception as e:
        print(f"  [WARN] Could not fetch JSON from {url}: {e}")
        return None


def extract_arxiv_id(url: str) -> str | None:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]+)", url)
    return match.group(1) if match else None


def fetch_arxiv_metadata(arxiv_id: str) -> dict:
    url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
    xml = fetch(url, timeout=15)
    if not xml:
        return {}

    title_match    = re.search(r"<title>(.*?)</title>", xml, re.DOTALL)
    abstract_match = re.search(r"<summary>(.*?)</summary>", xml, re.DOTALL)
    authors        = re.findall(r"<name>(.*?)</name>", xml)
    year_match     = re.search(r"<published>(\d{4})", xml)

    title    = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    abstract = re.sub(r"\s+", " ", abstract_match.group(1)).strip() if abstract_match else ""

    if title.lower().startswith("arxiv query"):
        title_match2 = re.search(r"<title>(.*?)</title>.*?<title>(.*?)</title>", xml, re.DOTALL)
        title = re.sub(r"\s+", " ", title_match2.group(2)).strip() if title_match2 else title

    return {
        "title":    title,
        "abstract": abstract,
        "authors":  authors,
        "year":     year_match.group(1) if year_match else "",
    }


def fetch_semantic_scholar_metadata(arxiv_id: str) -> dict:
    fields = "title,year,citationCount,influentialCitationCount,fieldsOfStudy"
    url    = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}?fields={fields}"
    data   = _get_json(url)
    return data if isinstance(data, dict) else {}


def fetch_semantic_scholar_citations(arxiv_id: str, limit: int = 100) -> list[dict]:
    fields = "title,authors,year,externalIds,abstract"
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
        f"/citations?fields={fields}&limit={limit}"
    )
    data = _get_json(url)
    if not isinstance(data, dict) or "data" not in data:
        return []
    return data["data"]


def extract_metadata(url: str) -> dict:
    arxiv_id = extract_arxiv_id(url)
    if arxiv_id:
        print(f"  Detected arXiv paper: {arxiv_id}")
        arxiv = fetch_arxiv_metadata(arxiv_id)
        ss    = fetch_semantic_scholar_metadata(arxiv_id)

        title       = arxiv.get("title") or ss.get("title") or ""
        description = arxiv.get("abstract", "")
        authors     = arxiv.get("authors", [])
        year        = arxiv.get("year") or str(ss.get("year") or "")

        raw_text = f"{title} {description}"
        words    = re.findall(r"\b[A-Za-zÀ-ÿ]{4,}\b", raw_text)
        stopwords = {
            "that", "this", "with", "from", "have", "been", "will", "were", "their",
            "they", "what", "when", "which", "about", "more", "than", "your", "into",
            "also", "some", "most", "many", "such", "other", "over", "just", "like",
            "show", "these", "paper", "using", "model", "models", "results", "work",
        }
        seen, keywords = set(), []
        for w in words:
            lw = w.lower()
            if lw not in stopwords and lw not in seen:
                seen.add(lw)
                keywords.append(w)

        return {
            "title":                      title,
            "description":                description,
            "keywords":                   keywords[:12],
            "authors":                    authors,
            "year":                       year,
            "citation_count":             ss.get("citationCount"),
            "influential_citation_count": ss.get("influentialCitationCount"),
            "fields_of_study":            ss.get("fieldsOfStudy") or [],
            "_arxiv_id":                  arxiv_id,
        }

    html = fetch(url)
    if not html:
        return {"title": "", "description": "", "keywords": []}

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title       = html_to_text(title_match.group(1)) if title_match else ""

    desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if not desc_match:
        desc_match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
            html, re.IGNORECASE,
        )
    description = desc_match.group(1).strip() if desc_match else ""

    og_title_match = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if og_title_match:
        title = og_title_match.group(1).strip()

    raw_text  = f"{title} {description}"
    words     = re.findall(r"\b[A-Za-zÀ-ÿ]{4,}\b", raw_text)
    stopwords = {
        "that", "this", "with", "from", "have", "been", "will", "were", "their",
        "they", "what", "when", "which", "about", "more", "than", "your", "into",
        "also", "some", "most", "many", "such", "other", "over", "just", "like",
    }
    seen, keywords = set(), []
    for w in words:
        lw = w.lower()
        if lw not in stopwords and lw not in seen:
            seen.add(lw)
            keywords.append(w)

    return {
        "title":       title,
        "description": description,
        "keywords":    keywords[:12],
    }


_USAGE_PATTERNS = [
    ("Critical discussion",
     r"critic|disagree|wrong|flawed|problem with|mislead|incorrect|debunk|contradict"
     r"|overstat|overfit|concern|limitation|issue with|doubt|skepti|not convinced"
     r"|doesn.t hold|cherry.pick|misunderstand|pushback|counterargument"),
    ("Reuse of ideas / derivative",
     r"inspired by|based on|building on|following\b|similar approach|adapted from"
     r"|extend|replicate|reproduct|implement.*paper|use.*method|fork|port\b|ported"
     r"|we use|we adopt|we follow|our.*based on|using their"),
    ("Summary / paraphrase",
     r"summar|paraphras|in brief|overview|recap|explain|tldr|tl;dr|break.?down"
     r"|key (finding|insight|takeaway|result|point)|the (paper|study) (show|find|argue|propose)"
     r"|what the paper|main (contribution|idea|claim)"),
    ("Direct quote / citation",
     r"quot|according to|as stated|writes that|states that|argued that|they show"
     r"|they find|they report|the authors|cite|citing|cited by|references?\b"),
    ("Positive endorsement",
     r"recommend|must.read|excellent|insightful|well.written|great paper|love this"
     r"|brilliant|impressive|fascinating|mind.?blow|seminal|underrated|hidden gem"
     r"|everyone should|worth reading|best paper|good read|really good|so good"),
    ("Question / Help request",
     r"has anyone|can anyone|does anyone|how do (i|you|we)|what is|why does|i.m (confused|lost|stuck)"
     r"|help me|don.t understand|could someone|any ideas|not sure (how|why|what)"),
    ("News mention",
     r"reported|journalist|press|media|coverage|breaking|announcement|publish|released"
     r"|just came out|new paper|new (from|by)"),
    ("General discussion",
     r"discuss|talk about|think about|wonder|opinion|thought|perspective|interesting"
     r"|curious|what do you|anyone else|i (think|feel|believe|found|noticed)"
     r"|seems like|looks like|sounds like"),
    ("Contextual reference",
     r"see also|related to|as discussed|points? to|similar to|reminds me|like\b.*paper"),
]


def classify_usage(snippet: str, platform: str = "") -> str:
    snippet_lower = snippet.lower()
    for label, pattern in _USAGE_PATTERNS:
        if re.search(pattern, snippet_lower):
            return label
    if platform in ("Reddit", "Hacker News"):
        return "General discussion"
    if platform in ("Academic paper", "DOI / Journal"):
        return "Academic citation"
    return "General mention"


def _hn_search(query: str, num: int = 20) -> list[dict]:
    encoded = urllib.parse.quote_plus(query)
    url     = f"https://hn.algolia.com/api/v1/search?query={encoded}&tags=(story,comment)&hitsPerPage={num}"
    data    = _get_json(url)
    if not data or "hits" not in data:
        return []

    results = []
    for hit in data["hits"]:
        object_id     = hit.get("objectID", "")
        hn_thread_url = f"https://news.ycombinator.com/item?id={object_id}"
        title         = hit.get("title") or hit.get("story_title") or ""
        text          = hit.get("story_text") or hit.get("comment_text") or ""
        points        = hit.get("points") or hit.get("story_points") or 0
        num_comments  = hit.get("num_comments", "")
        meta          = f"[{points} points" + (f", {num_comments} comments]" if num_comments else "]")
        snippet       = f"{title} {meta} {html_to_text(text)}".strip()[:500]
        if not snippet:
            continue
        results.append({"url": hn_thread_url, "snippet": snippet})
    return results


def _hn_search_by_url(arxiv_url: str, num: int = 10) -> list[dict]:
    encoded       = urllib.parse.quote_plus(arxiv_url)
    url           = f"https://hn.algolia.com/api/v1/search?query={encoded}&tags=story&hitsPerPage={num}"
    data          = _get_json(url)
    if not data or "hits" not in data:
        return []

    results = []
    for hit in data["hits"]:
        object_id     = hit.get("objectID", "")
        hn_thread_url = f"https://news.ycombinator.com/item?id={object_id}"
        title         = hit.get("title") or ""
        points        = hit.get("points") or 0
        num_comments  = hit.get("num_comments", "")
        meta          = f"[{points} points" + (f", {num_comments} comments]" if num_comments else "]")
        snippet       = f"{title} {meta}".strip()
        if not snippet:
            continue
        results.append({"url": hn_thread_url, "snippet": snippet})
    return results


def _reddit_search(query: str, num: int = 20) -> list[dict]:
    encoded = urllib.parse.quote_plus(query)
    url     = f"https://www.reddit.com/search.json?q={encoded}&sort=relevance&limit={num}&type=link,comment"
    data    = _get_json(url)
    if not data:
        return []

    results, children = [], []
    if isinstance(data, dict):
        children = data.get("data", {}).get("children", [])
    elif isinstance(data, list):
        for section in data:
            children += section.get("data", {}).get("children", [])

    for child in children:
        post         = child.get("data", {})
        ref_url      = f"https://www.reddit.com{post.get('permalink', '')}"
        title        = post.get("title", "")
        body         = post.get("selftext") or post.get("body") or ""
        score        = post.get("score", "")
        num_comments = post.get("num_comments", "")
        meta         = f"[{score} upvotes, {num_comments} comments]" if score else ""
        snippet      = f"{title} {meta} {body}".strip()[:500]
        if not snippet or not ref_url.startswith("https://www.reddit.com/r/"):
            continue
        results.append({"url": ref_url, "snippet": snippet})
    return results


def _news_search(query: str, num: int = 10) -> list[dict]:
    encoded = urllib.parse.quote_plus(query)
    url     = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    xml     = fetch(url, timeout=15)
    if not xml:
        return []

    items   = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
    results = []
    for item in items[:num]:
        title_m = re.search(r"<title>(.*?)</title>", item, re.DOTALL)
        link_m  = re.search(r"<link/>(.*?)<", item, re.DOTALL) or re.search(r"<link>(.*?)</link>", item, re.DOTALL)
        desc_m  = re.search(r"<description>(.*?)</description>", item, re.DOTALL)
        source_m = re.search(r"<source[^>]*>(.*?)</source>", item, re.DOTALL)

        title   = html_to_text(title_m.group(1)) if title_m else ""
        ref_url = link_m.group(1).strip() if link_m else ""
        desc    = html_to_text(desc_m.group(1)) if desc_m else ""
        source  = source_m.group(1).strip() if source_m else ""

        snippet = f"{title}"
        if source:
            snippet += f" [{source}]"
        if desc:
            snippet += f" — {desc}"
        snippet = snippet.strip()[:500]

        if not ref_url or not snippet:
            continue
        results.append({"url": ref_url, "snippet": snippet})
    return results


def _wikipedia_search(query: str, num: int = 10) -> list[dict]:
    encoded = urllib.parse.quote_plus(query)
    url     = (
        f"https://en.wikipedia.org/w/api.php?action=query&list=search"
        f"&srsearch={encoded}&format=json&srlimit={num}&srprop=snippet"
    )
    data = _get_json(url)
    if not data:
        return []

    results = []
    for item in data.get("query", {}).get("search", []):
        title    = item.get("title", "")
        snippet  = html_to_text(item.get("snippet", ""))
        page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        if not snippet:
            continue
        results.append({"url": page_url, "snippet": f"{title} — {snippet}"[:500]})
    return results


def _reddit_search_by_url(arxiv_url: str, num: int = 10) -> list[dict]:
    encoded  = urllib.parse.quote_plus(f"url:{arxiv_url}")
    url      = f"https://www.reddit.com/search.json?q={encoded}&sort=relevance&limit={num}&type=link"
    data     = _get_json(url)
    if not data:
        return []

    results  = []
    children = data.get("data", {}).get("children", []) if isinstance(data, dict) else []
    for child in children:
        post         = child.get("data", {})
        ref_url      = f"https://www.reddit.com{post.get('permalink', '')}"
        title        = post.get("title", "")
        score        = post.get("score", "")
        num_comments = post.get("num_comments", "")
        meta         = f"[{score} upvotes, {num_comments} comments]" if score else ""
        snippet      = f"{title} {meta}".strip()
        if not snippet or not ref_url.startswith("https://www.reddit.com/r/"):
            continue
        results.append({"url": ref_url, "snippet": snippet})
    return results


def _semantic_scholar_citations_to_results(arxiv_id: str) -> list[dict]:
    print(f"  Fetching citations from Semantic Scholar …")
    citations = fetch_semantic_scholar_citations(arxiv_id)
    results   = []
    for entry in citations:
        paper    = entry.get("citingPaper", {})
        title    = paper.get("title", "(no title)")
        year     = paper.get("year", "")
        authors  = ", ".join(a["name"] for a in paper.get("authors", [])[:3])
        abstract = (paper.get("abstract") or "")[:300]
        snippet  = f"{title} — {authors} ({year}). {abstract}".strip(" —.")

        ext = paper.get("externalIds") or {}
        if ext.get("ArXiv"):
            ref_url = f"https://arxiv.org/abs/{ext['ArXiv']}"
        elif ext.get("DOI"):
            ref_url = f"https://doi.org/{ext['DOI']}"
        else:
            pid     = paper.get("paperId", "")
            ref_url = f"https://www.semanticscholar.org/paper/{pid}" if pid else ""

        if not ref_url:
            continue

        results.append({
            "url":        ref_url,
            "snippet":    snippet[:500],
            "query":      "Semantic Scholar citations",
            "usage_type": classify_usage(snippet, "Academic paper"),
            "platform":   "Academic paper",
        })
    print(f"  Found {len(results)} academic citations.")
    return results


_ACADEMIC_PLATFORMS = {"Academic paper", "DOI / Journal", "arXiv", "Semantic Scholar"}

_LLM_CATEGORIES = [
    "Critical discussion",
    "Reuse of ideas / derivative",
    "Summary / paraphrase",
    "Direct quote / citation",
    "Positive endorsement",
    "Question / Help request",
    "News mention",
    "General discussion",
    "Contextual reference",
    "General mention",
]


def _classify_usage_batch_llm(results: list[dict], paper_title: str = "") -> list[dict]:
    try:
        import anthropic as _anthropic
    except ImportError:
        print("  [WARN] anthropic package not installed — skipping LLM classification")
        return results

    to_classify = [
        (i, r) for i, r in enumerate(results)
        if r.get("platform") not in _ACADEMIC_PLATFORMS
    ]
    if not to_classify:
        return results

    context = f'Paper: "{paper_title}"\n\n' if paper_title else ""
    snippets_text = "\n".join(
        f"{j+1}. [{r['platform']}] {r['snippet'][:300]}"
        for j, (_, r) in enumerate(to_classify)
    )
    categories_text = "\n".join(f"- {c}" for c in _LLM_CATEGORIES)
    prompt = (
        f"{context}Classify each snippet by how it references or discusses the paper.\n\n"
        f"Categories:\n{categories_text}\n\n"
        f"Snippets:\n{snippets_text}\n\n"
        f"Reply with ONLY a JSON array of strings, one classification per snippet, in the same order. "
        f"Each string must be exactly one of the category names listed above."
    )

    try:
        client = _anthropic.Anthropic()
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            classifications = json.loads(match.group())
            for j, (i, _) in enumerate(to_classify):
                if j < len(classifications) and classifications[j] in _LLM_CATEGORIES:
                    results[i]["usage_type"] = classifications[j]
    except Exception as e:
        print(f"  [WARN] LLM classification failed: {e}")

    return results


def search_references(article_url: str, title: str, keywords: list[str]) -> list[dict]:
    seen_urls:   set[str]   = set()
    all_results: list[dict] = []

    def _add(results: list[dict], query: str) -> None:
        for r in results:
            url = r["url"]
            if not url or url == article_url or url in seen_urls:
                continue
            seen_urls.add(url)
            platform   = _detect_platform(url)
            usage_type = classify_usage(r["snippet"], platform)
            all_results.append({
                "url":        url,
                "snippet":    r["snippet"],
                "query":      query,
                "usage_type": usage_type,
                "platform":   platform,
            })

    arxiv_id = extract_arxiv_id(article_url)
    if arxiv_id:
        _add(_semantic_scholar_citations_to_results(arxiv_id), "Semantic Scholar citations")

    if not title:
        print("  [WARN] No title found — skipping forum/social search.")
        return all_results

    short_title = " ".join(title.split()[:10])

    print(f"  Searching Hacker News …")
    _add(_hn_search(short_title, num=30), f"HN: {short_title}")
    if arxiv_id:
        _add(_hn_search(arxiv_id, num=10), f"HN: {arxiv_id}")
        _add(_hn_search_by_url(article_url, num=10), f"HN: url={article_url}")

    print(f"  Searching Reddit …")
    _add(_reddit_search(short_title, num=25), f"Reddit: {short_title}")
    if arxiv_id:
        _add(_reddit_search(arxiv_id, num=10), f"Reddit: {arxiv_id}")
        _add(_reddit_search_by_url(article_url, num=10), f"Reddit: url={article_url}")

    print(f"  Searching Wikipedia …")
    _add(_wikipedia_search(short_title, num=10), f"Wikipedia: {short_title}")
    if arxiv_id:
        _add(_wikipedia_search(arxiv_id, num=5), f"Wikipedia: {arxiv_id}")

    print(f"  Searching News …")
    _add(_news_search(short_title, num=10), f"News: {short_title}")
    if arxiv_id:
        _add(_news_search(arxiv_id, num=5), f"News: {arxiv_id}")

    print(f"  Classifying usage types with Claude …")
    all_results = _classify_usage_batch_llm(all_results, title)

    return all_results


_PLATFORM_MAP = [
    (r"reddit\.com",                   "Reddit"),
    (r"news\.ycombinator",             "Hacker News"),
    (r"twitter\.com|x\.com",           "Twitter / X"),
    (r"linkedin\.com",                 "LinkedIn"),
    (r"medium\.com",                   "Medium"),
    (r"substack\.com",                 "Substack"),
    (r"quora\.com",                    "Quora"),
    (r"stackoverflow\.com",            "Stack Overflow"),
    (r"youtube\.com",                  "YouTube"),
    (r"facebook\.com",                 "Facebook"),
    (r"mastodon\.",                    "Mastodon"),
    (r"dev\.to",                       "DEV Community"),
    (r"hackernoon\.com",               "HackerNoon"),
    (r"lobste\.rs",                    "Lobsters"),
    (r"slashdot\.org",                 "Slashdot"),
    (r"wordpress\.com|\.wordpress\.",  "WordPress blog"),
    (r"blogspot\.com",                 "Blogspot"),
    (r"wikipedia\.org",                 "Wikipedia"),
    (r"news\.google\.com",             "Google News"),
    (r"bbc\.(co\.uk|com)",             "BBC"),
    (r"nytimes\.com",                  "New York Times"),
    (r"theguardian\.com",              "The Guardian"),
    (r"wired\.com",                    "Wired"),
    (r"techcrunch\.com",               "TechCrunch"),
    (r"technologyreview\.com",         "MIT Tech Review"),
    (r"nature\.com",                   "Nature"),
    (r"scientificamerican\.com",       "Scientific American"),
    (r"arxiv\.org",                    "arXiv"),
    (r"semanticscholar\.org",          "Semantic Scholar"),
    (r"doi\.org",                      "DOI / Journal"),
]


def _detect_platform(url: str) -> str:
    for pattern, label in _PLATFORM_MAP:
        if re.search(pattern, url, re.IGNORECASE):
            return label
    return "External website"


def _bar(value: int, max_value: int, width: int = 20) -> str:
    filled = int(round(value / max_value * width)) if max_value else 0
    return "█" * filled + "░" * (width - filled)


def generate_report(article_url: str, metadata: dict, results: list[dict]) -> str:
    title     = metadata.get("title", "(unknown title)")
    description = metadata.get("description", "")
    keywords  = metadata.get("keywords", [])
    authors   = metadata.get("authors", [])
    year      = metadata.get("year", "")
    cit_count = metadata.get("citation_count")
    inf_count = metadata.get("influential_citation_count")
    fields    = metadata.get("fields_of_study", [])

    platform_counts: dict[str, int] = {}
    usage_counts:    dict[str, int] = {}

    for r in results:
        p = r.get("platform", "External website")
        u = r.get("usage_type", "General mention")
        platform_counts[p] = platform_counts.get(p, 0) + 1
        usage_counts[u]    = usage_counts.get(u, 0) + 1

    max_p = max(platform_counts.values(), default=1)
    max_u = max(usage_counts.values(), default=1)

    lines = []
    sep   = "═" * 70

    lines += [
        sep,
        "  ARTICLE REFERENCE ANALYSIS REPORT",
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        sep,
        "",
        "ARTICLE",
        "-------",
        f"  URL   : {article_url}",
        f"  Title : {title}",
    ]
    if authors:
        lines.append(f"  Authors: {', '.join(authors[:5])}")
    if year:
        lines.append(f"  Year  : {year}")
    if fields:
        lines.append(f"  Fields: {', '.join(fields)}")
    if description:
        lines.append(f"  Abstract: {description[:200]}{'…' if len(description) > 200 else ''}")
    if keywords:
        lines.append(f"  Terms : {', '.join(keywords)}")

    lines += ["", "SUMMARY", "-------"]
    if cit_count is not None:
        lines.append(f"  Total citations (Semantic Scholar) : {cit_count}")
    if inf_count is not None:
        lines.append(f"  Influential citations              : {inf_count}")
    lines += [
        f"  References found in this run      : {len(results)}",
        f"  Unique platforms                  : {len(platform_counts)}",
        f"  Usage types identified            : {len(usage_counts)}",
        "",
    ]

    if platform_counts:
        lines += ["DISTRIBUTION BY PLATFORM", "------------------------"]
        for platform, count in sorted(platform_counts.items(), key=lambda x: -x[1]):
            bar = _bar(count, max_p)
            lines.append(f"  {platform:<30} {bar}  {count}")
        lines.append("")

    if usage_counts:
        lines += ["DISTRIBUTION BY USAGE TYPE", "--------------------------"]
        for usage, count in sorted(usage_counts.items(), key=lambda x: -x[1]):
            bar = _bar(count, max_u)
            lines.append(f"  {usage:<35} {bar}  {count}")
        lines.append("")

    if results:
        lines += ["DETAILED REFERENCES", "-------------------"]
        for i, r in enumerate(results, 1):
            lines += [
                f"  [{i:02d}] Platform   : {r.get('platform', '?')}",
                f"       URL        : {r['url'][:90]}{'…' if len(r['url']) > 90 else ''}",
                f"       Usage type : {r.get('usage_type', '?')}",
                f"       Snippet    : {r['snippet'][:200]}{'…' if len(r['snippet']) > 200 else ''}",
                "",
            ]

    lines += [sep, "  END OF REPORT", sep]
    return "\n".join(lines)


def export_json(article_url: str, metadata: dict, results: list[dict]) -> str:
    clean_meta = {k: v for k, v in metadata.items() if not k.startswith("_")}
    data = {
        "generated_at": datetime.now().isoformat(),
        "article": {
            "url": article_url,
            **clean_meta,
        },
        "summary": {
            "total_references": len(results),
            "platforms":        {},
            "usage_types":      {},
        },
        "references": results,
    }
    for r in results:
        p = r.get("platform", "External website")
        u = r.get("usage_type", "General mention")
        data["summary"]["platforms"][p]   = data["summary"]["platforms"].get(p, 0) + 1
        data["summary"]["usage_types"][u] = data["summary"]["usage_types"].get(u, 0) + 1

    return json.dumps(data, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze how a public article is referenced or discussed online.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url")
    parser.add_argument("--output", choices=["text", "json", "both"], default="text")
    parser.add_argument("--save", metavar="FILE")
    args = parser.parse_args()

    url = args.url.strip()

    if not re.match(r"https?://", url):
        print(f"[ERROR] URL must start with http:// or https://  — got: {url}")
        sys.exit(1)

    print(f"\n{'─'*60}")
    print(f"  Article Reference Analyzer")
    print(f"{'─'*60}")
    print(f"  Target URL : {url}")
    print(f"{'─'*60}\n")

    print("Step 1/3  Extracting article metadata …")
    metadata = extract_metadata(url)
    print(f"  Title    : {metadata['title'] or '(not found)'}")
    print(f"  Keywords : {', '.join(metadata['keywords']) or '(none detected)'}\n")

    print("Step 2/3  Searching for references …")
    results = search_references(url, metadata["title"], metadata["keywords"])
    print(f"\n  Found {len(results)} unique references.\n")

    print("Step 3/3  Generating report …\n")

    if args.output in ("text", "both"):
        report = generate_report(url, metadata, results)
        print(report)
        if args.save and args.output == "text":
            with open(args.save, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\n  Report saved to: {args.save}")

    if args.output in ("json", "both"):
        report_json = export_json(url, metadata, results)
        if args.output == "json":
            print(report_json)
        if args.save:
            fname = args.save if args.output == "json" else args.save.rsplit(".", 1)[0] + ".json"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(report_json)
            print(f"\n  JSON report saved to: {fname}")

    if not results:
        print("\n  [INFO] No references found. Try a more widely shared article,")
        print("         or check if the article title could be extracted correctly.")


if __name__ == "__main__":
    main()
