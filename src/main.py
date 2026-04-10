import sys
import re
from datetime import datetime
sys.path.insert(0, "src")

from processing import extract_metadata, search_references, generate_report, export_json

URL    = "https://arxiv.org/abs/2001.08361"
OUTPUT = "both"

_arxiv_id = re.search(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]+)", URL)
_slug     = _arxiv_id.group(1) if _arxiv_id else re.sub(r"[^a-zA-Z0-9]", "_", URL)[:40]
_ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
SAVE      = f"report_{_slug}_{_ts}"

if not re.match(r"https?://", URL):
    print(f"[ERROR] URL muss mit http:// oder https:// beginnen — erhalten: {URL}")
    sys.exit(1)

print(f"\n{'─'*60}")
print(f"  Article Reference Analyzer")
print(f"{'─'*60}")
print(f"  Target URL : {URL}")
print(f"{'─'*60}\n")

print("Step 1/3  Extracting article metadata …")
metadata = extract_metadata(URL)
print(f"  Title    : {metadata['title'] or '(not found)'}")
print(f"  Keywords : {', '.join(metadata['keywords']) or '(none detected)'}\n")

print("Step 2/3  Searching for references …")
results = search_references(URL, metadata["title"], metadata["keywords"])
print(f"\n  Found {len(results)} unique references.\n")

print("Step 3/3  Generating report …\n")

if OUTPUT in ("text", "both"):
    report = generate_report(URL, metadata, results)
    print(report)
    if SAVE and OUTPUT == "text":
        with open(SAVE, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  Report saved to: {SAVE}")

if OUTPUT in ("json", "both"):
    report_json = export_json(URL, metadata, results)
    if OUTPUT == "json":
        print(report_json)
    if SAVE:
        fname = SAVE if OUTPUT == "json" else SAVE.rsplit(".", 1)[0] + ".json"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report_json)
        print(f"\n  JSON report saved to: {fname}")

if not results:
    print("\n  No references found.")