# AI Tutor Backend

An AI-native that ingests course materials (PDF/PPTX) and powers a **RAG Tutor** grounded in those lectures.

## Demo

https://github.com/user-attachments/assets/8f85a144-37ae-4001-b37a-5600dbfaff8d

## Installation

### 1) Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Configure environment

```bash
cp .env.example .env
```

Set `AI_TUTOR_GEMINI_API_KEY` in `.env`.

### 3) Run

```bash
python -m ai_tutor.cli serve
```

Open `http://localhost:8000/`.

## Quick start (CLI)

```bash
python -m ai_tutor.cli create-course --title "3D Computer Vision"
python -m ai_tutor.cli ingest --course-id <ID> --file lecture01.pdf --lecture-number 1 --lecture-title "Intro"
python -m ai_tutor.cli ask --course-id <ID> "Explain the pinhole camera model."
```

## What's included

- **Tutor**: grounded answers with citations like `[Lecture X, Slide Y]`
- **Ingestion**: PDF/PPTX → per-slide/page chunks (with optional vision descriptions)
- **Retrieval**: hybrid search (BM25 + vectors)
- **Extras**: quizzes, study guides, audio overview

## Notes

- `pdf2image` may require **Poppler** installed on your system.
- The web UI renders LaTeX using **KaTeX**.

---

## Architecture Overview

```
                        ┌─────────────────────────────────────────────┐
                        │              AI Tutor Backend               │
                        └─────────────────────────────────────────────┘

    ┌──────────────┐     ┌──────────────────────────────────────────┐
    │  PDF / PPTX  │────▸│           INGESTION PIPELINE             │
    │   Upload     │     │                                          │
    └──────────────┘     │  1. Structural Extraction (Marker/pptx)  │
                         │  2. Page Image Rendering (pdf2image)     │
                         │  3. Vision Pass (Gemini) for visual      │
                         │     content: diagrams, equations, charts │
                         │  4. Semantic Chunking (slide-level)      │
                         │  5. Hierarchical Summarization           │
                         │     - Lecture summaries                  │
                         │     - Cross-lecture topic summaries      │
                         │  6. Embedding + Indexing                 │
                         └──────────┬───────────────────────────────┘
                                    │
                    ┌───────────────────────────────┐
                    ▼                               ▼
             ┌──────────┐                   ┌──────────────┐
             │ ChromaDB │                   │   SQLite     │
             │ (vectors)│                   │ (chunks +    │
             └──────────┘                   │  metadata +  │
                    │                       │  quizzes)    │
                    └───────────────┼───────└──────────────┘
                                    ▼

                         ┌────────────────────┐
    ┌──────────┐         │  RETRIEVAL LAYER   │
    │ Student  │────────▸│                    │
    │ Prompt   │         │  Hybrid Search     │
    └──────────┘         │  (BM25 + Vector)   │
                         │  BM25 Scoring      │
                         │  RRF Fusion        │
                         │  Cross-Encoder     │
                         │  Reranking         │
                         └────────┬───────────┘
                                  ▼
                         ┌────────────────────┐
                         │  GENERATION LAYER  │
                         │                    │
                         │  Gemini Flash      │
                         │  + Grounded Prompt │
                         │  + Source Citations │
                         └────────┬───────────┘
                ┌─────────────────┼──────────────────┐
                ▼                 ▼                  ▼
       ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
       │ Tutor Answer   │  │ Quiz JSON      │  │ Audio Overview │
       │ + Sources      │  │ (saved in DB)  │  │ (TTS file)     │
       └────────────────┘  └────────────────┘  └────────────────┘
```

---

## How It Works

### Ingestion Pipeline

When a professor uploads a lecture file, the system processes it through six stages:

**1. Structural Extraction**
- **PDFs** are processed with [Marker](https://github.com/VikParuchuri/marker), which produces clean Markdown with LaTeX equations preserved, table structures maintained, and image locations marked.
- **PowerPoint files** are processed with `python-pptx`, extracting text from all shapes, tables, and embedded images.

**2. Page Image Rendering**
Every page/slide is rendered to a PNG image using `pdf2image` (backed by Poppler). These images serve as input for the visual understanding pass.

**3. Visual Understanding Pass (Gemini Vision)**
This is the most important step for handling non-textual content. For each page, we compute a text density score (character count). Pages with low text density — common in engineering/math courses where slides contain only diagrams or equations — are sent to **Gemini 2.0 Flash's vision capability** with this prompt:

> "You are an expert teaching assistant. Describe the academic content of this lecture slide in detail. Include any text visible, descriptions of diagrams, charts, figures, and their meaning. Any mathematical equations or formulas, written in LaTeX notation. What a student should understand from this slide."

Pages with high text density also get a vision pass if they contain detected images. The result is a rich textual description that captures the *meaning* of visual content — turning a diagram of a rotation matrix into a searchable, retrievable paragraph about 3D transformations.

**4. Semantic Chunking**
The primary chunk unit is **one slide/page** — the natural unit of meaning in lecture materials. Each chunk carries metadata:
- `course_id`, `lecture_number`, `lecture_title`, `page_number`
- `has_equations`, `has_images`
- `chunk_type`: "slide", "lecture_summary", or "topic_summary"

The chunk's `combined_text` merges extracted text with the vision description. Pages exceeding 1000 tokens are split into overlapping sub-chunks.

**5. Hierarchical Summarization**
After chunking, the system generates summaries at two levels:
- **Lecture-level summaries**: All slide chunks from one lecture are sent to Gemini to produce a 400-600 word summary covering main topics, key formulas, and how concepts build on each other.
- **Cross-lecture topic summaries**: After any new lecture is ingested, all lecture summaries are analyzed together to produce a synthesis of how topics connect across the entire course.

These summaries are embedded and stored as retrievable chunks, enabling the system to answer cross-lecture questions without needing to retrieve dozens of individual slides.

**6. Embedding & Indexing**
All chunks (slides + summaries) are:
- Embedded with `all-MiniLM-L6-v2` (384-dimensional, runs locally) and stored in ChromaDB
- Scored with BM25 (tokenized text) for keyword matching (a ranking function over text, not a database)

When a professor uploads their 8th PDF, only that document is processed through stages 1-4. The system then incrementally updates the lecture summary for that lecture and regenerates topic summaries across all lectures. Existing chunks from earlier uploads are untouched.

---

### Retrieval Layer

When a question comes in, the retrieval pipeline runs:

1. **Query Analysis**: Parse the query for metadata hints (e.g., "Week 3" → filter to `lecture_number=3`)
2. **BM25 Search**: Keyword-based search over all chunk texts → top 20 candidates. Catches exact term matches critical for technical vocabulary (e.g., "epipolar geometry", "backpropagation").
3. **Vector Search**: Semantic similarity search in ChromaDB → top 20 candidates. Catches meaning-based matches where the student uses different words than the slides.
4. **Reciprocal Rank Fusion (RRF)**: Merges the two ranked lists into a single ranking. RRF is simple, parameter-light, and empirically strong — it works by `score(d) = Σ 1/(k + rank(d))` across both lists.
5. **Cross-Lecture Injection**: If the query contains indicators like "relate", "compare", "across lectures", "everything" — the system injects lecture summaries and topic summaries into the candidate pool.
6. **Cross-Encoder Reranking**: The top 20 fused candidates are re-scored by a cross-encoder (`ms-marco-MiniLM-L-6-v2`) which reads each (query, chunk) pair jointly for more accurate relevance judgment. The top 8 are passed to the generation layer.

---

### AI Tutor (Feature A)

The tutor receives the reranked chunks and constructs a grounded prompt:

```
System: You are an AI tutor for the course "{course_title}".
- Answer ONLY using the provided lecture materials.
- If the answer spans multiple lectures, explicitly reference which lectures.
- Cite your sources as [Lecture X, Slide Y].
- If unsure, say so honestly. Do NOT make up information.

=== COURSE MATERIALS ===
[Source 1: Lecture 3, Slide 14 — rotation_matrices.pdf]
Content of the chunk...

[Source 2: Lecture 7, Slide 8 — camera_models.pdf]
Content of the chunk...
=== END MATERIALS ===

Student Question: How do rotation matrices relate to camera calibration?
```

The response includes:
- The answer text with inline source citations
- A structured `sources` list: `[{lecture_number, page_number, source_file}]`
- The number of chunks retrieved

**Cross-lecture questions** work because: (a) the hierarchical summaries provide high-level connections, (b) the retrieval layer injects these summaries when it detects cross-lecture intent, and (c) the prompt explicitly instructs the model to reference multiple lectures.

---

## Quiz Generator

The Quiz Generator shares the **exact same ingestion pipeline and retrieval layer** as the AI Tutor. The only difference is in how retrieval is triggered and how the LLM prompt is structured.

### Input

```json
{
    "num_questions": 10,
    "lectures_to_cover": [3, 5, 7],
    "topics": ["camera calibration", "epipolar geometry"],
    "question_types": ["mcq", "short_answer"]
}
```

If `lectures_to_cover` is empty, the system covers all lectures proportionally.

### How It Uses the Same Foundation

**Retrieval**: Instead of a student's free-form question, the system constructs programmatic queries:
- `"Key concepts and important definitions from Lecture 3 about camera calibration"`
- `"Main formulas and theorems from Lecture 5 about epipolar geometry"`

For each lecture/topic combination, 8-10 chunks are retrieved. For "cover everything" mode, the system retrieves lecture-level summaries for all lectures and samples proportionally.

**Generation Prompt (for MCQ)**:

```
You are a professor creating a quiz for the course "{course_title}".

Generate {n} multiple-choice questions based ONLY on the provided materials.

For each question:
1. Write a clear question stem
2. Provide 4 options (A-D) with exactly one correct answer
3. The correct answer must be directly supported by the materials
4. Distractors should be plausible but clearly wrong based on the material
5. Include a brief explanation referencing the source [Lecture X, Slide Y]

Materials:
{retrieved_chunks}
```

**Validation**: After generation, each question is checked:
- Does the correct answer appear in or follow from the retrieved source chunks?
- Are the distractors plausible (not absurd)?
- Questions that fail validation are regenerated or discarded.

**Coverage Guarantee**: For "cover everything" mode, the system ensures at least one question per lecture by cycling through lecture summaries. This prevents the quiz from clustering on one topic.

### Why This Works from the Same Foundation

Both features are just different "views" into the same knowledge base:
- The **AI Tutor** takes a student question → retrieves relevant chunks → generates an answer
- The **Quiz Generator** takes a professor's spec → retrieves relevant chunks → generates questions

The ingestion pipeline, chunk storage, embedding, BM25 index, hierarchical summaries, and hybrid retrieval are identical. Only the final prompt to the LLM changes.

---

## Handling Visual & Mathematical Content

### The Challenge

Academic slides — especially in STEM courses — are not just text. A 3D Computer Vision lecture might have slides that contain:
- A diagram of epipolar geometry with no text explanation
- A slide with only a 4x4 transformation matrix
- A chart comparing different feature detectors
- Code output screenshots

Traditional text-only RAG systems lose 30-50% of the information on these slides.

### Our Approach

**Dual extraction**: Every page gets both text extraction (Marker) and image rendering (pdf2image). Marker handles LaTeX equations well, converting them to `$...$` notation. But it cannot interpret diagrams.

**Vision-based understanding**: Pages with low text density OR detected images get sent to Gemini Vision. This turns a diagram of a pinhole camera model into a paragraph like:

> "This slide shows a pinhole camera model diagram. A 3D point P in world coordinates is projected through the camera center (optical center) onto the image plane, creating a 2D point p. The relationship is governed by the projection equation p = K[R|t]P, where K is the intrinsic matrix, R is the rotation matrix, and t is the translation vector..."

This description is merged with any extracted text to form the chunk's `combined_text`, which is then embedded and indexed. Now when a student asks "How does the pinhole camera model work?", the system can retrieve this chunk even though the original slide had no searchable text.

### Equations

Marker preserves LaTeX notation from PDFs. For slides where equations are rendered as images (common in PowerPoint), Gemini Vision transcribes them to LaTeX. The system stores equations in LaTeX form, which:
- Is searchable (BM25 can match `\nabla`, `\frac{d}{dx}`)
- Embeds meaningfully (the embedding model has seen LaTeX in training data)
- Renders correctly in the tutor's response


---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/courses/` | Create a new course |
| `GET` | `/courses/` | List all courses |
| `GET` | `/courses/{id}` | Get course details |
| `GET` | `/courses/{id}/stats` | Course statistics |
| `POST` | `/courses/{id}/materials/` | Upload a file (triggers ingestion) |
| `GET` | `/courses/{id}/materials/` | List materials |
| `GET` | `/courses/{id}/materials/{id}/status` | Ingestion status |
| `POST` | `/courses/{id}/tutor/ask` | Ask the AI tutor |
