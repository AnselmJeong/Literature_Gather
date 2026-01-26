# PRD: Citation Snowball - Academic Reference Discovery Tool

## 1. Overview

### 1.1 Product Summary
**Citation Snowball**은 biomedical 연구자가 소수의 seed article로부터 시작하여 관련 문헌을 체계적으로 확장 수집할 수 있는 cli application이다. Bidirectional citation analysis와 author tracking을 통해 foundational papers와 recent developments를 균형있게 발견하고, saturation detection을 통해 효율적인 수집 종료 시점을 제시한다.

### 1.2 Problem Statement
- **Backward citation만 사용 시**: 오래된 논문들만 계속 추천됨
- **단순 citation count 기반**: age bias로 인해 recent breakthrough를 놓침
- **Forward citation만 사용 시**: foundational papers를 놓침
- **수동 문헌 검색**: 시간 소모적이고 체계적이지 않음

### 1.3 Solution
Multi-signal hybrid approach를 통한 자동화된 snowball sampling:
- Bidirectional citation analysis (forward + backward)
- Citation velocity 기반 scoring
- Author network tracking
- Saturation detection으로 수렴 시점 판별
- 최종 결과물 자동 다운로드 또는 링크 리포트 생성

---

## 2. User Personas

### Primary User
- **Role**: Biomedical 분야 연구자 (PhD student, postdoc, PI)
- **Need**: 새로운 연구 주제에 대해 빠르게 comprehensive한 문헌 세트 구축
- **Pain Point**: 수동 검색의 비효율성, 중요 논문 누락 우려
- **Technical Level**: 기본적인 cli app 사용 가능, 프로그래밍 지식 불필요

---

## 3. Core Features

### 3.1 Seed Article Import

#### 3.1.1 Functionality
로컬 폴더에 저장된 PDF 파일들을 스캔하여 seed article로 등록

#### 3.1.2 Requirements
- [ ] 사용자가 폴더 경로를 지정하면 해당 폴더 내 모든 PDF 파일 탐지
- [ ] 각 PDF에서 metadata 추출 시도:
  - DOI (우선순위 1)
  - Title + Authors (DOI 없을 경우)
  - PMID (biomedical의 경우)
- [ ] 추출된 identifier로 OpenAlex API 조회하여 Work ID 획득
- [ ] 매칭 실패 시 사용자에게 수동 입력 옵션 제공
- [ ] Seed article 목록을 UI에 표시 (title, year, authors, DOI)

#### 3.1.3 Technical Notes
- PDF metadata 추출: `pypdf` 또는 `pdfplumber` 라이브러리 사용
- DOI regex pattern: `10.\d{4,9}/[-._;()/:A-Z0-9]+`
- CrossRef API로 title 기반 DOI lookup 가능 (fallback)

### 3.2 Citation Network Expansion (Snowballing)

#### 3.2.1 Expansion Directions

**A. Forward Citations (Citing Works)**
- Seed를 인용한 newer papers 수집
- OpenAlex endpoint: `GET /works?filter=cites:{work_id}`
- 목적: Recent developments, subsequent research 발견

**B. Backward Citations (References)**
- Seed가 인용한 papers 수집
- OpenAlex endpoint: `GET /works/{work_id}` → `referenced_works` 필드
- 목적: Foundational papers, theoretical basis 발견

**C. Author Tracking**
- Seed 저자들의 최근 publications 수집
- OpenAlex endpoint: `GET /works?filter=author.id:{author_id}`
- 목적: Key researchers의 관련 연구 발견

#### 3.2.2 Scoring Algorithm

각 candidate paper에 대해 composite score 계산:

```python
def calculate_score(paper, seeds, current_year):
    # 1. Citation Velocity (normalized by age)
    age = current_year - paper.publication_year + 1
    citation_velocity = paper.cited_by_count / age
    
    # 2. Recent Citation Activity
    # OpenAlex provides counts_by_year field
    recent_citations = sum(paper.counts_by_year[-3:])  # last 3 years
    
    # 3. Foundational Score (for backward citations)
    # How many seeds cite this paper?
    seeds_citing = count_seeds_citing(paper, seeds)
    foundational_score = seeds_citing / len(seeds)
    
    # 4. Author Overlap
    seed_authors = get_all_seed_author_ids(seeds)
    paper_authors = set(paper.author_ids)
    author_overlap = len(seed_authors & paper_authors) / len(paper_authors)
    
    # 5. Recency Bonus
    recency_bonus = max(0, 1 - (current_year - paper.publication_year) / 10)
    
    # Weighted combination
    score = (
        w1 * normalize(citation_velocity) +
        w2 * normalize(recent_citations) +
        w3 * foundational_score +
        w4 * author_overlap +
        w5 * recency_bonus
    )
    
    return score

# Default weights (user-adjustable)
DEFAULT_WEIGHTS = {
    'w1_citation_velocity': 0.25,
    'w2_recent_citations': 0.20,
    'w3_foundational': 0.25,
    'w4_author_overlap': 0.15,
    'w5_recency': 0.15
}
```

#### 3.2.3 Filtering Criteria

**Inclusion filters:**
- Publication year >= user-defined cutoff (default: no limit for backward, last 10 years for forward)
- Document type: journal article, review, preprint (configurable)
- Language: English (default, configurable)

**Exclusion filters:**
- Already in current collection
- Retracted papers
- Below minimum citation threshold (configurable, default: 0)

#### 3.2.4 Iteration Process

```
ITERATION WORKFLOW:

1. Initialize:
   - working_set = seed_articles
   - all_collected = seed_articles
   - iteration_count = 0

2. For each iteration:
   a. For each paper in working_set:
      - Fetch forward citations
      - Fetch backward citations (references)
      - Fetch recent papers by authors
   
   b. Aggregate all candidates
   
   c. Apply filters and scoring
   
   d. Select top N candidates not in all_collected
   
   e. new_papers = selected candidates
   
   f. Calculate metrics:
      - growth_rate = len(new_papers) / len(all_collected)
      - novelty_rate = len(new_papers) / len(all_candidates)
   
   g. Update sets:
      - all_collected += new_papers
      - working_set = new_papers (for next iteration)
   
   h. iteration_count += 1
   
   i. Check termination conditions

3. Return all_collected with scores and metadata
```

### 3.3 Saturation Detection

#### 3.3.1 Automatic Detection

```python
def check_saturation(metrics, config):
    """
    Returns: (is_saturated: bool, reason: str, confidence: float)
    """
    
    # Condition 1: Growth rate below threshold
    if metrics.growth_rate < config.growth_threshold:  # default: 0.05 (5%)
        return True, "Growth rate below threshold", metrics.growth_rate
    
    # Condition 2: Novelty rate below threshold
    if metrics.novelty_rate < config.novelty_threshold:  # default: 0.10 (10%)
        return True, "Most candidates already collected", metrics.novelty_rate
    
    # Condition 3: Maximum iterations reached
    if metrics.iteration_count >= config.max_iterations:  # default: 5
        return True, "Maximum iterations reached", 1.0
    
    # Condition 4: Maximum papers reached
    if len(metrics.all_collected) >= config.max_papers:  # default: 500
        return True, "Maximum paper limit reached", 1.0
    
    return False, None, 0.0
```

#### 3.3.2 User Control Options

| Mode | Description |
|------|-------------|
| **Automatic** | 시스템이 saturation 감지 시 자동 종료 |
| **Semi-automatic** | Saturation 감지 시 사용자에게 계속 여부 확인 |
| **Manual** | 매 iteration 후 사용자가 계속/종료 결정 |
| **Fixed iterations** | 사용자가 지정한 횟수만큼만 실행 |

#### 3.3.3 Saturation Visualization

매 iteration 후 표시할 정보:
- Current collection size
- New papers added this iteration
- Growth rate trend (line chart)
- Estimated saturation progress (progress bar)
- Top new discoveries (preview list)

### 3.4 Results Management

#### 3.4.1 Collection View

수집된 논문 목록 표시:
- Sortable columns: Score, Year, Citations, Title, Authors
- Filtering: By year range, citation count, score threshold
- Grouping: By iteration added, by discovery method (forward/backward/author)
- Selection: Checkbox로 다운로드 대상 선택

#### 3.4.2 Paper Details

개별 논문 클릭 시 상세 정보:
- Full metadata (title, authors, abstract, journal, DOI, etc.)
- Discovery path: 어떤 seed로부터 어떤 방식으로 발견되었는지
- Score breakdown: 각 scoring component 값
- OpenAlex link, DOI link

### 3.5 PDF Download & Report Generation

#### 3.5.1 Download Process

```
DOWNLOAD WORKFLOW:

1. User selects papers to download (or "select all")

2. For each selected paper:
   a. Query Unpaywall API with DOI
      GET https://api.unpaywall.org/v2/{doi}?email={user_email}
   
   b. If open access URL found:
      - Attempt download from best_oa_location.url_for_pdf
      - Save to user-specified directory
      - Filename format: {year}_{first_author}_{short_title}.pdf
   
   c. Record result:
      - Success: file path
      - Failure: reason (no OA, download error, etc.)

3. Generate download report
```

#### 3.5.2 Unpaywall Integration

```python
def get_pdf_url(doi, email):
    """
    Query Unpaywall for open access PDF URL
    """
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        if data.get('is_oa'):
            # Prefer PDF over landing page
            best_loc = data.get('best_oa_location', {})
            return {
                'pdf_url': best_loc.get('url_for_pdf'),
                'landing_url': best_loc.get('url'),
                'version': best_loc.get('version'),  # published, accepted, submitted
                'host_type': best_loc.get('host_type')  # publisher, repository
            }
    return None
```

#### 3.5.3 HTML Report Generation

다운로드 실패한 논문들에 대한 HTML 리포트:

```html
<!-- report_template.html -->
<!DOCTYPE html>
<html>
<head>
    <title>Citation Snowball - Download Report</title>
    <style>
        /* Clean, printable styling */
        body { font-family: Arial, sans-serif; max-width: 900px; margin: auto; }
        .paper { border-bottom: 1px solid #eee; padding: 15px 0; }
        .title { font-weight: bold; font-size: 1.1em; }
        .meta { color: #666; font-size: 0.9em; }
        .links a { margin-right: 15px; }
        .success { background-color: #e8f5e9; }
        .failed { background-color: #fff3e0; }
    </style>
</head>
<body>
    <h1>Download Report</h1>
    <p>Generated: {timestamp}</p>
    <p>Total: {total} | Downloaded: {success_count} | Failed: {failed_count}</p>
    
    <h2>Papers Requiring Manual Download</h2>
    {for each failed_paper}
    <div class="paper failed">
        <div class="title">{title}</div>
        <div class="meta">{authors} ({year}) - {journal}</div>
        <div class="links">
            <a href="{doi_url}">DOI</a>
            <a href="{publisher_url}">Publisher</a>
            <a href="{google_scholar_url}">Google Scholar</a>
            <a href="{scihub_doi}">Sci-Hub</a>
        </div>
        <div class="reason">Reason: {failure_reason}</div>
    </div>
    {end for}
    
    <h2>Successfully Downloaded</h2>
    {for each success_paper}
    <div class="paper success">
        <div class="title">{title}</div>
        <div class="meta">{authors} ({year})</div>
        <div class="file">Saved: {file_path}</div>
    </div>
    {end for}
</body>
</html>
```

---

## 4. Technical Architecture

### 4.1 Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Framework** | rich package for beautiful cli experience |  |
| **Language** | Python |  |
| **Local Database** | SQLite (via better-sqlite3) | Lightweight, no server needed |
| **PDF Parsing** |  | Pure JS, no native deps |
| **HTTP Client** | axios | Reliable, interceptors for rate limiting |
| **State Management** | Zustand | Simple, lightweight |
| **UI Components** | shadcn/ui + Tailwind | Modern, customizable |

**Alternative Stack (Python-based):**

| Component | Technology |
|-----------|------------|
| **Framework** | Tauri + React (or PyQt/PySide6) |
| **Backend** | Python |
| **PDF Parsing** | pypdf, pdfplumber |
| **Database** | SQLite |
| **HTTP Client** | httpx (async) |

### 4.2 Data Models

```typescript
// TypeScript interfaces

interface Paper {
  id: string;                    // Internal UUID
  openalex_id: string;           // OpenAlex Work ID
  doi: string | null;
  pmid: string | null;
  title: string;
  authors: Author[];
  publication_year: number;
  journal: string | null;
  abstract: string | null;
  cited_by_count: number;
  counts_by_year: YearCount[];
  referenced_works: string[];    // OpenAlex IDs
  
  // Computed/derived
  score: number;
  score_components: ScoreBreakdown;
  discovery_method: 'seed' | 'forward' | 'backward' | 'author';
  discovered_from: string[];     // Paper IDs that led to this
  iteration_added: number;
  
  // Download status
  download_status: 'pending' | 'success' | 'failed' | 'skipped';
  local_path: string | null;
  oa_url: string | null;
}

interface Author {
  openalex_id: string;
  name: string;
  orcid: string | null;
}

interface YearCount {
  year: number;
  cited_by_count: number;
}

interface ScoreBreakdown {
  citation_velocity: number;
  recent_citations: number;
  foundational_score: number;
  author_overlap: number;
  recency_bonus: number;
  total: number;
}

interface IterationMetrics {
  iteration_number: number;
  timestamp: string;
  papers_before: number;
  papers_after: number;
  new_papers: number;
  growth_rate: number;
  novelty_rate: number;
  forward_found: number;
  backward_found: number;
  author_found: number;
}

interface ProjectConfig {
  // Scoring weights
  weights: {
    citation_velocity: number;
    recent_citations: number;
    foundational: number;
    author_overlap: number;
    recency: number;
  };
  
  // Filtering
  min_year: number | null;
  max_year: number | null;
  min_citations: number;
  include_preprints: boolean;
  language: string[];
  
  // Iteration control
  iteration_mode: 'automatic' | 'semi-automatic' | 'manual' | 'fixed';
  max_iterations: number;
  max_papers: number;
  growth_threshold: number;
  novelty_threshold: number;
  papers_per_iteration: number;  // Top N to add each round
  
  // Download
  download_directory: string;
  user_email: string;  // For Unpaywall polite pool
}
```

### 4.3 Database Schema

```sql
-- SQLite Schema

CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  config JSON NOT NULL
);

CREATE TABLE papers (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  openalex_id TEXT UNIQUE,
  doi TEXT,
  pmid TEXT,
  title TEXT NOT NULL,
  authors JSON NOT NULL,
  publication_year INTEGER,
  journal TEXT,
  abstract TEXT,
  cited_by_count INTEGER DEFAULT 0,
  counts_by_year JSON,
  referenced_works JSON,
  
  -- Discovery metadata
  score REAL,
  score_components JSON,
  discovery_method TEXT CHECK(discovery_method IN ('seed', 'forward', 'backward', 'author')),
  discovered_from JSON,  -- Array of paper IDs
  iteration_added INTEGER,
  
  -- Download
  download_status TEXT DEFAULT 'pending',
  local_path TEXT,
  oa_url TEXT,
  
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE iterations (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  iteration_number INTEGER NOT NULL,
  started_at DATETIME,
  completed_at DATETIME,
  metrics JSON,
  
  UNIQUE(project_id, iteration_number)
);

CREATE TABLE api_cache (
  cache_key TEXT PRIMARY KEY,
  response JSON NOT NULL,
  cached_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME
);

-- Indexes
CREATE INDEX idx_papers_project ON papers(project_id);
CREATE INDEX idx_papers_openalex ON papers(openalex_id);
CREATE INDEX idx_papers_doi ON papers(doi);
CREATE INDEX idx_papers_score ON papers(project_id, score DESC);
CREATE INDEX idx_iterations_project ON iterations(project_id);
```

### 4.4 API Integration

#### 4.4.1 OpenAlex API

```typescript
// OpenAlex API wrapper

const OPENALEX_BASE = 'https://api.openalex.org';

interface OpenAlexConfig {
  email: string;  // For polite pool
  perPage: number;
  maxRetries: number;
}

class OpenAlexClient {
  private config: OpenAlexConfig;
  private rateLimiter: RateLimiter;
  
  constructor(config: OpenAlexConfig) {
    this.config = config;
    this.rateLimiter = new RateLimiter({
      maxRequests: 10,
      perMilliseconds: 1000
    });
  }
  
  // Get single work by ID
  async getWork(workId: string): Promise<Work> {
    const url = `${OPENALEX_BASE}/works/${workId}?mailto=${this.config.email}`;
    return this.fetchWithRetry(url);
  }
  
  // Get works citing a specific work (forward citations)
  async getCitingWorks(workId: string, cursor: string = '*'): Promise<WorksResponse> {
    const url = `${OPENALEX_BASE}/works?filter=cites:${workId}&per_page=${this.config.perPage}&cursor=${cursor}&mailto=${this.config.email}`;
    return this.fetchWithRetry(url);
  }
  
  // Get works by author
  async getAuthorWorks(authorId: string, fromYear?: number): Promise<WorksResponse> {
    let filter = `author.id:${authorId}`;
    if (fromYear) {
      filter += `,from_publication_date:${fromYear}-01-01`;
    }
    const url = `${OPENALEX_BASE}/works?filter=${filter}&sort=publication_date:desc&per_page=${this.config.perPage}&mailto=${this.config.email}`;
    return this.fetchWithRetry(url);
  }
  
  // Search by DOI
  async getWorkByDoi(doi: string): Promise<Work | null> {
    const url = `${OPENALEX_BASE}/works/doi:${doi}?mailto=${this.config.email}`;
    try {
      return await this.fetchWithRetry(url);
    } catch (e) {
      return null;
    }
  }
  
  // Search by title (fuzzy)
  async searchByTitle(title: string): Promise<WorksResponse> {
    const url = `${OPENALEX_BASE}/works?search=${encodeURIComponent(title)}&per_page=5&mailto=${this.config.email}`;
    return this.fetchWithRetry(url);
  }
  
  // Batch fetch multiple works
  async getWorksBatch(workIds: string[]): Promise<Work[]> {
    // OpenAlex supports filter with OR: works?filter=openalex_id:W1|W2|W3
    // Max ~50 IDs per request
    const batches = chunk(workIds, 50);
    const results: Work[] = [];
    
    for (const batch of batches) {
      const filter = batch.map(id => id.replace('https://openalex.org/', '')).join('|');
      const url = `${OPENALEX_BASE}/works?filter=openalex_id:${filter}&per_page=50&mailto=${this.config.email}`;
      const response = await this.fetchWithRetry(url);
      results.push(...response.results);
    }
    
    return results;
  }
  
  private async fetchWithRetry(url: string, retries = 0): Promise<any> {
    await this.rateLimiter.acquire();
    
    try {
      const response = await axios.get(url);
      return response.data;
    } catch (error) {
      if (retries < this.config.maxRetries && error.response?.status === 429) {
        await sleep(Math.pow(2, retries) * 1000);
        return this.fetchWithRetry(url, retries + 1);
      }
      throw error;
    }
  }
}
```

#### 4.4.2 Unpaywall API

```typescript
// Unpaywall API wrapper

const UNPAYWALL_BASE = 'https://api.unpaywall.org/v2';

interface UnpaywallResult {
  is_oa: boolean;
  best_oa_location: {
    url: string;
    url_for_pdf: string | null;
    version: 'publishedVersion' | 'acceptedVersion' | 'submittedVersion';
    host_type: 'publisher' | 'repository';
  } | null;
}

class UnpaywallClient {
  private email: string;
  private rateLimiter: RateLimiter;
  
  constructor(email: string) {
    this.email = email;
    this.rateLimiter = new RateLimiter({
      maxRequests: 10,
      perMilliseconds: 1000
    });
  }
  
  async checkOA(doi: string): Promise<UnpaywallResult | null> {
    await this.rateLimiter.acquire();
    
    const url = `${UNPAYWALL_BASE}/${encodeURIComponent(doi)}?email=${this.email}`;
    
    try {
      const response = await axios.get(url);
      return response.data;
    } catch (error) {
      if (error.response?.status === 404) {
        return null;  // DOI not found
      }
      throw error;
    }
  }
  
  async downloadPdf(pdfUrl: string, savePath: string): Promise<boolean> {
    try {
      const response = await axios.get(pdfUrl, {
        responseType: 'arraybuffer',
        timeout: 30000,
        headers: {
          'User-Agent': 'CitationSnowball/1.0 (mailto:' + this.email + ')'
        }
      });
      
      await fs.writeFile(savePath, response.data);
      return true;
    } catch (error) {
      console.error(`Download failed for ${pdfUrl}:`, error.message);
      return false;
    }
  }
}
```

### 4.5 Application Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        APPLICATION FLOW                          │
└─────────────────────────────────────────────────────────────────┘

[1. PROJECT SETUP]
     │
     ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Select     │────▶│  Parse PDF  │────▶│  Resolve    │
│  PDF Folder │     │  Metadata   │     │  to OpenAlex│
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │ Seed Papers │
                                        │  Confirmed  │
                                        └─────────────┘
                                               │
[2. SNOWBALLING]                               │
     │◀────────────────────────────────────────┘
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  ITERATION LOOP                                                  │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐           │
│  │  Forward    │   │  Backward   │   │   Author    │           │
│  │  Citations  │   │  Citations  │   │  Tracking   │           │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘           │
│         │                 │                 │                   │
│         └────────────┬────┴────────────────┘                   │
│                      ▼                                          │
│              ┌─────────────┐                                    │
│              │  Aggregate  │                                    │
│              │  Candidates │                                    │
│              └──────┬──────┘                                    │
│                     ▼                                           │
│              ┌─────────────┐                                    │
│              │   Filter &  │                                    │
│              │    Score    │                                    │
│              └──────┬──────┘                                    │
│                     ▼                                           │
│              ┌─────────────┐                                    │
│              │  Select Top │                                    │
│              │  N Papers   │                                    │
│              └──────┬──────┘                                    │
│                     ▼                                           │
│              ┌─────────────┐     ┌─────────────┐               │
│              │   Update    │────▶│  Check      │               │
│              │ Collection  │     │ Saturation  │               │
│              └─────────────┘     └──────┬──────┘               │
│                                         │                       │
│                     ┌───────────────────┼───────────────────┐  │
│                     ▼                   ▼                   ▼  │
│              [Not Saturated]    [User Decision]     [Saturated]│
│                     │                   │                   │  │
│                     └───────┬───────────┘                   │  │
│                             │                               │  │
│                    Continue Loop ◀──────────────────────────┘  │
│                             │           (if user continues)    │
└─────────────────────────────┼───────────────────────────────────┘
                              │
                              ▼
[3. RESULTS]           ┌─────────────┐
                       │  Final      │
                       │ Collection  │
                       └──────┬──────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
       ┌───────────┐   ┌───────────┐   ┌───────────┐
       │  Browse   │   │  Download │   │  Export   │
       │  & Filter │   │   PDFs    │   │  Report   │
       └───────────┘   └─────┬─────┘   └───────────┘
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
             [OA Available]    [Not Available]
                    │                 │
                    ▼                 ▼
             ┌───────────┐     ┌───────────┐
             │ Auto      │     │ Generate  │
             │ Download  │     │ HTML Links│
             └───────────┘     └───────────┘
```

---

## 5. User Interface Design

### 5.1 Screen Flow

```
┌─────────────────────────────────────────────────────────────┐
│  Main Window                                                 │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │ Projects│  │  Seeds  │  │Snowball │  │ Results │        │
│  │         │  │         │  │         │  │         │        │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘        │
│       │            │            │            │              │
├───────┴────────────┴────────────┴────────────┴──────────────┤
│                                                              │
│  [CONTENT AREA - Changes based on selected tab]             │
│                                                              │
│                                                              │
│                                                              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Key Screens

#### 5.2.1 Projects Screen
- List of saved projects
- Create new project button
- Project cards showing: name, paper count, last updated, status

#### 5.2.2 Seeds Screen
- Folder selector button
- List of detected PDFs with metadata extraction status
- Manual DOI/title entry for failed extractions
- "Confirm Seeds" button to proceed

#### 5.2.3 Snowball Screen
- Configuration panel (weights, filters, iteration mode)
- "Start Snowballing" button
- Real-time progress display:
  - Current iteration number
  - Papers found this iteration
  - Growth rate chart
  - Saturation indicator
- Pause/Resume/Stop controls
- Iteration log

#### 5.2.4 Results Screen
- Sortable/filterable paper table
- Paper detail sidebar
- Selection checkboxes
- Download controls:
  - "Download Selected" button
  - "Download All" button
  - Progress indicator
- Export options:
  - HTML report
  - CSV export
  - BibTeX export

### 5.3 UI Components Specification

#### Paper Card Component
```
┌────────────────────────────────────────────────────────────┐
│ ☐  [Score: 0.85]                              [2023]       │
│                                                            │
│ Paper Title Goes Here and Can Be Quite Long               │
│                                                            │
│ Author A, Author B, Author C                              │
│ Journal of Something • Cited by: 142                      │
│                                                            │
│ [Forward ↗]  [Backward ↙]  [Author 👤]     [DOI] [PDF]    │
│ ─────────────────────────────────────────────             │
│ Discovered via: Seed Paper Title... (forward citation)     │
└────────────────────────────────────────────────────────────┘
```

#### Saturation Indicator Component
```
┌────────────────────────────────────────────────────────────┐
│  SATURATION PROGRESS                                       │
│                                                            │
│  ████████████████░░░░░░░░░░░░░░  ~60% to saturation       │
│                                                            │
│  Iteration: 3/5  │  Growth: 12%  │  Papers: 156           │
│                                                            │
│  [Continue] [Stop Here]                                    │
└────────────────────────────────────────────────────────────┘
```

---

## 6. Configuration Options

### 6.1 Default Settings

```json
{
  "scoring": {
    "weights": {
      "citation_velocity": 0.25,
      "recent_citations": 0.20,
      "foundational": 0.25,
      "author_overlap": 0.15,
      "recency": 0.15
    }
  },
  "filtering": {
    "min_year": null,
    "max_year": null,
    "min_citations": 0,
    "include_preprints": true,
    "languages": ["en"],
    "document_types": ["journal-article", "review", "posted-content"]
  },
  "iteration": {
    "mode": "semi-automatic",
    "max_iterations": 5,
    "max_papers": 500,
    "papers_per_iteration": 50,
    "growth_threshold": 0.05,
    "novelty_threshold": 0.10
  },
  "download": {
    "auto_download": false,
    "directory": "~/Downloads/CitationSnowball",
    "filename_template": "{year}_{first_author}_{title_short}",
    "generate_report": true
  },
  "api": {
    "user_email": "",
    "cache_duration_days": 7,
    "request_delay_ms": 100
  }
}
```

### 6.2 User-Configurable Parameters

| Parameter | Description | Default | Range |
|-----------|-------------|---------|-------|
| Citation velocity weight | Importance of citations per year | 0.25 | 0-1 |
| Recent citations weight | Importance of last 3 years citations | 0.20 | 0-1 |
| Foundational weight | Importance of being cited by multiple seeds | 0.25 | 0-1 |
| Author overlap weight | Importance of shared authors with seeds | 0.15 | 0-1 |
| Recency weight | Bonus for newer papers | 0.15 | 0-1 |
| Min publication year | Earliest year to include | None | 1900-current |
| Min citations | Minimum citation count | 0 | 0-1000 |
| Max iterations | Maximum snowball rounds | 5 | 1-20 |
| Max papers | Maximum collection size | 500 | 50-2000 |
| Growth threshold | Stop when growth below this | 5% | 1-20% |

---

## 7. Error Handling

### 7.1 Error Categories

| Category | Examples | Handling |
|----------|----------|----------|
| **Network** | API timeout, no internet | Retry with backoff, queue for later |
| **API** | Rate limit, invalid response | Exponential backoff, cache |
| **PDF Parse** | Corrupt file, no metadata | Mark for manual entry |
| **Resolution** | DOI not found, ambiguous match | Prompt user for clarification |
| **Download** | 403 forbidden, file not PDF | Add to failed report |

### 7.2 Resilience Strategies

```typescript
// Retry configuration
const RETRY_CONFIG = {
  maxRetries: 3,
  initialDelay: 1000,
  maxDelay: 30000,
  backoffMultiplier: 2
};

// Circuit breaker for API
const CIRCUIT_BREAKER = {
  failureThreshold: 5,
  resetTimeout: 60000
};
```

---

## 8. Performance Considerations

### 8.1 Caching Strategy

- **API responses**: Cache OpenAlex responses for 7 days
- **PDF metadata**: Cache extracted metadata permanently
- **Scoring**: Recalculate only when weights change

### 8.2 Batch Operations

- Batch OpenAlex requests (up to 50 IDs per request)
- Parallel Unpaywall checks (with rate limiting)
- Background processing for large operations

### 8.3 Expected Performance

| Operation | Expected Duration |
|-----------|-------------------|
| PDF folder scan (100 files) | < 30 seconds |
| Single iteration (50 papers working set) | 1-3 minutes |
| Full snowball (5 iterations) | 5-15 minutes |
| Download 100 PDFs | 5-20 minutes |

---

## 9. Future Enhancements (Out of Scope for v1)

- [ ] Integration with reference managers (Zotero, Mendeley)
- [ ] Semantic similarity analysis (beyond citation network)
- [ ] Collaborative projects (shared collections)
- [ ] Cloud sync for projects
- [ ] Browser extension for ad-hoc paper addition
- [ ] Citation graph visualization
- [ ] Abstract-based relevance filtering using LLM
- [ ] Automated keyword extraction from seed PDFs

---

## 10. Success Metrics

### 10.1 Functional Criteria
- [ ] Successfully imports PDFs and resolves to OpenAlex IDs (>90% success rate)
- [ ] Executes snowballing iterations without errors
- [ ] Correctly identifies saturation point
- [ ] Downloads available OA PDFs
- [ ] Generates accurate HTML report for unavailable papers

### 10.2 Quality Criteria
- [ ] Discovered papers are relevant to seed topic (user validation)
- [ ] Balance of foundational and recent papers achieved
- [ ] No duplicate papers in collection
- [ ] Scoring correlates with user-perceived importance

---

## Appendix A: OpenAlex API Reference

### Relevant Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /works/{id}` | Single work details |
| `GET /works?filter=cites:{id}` | Forward citations |
| `GET /works?filter=doi:{doi}` | Lookup by DOI |
| `GET /works?search={title}` | Title search |
| `GET /works?filter=author.id:{id}` | Author's works |

### Useful Fields

```json
{
  "id": "https://openalex.org/W2741809807",
  "doi": "https://doi.org/10.1038/s41586-019-1724-z",
  "title": "...",
  "publication_year": 2019,
  "cited_by_count": 1234,
  "counts_by_year": [
    {"year": 2024, "cited_by_count": 200},
    {"year": 2023, "cited_by_count": 350}
  ],
  "authorships": [...],
  "referenced_works": ["https://openalex.org/W...", ...],
  "related_works": ["https://openalex.org/W...", ...]
}
```

---

## Appendix B: Unpaywall API Reference

### Endpoint
```
GET https://api.unpaywall.org/v2/{doi}?email={email}
```

### Response Structure
```json
{
  "doi": "10.1038/nature12373",
  "is_oa": true,
  "best_oa_location": {
    "url": "https://...",
    "url_for_pdf": "https://...",
    "version": "publishedVersion",
    "host_type": "publisher"
  },
  "oa_locations": [...]
}
```

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **Forward citation** | Paper that cites the target paper (newer) |
| **Backward citation** | Paper cited by the target paper (older) |
| **Citation velocity** | Citations per year since publication |
| **Bibliographic coupling** | Papers sharing common references |
| **Co-citation** | Papers cited together by other works |
| **Saturation** | Point where snowballing yields diminishing returns |
| **Seed article** | Initial paper(s) starting the snowball process |
| **Working set** | Papers being expanded in current iteration |
