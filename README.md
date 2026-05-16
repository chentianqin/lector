# Lector — Vectorless Reasoning-based RAG

> **Lector**（拉丁语：「读者」）— 像人一样阅读文档的 AI，而不是搜索引擎。

**[English](#english)** | **[中文](#中文)**

---

<a id="english"></a>

## English

Lector is a vectorless, reasoning-based RAG system for long document understanding. Instead of chunking + embedding + vector search, Lector uses LLM reasoning to build tree-structured indexes and retrieve relevant content by understanding document semantics.

### Features

- **No vector database** — Pure reasoning-based retrieval, no embeddings needed
- **Tree-structured indexing** — Documents are organized into hierarchical trees with summaries at each node
- **Auto-search** — Ask questions without selecting documents; Lector automatically finds relevant content across all indexed files
- **Link local files** — Link PDF/Markdown files by path (no upload/copy), supports single files and folders
- **Chinese support** — Built-in Chinese text search with sliding-window token matching
- **Dark mode** — Full dark mode support
- **Beautiful UI** — EB Garamond serif typography, particle animations, breathing glow effects (花叔Design philosophy)

### Quick Start

#### 1. Install dependencies

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

#### 2. Configure LLM API

Create a `.env` file in the project root:

```bash
PAGEINDEX_API_KEY=your-api-key-here
PAGEINDEX_API_BASE=https://api.openai.com/v1  # or your preferred endpoint
PAGEINDEX_MODEL=gpt-4o  # or any model supported by litellm
```

#### 3. Run the web app

```bash
python web_app/app.py
```

Open http://localhost:7860 in your browser.

#### 4. Link documents

- Enter an absolute file path (e.g. `/path/to/document.pdf`) and click **Link**
- Or click **Choose** to pick a file from your system, then complete the absolute path
- Supports `.pdf`, `.md`, `.markdown`, `.txt` files
- Use **Link Folder** to batch-index all supported files in a directory

#### 5. Ask questions

- Type any question in the search bar — Lector will auto-search across all indexed documents
- Or click a document in the sidebar to focus your question on that document

### Architecture

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

### API Endpoints

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

### Design Philosophy

**One detail at 120%, others at 80%** — The breathing logo glow is the 120% detail; everything else supports it quietly.

Anti-AI-slop rules: no purple gradients, no emoji in UI, no Inter/Roboto, no card+border-accent pattern.

---

<a id="中文"></a>

## 中文

Lector 是一个无向量的、基于推理的 RAG 系统，用于长文档理解。不同于传统的「分块 + 嵌入 + 向量搜索」方案，Lector 使用 LLM 推理能力构建树状索引，通过理解文档语义来检索相关内容。

### 特性

- **无需向量数据库** — 纯推理式检索，不需要嵌入模型
- **树状索引** — 文档被组织为层级树结构，每个节点带有摘要
- **自动搜索** — 无需手动选择文档，提问时自动在所有已索引文档中查找相关内容
- **链接本地文件** — 通过路径链接 PDF/Markdown 文件（无需上传/复制），支持单文件和文件夹
- **中文支持** — 内置中文文本搜索，使用滑动窗口分词匹配
- **暗色模式** — 完整的暗色模式支持
- **精致界面** — EB Garamond 衬线字体、粒子动画、呼吸光效（花叔Design 哲学）

### 快速开始

#### 1. 安装依赖

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装核心依赖
pip install -r requirements.txt

# 安装 Web 应用依赖
pip install flask flask-cors playwright
playwright install chromium
```

#### 2. 配置 LLM API

在项目根目录创建 `.env` 文件：

```bash
PAGEINDEX_API_KEY=你的API密钥
PAGEINDEX_API_BASE=https://api.openai.com/v1  # 或你使用的 API 端点
PAGEINDEX_MODEL=gpt-4o  # 或 litellm 支持的任何模型
```

#### 3. 启动 Web 应用

```bash
python web_app/app.py
```

在浏览器中打开 http://localhost:7860

#### 4. 链接文档

- 输入文件的绝对路径（如 `/路径/文档.pdf`），点击 **Link**
- 或点击 **Choose** 从系统中选择文件，然后补全绝对路径
- 支持 `.pdf`、`.md`、`.markdown`、`.txt` 格式
- 使用 **Link Folder** 可批量索引目录中的所有支持文件

#### 5. 提问

- 在搜索栏输入任意问题 — Lector 会自动在所有已索引文档中搜索相关内容
- 或点击侧边栏中的文档，将问题聚焦到该文档

### 项目结构

```
web_app/
├── app.py              # Flask 服务端（API + 页面渲染）
├── templates/
│   └── index.html      # 单页应用（HTML + CSS + JS）
├── static/
│   ├── logo.svg        # Lector Logo（矢量图）
│   └── logo.png        # Lector Logo（位图备用）
├── workspace/          # 已索引文档数据（自动创建）
└── uploads/            # （空 — 上传功能已移除）
```

### API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/documents` | GET | 列出所有已索引文档 |
| `/api/index-local` | POST | 通过路径链接本地文件 |
| `/api/index-folder` | POST | 链接文件夹中的所有文件 |
| `/api/index/jobs` | GET | 获取索引任务状态 |
| `/api/document/<id>` | DELETE | 删除文档 |
| `/api/documents` | DELETE | 删除所有文档 |
| `/api/chat` | POST | 与 AI 对话（未选文档时自动搜索） |
| `/api/document/<id>/structure` | GET | 获取文档树状结构 |
| `/api/document/<id>/file` | GET | 获取原始文件 |

### 设计哲学

**一个细节做到 120%，其余做到 80%** — 呼吸光效的 Logo 是那个 120% 的细节，其他一切安静地衬托它。

反 AI 俗套规则：不用紫色渐变、不用 emoji 做 UI、不用 Inter/Roboto、不用卡片+边框高亮模式。

---

## License

Same as original PageIndex project.
