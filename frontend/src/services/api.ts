/**
 * API 客户端
 */

const BASE_URL = '/api'

interface ApiOptions {
    method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
    body?: unknown
}

async function request<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
    const { method = 'GET', body } = options

    const config: RequestInit = {
        method,
        headers: {
            'Content-Type': 'application/json',
        },
    }

    if (body) {
        config.body = JSON.stringify(body)
    }

    const response = await fetch(`${BASE_URL}${endpoint}`, config)

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(error.detail || `HTTP ${response.status}`)
    }

    return response.json()
}

export const api = {
    get: <T>(endpoint: string) => request<T>(endpoint),
    post: <T>(endpoint: string, body?: unknown) => request<T>(endpoint, { method: 'POST', body }),
    put: <T>(endpoint: string, body?: unknown) => request<T>(endpoint, { method: 'PUT', body }),
    patch: <T>(endpoint: string, body?: unknown) => request<T>(endpoint, { method: 'PATCH' as any, body }),
    delete: <T>(endpoint: string) => request<T>(endpoint, { method: 'DELETE' }),
}

// ============ Tasks API ============
export const tasksApi = {
    list: () => api.get<Task[]>('/tasks?page_size=5000'),
    get: (taskId: string) => api.get<Task>(`/tasks/${taskId}`),
    logs: (taskId: string) => api.get<TaskLogEntry[]>(`/tasks/${taskId}/logs?limit=300`),
    create: (data: CreateTaskData) => api.post<Task>('/tasks', data),
    start: (taskId: string) => api.post<{ message: string }>(`/tasks/${taskId}/start`),
    pause: (taskId: string) => api.post<{ message: string }>(`/tasks/${taskId}/pause`),
    cancel: (taskId: string) => api.post<{ message: string }>(`/tasks/${taskId}/cancel`),
    delete: (taskId: string) => api.delete<{ message: string }>(`/tasks/${taskId}`),
    clear: (includeRunning = false) => api.delete<{ message: string }>(`/tasks?include_running=${includeRunning}`),
    // 批次 API
    listBatches: () => api.get<BatchSummary[]>('/tasks/batches'),
    getBatchTasks: (batchId: string) => api.get<Task[]>(`/tasks/batches/${batchId}`),
    deleteBatch: (batchId: string) => api.delete<{ message: string }>(`/tasks/batches/${batchId}`),
}

export interface TaskLogEntry {
    id?: number
    type?: string
    task_id?: string
    level: string
    message: string
    timestamp?: string
}

// ============ Accounts API ============
export const accountsApi = {
    list: (params?: {
        status?: string;
        health_status?: string;
        region?: string;
        search?: string;
        start_date?: string;
        end_date?: string;
        usage_status?: string;
        page?: number;
        page_size?: number
    }) => {
        const query = new URLSearchParams()
        if (params?.status) query.set('status', params.status)
        if (params?.health_status) query.set('health_status', params.health_status)
        if (params?.region) query.set('region', params.region)
        if (params?.search) query.set('search', params.search)
        if (params?.start_date) query.set('start_date', params.start_date)
        if (params?.end_date) query.set('end_date', params.end_date)
        if (params?.usage_status) query.set('usage_status', params.usage_status)
        if (params?.page) query.set('page', String(params.page))
        if (params?.page_size) query.set('page_size', String(params.page_size))
        return api.get<Account[]>(`/accounts?${query}`)
    },
    get: (id: number) => api.get<Account>(`/accounts/${id}`),
    getStats: (params?: {
        status?: string;
        health_status?: string;
        region?: string;
        search?: string;
        start_date?: string;
        end_date?: string;
        usage_status?: string;
    }) => {
        const query = new URLSearchParams()
        if (params?.status) query.set('status', params.status)
        if (params?.health_status) query.set('health_status', params.health_status)
        if (params?.region) query.set('region', params.region)
        if (params?.search) query.set('search', params.search)
        if (params?.start_date) query.set('start_date', params.start_date)
        if (params?.end_date) query.set('end_date', params.end_date)
        if (params?.usage_status) query.set('usage_status', params.usage_status)
        return api.get<AccountStats>(`/accounts/count?${query}`)
    },
    delete: (id: number) => api.delete<{ message: string }>(`/accounts/${id}`),
    export: (params?: {
        status?: string;
        health_status?: string;
        region?: string;
        search?: string;
        start_date?: string;
        end_date?: string;
        usage_status?: string;
        format?: 'csv' | 'json';
    }) => {
        const query = new URLSearchParams()
        if (params?.status) query.set('status', params.status)
        if (params?.health_status) query.set('health_status', params.health_status)
        if (params?.region) query.set('region', params.region)
        if (params?.search) query.set('search', params.search)
        if (params?.start_date) query.set('start_date', params.start_date)
        if (params?.end_date) query.set('end_date', params.end_date)
        if (params?.usage_status) query.set('usage_status', params.usage_status)
        if (params?.format) query.set('format', params.format)
        window.open(`${BASE_URL}/accounts/export?${query}`, '_blank')
    },

    // New methods
    refreshStatus: (id: number) => api.post<Account>(`/accounts/${id}/refresh-status`),
    checkin: (id: number) => api.post<Account>(`/accounts/${id}/checkin`),
    checkOffer: (id: number) => api.post<Account>(`/accounts/${id}/check-offer`),
    batchRefreshStatus: (ids: number[]) => api.post<{ message: string }>('/accounts/batch/refresh-status', { ids }),
    batchCheckin: (ids: number[]) => api.post<{ message: string }>('/accounts/batch/checkin', { ids }),
    batchDelete: (ids: number[]) => api.post<{ message: string }>('/accounts/batch', { ids }),
    toggleGeneration: (id: number, isEnabled: boolean) =>
        api.post<{ message: string }>(`/content/accounts/${id}/toggle?is_enabled=${isEnabled}`),
    batchToggleGeneration: (params: {
        status?: string;
        health_status?: string;
        region?: string;
        search?: string;
        usage_status?: string;
        is_enabled: boolean;
    }) => {
        const query = new URLSearchParams()
        if (params.status) query.set('status', params.status)
        if (params.health_status) query.set('health_status', params.health_status)
        if (params.region) query.set('region', params.region)
        if (params.search) query.set('search', params.search)
        if (params.usage_status) query.set('usage_status', params.usage_status)
        query.set('is_enabled', String(params.is_enabled))
        return api.post<{ message: string; updated: number }>(`/content/accounts/batch-toggle?${query}`)
    },
    manualCreate: (data: { email: string; region: string; session_id: string }) =>
        api.post<Account>('/accounts/manual', data),
    manualImport: (data: { mode: 'csv' | 'txt'; content: string }) =>
        api.post<{ success: number; skipped: number; failed: number; errors: { line: number; email?: string; reason: string }[] }>(
            '/accounts/manual/import',
            data
        ),
}

// ============ Content Generation API ============
export const contentApi = {
    generate: (data: ContentGenerationRequest) => api.post<ContentGenerationJob>('/content/generate', data),
    getModels: (params?: { region?: string }) => {
        const query = new URLSearchParams()
        if (params?.region) query.set('region', params.region)
        return api.get<ContentGenerationModels>(`/content/models?${query}`)
    },
    listJobs: (params?: { job_type?: string; status?: string }) => {
        const query = new URLSearchParams()
        if (params?.job_type) query.set('job_type', params.job_type)
        if (params?.status) query.set('status', params.status)
        return api.get<ContentGenerationJob[]>(`/content/jobs?${query}`)
    },
    getJob: (id: number) => api.get<ContentGenerationJob>(`/content/jobs/${id}`),
    cancelJob: (id: number) => api.post<ContentGenerationJob>(`/content/jobs/${id}/cancel`),
    deleteJob: (id: number) => api.delete<{ message: string }>(`/content/jobs/${id}`),
    batchDeleteJobs: (ids: number[]) => api.post<{ message: string, deleted: number }>('/content/jobs/batch-delete', ids),
    retryJob: (id: number) => api.post<ContentGenerationJob>(`/content/jobs/${id}/retry`),
}

// ============ Proxies API ============
export const proxiesApi = {
    list: (params: {
        page?: number
        page_size?: number
        node_type?: string
        region?: string
        enabled?: string
        sort_by?: 'name' | 'latency' | 'usage'
        sort_dir?: 'asc' | 'desc'
    } = {}) => {
        const query = new URLSearchParams()
        Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined && value !== '' && value !== 'all') query.set(key, String(value))
        })
        return api.get<ProxyListResponse>(`/proxies?${query}`)
    },
    facets: () => api.get<{ types: string[]; regions: string[] }>('/proxies/facets'),
    import: (text: string) =>
        api.post<{ inserted: number; duplicates: number; errors: { line: number; reason: string }[]; message: string }>(
            '/proxies/import', { text }
        ),
    sync: () => api.post<{ message: string }>('/proxies/sync'),
    getClashStatus: () => api.get<{ connected: boolean; current_node: string | null }>('/proxies/clash-status'),
    regions: () => api.get<{ regions: string[] }>('/proxies/regions'),
    toggle: (id: number) => api.post<ProxyNode>(`/proxies/${id}/toggle`),
    batchToggle: (ids: number[], is_enabled: boolean) =>
        api.post<{ message: string }>(`/proxies/batch-toggle`, { ids, is_enabled }),
    update: (id: number, data: { region_tag?: string; is_enabled?: boolean }) =>
        api.put<ProxyNode>(`/proxies/${id}`, data),
    testLatency: () => api.post<{ message: string }>('/proxies/test-latency'),
    testNodeLatency: (id: number) => api.post<ProxyNode>(`/proxies/${id}/test-latency`),
    // New Pool Methods
    getPoolStatus: () => api.get<{ total: number; active: number; idle: number }>('/proxies/pool/status'),
    reloadPool: () => api.post<{ message: string; count: number }>('/proxies/pool/reload'),
}

// ============ Domains API ============
export const domainsApi = {
    list: () => api.get<Domain[]>('/domains'),
    create: (data: CreateDomainData) => api.post<Domain>('/domains', data),
    update: (id: number, data: Partial<Domain>) => api.put<Domain>(`/domains/${id}`, data),
    delete: (id: number) => api.delete<{ message: string }>(`/domains/${id}`),
    toggle: (id: number) => api.post<Domain>(`/domains/${id}/toggle`),
    test: (id: number) => api.post<{ message: string; success: boolean }>(`/domains/${id}/test`),
}

// ============ Settings API ============
export const settingsApi = {
    get: () => api.get<Settings>('/settings'),
    update: (data: Partial<Settings>) => api.put<{ message: string }>('/settings', data),
}

// ============ Outlook Mailboxes API ============
export const outlookMailboxesApi = {
    list: (page = 1, pageSize = 50) =>
        api.get<OutlookMailboxListResponse>(`/outlook-mailboxes?page=${page}&page_size=${pageSize}`),
    batchCreate: (emails: string[], providerType: 'outlook' | 'generic_api', note?: string) =>
        api.post<{ message: string; success: boolean }>('/outlook-mailboxes/batch', {
            emails,
            provider_type: providerType,
            note,
        }),
    toggle: (id: number, isEnabled: boolean) =>
        api.patch<OutlookMailbox>(`/outlook-mailboxes/${id}`, { is_enabled: isEnabled }),
    delete: (id: number) =>
        api.delete<{ message: string }>(`/outlook-mailboxes/${id}`),
}

// ============ Types ============
export interface Task {
    id: number
    task_id: string
    batch_id?: string
    batch_name?: string
    status: 'created' | 'queued' | 'running' | 'paused' | 'completed' | 'cancelled' | 'failed'
    total_count: number
    success_count: number
    failure_count: number
    progress: number
    proxy_strategy?: string
    email_prefix_pattern?: string
    assigned_email?: string
    assigned_proxy_region?: string
    assigned_proxy_name?: string
    retry_count: number
    max_retries: number
    current_step?: string
    created_at: string
    completed_at?: string
}

export interface BatchSummary {
    batch_id: string
    batch_name: string
    total_tasks: number
    success_count: number
    failure_count: number
    progress: number
    status: string
    created_at: string
}

export interface CreateTaskData {
    total_count: number
    domain_mode: 'manual' | 'auto_rotate'
    domain_ids?: number[]
    proxy_strategy: 'round_robin' | 'random' | 'least_used';
    proxy_region: string;
    email_prefix_pattern: string;
    max_retries: number;
    concurrency: number;
    email_source: 'cloudflare' | 'outlook' | 'generic_api';
}

export interface Account {
    id: number
    email: string
    password: string
    session_id?: string
    status: 'pending' | 'registering' | 'success' | 'active' | 'failed' | 'banned'
    last_login_status?: 'success' | 'failed'
    is_valid: string
    proxy_node_name: string | null
    region: string | null
    registration_ip?: string
    registration_asn?: string
    registration_browser_profile?: string
    registration_browser_version?: string
    health_status: 'healthy' | 'expired' | 'banned' | 'unknown'
    created_at: string
    task_id?: string

    // 积分相关
    credits_total: number
    credits_gift: number
    credits_purchase: number
    credits_vip: number

    last_credit_check_at?: string
    last_checkin_at?: string

    // 订阅优惠资格
    offer_status?: 'unchecked' | 'checking' | 'eligible' | 'ineligible' | 'error'
    offer_product_id?: string
    offer_price_amount?: number
    offer_origin_price_amount?: number
    offer_currency_code?: string
    offer_discount_percent?: number
    offer_checked_at?: string
    offer_error?: string

    // 内容生成池
    gen_enabled?: boolean
    gen_enabled_at?: string
    gen_last_used_at?: string
    gen_locked_until?: string
    gen_auto_disabled_reason?: string
}

export interface ContentGenerationRequest {
    job_type: 'image' | 'video'
    prompt: string
    model?: string
    ratio?: string
    resolution?: string
    duration?: number
    input_images?: string[]
    input_videos?: string[]
    async_mode?: boolean
    function_mode?: string
}

export interface ContentGenerationJob {
    id: number
    job_type: 'image' | 'video'
    status: 'queued' | 'submitting' | 'submitted' | 'processing' | 'success' | 'failed' | 'cancelled'
    prompt?: string
    model?: string
    ratio?: string
    resolution?: string
    duration?: number
    function_mode?: string
    input_images?: string[]
    output_urls?: string[]
    thumbnail_urls?: string[]
    local_urls?: string[]
    error_message?: string
    remote_task_id?: string
    remote_history_id?: string
    remote_kind?: string
    remote_status?: string
    remote_fail_code?: string
    remote_error_message?: string
    progress?: number
    account_id?: number
    region?: string
    submitted_at?: string
    finished_at?: string
    created_at?: string
    updated_at?: string
}

export interface ContentGenerationModels {
    region: string
    profile: string
    model_set: string
    image_models: string[]
    video_models: string[]
    source: string
}

export interface AccountStats {
    total: number
    success: number
    failed: number
    pending: number
    success_rate: number
    matched: number
}

export interface ProxyNode {
    id: number
    name: string
    node_type?: string
    host?: string
    port?: number
    username?: string
    password?: string
    protocol?: string
    source?: string
    region_tag?: string
    is_enabled: boolean
    latency?: number
    is_healthy?: boolean
    status_icon: string
    usage_count: number
    last_tested_at?: string
}

export interface ProxyListResponse {
    items: ProxyNode[]
    total: number
    page: number
    page_size: number
    pages: number
}

export interface Domain {
    id: number
    domain: string
    cf_zone_id?: string
    is_enabled: boolean
    usage_count: number
    usage_limit: number
    is_available: boolean
    note?: string
    created_at: string
}

export interface CreateDomainData {
    domain: string
    cf_zone_id?: string
    usage_limit?: number
    note?: string
}

export interface Settings {
    dreamina_url: string
    register_timeout: number
    verification_timeout: number
    max_retry_count: number
    gen_async_enabled: boolean
    gen_image_async_poll_interval: number
    gen_video_async_poll_interval: number
    gen_auto_delete_account: boolean
    register_interval_min: number
    register_interval_max: number
    password_length: number
    password_include_special: boolean
    browser_headless: boolean
    browser_block_media: boolean
    clash_controller_url: string
    clash_secret?: string
    clash_proxy_port: number
    clash_proxy_group: string
    proxy_pool_keywords?: string
    mihomo_binary_path?: string
    clash_config_path?: string
    proxy_pool_start_port: number
    proxy_pool_size: number
    ext_proxy_file_path?: string
    cf_account_id?: string
    cf_kv_namespace_id?: string
    cf_api_token?: string
    // Worker HTTP 邮箱接入（替代官方 KV API）
    cf_worker_domain?: string
    cf_worker_admin_password?: string
    cf_email_domains?: string
    max_concurrency: number
    // Outlook Manager
    outlook_manager_url?: string
    outlook_manager_api_key?: string
    outlook_poll_interval?: number
    outlook_poll_timeout?: number
}

export interface OutlookMailbox {
    id: number
    email: string
    provider_type: 'outlook' | 'generic_api'
    has_code_url: boolean
    note?: string
    is_enabled: boolean
    usage_count: number
    last_used_at?: string
    created_at: string
}

export interface OutlookMailboxListResponse {
    total: number
    page: number
    page_size: number
    items: OutlookMailbox[]
}
