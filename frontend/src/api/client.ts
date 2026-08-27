// 后端 API 调用封装 —— 与 FastAPI 后端的 REST 契约一一对应。

// ---------- 类型定义 ----------
export type NoteStatus = 'pending' | 'processing' | 'done' | 'failed'

export interface Note {
  id: number
  file_path: string
  title: string | null
  ocr_text: string | null
  summary: string | null
  keywords: string[] | null
  source_device: string | null
  source_app: string | null
  status: NoteStatus
  embedding: number[] | null
  thumbnail_path: string | null
  file_hash: string | null
  ocr_model: string | null
  manually_edited?: boolean
  created_at: string
  processed_at: string | null
}

export interface NotesListResponse {
  items: Note[]
  total: number
  limit: number
  offset: number
}

export interface GraphNode {
  id: number
  title: string
  source_device: string | null
  source_app: string | null
  thumbnail_path: string | null
  status: NoteStatus
  created_at: string
}

export interface GraphEdge {
  source: number
  target: number
  weight: number
  link_type: string | null
  reason: string | null
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface Citation {
  note_id: number
  title: string
  snippet: string
  score: number
}

export interface QaAskResponse {
  answer: string
  citations: Citation[]
  qa_id: number
  memories_used?: MemoryUsed[]
  tools_used?: ToolCall[]
  cards_used?: KnowledgeCard[]
  card_draft?: CardDraft | null
}

export interface CardDraft {
  title: string
  core_summary: string
  key_conclusion: string
  application_scenario: string
  agent_question: string
  source_note_ids: number[]
  qa_id: number | null
  session_id: string | null
}

export interface KnowledgeCard {
  id: number
  qa_id: number | null
  session_id: string | null
  title: string
  core_summary: string
  key_conclusion: string
  application_scenario: string
  agent_question: string
  user_answer: string
  ai_supplement: string
  source_note_ids: number[]
  status: string
  created_at: string
  updated_at: string
  use_count: number
  last_used_at: string | null
  verdict?: string | null
  review_count?: number
  last_reviewed_at?: string | null
  next_review_at?: string | null
  mastery_level?: string | null
  links?: CardLink[]
}

export interface CardLink {
  source_type: 'card' | 'note'
  source_id: number
  target_type: 'card' | 'note'
  target_id: number
  weight: number
  reason: string | null
}

export interface FinalizeCardResponse {
  card_id: number
  verdict: 'correct' | 'needs_supplement' | 'skipped'
  ai_supplement: string
  linked_notes: number
}

export interface ToolCall {
  name: string
  arguments: Record<string, unknown>
  result_preview: string
}

export interface QaSession {
  session_id: string
  title: string | null
  created_at: string
  updated_at: string
  msg_count: number
  last_question?: string | null
  last_answer?: string | null
}

export interface MemoryUsed {
  score: number
  memory: UserMemory
}

export interface UserMemory {
  id: number
  type: 'preference' | 'fact' | 'correction' | 'term' | 'ocr_correction' | 'ocr_addition'
  content: string
  source: string | null
  weight: number
  related_qa_id: number | null
  created_at: string
  last_used_at: string | null
  use_count: number
}

export interface QaHistoryItem {
  id: number
  question: string
  answer: string
  citations: Citation[]
  created_at: string
}

export interface Stats {
  notes_total: number
  notes_done: number
  notes_pending: number
  notes_failed: number
  links_total: number
  qa_total: number
  feedback_total: number
  queue_size: number
  growth: GrowthStats
}

export interface GrowthStats {
  classified_notes: number
  practice_notes: number
  reference_notes: number
  knowledge_density: number
  call_frequency: number
  validation_depth: number
  cards_total: number
  cards_validated: number
  cards_used: number
  due_cards: number
  latest_review_date: string | null
}

export interface GrowthReview {
  id: number
  review_date: string
  content: {
    headline?: string
    kept?: { title: string; why: string }[]
    mistakes?: { title: string; correction: string; next_action: string }[]
    adjustments?: string[]
    review_questions?: string[]
    skill_updates?: { skill: string; level: string; reason: string }[]
    system_metrics?: Record<string, unknown>
    due_card_ids?: number[]
  }
  model: string | null
  note_ids: string | null
  created_at: string
  updated_at: string
}

export interface KnowledgeCardReview extends KnowledgeCard {
  verdict: string | null
  review_count: number
  last_reviewed_at: string | null
  next_review_at: string | null
  mastery_level: string | null
}

export interface Health {
  status: string
  openai_configured: boolean
  llm_model: string
  embedding_model: string
}

// ---------- 设置与系统 ----------
export interface WatchFolder {
  id: string
  path: string
  device: string
  app: string
  enabled: boolean
  recursive: boolean
  auto: boolean
}

export interface ModelConfig {
  llm_model: string
  qa_model: string
  embedding_model: string
  embedding_dim: number
  openai_base_url: string
  openai_api_key_set: boolean
}

export interface OcrModel {
  id: string
  name: string
  model: string
  enabled: boolean
  is_primary: boolean
}

export interface RelayConfig {
  location: 'local' | 'cloud'
  host: string
  port: number
  note: string
}

export interface LinkParams {
  alpha: number
  beta: number
  gamma: number
  threshold: number
}

export interface AllSettings {
  watch_folders: WatchFolder[]
  model: ModelConfig
  ocr_models: OcrModel[]
  relay: RelayConfig
  link_params: LinkParams
  ui: { theme: string; device_override: string }
}

export interface DiscoveredFolder {
  path: string
  name: string
  file_count: number
  sample_files: string[]
  suggested_device: string
  suggested_app: string
}

export interface ScanResult {
  root: string
  discovered: DiscoveredFolder[]
  total: number
}

export interface PathTestResult {
  path: string
  exists: boolean
  is_dir: boolean
  readable: boolean
  file_count: number
  note_count: number
}

export interface SystemInfo {
  platform: {
    system: string
    release: string
    machine: string
    processor: string
    python: string
  }
  paths: {
    synced_notes_root: string
    thumbnail_dir: string
    db_path: string
    cloud_root: string
  }
  storage: {
    db_bytes: number
    notes_bytes: number
    thumbnail_bytes: number
    cloud_bytes: number
    disk_total_bytes: number
    disk_used_bytes: number
    disk_free_bytes: number
  }
  relay: RelayConfig
  watch_folders_count: number
}

export interface AccessInfo {
  host: string | null
  hostname: string
  mdns_host: string
  ports: {
    frontend: number
    api: number
    cloud_web: number
    syncthing: number
  }
  urls: {
    brain_web: string
    cloud_web_client: string
    api_health: string
    syncthing_web: string
  }
  cloud: {
    root: string
    upload_subdir: string
  }
}

export interface SourceStat {
  device: string | null
  app: string | null
  count: number
}

export interface ActivityLog {
  id: number
  event_type: 'model' | 'upload' | 'backup' | 'error' | string
  message: string
  model?: string | null
  device?: string | null
  app?: string | null
  note_id?: number | null
  file_name?: string | null
  created_at: string
}

export interface ActivityLogsResponse {
  items: ActivityLog[]
  total: number
  limit: number
  offset: number
}

// ---------- 请求基础 ----------
async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`GET ${url} 失败：${res.status}`)
  }
  return res.json() as Promise<T>
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(`POST ${url} 失败：${res.status}`)
  }
  return res.json() as Promise<T>
}

async function deleteJSON<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: 'DELETE' })
  if (!res.ok) {
    throw new Error(`DELETE ${url} 失败：${res.status}`)
  }
  return res.json() as Promise<T>
}

async function patchJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(`PATCH ${url} 失败：${res.status}`)
  }
  return res.json() as Promise<T>
}

async function putJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(`PUT ${url} 失败：${res.status}`)
  }
  return res.json() as Promise<T>
}

// ---------- API 函数 ----------
export interface NotesQuery {
  device?: string
  app?: string
  q?: string
  status?: NoteStatus | ''
  limit?: number
  offset?: number
}

export const api = {
  // 笔记
  listNotes: (params: NotesQuery = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== '' && v !== null) qs.set(k, String(v))
    })
    return getJSON<NotesListResponse>(`/api/notes?${qs.toString()}`)
  },
  getNote: (id: number) => getJSON<Note>(`/api/notes/${id}`),
  noteFileUrl: (id: number) => `/api/notes/${id}/file`,
  noteThumbnailUrl: (id: number) => `/api/notes/${id}/thumbnail`,
  reprocessNote: (id: number) =>
    postJSON<{ note_id: number; status: string; queued: boolean }>(
      `/api/notes/reprocess/${id}`,
      {},
    ),

  // 人工编辑笔记（OCR 修正）
  editNote: (id: number, body: {
    title?: string
    ocr_text?: string
    summary?: string
    keywords?: string[]
    recompute_embedding?: boolean
  }) => patchJSON<{ note_id: number; updated: boolean; manually_edited: boolean; note: Note }>(
    `/api/notes/${id}`,
    body,
  ),
  clearManualEdit: (id: number) =>
    postJSON<{ note_id: number; manually_edited: boolean }>(`/api/notes/${id}/clear-manual-edit`, {}),

  // 删除笔记（数据库记录 + links + 缩略图，可选删物理文件）
  deleteNote: (id: number, hard: boolean = false) =>
    deleteJSON<{ deleted: boolean; note_id: number; hard: boolean }>(
      `/api/notes/${id}?hard=${hard ? 'true' : 'false'}`,
    ),

  // 图谱
  getGraph: (params: { device?: string; app?: string; q?: string; status?: string } = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v) qs.set(k, v)
    })
    return getJSON<GraphData>(`/api/graph?${qs.toString()}`)
  },
  getNeighbors: (id: number) => getJSON<GraphData>(`/api/graph/neighbors/${id}`),
  // 含知识卡片的混合图谱（节点类型：note | card）
  getGraphWithCards: (centerCardId?: number) =>
    getJSON<{
      nodes: Array<{
        id: string
        type: 'note' | 'card'
        ref_id: number
        title: string
        subtitle?: string | null
        status?: string | null
        thumbnail_path?: string | null
        created_at?: string
      }>
      edges: Array<{
        source: string
        target: string
        source_type: 'note' | 'card'
        target_type: 'note' | 'card'
        weight: number
        reason: string | null
      }>
    }>(`/api/graph/cards${centerCardId ? `?center_card_id=${centerCardId}` : ''}`),

  // 问答
  ask: (question: string, sessionId?: string) =>
    postJSON<QaAskResponse>('/api/qa/ask', { question, session_id: sessionId }),
  getQaHistory: (limit = 50, offset = 0, sessionId?: string) => {
    const qs = new URLSearchParams()
    qs.set('limit', String(limit))
    qs.set('offset', String(offset))
    if (sessionId) qs.set('session_id', sessionId)
    return getJSON<{ items: QaHistoryItem[] }>(`/api/qa/history?${qs.toString()}`)
  },

  // 会话管理
  listSessions: (limit = 50) => {
    const qs = new URLSearchParams()
    qs.set('limit', String(limit))
    return getJSON<{ items: QaSession[]; total: number }>(`/api/qa/sessions?${qs.toString()}`)
  },
  renameSession: (sessionId: string, title: string) =>
    patchJSON<{ session_id: string; title: string }>(`/api/qa/sessions/${encodeURIComponent(sessionId)}`, { title }),
  deleteSession: (sessionId: string) =>
    deleteJSON<{ deleted: boolean; session_id: string }>(`/api/qa/sessions/${encodeURIComponent(sessionId)}`),

  // 长期记忆
  listMemories: (type?: string) => {
    const qs = new URLSearchParams()
    if (type) qs.set('type', type)
    return getJSON<{ items: UserMemory[]; total: number }>(`/api/qa/memories?${qs.toString()}`)
  },
  addMemory: (body: { type: UserMemory['type']; content: string; weight?: number }) =>
    postJSON<{ memory_id: number; memory: UserMemory }>('/api/qa/memories', body),
  updateMemory: (id: number, body: { content?: string; weight?: number; type?: UserMemory['type'] }) =>
    patchJSON<{ memory_id: number; memory: UserMemory }>(`/api/qa/memories/${id}`, body),
  deleteMemory: (id: number) => deleteJSON<{ deleted: boolean; memory_id: number }>(`/api/qa/memories/${id}`),

  // 反馈
  submitFeedback: (qa_id: number, rating: 'up' | 'down', correction?: string) =>
    postJSON<{ feedback_id: number; qa_id: number; rating: string }>(
      '/api/feedback',
      { qa_id, rating, correction },
    ),

  // —— 知识卡片 ——
  listCards: (limit = 50, offset = 0, sessionId?: string) => {
    const qs = new URLSearchParams()
    qs.set('limit', String(limit))
    qs.set('offset', String(offset))
    if (sessionId) qs.set('session_id', sessionId)
    return getJSON<{ items: KnowledgeCard[]; total: number }>(`/api/cards?${qs.toString()}`)
  },
  getCard: (id: number) => getJSON<KnowledgeCard>(`/api/cards/${id}`),
  finalizeCard: (body: CardDraft & { user_answer?: string }) =>
    postJSON<FinalizeCardResponse>('/api/cards/finalize', {
      qa_id: body.qa_id,
      session_id: body.session_id,
      title: body.title,
      core_summary: body.core_summary,
      key_conclusion: body.key_conclusion,
      application_scenario: body.application_scenario,
      agent_question: body.agent_question,
      user_answer: body.user_answer ?? '',
      source_note_ids: body.source_note_ids,
    }),
  patchCard: (id: number, body: Partial<KnowledgeCard>) =>
    patchJSON<{ card_id: number; updated: boolean }>(`/api/cards/${id}`, body),
  deleteCard: (id: number) => deleteJSON<{ deleted: boolean; card_id: number }>(`/api/cards/${id}`),

  // 系统
  getStats: () => getJSON<Stats>('/api/stats'),
  getDueCards: (limit = 20) => getJSON<{ items: KnowledgeCardReview[] }>(`/api/cards/due/review?limit=${limit}`),
  runGrowthTriage: (limit = 3) => postJSON<{ found: number; triaged: number }>(`/api/system/growth-triage?limit=${limit}`, {}),
  runGrowthReview: (date?: string) => postJSON<{ generated: boolean; reason?: string; review_id?: number }>(
    `/api/system/growth-review${date ? `?date=${encodeURIComponent(date)}` : ''}`,
    {},
  ),
  listGrowthReviews: (limit = 7) => getJSON<{ reviews: Omit<GrowthReview, 'content'>[] }>(`/api/system/growth-reviews?limit=${limit}`),
  getGrowthReview: (date: string) => getJSON<GrowthReview>(`/api/system/growth-reviews/${date}`),
  getHealth: () => getJSON<Health>('/api/health'),

  // —— 设置 ——
  getSettings: () => getJSON<AllSettings>('/api/settings'),
  updateSettings: (body: Partial<AllSettings>) => putJSON<AllSettings>('/api/settings', body),

  // 监听文件夹
  listFolders: () => getJSON<{ folders: WatchFolder[] }>('/api/folders'),
  addFolder: (body: { path: string; device: string; app: string; recursive?: boolean }) =>
    postJSON<{ folder: WatchFolder; watcher_reloaded: boolean }>('/api/folders', body),
  patchFolder: (id: string, body: { enabled?: boolean; device?: string; app?: string; recursive?: boolean }) =>
    patchJSON<{ folder: WatchFolder; watcher_reloaded: boolean }>(`/api/folders/${id}`, body),
  deleteFolder: (id: string) => deleteJSON<{ deleted: boolean; watcher_reloaded: boolean }>(`/api/folders/${id}`),
  scanFolders: (root: string, maxDepth = 3) =>
    postJSON<ScanResult>('/api/folders/scan', { root, max_depth: maxDepth }),
  testPath: (path: string) => postJSON<PathTestResult>('/api/folders/test', { path }),

  // —— 系统维护 ——
  getSystemInfo: () => getJSON<SystemInfo>('/api/system/info'),
  getAccessInfo: () => getJSON<AccessInfo>('/api/system/access'),
  triggerScan: () => postJSON<{ scanned: boolean; new_notes: number }>('/api/system/scan', {}),
  rebuildLinks: (note_id?: number) =>
    postJSON<{ rebuilt: boolean; scope: string; links: number }>('/api/system/rebuild-links', { note_id: note_id ?? null }),
  retryFailed: () => postJSON<{ retried: boolean; count: number }>('/api/system/retry-failed', {}),
  vacuumDb: () => postJSON<{ vacuumed: boolean; before_bytes: number; after_bytes: number }>('/api/system/vacuum', {}),
  reprocessAll: () => postJSON<{ reprocessed: boolean; count: number }>('/api/system/reprocess-all', {}),
  getSources: () => getJSON<{ sources: SourceStat[] }>('/api/system/sources'),
  listActivityLogs: (params: { event_type?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (value) qs.set(key, String(value))
    })
    return getJSON<ActivityLogsResponse>(`/api/activity-logs?${qs.toString()}`)
  },
  createBackup: () =>
    postJSON<{ backup_id: number; file_name: string; path: string; size_bytes: number }>(
      '/api/system/backup',
      {},
    ),

  // 每日归纳
  triggerDailySummary: (date?: string) =>
    postJSON<{ generated: boolean; summary_id?: number; notes_count?: number; reason?: string }>(
      `/api/system/daily-summary${date ? `?date=${date}` : ''}`,
      {},
    ),
  listDailySummaries: (limit = 7) =>
    getJSON<{ summaries: Array<{ id: number; date: string; content: string; note_ids: number[]; created_at: string; updated_at: string }> }>(
      `/api/system/daily-summaries?limit=${limit}`,
    ),
  getDailySummary: (date: string) =>
    getJSON<{ id: number; date: string; content: string; note_ids: number[]; created_at: string; updated_at: string }>(
      `/api/system/daily-summaries/${date}`,
    ),
  triggerDecay: () =>
    postJSON<{ links: { decayed: number; removed: number }; memories: { removed: number } }>(
      '/api/system/decay',
      {},
    ),

  // —— OCR 模型管理 ——
  listOcrModels: () => getJSON<{ models: OcrModel[] }>('/api/ocr-models'),
  addOcrModel: (body: { name: string; model: string; enabled?: boolean; is_primary?: boolean }) =>
    postJSON<{ model: OcrModel; models: OcrModel[] }>('/api/ocr-models', body),
  patchOcrModel: (id: string, body: Partial<OcrModel>) =>
    patchJSON<{ model: OcrModel; models: OcrModel[] }>(`/api/ocr-models/${id}`, body),
  deleteOcrModel: (id: string) => deleteJSON<{ deleted: boolean; models: OcrModel[] }>(`/api/ocr-models/${id}`),

  // —— 用指定模型重新 OCR ——
  reocrNote: (note_id: number, model_id?: string) =>
    postJSON<{
      note_id: number
      status: string
      ocr_model: string | null
      title: string | null
      ocr_text: string | null
      summary: string | null
      keywords: string[] | null
    }>(`/api/notes/${note_id}/reocr`, { model_id: model_id ?? null }),

  // —— 笔记上传 ——
  uploadNotes: async (files: File[], device?: string, app?: string) => {
    const fd = new FormData()
    files.forEach((f) => fd.append('files', f))
    if (device) fd.append('device', device)
    if (app) fd.append('app', app)
    const res = await fetch('/api/upload', { method: 'POST', body: fd })
    if (!res.ok) throw new Error(`上传失败：${res.status}`)
    return res.json() as Promise<{
      status: string
      total: number
      success: number
      failed: number
      files: Array<{ filename: string; success: boolean; error?: string; saved_as?: string; note_id?: number; enqueue?: string }>
      message: string
    }>
  },

  // —— OCR 模型重置 ——
  resetOcrModels: () => postJSON<{ models: OcrModel[] }>('/api/ocr-models/reset', {}),
}
