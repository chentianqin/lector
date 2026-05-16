"""
PageIndex Web UI — Flask application
Vectorless, reasoning-based RAG system with a beautiful frontend.
"""

import os
import sys
import json
import uuid
import threading
import time
import traceback
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, jsonify, send_from_directory

# Add PageIndex to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pageindex.client import PageIndexClient

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB

WORKSPACE = Path(__file__).resolve().parent / "workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)

# Global client — initialized lazily
_client = None
_client_lock = threading.Lock()

# Indexing jobs tracking
_indexing_jobs = {}
_indexing_jobs_lock = threading.Lock()


def get_client() -> PageIndexClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = PageIndexClient(workspace=str(WORKSPACE))
        return _client


def _run_index(job_id: str, file_path: str, mode: str):
    """Run indexing in a background thread, updating job status."""
    try:
        # Check for API key before indexing PDFs
        import os
        if not os.getenv("PAGEINDEX_API_KEY") and not os.getenv("OPENAI_API_KEY") and not os.getenv("CHATGPT_API_KEY"):
            ext = os.path.splitext(file_path)[1].lower()
            if ext == '.pdf':
                with _indexing_jobs_lock:
                    _indexing_jobs[job_id]["status"] = "failed"
                    _indexing_jobs[job_id]["error"] = "PDF indexing requires an OpenAI API key. Please set OPENAI_API_KEY in your environment or create a .env file. Markdown files work without an API key."
                    _indexing_jobs[job_id]["progress"] = "Failed: No API key configured"
                return

        with _indexing_jobs_lock:
            _indexing_jobs[job_id]["status"] = "indexing"
            _indexing_jobs[job_id]["progress"] = "Building document structure with LLM reasoning..."

        client = get_client()
        doc_id = client.index(file_path, mode=mode)

        with _indexing_jobs_lock:
            _indexing_jobs[job_id]["status"] = "completed"
            _indexing_jobs[job_id]["doc_id"] = doc_id
            _indexing_jobs[job_id]["progress"] = "Indexing complete"
            _indexing_jobs[job_id]["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        # Provide more helpful error messages for common issues
        if 'toc_detected' in error_msg or 'rate_limit' in error_msg.lower():
            error_msg = f"LLM call failed — this usually means your API key is invalid, rate-limited, or the model name is wrong. Error: {e}"
        with _indexing_jobs_lock:
            _indexing_jobs[job_id]["status"] = "failed"
            _indexing_jobs[job_id]["error"] = error_msg
            _indexing_jobs[job_id]["progress"] = f"Failed: {error_msg}"


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    resp = render_template("index.html")
    from flask import make_response
    response = make_response(resp)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response



@app.route("/api/index-local", methods=["POST"])
def api_index_local():
    """Index a local file by path (no upload needed)."""
    data = request.get_json(force=True)
    file_path = data.get("path", "").strip()
    if not file_path:
        return jsonify({"error": "No file path provided"}), 400

    file_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(file_path):
        return jsonify({"error": f"File not found: {file_path}"}), 404

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".pdf", ".md", ".markdown", ".txt"):
        return jsonify({"error": f"Unsupported file type: {ext}. Use .pdf or .md"}), 400

    filename = os.path.basename(file_path)
    mode = "auto"
    job_id = uuid.uuid4().hex[:12]

    with _indexing_jobs_lock:
        _indexing_jobs[job_id] = {
            "id": job_id,
            "filename": filename,
            "status": "queued",
            "progress": "Linking local file, queued for indexing...",
            "created_at": datetime.now().isoformat(),
            "doc_id": None,
            "error": None,
        }

    thread = threading.Thread(target=_run_index, args=(job_id, file_path, mode), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "filename": filename, "status": "queued"})


@app.route("/api/index-folder", methods=["POST"])
def api_index_folder():
    """Index all supported files in a local folder."""
    data = request.get_json(force=True)
    folder_path = data.get("path", "").strip()
    recursive = data.get("recursive", True)
    if not folder_path:
        return jsonify({"error": "No folder path provided"}), 400

    folder_path = os.path.abspath(os.path.expanduser(folder_path))
    if not os.path.isdir(folder_path):
        return jsonify({"error": f"Directory not found: {folder_path}"}), 404

    supported_ext = {".pdf", ".md", ".markdown", ".txt"}
    found_files = []

    if recursive:
        for root, dirs, files in os.walk(folder_path):
            # Skip hidden dirs and common non-content dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", ".venv", "venv")]
            for f in sorted(files):
                if os.path.splitext(f)[1].lower() in supported_ext:
                    found_files.append(os.path.join(root, f))
    else:
        for f in sorted(os.listdir(folder_path)):
            full = os.path.join(folder_path, f)
            if os.path.isfile(full) and os.path.splitext(f)[1].lower() in supported_ext:
                found_files.append(full)

    if not found_files:
        return jsonify({"error": "No supported files found in this directory", "found_count": 0}), 404

    # Create indexing jobs for each file
    jobs = []
    for file_path in found_files:
        filename = os.path.basename(file_path)
        mode = "auto"
        job_id = uuid.uuid4().hex[:12]

        with _indexing_jobs_lock:
            _indexing_jobs[job_id] = {
                "id": job_id,
                "filename": filename,
                "status": "queued",
                "progress": "Queued for indexing...",
                "created_at": datetime.now().isoformat(),
                "doc_id": None,
                "error": None,
            }

        thread = threading.Thread(target=_run_index, args=(job_id, file_path, mode), daemon=True)
        thread.start()
        jobs.append({"job_id": job_id, "filename": filename})

    return jsonify({
        "status": "queued",
        "folder": folder_path,
        "found_count": len(found_files),
        "jobs": jobs,
    })


@app.route("/api/index/jobs", methods=["GET"])
def api_index_jobs():
    """List all indexing jobs (active and recently completed)."""
    with _indexing_jobs_lock:
        jobs = []
        for job_id, job in _indexing_jobs.items():
            jobs.append({
                "job_id": job_id,
                "filename": job.get("filename", ""),
                "status": job.get("status", "unknown"),
                "progress": job.get("progress", ""),
                "error": job.get("error"),
            })
    return jsonify(jobs)


@app.route("/api/index/<job_id>", methods=["GET"])
def api_index_status(job_id):
    with _indexing_jobs_lock:
        job = _indexing_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/documents", methods=["GET"])
def api_documents():
    client = get_client()
    docs = []
    for doc_id, doc in client.documents.items():
        entry = {
            "id": doc_id,
            "doc_name": doc.get("doc_name", ""),
            "doc_description": doc.get("doc_description", ""),
            "type": doc.get("type", ""),
            "path": doc.get("path", ""),
        }
        if doc.get("type") == "pdf":
            entry["page_count"] = doc.get("page_count", 0)
        elif doc.get("type") == "md":
            entry["line_count"] = doc.get("line_count", 0)
        docs.append(entry)
    return jsonify(docs)


@app.route("/api/document/<doc_id>", methods=["GET"])
def api_document(doc_id):
    client = get_client()
    result = json.loads(client.get_document(doc_id))
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/api/document/<doc_id>/file", methods=["GET"])
def api_document_file(doc_id):
    client = get_client()
    doc = client.documents.get(doc_id)
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    doc_name = doc.get("doc_name", "")
    # Use original file path stored in metadata
    file_path = doc.get("file_path", "")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404
    from flask import send_file
    mime = "application/pdf" if doc_name.endswith(".pdf") else "text/markdown"
    return send_file(str(file_path), mimetype=mime)


@app.route("/api/document/<doc_id>/structure", methods=["GET"])
def api_document_structure(doc_id):
    client = get_client()
    result = json.loads(client.get_document_structure(doc_id))
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/api/document/<doc_id>/pages", methods=["GET"])
def api_document_pages(doc_id):
    pages = request.args.get("pages", "1")
    client = get_client()
    result = json.loads(client.get_page_content(doc_id, pages))
    if isinstance(result, dict) and "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/query", methods=["POST"])
def api_query():
    """Reasoning-based query: find relevant nodes from structure + content."""
    data = request.get_json(force=True)
    doc_id = data.get("doc_id")
    query = data.get("query", "").strip()

    if not doc_id or not query:
        return jsonify({"error": "doc_id and query are required"}), 400

    client = get_client()

    # Get structure
    structure = json.loads(client.get_document_structure(doc_id))
    if isinstance(structure, dict) and "error" in structure:
        return jsonify(structure), 404

    # Get document info
    doc_info = json.loads(client.get_document(doc_id))
    if "error" in doc_info:
        return jsonify(doc_info), 404

    doc_type = doc_info.get("type", "pdf")

    # Pre-fetch all node content for full-text search
    node_contents = {}
    for node in structure:
        nid = node.get("node_id", "")
        try:
            if doc_type == "pdf" and node.get("start_index") and node.get("end_index"):
                page_range = f"{node['start_index']}-{node['end_index']}"
            elif doc_type == "md" and node.get("line_num"):
                line_num = node.get("line_num")
                total_lines = doc_info.get("line_count", 100)
                start_line = max(1, line_num - 2)
                end_line = min(total_lines, line_num + 30)
                page_range = f"{start_line}-{end_line}"
            else:
                page_range = None
            if page_range:
                content = json.loads(client.get_page_content(doc_id, page_range))
                if isinstance(content, list):
                    # Concatenate all page content for this node
                    full_text = " ".join(p.get("content", "") for p in content)
                    node_contents[nid] = full_text
        except Exception:
            pass

    # Keyword matching on structure + content
    query_lower = query.lower()
    query_terms = query_lower.split()

    matched_nodes = []

    def search_nodes(nodes, depth=0):
        for node in nodes:
            title = node.get("title", "").lower()
            summary = (node.get("summary", "") or node.get("prefix_summary", "")).lower()
            nid = node.get("node_id", "")
            # Get pre-fetched content text
            content_text = node_contents.get(nid, "").lower()
            # Also create compact version (remove spaces for PDF extracted text)
            content_compact = content_text.replace(" ", "")
            score = 0
            for term in query_terms:
                if term in title:
                    score += 3
                if term in summary:
                    score += 2
                if term in content_text:
                    score += 2
                elif term in content_compact:
                    score += 2
            if score > 0:
                matched_nodes.append({
                    "node_id": nid,
                    "title": node.get("title", ""),
                    "summary": node.get("summary", "") or node.get("prefix_summary", ""),
                    "start_index": node.get("start_index"),
                    "end_index": node.get("end_index"),
                    "line_num": node.get("line_num"),
                    "score": score,
                    "depth": depth,
                    "has_children": bool(node.get("nodes")),
                })
            if node.get("nodes"):
                search_nodes(node["nodes"], depth + 1)

    search_nodes(structure)

    # Sort by score descending
    matched_nodes.sort(key=lambda x: x["score"], reverse=True)

    # Fetch content for top matches
    results = []
    for node in matched_nodes[:5]:
        pages_content = []

        if doc_type == "pdf" and node.get("start_index") and node.get("end_index"):
            page_range = f"{node['start_index']}-{node['end_index']}"
            try:
                content = json.loads(client.get_page_content(doc_id, page_range))
                if isinstance(content, list):
                    pages_content = content
            except Exception:
                pass
        elif doc_type == "md" and node.get("line_num"):
            # For markdown, fetch content around the line number
            # Get a range of lines centered on the node's line_num
            line_num = node.get("line_num")
            # Fetch a window of lines
            total_lines = doc_info.get("line_count", 100)
            start_line = max(1, line_num - 2)
            end_line = min(total_lines, line_num + 30)
            try:
                content = json.loads(client.get_page_content(doc_id, f"{start_line}-{end_line}"))
                if isinstance(content, list):
                    pages_content = content
            except Exception:
                pass

        results.append({
            "node": node,
            "pages": pages_content,
        })

    return jsonify({
        "query": query,
        "doc_id": doc_id,
        "doc_type": doc_type,
        "matches": len(matched_nodes),
        "results": results,
    })


@app.route("/api/document/<doc_id>/node/<node_id>/content", methods=["GET"])
def api_node_content(doc_id, node_id):
    """Fetch content for a specific node from the tree structure."""
    client = get_client()

    # Get document info
    doc_info = json.loads(client.get_document(doc_id))
    if "error" in doc_info:
        return jsonify(doc_info), 404

    doc_type = doc_info.get("type", "pdf")

    # Get full structure to find the node
    structure = json.loads(client.get_document_structure(doc_id))
    if isinstance(structure, dict) and "error" in structure:
        return jsonify(structure), 404

    # Find the node by node_id
    def find_node(nodes, target_id):
        for node in nodes:
            if node.get("node_id") == target_id:
                return node
            if node.get("nodes"):
                result = find_node(node["nodes"], target_id)
                if result:
                    return result
        return None

    target = find_node(structure, node_id)
    if not target:
        return jsonify({"error": f"Node {node_id} not found"}), 404

    # Fetch content based on document type
    pages_content = []
    if doc_type == "pdf" and target.get("start_index") and target.get("end_index"):
        page_range = f"{target['start_index']}-{target['end_index']}"
        try:
            content = json.loads(client.get_page_content(doc_id, page_range))
            if isinstance(content, list):
                pages_content = content
        except Exception:
            pass
    elif doc_type == "md" and target.get("line_num"):
        line_num = target.get("line_num")
        total_lines = doc_info.get("line_count", 100)
        # For leaf nodes, get a small window; for parent nodes, get until next sibling
        if target.get("nodes") and len(target["nodes"]) > 0:
            # Parent node — get broader range
            start_line = max(1, line_num)
            end_line = min(total_lines, line_num + 50)
        else:
            start_line = max(1, line_num - 2)
            end_line = min(total_lines, line_num + 30)
        try:
            content = json.loads(client.get_page_content(doc_id, f"{start_line}-{end_line}"))
            if isinstance(content, list):
                pages_content = content
        except Exception:
            pass

    return jsonify({
        "node_id": node_id,
        "title": target.get("title", ""),
        "summary": target.get("summary", "") or target.get("prefix_summary", ""),
        "doc_type": doc_type,
        "pages": pages_content,
    })


@app.route("/api/document/<doc_id>/tree-stats", methods=["GET"])
def api_tree_stats(doc_id):
    """Get statistics about the document tree."""
    client = get_client()
    structure = json.loads(client.get_document_structure(doc_id))
    if isinstance(structure, dict) and "error" in structure:
        return jsonify(structure), 404

    total_nodes = 0
    leaf_nodes = 0
    max_depth = 0

    def traverse(nodes, depth=0):
        nonlocal total_nodes, leaf_nodes, max_depth
        for node in nodes:
            total_nodes += 1
            if not node.get("nodes") or len(node.get("nodes", [])) == 0:
                leaf_nodes += 1
            max_depth = max(max_depth, depth)
            if node.get("nodes"):
                traverse(node["nodes"], depth + 1)

    traverse(structure)

    return jsonify({
        "total_nodes": total_nodes,
        "leaf_nodes": leaf_nodes,
        "branch_nodes": total_nodes - leaf_nodes,
        "max_depth": max_depth,
    })


@app.route("/api/document/<doc_id>/export", methods=["GET"])
def api_export_structure(doc_id):
    """Export the full document structure as JSON."""
    client = get_client()
    doc_info = json.loads(client.get_document(doc_id))
    if "error" in doc_info:
        return jsonify(doc_info), 404

    structure = json.loads(client.get_document_structure(doc_id))
    if isinstance(structure, dict) and "error" in structure:
        return jsonify(structure), 404

    return jsonify({
        "doc_id": doc_id,
        "doc_name": doc_info.get("doc_name", ""),
        "doc_description": doc_info.get("doc_description", ""),
        "type": doc_info.get("type", ""),
        "structure": structure,
    })


@app.route("/api/config", methods=["GET"])
def api_get_config():
    """Get all LLM config: key, base_url, model_id."""
    key = os.getenv("PAGEINDEX_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_API_KEY")
    base_url = os.getenv("PAGEINDEX_API_BASE") or os.getenv("OPENAI_API_BASE", "")
    model_id = os.getenv("PAGEINDEX_MODEL_ID", "")
    # Read from config.yaml as fallback for model_id
    if not model_id:
        try:
            from pageindex.utils import ConfigLoader
            cfg = ConfigLoader().load()
            model_id = getattr(cfg, 'model', '')
        except Exception:
            pass
    return jsonify({
        "key_set": bool(key),
        "key_prefix": key[:8] + "..." if key else "",
        "base_url": base_url,
        "model_id": model_id,
    })


@app.route("/api/config", methods=["POST"])
def api_set_config():
    """Set all LLM config: key, base_url, model_id."""
    data = request.get_json(force=True)
    key = data.get("key", "").strip()
    base_url = data.get("base_url", "").strip()
    model_id = data.get("model_id", "").strip()

    if key:
        os.environ["PAGEINDEX_API_KEY"] = key
    if base_url:
        os.environ["PAGEINDEX_API_BASE"] = base_url
    if model_id:
        os.environ["PAGEINDEX_MODEL_ID"] = model_id

    # Update runtime config so PageIndex picks it up immediately
    from pageindex.utils import set_pageindex_llm_config
    set_pageindex_llm_config(api_key=key or None, api_base=base_url or None)

    # Write to .env file so it persists
    env_path = Path(__file__).resolve().parent.parent / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = [l for l in f.readlines() if not l.startswith((
                "PAGEINDEX_API_KEY=", "PAGEINDEX_API_BASE=", "PAGEINDEX_MODEL_ID="
            ))]
    if key:
        lines.append(f"PAGEINDEX_API_KEY={key}\n")
    if base_url:
        lines.append(f"PAGEINDEX_API_BASE={base_url}\n")
    if model_id:
        lines.append(f"PAGEINDEX_MODEL_ID={model_id}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)

    # Update config.yaml model_id if provided
    if model_id:
        try:
            import yaml
            config_path = Path(__file__).resolve().parent.parent / "pageindex" / "config.yaml"
            if config_path.exists():
                with open(config_path, "r") as f:
                    cfg = yaml.safe_load(f) or {}
                cfg["model"] = model_id
                cfg["retrieve_model"] = model_id
                with open(config_path, "w") as f:
                    yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        except Exception:
            pass

    # Re-initialize client so it picks up the new config
    global _client
    with _client_lock:
        _client = None

    return jsonify({"status": "saved", "key_set": bool(key)})


@app.route("/api/models", methods=["GET"])
def api_models():
    """Fetch available models from the configured API endpoint."""
    try:
        import openai
        api_key = os.getenv("PAGEINDEX_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_API_KEY")
        api_base = os.getenv("PAGEINDEX_API_BASE") or os.getenv("OPENAI_API_BASE", "")
        if not api_key:
            return jsonify({"error": "No API key configured"}), 400
        client = openai.OpenAI(api_key=api_key, base_url=api_base or None)
        models = client.models.list()
        model_ids = sorted([m.id for m in models.data])
        return jsonify(model_ids)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/global-query", methods=["POST"])
def api_global_query():
    """Search across ALL indexed documents for a query."""
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Query is required"}), 400

    client = get_client()
    results = []

    for doc_id, doc in client.documents.items():
        try:
            # Ensure doc is loaded
            if client.workspace:
                client._ensure_doc_loaded(doc_id)

            structure = None
            if doc.get("structure"):
                structure = doc["structure"]
            else:
                structure = json.loads(client.get_document_structure(doc_id))

            if not structure:
                continue

            doc_type = doc.get("type", "pdf")

            # Pre-fetch node content for full-text search
            node_contents = {}
            for node in structure:
                nid = node.get("node_id", "")
                try:
                    if doc_type == "pdf" and node.get("start_index") and node.get("end_index"):
                        page_range = f"{node['start_index']}-{node['end_index']}"
                    elif doc_type == "md" and node.get("line_num"):
                        line_num = node.get("line_num")
                        total_lines = doc.get("line_count", 100)
                        start_line = max(1, line_num - 2)
                        end_line = min(total_lines, line_num + 30)
                        page_range = f"{start_line}-{end_line}"
                    else:
                        page_range = None
                    if page_range:
                        content = json.loads(client.get_page_content(doc_id, page_range))
                        if isinstance(content, list):
                            full_text = " ".join(p.get("content", "") for p in content)
                            node_contents[nid] = full_text
                except Exception:
                    pass

            # Keyword matching on structure + content
            query_lower = query.lower()
            query_terms = query_lower.split()
            matched_nodes = []

            def search_nodes(nodes, depth=0):
                for node in nodes:
                    title = node.get("title", "").lower()
                    summary = (node.get("summary", "") or node.get("prefix_summary", "")).lower()
                    nid = node.get("node_id", "")
                    content_text = node_contents.get(nid, "").lower()
                    content_compact = content_text.replace(" ", "")
                    score = 0
                    for term in query_terms:
                        if term in title:
                            score += 3
                        if term in summary:
                            score += 2
                        if term in content_text:
                            score += 2
                        elif term in content_compact:
                            score += 2
                    if score > 0:
                        matched_nodes.append({
                            "node_id": nid,
                            "title": node.get("title", ""),
                            "summary": node.get("summary", "") or node.get("prefix_summary", ""),
                            "score": score,
                        })
                    if node.get("nodes"):
                        search_nodes(node["nodes"], depth + 1)

            search_nodes(structure)
            matched_nodes.sort(key=lambda x: x["score"], reverse=True)

            if matched_nodes:
                results.append({
                    "doc_id": doc_id,
                    "doc_name": doc.get("doc_name", ""),
                    "doc_type": doc.get("type", ""),
                    "matches": len(matched_nodes),
                    "top_results": matched_nodes[:5],
                })
        except Exception:
            pass

    results.sort(key=lambda x: x["matches"], reverse=True)
    return jsonify({"query": query, "total_docs": len(client.documents), "results": results})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Chat with AI using selected documents as context."""
    data = request.get_json(force=True)
    messages = data.get("messages", [])
    doc_ids = data.get("doc_ids", [])
    query = messages[-1]["content"] if messages else ""

    if not query:
        return jsonify({"error": "No message content"}), 400

    client = get_client()
    
    context_parts = []
    
    # If no docs selected, auto-search across ALL documents
    if not doc_ids:
        query_lower = query.lower()
        # For Chinese: also extract 2-char and 3-char substrings as fallback terms
        auto_terms = [query_lower]
        if len(query_lower) >= 4:
            # Add sliding window substrings (2-4 chars) for Chinese text
            for n in range(2, min(5, len(query_lower)+1)):
                for i in range(len(query_lower) - n + 1):
                    sub = query_lower[i:i+n]
                    if not sub.isspace() and len(sub.strip()) >= 2:
                        auto_terms.append(sub.strip())
        # Deduplicate while preserving order
        seen = set()
        unique_terms = []
        for t in auto_terms:
            if t not in seen:
                seen.add(t)
                unique_terms.append(t)
        auto_terms = unique_terms

        for doc_id_iter, doc_info in client.documents.items():
            try:
                if client.workspace:
                    client._ensure_doc_loaded(doc_id_iter)
                doc_name = doc_info.get("doc_name", "")
                doc_name_lower = doc_name.lower()
                # Score doc by name match
                name_score = 0
                for term in auto_terms:
                    if term in doc_name_lower:
                        name_score += 5
                # Get structure
                structure = doc_info.get("structure")
                if not structure:
                    structure = json.loads(client.get_document_structure(doc_id_iter))
                if not structure:
                    continue
                matched = []
                def _auto_search(nodes, depth=0):
                    for node in nodes:
                        title = node.get("title", "").lower()
                        summary = (node.get("summary", "") or node.get("prefix_summary", "")).lower()
                        score = 0
                        for term in auto_terms:
                            if term in title: score += 3
                            if term in summary: score += 2
                        if score > 0:
                            matched.append((score, node))
                        if node.get("nodes"): _auto_search(node["nodes"], depth+1)
                _auto_search(structure)
                # If doc name matches but no structure matches, include all top-level nodes
                if name_score > 0 and not matched:
                    for node in structure[:5]:
                        matched.append((name_score, node))
                matched.sort(key=lambda x: x[0], reverse=True)
                if matched:
                    for score, node in matched[:3]:
                        node_title = node.get("title", "")
                        node_summary = node.get("summary", "") or node.get("prefix_summary", "")
                        context_parts.append(f"[Doc: {doc_name}, Section: {node_title}]\n{node_summary}")
                        # Also get page content
                        doc_type = doc_info.get("type", "")
                        try:
                            if doc_type == "pdf" and node.get("start_index") and node.get("end_index"):
                                page_range = f"{node['start_index']}-{node['end_index']}"
                                content = json.loads(client.get_page_content(doc_id_iter, page_range))
                                if isinstance(content, list):
                                    for p in content:
                                        context_parts.append(f"[Doc: {doc_name}, Section: {node_title}, Page {p.get('page','')}]:\n{p.get('content','')}")
                            elif doc_type == "md" and node.get("line_num"):
                                line_num = node.get("line_num")
                                total_lines = doc_info.get("line_count", 100)
                                start_line = max(1, line_num - 2)
                                end_line = min(total_lines, line_num + 30)
                                content = json.loads(client.get_page_content(doc_id_iter, f"{start_line}-{end_line}"))
                                if isinstance(content, list):
                                    for p in content:
                                        context_parts.append(f"[Doc: {doc_name}, Section: {node_title}, Line {p.get('page','')}]:\n{p.get('content','')}")
                        except Exception:
                            pass
            except Exception:
                pass

    # Retrieve relevant content from each selected doc
    for doc_id in doc_ids:
        try:
            if client.workspace:
                client._ensure_doc_loaded(doc_id)

            doc = client.documents.get(doc_id)
            if not doc:
                continue

            structure = doc.get("structure")
            if not structure:
                structure = json.loads(client.get_document_structure(doc_id))

            if not structure:
                continue

            # Search for relevant nodes
            query_lower = query.lower()
            query_terms = query_lower.split()
            matched_nodes = []

            def _search(nodes, depth=0):
                for node in nodes:
                    title = node.get("title", "").lower()
                    summary = (node.get("summary", "") or node.get("prefix_summary", "")).lower()
                    score = 0
                    for term in query_terms:
                        if term in title:
                            score += 3
                        if term in summary:
                            score += 2
                    if score > 0:
                        matched_nodes.append((score, node))
                    if node.get("nodes"):
                        _search(node["nodes"], depth + 1)

            _search(structure)
            matched_nodes.sort(key=lambda x: x[0], reverse=True)

            doc_name = doc.get("doc_name", doc_id)
            
            # If keyword matching found results, use those
            if matched_nodes:
                for score, node in matched_nodes[:5]:
                    node_title = node.get("title", "")
                    node_summary = node.get("summary", "") or node.get("prefix_summary", "")
                    context_parts.append(f"[Doc: {doc_name}, Section: {node_title}]\n{node_summary}")

                    # Also try to get page content for top matches
                    doc_type = doc.get("type", "")
                    try:
                        if doc_type == "pdf" and node.get("start_index") and node.get("end_index"):
                            page_range = f"{node['start_index']}-{node['end_index']}"
                            content = json.loads(client.get_page_content(doc_id, page_range))
                            if isinstance(content, list):
                                for p in content:
                                    context_parts.append(f"[Doc: {doc_name}, Section: {node_title}, Page {p.get('page','')}]:\n{p.get('content','')}")
                        elif doc_type == "md" and node.get("line_num"):
                            line_num = node.get("line_num")
                            total_lines = doc.get("line_count", 100)
                            start_line = max(1, line_num - 2)
                            end_line = min(total_lines, line_num + 30)
                            content = json.loads(client.get_page_content(doc_id, f"{start_line}-{end_line}"))
                            if isinstance(content, list):
                                for p in content:
                                    context_parts.append(f"[Doc: {doc_name}, Section: {node_title}, Line {p.get('page','')}]:\n{p.get('content','')}")
                    except Exception:
                        pass
            else:
                # No keyword matches — send full document structure as context
                # Build a flattened outline of the document
                def _flatten(nodes, depth=0):
                    parts = []
                    for node in nodes:
                        title = node.get("title", "Untitled")
                        summary = node.get("summary", "") or node.get("prefix_summary", "")
                        indent = "  " * depth
                        parts.append(f"{indent}- {title}")
                        if summary:
                            parts.append(f"{indent}  Summary: {summary[:200]}")
                        if node.get("nodes"):
                            parts.extend(_flatten(node["nodes"], depth + 1))
                    return parts
                outline = "\n".join(_flatten(structure))
                context_parts.append(f"[Doc: {doc_name} — Full Structure Outline]\n{outline}")
                
                # Also try to get first few pages of content
                doc_type = doc.get("type", "")
                try:
                    if doc_type == "pdf":
                        page_count = doc.get("page_count", 0)
                        if page_count > 0:
                            content = json.loads(client.get_page_content(doc_id, f"1-{min(3, page_count)}"))
                            if isinstance(content, list):
                                for p in content:
                                    context_parts.append(f"[Doc: {doc_name}, Page {p.get('page','')}]:\n{p.get('content','')}")
                    elif doc_type == "md":
                        total_lines = doc.get("line_count", 100)
                        content = json.loads(client.get_page_content(doc_id, f"1-{min(50, total_lines)}"))
                        if isinstance(content, list):
                            for p in content:
                                context_parts.append(f"[Doc: {doc_name}, Line {p.get('page','')}]:\n{p.get('content','')}")
                except Exception:
                    pass
        except Exception:
            pass

    # Build system status info - always include so AI knows what's available
    system_status = []
    all_docs = []
    try:
        for doc_id, doc_info in client.documents.items():
            doc_name = doc_info.get("doc_name", doc_id)
            doc_type = doc_info.get("type", "unknown")
            doc_path = doc_info.get("path", "")
            line_count = doc_info.get("line_count", 0)
            page_count = doc_info.get("page_count", 0)
            size_info = f"{line_count} lines" if doc_type == "md" else f"{page_count} pages"
            all_docs.append(f"- {doc_name} ({doc_type}, {size_info}, path: {doc_path})")
        system_status.append(f"Total indexed documents: {len(all_docs)}")
        if all_docs:
            system_status.append("Document list:\n" + "\n".join(all_docs))
    except Exception:
        system_status.append("Unable to retrieve document list")
    system_status_text = "\n".join(system_status)

    # Build prompt with context
    if context_parts:
        context_text = "\n---\n".join(context_parts)
        system_content = f"You are Lector AI, a specialized assistant for the Lector document intelligence system. You have full knowledge of the system's state and can help users with any questions about their indexed documents.\n\n--- System Status ---\n{system_status_text}\n--- End System Status ---\n\n--- Document Context (auto-retrieved from all docs) ---\n{context_text}\n--- End Context ---\n\nRules:\n1. You know ALL documents in the system. When asked about file counts, file lists, or system status, answer directly from the System Status section above.\n2. When referencing content from documents, mention which document and section it comes from.\n3. You can explain document structures, summarize sections, compare information across documents, and help find specific details.\n4. Be concise but thorough. Use the document's own terminology.\n5. If a user asks about something not in the documents, don't make up answers — say so clearly.\n6. When you reference a specific section, mention the document name and section title so the user can find it."
    else:
        system_content = f"You are Lector AI, a specialized assistant for the Lector document intelligence system. You have full knowledge of the system's state and can help users with any questions about their indexed documents.\n\n--- System Status ---\n{system_status_text}\n--- End System Status ---\n\nRules:\n1. You know ALL documents in the system. When asked about file counts, file lists, or system status, answer directly from the System Status section above. Do NOT say you cannot see the files — you CAN see them in the System Status.\n2. If the user asks a question about specific document content, try to answer based on what you know. If you don't have the content, say you need the document to be selected first.\n3. You can describe what each document is about based on its name and metadata.\n4. Be helpful and direct. Don't deflect questions about the system itself."
    system_msg = {"role": "system", "content": system_content}
    full_messages = [system_msg] + messages

    # Call LLM
    try:
        from pageindex.utils import llm_completion, ConfigLoader
        config = ConfigLoader().load()
        model = os.getenv("PAGEINDEX_MODEL_ID") or getattr(config, 'model', 'gpt-4o-mini')
        # Build chat history for llm_completion
        chat_history = full_messages[:-1]
        response = llm_completion(model, full_messages[-1]["content"], chat_history=chat_history)
        return jsonify({"response": response, "context_docs": doc_ids, "context_parts_count": len(context_parts)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"LLM call failed: {str(e)}"}), 500


@app.route("/api/config/apikey", methods=["POST"])
def api_set_apikey():
    """Set the PageIndex LLM API key and base URL. Uses PAGEINDEX_ prefix to avoid polluting global env."""
    data = request.get_json(force=True)
    key = data.get("key", "").strip()
    base_url = data.get("base_url", "").strip()
    if not key:
        return jsonify({"error": "API key is required"}), 400
    # Set in PageIndex's own config, NOT global OPENAI_API_KEY
    os.environ["PAGEINDEX_API_KEY"] = key
    if base_url:
        os.environ["PAGEINDEX_API_BASE"] = base_url
    # Also update the runtime config so PageIndex picks it up immediately
    from pageindex.utils import set_pageindex_llm_config
    set_pageindex_llm_config(api_key=key, api_base=base_url)
    # Write to .env file so it persists (using PAGEINDEX_ prefix)
    env_path = Path(__file__).resolve().parent.parent / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = [l for l in f.readlines() if not l.startswith(("PAGEINDEX_API_KEY=", "PAGEINDEX_API_BASE="))]
    lines.append(f"PAGEINDEX_API_KEY={key}\n")
    if base_url:
        lines.append(f"PAGEINDEX_API_BASE={base_url}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)
    # Re-initialize client so it picks up the new config
    global _client
    with _client_lock:
        _client = None
    return jsonify({"status": "saved", "key_set": True})


@app.route("/api/config/apikey", methods=["GET"])
def api_check_apikey():
    """Check if a PageIndex LLM API key is configured."""
    key = os.getenv("PAGEINDEX_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_API_KEY")
    base_url = os.getenv("PAGEINDEX_API_BASE") or os.getenv("OPENAI_API_BASE", "")
    model_id = os.getenv("PAGEINDEX_MODEL_ID", "")
    if not model_id:
        try:
            from pageindex.utils import ConfigLoader
            cfg = ConfigLoader().load()
            model_id = getattr(cfg, 'model', '')
        except Exception:
            pass
    return jsonify({"key_set": bool(key), "key_prefix": key[:8] + "..." if key else "", "base_url": base_url, "model_id": model_id})


@app.route("/api/documents", methods=["DELETE"])
def api_documents_delete_all():
    """Delete all documents from the system."""
    client = get_client()
    doc_ids = list(client.documents.keys())
    deleted_count = 0
    for doc_id in doc_ids:
        # Remove from client
        del client.documents[doc_id]
        # Remove workspace files
        doc_file = WORKSPACE / f"{doc_id}.json"
        if doc_file.exists():
            doc_file.unlink()
        deleted_count += 1
    # Clear meta
    meta_file = WORKSPACE / "_meta.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r") as f:
                meta = json.load(f)
            for doc_id in doc_ids:
                meta.pop(doc_id, None)
            with open(meta_file, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception:
            pass
    return jsonify({"deleted_count": deleted_count})


@app.route("/api/document/<doc_id>/search", methods=["POST"])
def api_search_nodes(doc_id):
    """Search nodes by title or summary — returns matching nodes with their content."""
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    client = get_client()
    structure = json.loads(client.get_document_structure(doc_id))
    if isinstance(structure, dict) and "error" in structure:
        return jsonify(structure), 404

    query_lower = query.lower()
    matched = []

    def search(nodes, depth=0):
        for node in nodes:
            title = node.get("title", "").lower()
            summary = (node.get("summary", "") or node.get("prefix_summary", "")).lower()
            if query_lower in title or query_lower in summary:
                matched.append({
                    "node_id": node.get("node_id", ""),
                    "title": node.get("title", ""),
                    "summary": node.get("summary", "") or node.get("prefix_summary", ""),
                    "depth": depth,
                    "line_num": node.get("line_num"),
                    "start_index": node.get("start_index"),
                    "end_index": node.get("end_index"),
                })
            if node.get("nodes"):
                search(node["nodes"], depth + 1)

    search(structure)
    return jsonify({"query": query, "matches": matched})


@app.route("/api/document/<doc_id>", methods=["DELETE"])
def api_document_delete(doc_id):
    client = get_client()
    if doc_id not in client.documents:
        return jsonify({"error": "Document not found"}), 404

    # Remove from client
    del client.documents[doc_id]

    # Remove workspace files
    doc_file = WORKSPACE / f"{doc_id}.json"
    if doc_file.exists():
        doc_file.unlink()

    # Update meta
    meta_file = WORKSPACE / "_meta.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r") as f:
                meta = json.load(f)
            meta.pop(doc_id, None)
            with open(meta_file, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception:
            pass

    return jsonify({"deleted": doc_id})


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(str(Path(__file__).resolve().parent / "static"), filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"PageIndex Web UI starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
