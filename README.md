# ICLR 2026 Paper Scraper & Analyzer

This project provides tools to scrape accepted **ICLR 2026 (Oral)** papers, download their PDFs, and analyze the publication history of their authors using arXiv.

## Features

- **Paper Scraper**: efficiently fetches "Accept (Oral)" papers from OpenReview V2 API.
- **PDF Downloader**: automatically downloads PDFs to a local directory.
- **Author Analysis**: aggregates author metadata and fetches publication statistics from arXiv.
- **MongoDB Storage**: stores all metadata and analysis results in a MongoDB database.

## Prerequisites

- **Python 3.12+** (managed via `uv`)
- **Docker** (for MongoDB)
- **OpenReview Account** (username/password)

## Setup

1.  **Clone the repository** and enter the directory.

2.  **Environment Variables**:
    Create a `.env` file with your OpenReview credentials:
    ```bash
    OPENREVIEW_USERNAME=your_email@example.com
    OPENREVIEW_PASSWORD=your_password
    ```

3.  **Start MongoDB**:
    Use the provided Makefile to start a MongoDB container:
    ```bash
    make db
    ```
    (Or run `docker compose up -d mongodb` directly).

4.  **Install Dependencies**:
    ```bash
    uv sync
    ```

## Usage

The application is a CLI build with `typer`.

### 1. Process Papers

Scrape accepted papers and download PDFs:

```bash
uv run main.py process-papers
```

- Fetches metadata for all "Accept (Oral)" papers.
- Downloads PDFs to the `./pdfs` directory.
- Stores data in MongoDB collection `iclr-2026.papers`.

### 2. Analyze Authors

After processing papers, analyze the authors:

```bash
uv run main.py process-authors
```

- Extracts unique authors from the saved papers.
- Fetches profile info from OpenReview (institution, preferred name).
- Searches arXiv for total paper counts and latest publications.
- Stores data in MongoDB collection `iclr-2026.authors`.

### 3. Top Papers

List papers from proper ICLR 2026 authors (based on arXiv publication count):

```bash
uv run main.py top-papers --limit 20
```

- Filters authors by total arXiv hits.
- Lists top N authors.
- Displays ICLR 2026 papers authored by them.
- Optional: `--export results.json` to save output.

## Data Structure

**Database**: `iclr-2026`

### `papers` Collection
```json
{
  "_id": "PaperID",
  "title": "Paper Title",
  "authors": ["Author 1", "Author 2"],
  "decision": "Accept (Oral)",
  "pdf_path": "/abs/path/to/pdfs/PaperID.pdf",
  "published_date": ISODate("...")
}
```

### `authors` Collection
```json
{
  "_id": "~OpenReviewID_or_Name",
  "names": ["Author Name"],
  "iclr_2026_count": 1,
  "openreview": {
    "institution": "University Name"
  },
  "arxiv": {
    "total_hits": 42,
    "latest_paper": {
      "title": "Latest Work",
      "date": ISODate("..."),
      "url": "http://arxiv.org/abs/..."
    }
  }
}
```
