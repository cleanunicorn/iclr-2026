import typer
import os
import requests
import time
import arxiv
from datetime import datetime
from pymongo import MongoClient
from openreview.api import OpenReviewClient
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = typer.Typer()

# Constants
OPENREVIEW_BASEURL = 'https://api2.openreview.net'
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "iclr-2026"
COLLECTION_NAME = "papers"
AUTHORS_COLLECTION = "authors"
PDF_DIR = "pdfs"

def download_pdf(url, save_path):
    """Downloads PDF from url to save_path."""
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"Error downloading PDF from {url}: {e}")
        return False

@app.command()
def process_papers():
    """
    Scrapes ICLR 2026 'Accept (Oral)' papers,
    downloads PDFs, and stores metadata in MongoDB.
    """
    print(f"Connecting to MongoDB at {MONGO_URI}...")
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # Create PDF directory if it doesn't exist
    if not os.path.exists(PDF_DIR):
        os.makedirs(PDF_DIR)

    print("Initializing OpenReview Client...")
    try:
        client = OpenReviewClient(
            baseurl=OPENREVIEW_BASEURL,
            username=os.getenv('OPENREVIEW_USERNAME'),
            password=os.getenv('OPENREVIEW_PASSWORD')
        )
    except Exception as e:
        print(f"Failed to initialize client: {e}")
        return

    print("Fetching 'Accept (Oral)' papers...")
    # Efficient query using venue content
    papers = client.get_all_notes(content={'venue': 'ICLR 2026 Oral'})
    print(f"Found {len(papers)} Accept (Oral) papers.")

    processed_count = 0
    new_count = 0

    for paper in tqdm(papers, desc="Processing Papers"):
        try:
            paper_id = paper.id
            content = paper.content
            
            title = content.get('title', {}).get('value', 'Untitled')
            authors = content.get('authors', {}).get('value', [])
            authorids = content.get('authorids', {}).get('value', [])
            
            # Timestamp handling
            ts = paper.pdate if paper.pdate else paper.cdate
            published_date = datetime.fromtimestamp(ts / 1000.0) if ts else datetime.now()
            
            # PDF handling
            # PDF value is usually relative path e.g. /pdf/id.pdf
            pdf_suffix = content.get('pdf', {}).get('value', '')
            if pdf_suffix.startswith('/'):
                pdf_url = f"https://openreview.net{pdf_suffix}"
            else:
                 # fallback if it's full url or empty
                 pdf_url = pdf_suffix if pdf_suffix else f"https://openreview.net/pdf?id={paper_id}"

            pdf_filename = f"{paper_id}.pdf"
            pdf_path = os.path.join(PDF_DIR, pdf_filename)
            
            # Download PDF if not exists
            if not os.path.exists(pdf_path):
                # print(f"Downloading PDF: {title}")
                success = download_pdf(pdf_url, pdf_path)
                if not success:
                    print(f"Failed to download PDF for {paper_id}")
            
            # Upsert into MongoDB
            doc = {
                "_id": paper_id,
                "title": title,
                "authors": authors,
                "authorids": authorids,  # Added author IDs
                "published_date": published_date,
                "decision": "Accept (Oral)",
                "venue": "ICLR 2026 Oral",
                "pdf_url": pdf_url,
                "pdf_path": os.path.abspath(pdf_path),
                "forum_url": f"https://openreview.net/forum?id={paper.forum}",
                "processed_at": datetime.now()
            }
            
            result = collection.update_one(
                {"_id": paper_id},
                {"$set": doc},
                upsert=True
            )
            
            processed_count += 1
            if result.upserted_id:
                new_count += 1
                
        except Exception as e:
            print(f"Error processing paper {paper.id}: {e}")

    print(f"Finished processing.")
    print(f"Total Papers Found: {len(papers)}")
    print(f"Processed: {processed_count}")
    print(f"New Insertions: {new_count}")

@app.command()
def process_authors():
    """
    Analyzes authors from stored papers.
    Fetches profile from OpenReview (if available) and publication stats from arXiv.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    papers_col = db[COLLECTION_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    
    print("Initializing OpenReview Client...")
    try:
        or_client = OpenReviewClient(
            baseurl=OPENREVIEW_BASEURL,
            username=os.getenv('OPENREVIEW_USERNAME'),
            password=os.getenv('OPENREVIEW_PASSWORD')
        )
    except Exception as e:
        print(f"Failed to initialize OpenReview client: {e}")
        return

    # 1. Collect all unique authors from papers
    print("Collecting authors from papers...")
    all_papers = list(papers_col.find({}, {"authors": 1, "authorids": 1}))
    
    # Map author ID to Name (preferred) or Name to ID
    # We use a dictionary to deduplicate by ID if available, else by name.
    # Key: Author ID (if ~...) or Name. Value: {name, ids: set()}
    author_map = {}
    
    for p in all_papers:
        p_authors = p.get('authors', [])
        p_ids = p.get('authorids', [])
        
        # Zip them safely
        for i, name in enumerate(p_authors):
            aid = p_ids[i] if i < len(p_ids) else None
            
            # Use ID as key if it looks like a profile ID (~...)
            # Otherwise use name.
            key = aid if (aid and aid.startswith('~')) else name
            
            if key not in author_map:
                author_map[key] = {
                    "names": {name},
                    "ids": {aid} if aid else set(),
                    "papers_in_dataset": 0
                }
            else:
                author_map[key]["names"].add(name)
                if aid:
                    author_map[key]["ids"].add(aid)
            
            author_map[key]["papers_in_dataset"] += 1

    print(f"Found {len(author_map)} unique authors to process.")
    
    # Process each author
    for key, data in tqdm(author_map.items(), desc="Processing Authors"):
        # Check if already processed recently?
        # For now, simplistic upsert.
        
        primary_name = list(data["names"])[0]
        primary_id = list(data["ids"])[0] if data["ids"] else None
        
        # OpenReview Profile
        or_profile = {}
        if primary_id and primary_id.startswith('~'):
            try:
                # API V2 get_profile
                p = or_client.get_profile(primary_id)
                if p:
                    or_profile = {
                        "id": p.id,
                        "preferred_name": p.get_preferred_name(),
                        "institution": p.content.get('history', [{}])[0].get('institution', {}).get('name') if p.content.get('history') else None
                    }
            except Exception:
                pass
        
        # arXiv Stats
        arxiv_stats = {"total_hits": 0, "latest_paper": None}
        try:
            # Search by name. 
            # Note: Searching by name is ambiguous.
            search_query = f'au:"{primary_name}"'
            search = arxiv.Client().results(
                arxiv.Search(
                    query=search_query,
                    max_results=50, # Limit to avoid overload
                    sort_by=arxiv.SortCriterion.SubmittedDate
                )
            )
            
            count = 0
            latest = None
            
            # Iterate to count. 
            # The client returns a generator.
            for result in search:
                count += 1
                if count == 1:
                    latest = {
                        "title": result.title,
                        "date": result.published,
                        "url": result.entry_id
                    }
            
            arxiv_stats["total_hits"] = count # limited by max_results
            arxiv_stats["latest_paper"] = latest
            
            # If we hit max_results, we know it's at least that many
            if count == 50:
                arxiv_stats["total_hits"] = "50+"
                
        except Exception as e:
            # print(f"arXiv error for {primary_name}: {e}")
            pass

        # Prepare doc
        author_doc = {
            "_id": key, # ~ID or Name
            "names": list(data["names"]),
            "ids": list(data["ids"]),
            "iclr_2026_count": data["papers_in_dataset"],
            "openreview": or_profile,
            "arxiv": arxiv_stats,
            "updated_at": datetime.now()
        }
        
        try:
            authors_col.update_one(
                {"_id": key},
                {"$set": author_doc},
                upsert=True
            )
        except Exception as e:
            print(f"Error saving author {key}: {e}")

    print("Author processing complete.")

@app.command()
def top_papers(limit: int = 10, export: str = None):
    """
    Lists papers from the top prolific authors (based on arXiv stats).
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    papers_col = db[COLLECTION_NAME] # iclr-2026.papers

    print("Fetching top authors...")
    authors = list(authors_col.find({}))
    
    # Sort authors by arXiv total_hits
    def get_hits(a):
        hits = a.get('arxiv', {}).get('total_hits', 0)
        if isinstance(hits, str) and "50+" in hits:
            return 50 # Treat as high number
        return int(hits) if isinstance(hits, int) else 0

    authors.sort(key=get_hits, reverse=True)
    
    top_authors = authors[:limit]
    
    print(f"\n--- Top {limit} Authors (by arXiv count) ---")
    for i, author in enumerate(top_authors):
        hits = author.get('arxiv', {}).get('total_hits', 0)
        name = author.get('names', ['Unknown'])[0]
        print(f"{i+1}. {name} ({hits} papers)")

    # Collect papers for these authors
    print("\n--- Papers by Top Authors ---")
    
    top_author_names = set()
    for ta in top_authors:
        top_author_names.update(ta.get('names', []))
    
    # Find papers
    # Since MongoDB stored 'authors' as list of strings, we use $in
    query = {"authors": {"$in": list(top_author_names)}}
    papers = list(papers_col.find(query))
    
    # Organize by author to show clearly? Or list papers.
    # Let's list papers and mention which top author(s) are on it.
    
    results = []

    for p in papers:
        p_authors = p.get('authors', [])
        # find intersection
        intersect = [a for a in p_authors if a in top_author_names]
        
        paper_info = {
            "title": p.get('title'),
            "top_authors_on_paper": intersect,
            "all_authors": p_authors,
            "pdf_url": p.get('pdf_url'),
            "local_pdf": p.get('pdf_path')
        }
        results.append(paper_info)

        print(f"\nTitle: {paper_info['title']}")
        print(f"Top Authors: {', '.join(intersect)}")
        print(f"PDF: {paper_info['local_pdf']}")

    if export:
        import json
        with open(export, 'w') as f:
            # datetime not serializable, convert if needed but we constructed dicts with strings
            json.dump(results, f, indent=2)
        print(f"\nExported {len(results)} papers to {export}")

def make_request_with_backoff(url, params=None, max_retries=5, backoff_factor=1.0):
    """
    Makes a GET request with exponential backoff for 429 situations.
    """
    import time
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params)
            if r.status_code == 200:
                return r
            elif r.status_code == 429:
                sleep_time = backoff_factor * (2 ** attempt)
                print(f"Rate limited (429). Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                # Other errors, maybe transient?
                if r.status_code >= 500:
                    sleep_time = backoff_factor * (2 ** attempt)
                    time.sleep(sleep_time)
                else:
                     return r # Return error response
        except Exception as e:
            print(f"Request exception: {e}")
            sleep_time = backoff_factor * (2 ** attempt)
            time.sleep(sleep_time)
            
    return None

@app.command()
def enrich_authors(limit: int = 0):
    """
    Enriches author data with award estimates from Semantic Scholar.
    Uses ICLR 2026 papers to resolve Author IDs accurately.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    try:
        authors_col = db[AUTHORS_COLLECTION]
        papers_col = db[COLLECTION_NAME]
    except Exception as e:
        print(f"DB Error: {e}")
        return

    # Get authors who need enrichment (or all if we want to update)
    # targeting those without 'ss_id' or force update?
    # For now, process all or limit.
    query = {}
    total_authors = authors_col.count_documents(query)
    print(f"Found {total_authors} authors to enrich.")
    
    cursor = authors_col.find(query)
    if limit > 0:
        cursor = cursor.limit(limit)

    import time
    
    processed = 0
    updated = 0
    
    for author_doc in tqdm(list(cursor), desc="Enriching Authors"):
        processed += 1
        name = author_doc.get('names', [''])[0]
        aid = author_doc.get('_id')
        
        # Check if already has SS data? verify update strategy.
        # if 'ss_id' in author_doc: continue 
        
        # 1. Find a paper they authored to resolve ID
        paper = papers_col.find_one({"authors": name})
        if not paper:
            # Should not happen if data is consistent
            continue
            
        paper_title = paper.get('title')
        
        # 2. Search SS for this paper
        ss_author_id = None
        
        try:
            # Search Paper
            search_url = "https://api.semanticscholar.org/graph/v1/paper/search"
            # Use backoff
            r = make_request_with_backoff(search_url, params={"query": paper_title, "fields": "authors", "limit": 1})
            
            if r and r.status_code == 200:
                data = r.json()
                if 'data' in data and data['data']:
                    ss_paper = data['data'][0]
                    # Find matching author
                    for a in ss_paper.get('authors', []):
                        # Simple name match? 
                        # name in DB: "Evgeny Burnaev"
                        # name in SS: "E. Burnaev" or "Evgeny Burnaev"
                        # We use simple inclusion or approximate match?
                        # Let's try flexible match.
                        a_name = a.get('name', '')
                        if not a_name: continue
                        
                        # Check if last names match and first initial?
                        # Normalize
                        db_parts = name.lower().split()
                        ss_parts = a_name.lower().split()
                        
                        if len(db_parts) > 0 and len(ss_parts) > 0:
                            # Last name match
                            if db_parts[-1] == ss_parts[-1]:
                                ss_author_id = a.get('authorId')
                                break
        except Exception as e:
            # print(f"SS Search Error: {e}")
            pass
            
        if not ss_author_id:
            # Fallback: Search author by name? (Less reliable)
            pass
        else:
            # 3. Fetch Author Details (Awards check)
            try:
                # rate limit
                time.sleep(1.0) # be nice to public API
                
                details_url = f"https://api.semanticscholar.org/graph/v1/author/{ss_author_id}"
                # We need papers to scan for awards
                d_params = {
                    "fields": "papers.venue,papers.publicationVenue,papers.title,papers.year",
                    "limit": 500
                }
                
                # Use backoff
                r2 = make_request_with_backoff(details_url, params=d_params)
                
                if r2 and r2.status_code == 200:
                    details = r2.json()
                    papers_list = details.get('papers', [])
                    
                    # 4. Count Awards
                    award_keywords = ['best paper', 'award', 'spotlight', 'oral', 'distinguished', 'prize']
                    # Note: "Oral" might match "Temporal..." if insensitive? -> No, "Oral" is usually a standalone word or "Oral Presentation".
                    # Be careful with "Oral". In ICLR context, we are looking for filtered papers too.
                    # But checking previous history.
                    
                    award_count = 0
                    award_matches = []
                    
                    for p in papers_list:
                        venue_str = (p.get('venue') or '') + " " + (str(p.get('publicationVenue') or ''))
                        venue_lower = venue_str.lower()
                        title_lower = (p.get('title') or '').lower()
                        
                        # Heuristic check
                        found_kw = []
                        for kw in award_keywords:
                            if kw in venue_lower:
                                found_kw.append(kw)
                        
                        if found_kw:
                            award_count += 1
                            award_matches.append({
                                "title": p.get('title'),
                                "venue": venue_str,
                                "year": p.get('year'),
                                "keywords": found_kw
                            })
                            
                    # Update DB
                    authors_col.update_one(
                        {"_id": aid},
                        {"$set": {
                            "ss_id": ss_author_id,
                            "award_estimate_count": award_count,
                            "award_details": award_matches,
                            "enriched_at": datetime.now()
                        }}
                    )
                    updated += 1
                    
            except Exception as e:
                pass

    print(f"Enrichment complete. Processed {processed}. Updated {updated}.")

@app.command()
def show_awards():
    """
    Lists authors with detected awards.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    
    # query for award_estimate_count > 0
    query = {"award_estimate_count": {"$gt": 0}}
    authors = list(authors_col.find(query).sort("award_estimate_count", -1))
    
    print(f"Found {len(authors)} authors with potential awards.")
    
    for a in authors:
        name = a.get('names', [''])[0]
        count = a.get('award_estimate_count')
        details = a.get('award_details', [])
        print(f"\nAuthor: {name} (Count: {count})")
        for d in details:
            print(f"  - {d.get('title')} ({d.get('venue')})")

@app.command()
def awarded_papers():
    """
    Lists ICLR 2026 papers authored by individuals who have previously received awards.
    """
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client[DB_NAME]
    authors_col = db[AUTHORS_COLLECTION]
    papers_col = db[COLLECTION_NAME]
    
    # 1. Get awarded authors
    query = {"award_estimate_count": {"$gt": 0}}
    awarded_authors_docs = list(authors_col.find(query))
    
    if not awarded_authors_docs:
        print("No authors with detected awards found.")
        return

    # Extract names
    awarded_names = set()
    author_map = {} # Name -> Award Details
    for doc in awarded_authors_docs:
        for name in doc.get('names', []):
            awarded_names.add(name)
            author_map[name] = doc

    print(f"Found {len(awarded_names)} distinct names for {len(awarded_authors_docs)} awarded authors.")

    # 2. Find papers
    paper_query = {"authors": {"$in": list(awarded_names)}}
    papers = list(papers_col.find(paper_query))
    
    print(f"\n--- ICLR 2026 Papers by Awarded Authors ({len(papers)} found) ---")
    
    for p in papers:
        title = p.get('title')
        url = p.get('pdf_url')
        p_authors = p.get('authors', [])
        
        # Identify which authors are the awarded ones
        awards_on_paper = []
        for a in p_authors:
            if a in awarded_names:
                awards_on_paper.append(a)
        
        print(f"\nTitle: {title}")
        print(f"Awarded Authors: {', '.join(awards_on_paper)}")
        print(f"URL: {url}")
        
        for a in awards_on_paper:
            details = author_map[a].get('award_details', [])
            print(f"  * {a}: {len(details)} prior awards detected.")

if __name__ == "__main__":
    app()
