# Lector — Vectorless Reasoning-based RAG

> **Lector** (Latin: "reader") — an AI that reads documents like a human, not like a search engine.

Lector is a vectorless, reasoning-based RAG system for long document understanding. Instead of chunking + embedding + vector search, Lector uses LLM reasoning to build tree-structured indexes and retrieve relevant content by understanding document semantics.

## Features

- **No vector database** — Pure reasoning-based retrieval, no embeddings needed
- **Tree-structured indexing** — Documents are organized into hierarchical trees with summaries at each node
- **Auto-search** — Ask questions without selecting documents; Lector automatically finds relevant content across all indexed files
- **Link local files** — Link PDF/Markdown files by path (no upload/copy), supports single files and folders
- **Chinese support** — Built-in Chinese text search with sliding-window token matching
- **Dark mode** — Full dark mode support
- **Beautiful UI** — EB Garamond serif typography, particle animations, breathing glow effects (花叔Design philosophy)

## Quick Start

### 1. Install dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install core dependencies
pip install -r requirements.txt

# Install web app dependencies
pip install flask flask-cors playwright
playwright install chromium
```

### 2. Configure LLM API

Create a `.env` file in the project root:

```bash
PAGEINDEX_API_KEY=your-api-key-here
PAGEINDEX_API_BASE=https://api.openai.com/v1  # or your preferred endpoint
PAGEINDEX_MODEL=gpt-4o  # or any model supported by litellm
```

### 3. Run the web app

```bash
python web_app/app.py
```

Open http://localhost:7860 in your browser.

### 4. Link documents

- Enter an absolute file path (e.g. `/path/to/document.pdf`) and click **Link**
- Or click **Choose** to pick a file from your system, then complete the absolute path
- Supports `.pdf`, `.md`, `.markdown`, `.txt` files
- Use **Link Folder** to batch-index all supported files in a directory

### 5. Ask questions

- Type any question in the search bar — Lector will auto-search across all indexed documents
- Or click a document in the sidebar to focus your question on that document

## Architecture

```
web_app/
├── app.py              # Flask server (API + page rendering)
├── templates/
│   └── index.html      # Single-page app (HTML + CSS + JS)
├── static/
│   ├── logo.svg        # Lector logo (vector)
│   └── logo.png        # Lector logo (fallback)
├── workspace/          # Indexed document data (auto-created)
└── uploads/            # (empty — upload feature removed)
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/documents` | GET | List all indexed documents |
| `/api/index-local` | POST | Link a local file by path |
| `/api/index-folder` | POST | Link all files in a folder |
| `/api/index/jobs` | GET | Get indexing job status |
| `/api/document/<id>` | DELETE | Delete a document |
| `/api/documents` | DELETE | Delete all documents |
| `/api/chat` | POST | Chat with AI (auto-search if no docs selected) |
| `/api/document/<id>/structure` | GET | Get document tree structure |
| `/api/document/<id>/file` | GET | Get original file |

## Philosophy

**One detail at 120%, others at 80%** — The breathing logo glow is the 120% detail; everything else supports it quietly.

Anti-AI-slop rules: no purple gradients, no emoji in UI, no Inter/Roboto, no card+border-accent pattern.

## License

Same as original PageIndex project.