import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { Download, Sparkles, Plus, ImageIcon, Video, Scaling, Clock, Send, Trash2, PlayCircle, ChevronLeft, ChevronRight, RotateCcw, Film, Copy, AlertCircle } from 'lucide-react'
import { contentApi, ContentGenerationJob, ContentGenerationRequest } from '@/services/api'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

import { cn } from '@/lib/utils'
import { toast } from 'sonner'

// 素材项（图片/视频）
interface MediaItem {
    name: string        // 图片1, 视频1, etc.
    type: 'image' | 'video'
    dataUrl: string     // base64 data URL
    thumbnailUrl?: string
}

type JobType = 'video'
type FilterType = 'all'

const fallbackModelOptions: Record<JobType, string[]> = {
    video: ['jimeng-video-seedance-2.0-fast'],
}

const ACTIVE_JOB_STATUSES: ContentGenerationJob['status'][] = ['submitting', 'submitted', 'processing']
const SEEDANCE_MODELS = ['jimeng-video-seedance-2.0', 'jimeng-video-seedance-2.0-fast']

const POLL_INTERVAL_MS = 4000
const CACHE_STALE_MS = 10000
let cachedJobs: ContentGenerationJob[] = []
let cachedAt = 0
let fetchInFlight = false

export default function ContentGeneration() {
    const [jobs, setJobs] = useState<ContentGenerationJob[]>(() => cachedJobs)
    const [jobType, _setJobType] = useState<JobType>('video')
    const [filterType, _setFilterType] = useState<FilterType>('all')

    const [prompt, setPrompt] = useState('')
    const [model, setModel] = useState(() => localStorage.getItem('cg_model') || fallbackModelOptions.video[0])
    const [ratio, setRatio] = useState(() => localStorage.getItem('cg_ratio') || '16:9')
    const [resolution, setResolution] = useState('2k')
    const [duration, setDuration] = useState(() => Number(localStorage.getItem('cg_duration')) || 15)
    const [inputMedia, setInputMedia] = useState<MediaItem[]>([])
    const [selectedIds, setSelectedIds] = useState<number[]>([])
    const [isMultiSelectMode, setIsMultiSelectMode] = useState(false)
    const [previewJob, setPreviewJob] = useState<ContentGenerationJob | null>(null)
    const [previewIndex, setPreviewIndex] = useState(0)
    const [cardImageIndexes, setCardImageIndexes] = useState<Record<number, number>>({})
    const [isDragging, setIsDragging] = useState(false)
    const [isFocused, setIsFocused] = useState(false)
    const [isHovered, setIsHovered] = useState(false)
    const [selectOpen, setSelectOpen] = useState(false)
    const [showAtPopup, setShowAtPopup] = useState(false)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const atPopupRef = useRef<HTMLDivElement>(null)
    // 记忆用户选择的参数
    useEffect(() => { localStorage.setItem('cg_model', model) }, [model])
    useEffect(() => { localStorage.setItem('cg_ratio', ratio) }, [ratio])
    useEffect(() => { localStorage.setItem('cg_duration', String(duration)) }, [duration])

    // 获取下一个素材自动命名
    const getNextMediaName = useCallback((mediaType: 'image' | 'video', existing: MediaItem[]) => {
        const count = existing.filter(m => m.type === mediaType).length + 1
        return mediaType === 'image' ? `图片${count}` : `视频${count}`
    }, [])

    // 为视频生成缩略图（捕获第一帧）
    const generateVideoThumbnail = useCallback((file: File): Promise<string | undefined> => {
        return new Promise((resolve) => {
            const objectUrl = URL.createObjectURL(file)
            const video = document.createElement('video')
            video.preload = 'auto'
            video.muted = true
            video.playsInline = true
            // 超时兜底：8秒内没生成就放弃
            const cleanup = () => { URL.revokeObjectURL(objectUrl); video.src = '' }
            const timeout = setTimeout(() => { cleanup(); resolve(undefined) }, 8000)
            video.onloadedmetadata = () => {
                video.currentTime = Math.min(0.5, video.duration * 0.1)
            }
            video.onseeked = () => {
                clearTimeout(timeout)
                try {
                    const canvas = document.createElement('canvas')
                    const w = video.videoWidth
                    const h = video.videoHeight
                    if (w === 0 || h === 0) { cleanup(); resolve(undefined); return }
                    const scale = Math.min(200 / w, 200 / h)
                    canvas.width = Math.round(w * scale)
                    canvas.height = Math.round(h * scale)
                    const ctx = canvas.getContext('2d')
                    if (ctx) {
                        ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
                        resolve(canvas.toDataURL('image/jpeg', 0.7))
                    } else {
                        resolve(undefined)
                    }
                } catch {
                    resolve(undefined)
                }
                cleanup()
            }
            video.onerror = () => { clearTimeout(timeout); cleanup(); resolve(undefined) }
            video.src = objectUrl
        })
    }, [])

    const durationOptions = useMemo(() => {
        if (jobType !== 'video') return []
        if (SEEDANCE_MODELS.includes(model)) {
            return Array.from({ length: 12 }, (_, index) => index + 4)
        }
        return [5, 10]
    }, [jobType, model])


    const fetchJobs = async (options?: { force?: boolean }) => {
        if (fetchInFlight) return
        const now = Date.now()
        if (!options?.force && now - cachedAt < CACHE_STALE_MS) return
        fetchInFlight = true
        try {
            const data = await contentApi.listJobs()
            cachedJobs = data
            cachedAt = Date.now()
            setJobs(data)
        } catch (e) {
            console.error('Failed to fetch jobs', e)
        } finally {
            fetchInFlight = false
        }
    }

    const fetchModels = async () => {
        // 固定只使用 seedance-2.0-fast 模型
        setModel('jimeng-video-seedance-2.0-fast')
    }

    useEffect(() => {
        fetchModels()
        let timer: ReturnType<typeof setInterval> | null = null

        const stop = () => {
            if (timer) {
                clearInterval(timer)
                timer = null
            }
        }

        const start = () => {
            if (timer) return
            timer = setInterval(() => fetchJobs(), POLL_INTERVAL_MS)
        }

        const handleVisibility = () => {
            if (document.visibilityState === 'visible') {
                fetchJobs()
                start()
            } else {
                stop()
            }
        }

        handleVisibility()
        document.addEventListener('visibilitychange', handleVisibility)
        return () => {
            stop()
            document.removeEventListener('visibilitychange', handleVisibility)
        }
    }, [])

    useEffect(() => {
        setModel('jimeng-video-seedance-2.0-fast')
        setResolution('720p')
        setRatio('16:9')
        setDuration(15)
        setInputMedia([])
        setSelectedIds([])
    }, [jobType])

    useEffect(() => {
        if (jobType === 'video') {
            if (!durationOptions.includes(duration)) {
                setDuration(durationOptions[0] || 15)
            }
        }
    }, [jobType, model, duration, durationOptions])

    const handleGenerate = async () => {
        if (!prompt.trim()) return

        const images = inputMedia.filter(m => m.type === 'image').map(m => m.dataUrl)
        const videos = inputMedia.filter(m => m.type === 'video').map(m => m.dataUrl)
        const hasMedia = images.length > 0 || videos.length > 0

        const payload: ContentGenerationRequest = {
            job_type: jobType,
            prompt,
            model,
            ratio,
            resolution,
            duration: duration,
            input_images: images.length > 0 ? images : undefined,
            input_videos: videos.length > 0 ? videos : undefined,
            async_mode: true,
            // 有素材时自动使用 omni_reference 模式
            function_mode: hasMedia ? 'omni_reference' : undefined,
        }
        await contentApi.generate(payload)
        setPrompt('')
        setInputMedia([])
        fetchJobs({ force: true })
    }

    // 重试失败任务——在原有任务上原地重试，不丢失参数，不产生重复卡片
    const handleRetry = async (job: ContentGenerationJob) => {
        try {
            await contentApi.retryJob(job.id)
            fetchJobs({ force: true })
        } catch (error: any) {
            console.error('Retry failed:', error)
        }
    }

    // 同款生成——复用任务的 prompt 和参数到输入框
    const handleUsePrompt = (job: ContentGenerationJob) => {
        if (job.prompt) setPrompt(job.prompt)
        if (job.model) setModel(job.model)
        if (job.ratio) setRatio(job.ratio)
        if (job.resolution) setResolution(job.resolution)
        if (job.duration) setDuration(job.duration)

        // 复用素材（input_images 存储的是 base64 data URL）
        const restoredMedia: MediaItem[] = []
        if (job.input_images && job.input_images.length > 0) {
            let imgCount = 0
            let vidCount = 0
            for (const dataUrl of job.input_images) {
                // 通过 data URL 的 MIME 类型判断是图片还是视频
                const isVideo = dataUrl.startsWith('data:video/')
                if (isVideo) {
                    vidCount++
                    restoredMedia.push({ name: `视频${vidCount}`, type: 'video', dataUrl })
                } else {
                    imgCount++
                    restoredMedia.push({ name: `图片${imgCount}`, type: 'image', dataUrl })
                }
            }
        }
        setInputMedia(restoredMedia)

        const mediaHint = restoredMedia.length > 0 ? `，含 ${restoredMedia.length} 个素材` : ''
        toast.success(`已填入参数${mediaHint}，可修改后生成`)
        // 滚动到底部输入框
        setTimeout(() => textareaRef.current?.focus(), 200)
    }

    const handleFiles = async (files: FileList | File[]) => {
        const list = Array.from(files).slice(0, 10)
        const newItems: MediaItem[] = []

        for (const file of list) {
            const dataUrl = await new Promise<string>((resolve) => {
                const reader = new FileReader()
                reader.onload = () => resolve(String(reader.result || ''))
                reader.readAsDataURL(file)
            })
            const isVideo = file.type.startsWith('video/')
            const mediaType = isVideo ? 'video' as const : 'image' as const
            const allMedia = [...inputMedia, ...newItems]
            const name = getNextMediaName(mediaType, allMedia)
            let thumbnailUrl: string | undefined
            if (isVideo) {
                thumbnailUrl = await generateVideoThumbnail(file)
            }
            newItems.push({ name, type: mediaType, dataUrl, thumbnailUrl })
        }

        setInputMedia(prev => [...prev, ...newItems].slice(0, 12))
    }

    const handleDrop = async (event: React.DragEvent<HTMLDivElement>) => {
        event.preventDefault()
        setIsDragging(false)
        if (event.dataTransfer.files?.length) {
            await handleFiles(event.dataTransfer.files)
        }
    }

    const handleFileClick = async (event: React.ChangeEvent<HTMLInputElement>) => {
        if (event.target.files?.length) {
            await handleFiles(event.target.files)
            event.target.value = ''
        }
    }

    const handlePaste = async (event: React.ClipboardEvent) => {
        if (event.clipboardData.files?.length) {
            await handleFiles(event.clipboardData.files)
        }
    }

    const removeMedia = (index: number) => {
        setInputMedia(prev => prev.filter((_, i) => i !== index))
    }

    // @ 素材引用：在光标处插入 @名称
    const insertAtReference = (mediaName: string) => {
        const textarea = textareaRef.current
        if (!textarea) return
        const pos = textarea.selectionStart || 0
        // 找到光标前最后一个 @ 的位置
        const beforeCursor = prompt.slice(0, pos)
        const atIdx = beforeCursor.lastIndexOf('@')
        if (atIdx >= 0) {
            // 替换 @ 后面的内容为选中的素材名
            const newPrompt = prompt.slice(0, atIdx) + '@' + mediaName + prompt.slice(pos)
            setPrompt(newPrompt)
            // 移动光标到插入内容之后
            setTimeout(() => {
                const newPos = atIdx + 1 + mediaName.length
                textarea.setSelectionRange(newPos, newPos)
                textarea.focus()
            }, 0)
        }
        setShowAtPopup(false)
    }

    // 监听 textarea 输入，检测 @ 字符
    const handlePromptChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        const value = e.target.value
        setPrompt(value)
        const pos = e.target.selectionStart || 0
        const charBefore = value[pos - 1]
        if (charBefore === '@' && inputMedia.length > 0) {
            setShowAtPopup(true)
        } else if (showAtPopup) {
            // 如果正在显示弹出，检查是否还在 @ 后面输入（用于过滤）
            const beforeCursor = value.slice(0, pos)
            const atIdx = beforeCursor.lastIndexOf('@')
            if (atIdx < 0) {
                setShowAtPopup(false)
            }
        }
    }

    const filteredJobs = useMemo(() => {
        let res = jobs
        if (filterType !== 'all') {
            res = res.filter(j => j.job_type === filterType)
        }
        return res
    }, [jobs, filterType])

    const toggleSelection = (id: number) => {
        setSelectedIds(prev => prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id])
    }
    
    const handleSelectAllToggle = () => {
        if (selectedIds.length === filteredJobs.length && filteredJobs.length > 0) {
            // 反选逻辑: all to none, otherwise invert selection? The requested was "全选和反选" (Select All and Invert Selection).
            // Actually, if it's "全不选" then they just want to deselect. Let's do Invert Selection.
            setSelectedIds(filteredJobs.filter(j => !selectedIds.includes(j.id)).map(j => j.id))
        } else {
            // If nothing is selected, select all. Or we can just strictly do Invert Selection.
            // Oh wait, the prompt asks: "全选和反选，反选不是全不选" => So "全选" (Select All) and "反选" (Invert Selection).
            // The logic: if selected === total, then Invert should naturally make it `none`. 
            setSelectedIds(filteredJobs.filter(j => !selectedIds.includes(j.id)).map(j => j.id))
        }
    }

    const isExpanded = isFocused || isHovered || selectOpen || prompt.trim() !== '' || inputMedia.length > 0


    const handleDownload = async (url?: string, index?: number, localUrl?: string) => {
        if (!url && !localUrl) return
        
        // 1. 本地文件优先：直接跳转静态资源路径（速度最快）
        if (localUrl) {
            const link = document.createElement('a')
            link.href = localUrl
            link.download = localUrl.split('/').pop()?.split('?')[0] || `file_${index || 0}`
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
            return
        }

        // 2. 远程文件通过 Proxy 接口跳转
        // 废弃原有的 fetch + blob 逻辑，避免浏览器等待大视频缓冲完才弹窗
        // 直接跳转链接会触发浏览器自带的下载管理，秒开“另存为”对话框
        if (url) {
            const downloadUrl = `/api/content/download-proxy?url=${encodeURIComponent(url)}`
            const link = document.createElement('a')
            link.href = downloadUrl
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
        }
    }

    const handleBatchDownload = async () => {
        const selectedJobs = filteredJobs.filter(job => selectedIds.includes(job.id))
        if (!selectedJobs.length) return
        
        const jobIds = selectedJobs.map(j => j.id).join(',')
        
        // 调用后端流式 ZIP 打包接口。不再在前端下载各子文件并打包。
        // 使用隐藏链接触发，确保浏览器能正确接收 Content-Disposition
        const batchUrl = `/api/content/batch-download?ids=${jobIds}`
        const link = document.createElement('a')
        link.href = batchUrl
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        
        toast.success(`正在准备下载包 (${selectedJobs.length} 个任务)...`)
    }
    
    const handleDelete = async (id: number) => {
        try {
            await contentApi.deleteJob(id)
            setSelectedIds(prev => prev.filter(i => i !== id))
            await fetchJobs({ force: true })
        } catch (e) {
            console.error('Failed to delete job', e)
        }
    }
    
    const handleBatchDelete = async () => {
        if (!selectedIds.length) return
        try {
            await contentApi.batchDeleteJobs(selectedIds)
            setSelectedIds([])
            await fetchJobs({ force: true })
        } catch (e) {
            console.error('Batch delete failed', e)
        }
    }

    return (
        <div className="flex-1 space-y-4 pb-48 h-[calc(100vh-100px)] overflow-y-auto pr-2 animate-in fade-in duration-500 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
            <div className="flex items-center justify-end sticky top-0 z-40 bg-background pb-4 pt-4 -mx-2 px-6 border-b border-white/5 shadow-md">
                <div className="flex items-center gap-2">
                    <Button
                        variant={isMultiSelectMode ? "default" : "outline"}
                        size="sm"
                        className={cn("h-9 rounded-[10px] gap-1.5", isMultiSelectMode ? "bg-emerald-600 hover:bg-emerald-700 text-white" : "border-white/5 bg-card/40 hover:bg-white/10")}
                        onClick={() => { setIsMultiSelectMode(!isMultiSelectMode); if (isMultiSelectMode) setSelectedIds([]) }}
                    >
                        {isMultiSelectMode ? '退出多选' : '多选'}
                    </Button>
                    {isMultiSelectMode && (
                    <>
                    <Button variant="outline" size="sm" className="h-9 border-white/5 bg-card/40 hover:bg-white/10 rounded-[10px]" onClick={() => setSelectedIds(filteredJobs.map(j => j.id))}>
                        全选
                    </Button>
                    <Button variant="outline" size="sm" className="h-9 border-white/5 bg-card/40 hover:bg-white/10 rounded-[10px]" onClick={handleSelectAllToggle}>
                        反选
                    </Button>
                    <Button variant="outline" size="sm" className="h-9 border-white/5 bg-card/40 hover:bg-white/10 gap-2 rounded-[10px]" onClick={handleBatchDownload} disabled={selectedIds.length === 0}>
                        <Download className="h-4 w-4" />打包下载
                    </Button>
                    <Button variant="destructive" size="sm" className="h-9 gap-2 rounded-[10px]" onClick={handleBatchDelete} disabled={selectedIds.length === 0}>
                        <Trash2 className="h-4 w-4" />批量删除
                    </Button>
                    </>
                    )}
                </div>
            </div>

            <div style={{ paddingBottom: '320px' }}>
                <div className="flex flex-wrap gap-2 max-w-[1800px] mx-auto">
                {filteredJobs.map((job) => {
                    const currentIndex = cardImageIndexes[job.id] || 0
                    const thumbCover = job.thumbnail_urls?.[currentIndex] || job.thumbnail_urls?.[0]
                    const cover = thumbCover || job.output_urls?.[currentIndex] || job.output_urls?.[0]
                    const originalCover = job.output_urls?.[currentIndex] || job.output_urls?.[0]
                    const selected = selectedIds.includes(job.id)
                    const count = job.output_urls?.length || 0

                    // 宽高比：用于 flex-grow，让每个卡片按比例分配宽度
                    const getAspectNum = (r?: string) => {
                        if (!r) return 0.75
                        const [w, h] = r.split(':').map(Number)
                        return (w && h) ? w / h : 0.75
                    }
                    const aspect = getAspectNum(job.ratio)
                    return (
                        <Card key={job.id}
                            className={cn(
                                "group border bg-transparent hover:border-white/15 rounded-xl overflow-hidden shadow-lg hover:shadow-2xl hover:shadow-black/40 p-0 transition-all duration-300",
                                selected ? "border-emerald-400/70 shadow-[0_0_16px_rgba(52,211,153,0.3)] ring-1 ring-emerald-400/30" : "border-white/[0.06]"
                            )}
                            style={{ height: 220, flexGrow: aspect, flexBasis: `${186 * aspect}px`, minWidth: 100, maxWidth: `${186 * aspect * 1.15}px` }}
                        >
                            <CardContent className="p-0 relative w-full h-full">
                                {/* 主预览区 */}
                                <button
                                    type="button"
                                    onClick={() => {
                                        if (isMultiSelectMode) {
                                            toggleSelection(job.id)
                                        } else {
                                            setPreviewIndex(currentIndex)
                                            setPreviewJob({ ...job })
                                        }
                                    }}
                                    className="w-full h-full overflow-hidden flex items-center justify-center relative group/btn"
                                >
                                    {cover ? (
                                        job.job_type === 'video' ? (
                                            <div className="w-full h-full relative group/vid">
                                                <video
                                                    src={originalCover || ""}
                                                    className="w-full h-full object-cover"
                                                    preload="metadata"
                                                    poster={thumbCover}
                                                    muted loop playsInline
                                                    onMouseOver={(e) => e.currentTarget.play()}
                                                    onMouseOut={(e) => e.currentTarget.pause()}
                                                />
                                                <div className="absolute inset-0 flex items-center justify-center bg-black/10 opacity-0 group-hover/vid:opacity-100 transition-opacity duration-300 pointer-events-none">
                                                    <PlayCircle className="h-10 w-10 text-white/80 drop-shadow-xl" />
                                                </div>
                                                <div className="absolute top-2.5 left-2.5 z-10 flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-black/50 backdrop-blur-md border border-white/10">
                                                    <Film className="h-3 w-3 text-white/80" />
                                                    {job.duration && <span className="text-[10px] text-white/70 font-medium">{job.duration}s</span>}
                                                </div>
                                            </div>
                                        ) : (
                                            <img
                                                src={cover || ""}
                                                alt="preview"
                                                loading="lazy"
                                                decoding="async"
                                                className="w-full h-full object-cover transition-transform duration-500 group-hover/btn:scale-[1.03]"
                                            />
                                        )
                                    ) : (
                                        ACTIVE_JOB_STATUSES.includes(job.status) ? (
                                            <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-b from-slate-900/90 to-black/95">
                                                <div className="absolute inset-0 -translate-x-full animate-[shimmer_2.5s_infinite] bg-gradient-to-r from-transparent via-white/[0.03] to-transparent" />
                                                <div className="absolute left-0 right-0 h-px bg-gradient-to-r from-transparent via-cyan-500/60 to-transparent animate-[scan_2.5s_ease-in-out_infinite]" />
                                                <div className="relative mb-5">
                                                    <div className="absolute inset-0 rounded-full animate-ping bg-cyan-500/30 scale-150"></div>
                                                    {job.job_type === 'image' ? <ImageIcon className="h-7 w-7 text-cyan-400 relative z-10" /> : <Video className="h-7 w-7 text-cyan-400 relative z-10" />}
                                                </div>
                                                <div className="w-2/3 max-w-[140px] relative z-10">
                                                    <div className="flex items-center justify-between mb-1">
                                                        <span className="text-[10px] font-medium text-white/50 tracking-wider">
                                                            {job.status === 'submitting' ? '提交中' : job.status === 'submitted' ? '排队中' : '生成中'}
                                                        </span>
                                                        <span className="text-[10px] font-mono font-semibold text-cyan-400 tabular-nums">
                                                            {job.progress || 0}%
                                                        </span>
                                                    </div>
                                                    <div className="h-1 rounded-full bg-white/10 overflow-hidden">
                                                        <div className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-400 transition-all duration-700 ease-out" style={{ width: `${Math.max(job.progress || 0, 3)}%` }} />
                                                    </div>
                                                </div>
                                            </div>
                                        ) : job.status === 'failed' ? (
                                            <div className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-b from-red-950/30 to-black/90">
                                                <div className="h-10 w-10 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center mb-2">
                                                    <AlertCircle className="h-5 w-5 text-red-400" />
                                                </div>
                                                <span className="text-[11px] text-red-400/80 font-medium">生成失败</span>
                                            </div>
                                        ) : (
                                            <div className="absolute inset-0 flex items-center justify-center bg-black/60">
                                                <Sparkles className="h-5 w-5 text-white/20" />
                                            </div>
                                        )
                                    )}

                                    {/* 底部渐变信息叠加层 */}
                                    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent pt-10 pb-2.5 px-3 pointer-events-none">
                                        {job.prompt && (
                                            <p className="text-[11px] text-white/55 leading-[1.4] line-clamp-2 mb-1.5">{job.prompt}</p>
                                        )}
                                        {job.status === 'failed' && (job.error_message || job.remote_error_message) && (
                                            <div className="flex items-start gap-1 mb-1">
                                                <AlertCircle className="h-3 w-3 text-red-400 shrink-0 mt-px" />
                                                <p className="text-[10px] text-red-400/70 leading-snug line-clamp-1">{job.error_message || job.remote_error_message}</p>
                                            </div>
                                        )}
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-1.5">
                                                {ACTIVE_JOB_STATUSES.includes(job.status) ? (
                                                    <span className="flex items-center gap-1 text-[10px] text-blue-400 font-medium">
                                                        <span className="relative flex h-1.5 w-1.5"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span><span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-blue-400"></span></span>
                                                        {job.status === 'submitting' ? '提交中' : job.status === 'submitted' ? '已提交' : '生成中'}
                                                    </span>
                                                ) : job.status === 'success' ? (
                                                    <span className="text-[10px] text-emerald-400/80 font-medium">✓ 完成</span>
                                                ) : job.status === 'failed' ? (
                                                    <span className="text-[10px] text-red-400/80 font-medium">✕ 失败</span>
                                                ) : null}
                                            </div>
                                            <span className="text-[10px] text-white/25 font-mono tabular-nums">
                                                {job.created_at ? new Date(job.created_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) : ''}
                                            </span>
                                        </div>
                                    </div>




                                    {/* 右上角操作区：重试 + 下载 + 删除 */}
                                    <div className="absolute top-2.5 right-2.5 opacity-0 group-hover:opacity-100 transition-all duration-200 z-10 flex items-center gap-1">
                                        {job.status === 'failed' && (
                                            <div className="cursor-pointer" onClick={(e) => { e.stopPropagation(); handleRetry(job) }} title="重试">
                                                <span className="h-7 w-7 flex items-center justify-center rounded-md bg-black/40 border border-white/10 backdrop-blur-md hover:bg-amber-500/60 transition-colors">
                                                    <RotateCcw className="h-3.5 w-3.5 text-white/80" />
                                                </span>
                                            </div>
                                        )}
                                        {job.status !== 'failed' && (
                                        <div className="cursor-pointer" onClick={(e) => { e.stopPropagation(); handleDownload(originalCover, currentIndex, job.local_urls?.[currentIndex]) }}>
                                            <span className="h-7 w-7 flex items-center justify-center rounded-md bg-black/40 border border-white/10 backdrop-blur-md hover:bg-black/60 transition-colors">
                                                <Download className="h-3.5 w-3.5 text-white/80" />
                                            </span>
                                        </div>
                                        )}
                                        <div className="cursor-pointer" onClick={(e) => { e.stopPropagation(); handleDelete(job.id) }}>
                                            <span className="h-7 w-7 flex items-center justify-center rounded-md bg-black/40 border border-white/10 backdrop-blur-md hover:bg-red-500/60 transition-colors">
                                                <Trash2 className="h-3.5 w-3.5 text-white/80" />
                                            </span>
                                        </div>
                                    </div>

                                    {job.job_type === 'image' && count > 1 && (
                                        <span className="absolute bottom-14 right-3 text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-black/50 backdrop-blur-md text-white/70 border border-white/10 z-10 pointer-events-none">
                                            {currentIndex + 1}/{count}
                                        </span>
                                    )}
                                </button>

                                {/* 底部操作栏 */}
                                <div className="flex items-center justify-between px-2.5 py-1.5">
                                    {job.job_type === 'image' && count > 1 ? (
                                        <div className="flex items-center gap-1 overflow-x-auto [&::-webkit-scrollbar]:hidden">
                                            {(job.thumbnail_urls?.length ? job.thumbnail_urls : job.output_urls)?.map((url, idx) => (
                                                <button key={idx} type="button"
                                                    onClick={(e) => { e.stopPropagation(); setCardImageIndexes(prev => ({ ...prev, [job.id]: idx })) }}
                                                    className={cn("h-7 w-7 shrink-0 rounded-md overflow-hidden border transition-all", currentIndex === idx ? "border-white/50 opacity-100" : "border-transparent opacity-40 hover:opacity-80")}
                                                >
                                                    <img src={url || ''} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover"
                                                        onError={(e) => { const t = e.currentTarget; const o = job.output_urls?.[idx]; if (o && t.src !== o) t.src = o; }} />
                                                </button>
                                            ))}
                                        </div>
                                    ) : <div className="flex-1" />}

                                    <div className="flex items-center gap-0.5 shrink-0 ml-auto">
                                        {job.prompt && (
                                            <button type="button" title="同款生成"
                                                className="opacity-0 group-hover:opacity-100 transition-all duration-200 h-7 w-7 flex items-center justify-center rounded-md text-white/40 hover:text-emerald-400 hover:bg-emerald-500/10"
                                                onClick={(e) => { e.stopPropagation(); handleUsePrompt(job) }}>
                                                <Copy className="h-3.5 w-3.5" />
                                            </button>
                                        )}
                                        <button type="button" title="删除"
                                            className="opacity-0 group-hover:opacity-100 transition-all duration-200 h-7 w-7 flex items-center justify-center rounded-md text-white/40 hover:text-red-400 hover:bg-red-500/10"
                                            onClick={(e) => { e.stopPropagation(); handleDelete(job.id) }}>
                                            <Trash2 className="h-3.5 w-3.5" />
                                        </button>
                                    </div>
                                </div>
                            </CardContent>
                        </Card>
                    )
                })}
                </div>
        </div>


            <div className="fixed left-1/2 -translate-x-1/2 bottom-6 z-50 transition-all duration-300 w-[min(680px,90vw)]">
                <div
                    className={cn(
                        "rounded-2xl border border-white/10 bg-black/70 shadow-2xl backdrop-blur-3xl flex flex-col transition-all duration-500 hover:border-white/15",
                        isDragging && "border-emerald-400/80 shadow-[0_0_30px_rgba(52,211,153,0.3)] bg-green-950/30",
                        isExpanded ? "p-4 gap-3" : "p-2.5 gap-0"
                    )}
                    onMouseEnter={() => setIsHovered(true)}
                    onMouseLeave={() => setIsHovered(false)}
                    onDragOver={(e) => {
                        e.preventDefault()
                        setIsDragging(true)
                    }}
                    onDragLeave={() => setIsDragging(false)}
                    onDrop={handleDrop}
                >
                    {/* Top Area: Uploaded Media (图片 + 视频) */}
                    <div 
                        className={cn(
                            "flex items-center gap-3 overflow-x-auto transition-all duration-300 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]",
                            isExpanded ? "max-h-24 opacity-100 mb-0 pb-1" : "max-h-0 opacity-0 mb-0 pb-0"
                        )}
                    >
                        {inputMedia.map((media, idx) => (
                            <div key={`${media.name}-${idx}`} className="group relative h-16 w-16 shrink-0 rounded-2xl overflow-hidden border border-white/10 bg-black/40 shadow-sm transition-transform hover:scale-105">
                                {media.type === 'image' ? (
                                    <img src={media.dataUrl} alt={media.name} className="h-full w-full object-cover" />
                                ) : (
                                    <>
                                        {media.thumbnailUrl ? (
                                            <img src={media.thumbnailUrl} alt={media.name} className="h-full w-full object-cover" />
                                        ) : (
                                            <div className="h-full w-full bg-purple-900/40 flex items-center justify-center">
                                                <Film className="h-6 w-6 text-purple-400" />
                                            </div>
                                        )}
                                        <div className="absolute bottom-0 right-0 p-0.5 bg-purple-500/80 rounded-tl-lg">
                                            <Video className="h-2.5 w-2.5 text-white" />
                                        </div>
                                    </>
                                )}
                                {/* 素材名称 */}
                                <div className="absolute bottom-0 left-0 right-0 bg-black/70 text-center">
                                    <span className="text-[9px] text-white/80 leading-none">{media.name}</span>
                                </div>
                                {/* 删除按钮 */}
                                <button
                                    className="absolute inset-0 bg-black/60 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                                    onClick={() => removeMedia(idx)}
                                >
                                    <Trash2 className="h-4 w-4 text-red-400" />
                                </button>
                            </div>
                        ))}
                        <label className="h-16 w-16 shrink-0 rounded-2xl border border-dashed border-white/20 bg-white/5 flex flex-col items-center justify-center text-xs text-muted-foreground cursor-pointer hover:bg-white/10 hover:border-white/30 transition-all group">
                            <Plus className="h-5 w-5 mb-1 group-hover:text-emerald-400 transition-colors" />
                            <span className="text-[10px] scale-90">添加</span>
                            <input type="file" accept="image/*,video/*" multiple className="hidden" onChange={handleFileClick} />
                        </label>
                    </div>

                    {/* Middle Area: Prompt Input + @ Popup */}
                    <div 
                        className={cn(
                            "relative transition-all duration-300",
                            isExpanded ? "max-h-[300px] opacity-100" : "max-h-0 opacity-0 scale-95"
                        )}
                    >
                        <Textarea
                            ref={textareaRef}
                            value={prompt}
                            onChange={handlePromptChange}
                            onFocus={() => setIsFocused(true)}
                            onBlur={() => {
                                setIsFocused(false)
                                // 延迟关闭 @ 弹出，让点击事件先触发
                                setTimeout(() => setShowAtPopup(false), 200)
                            }}
                            onPaste={handlePaste}
                            onKeyDown={(e) => {
                                if (showAtPopup && e.key === 'Escape') {
                                    setShowAtPopup(false)
                                    e.preventDefault()
                                }
                            }}
                            placeholder={inputMedia.length > 0 ? '使用 @ 快速调用参考内容，例如：@图片1 模仿 @视频1 的动作' : '请描述你想生成的内容...'}
                            className="min-h-[100px] resize-none bg-white/5 border-transparent outline-none focus-visible:ring-1 focus-visible:ring-emerald-500/50 rounded-2xl text-[15px] leading-relaxed px-4 py-3 placeholder:text-muted-foreground/60 focus:bg-white/10 transition-all"
                        />

                        {/* @ 素材引用弹出菜单 */}
                        {showAtPopup && inputMedia.length > 0 && (
                            <div
                                ref={atPopupRef}
                                className="absolute bottom-full left-4 mb-2 w-56 bg-black/95 backdrop-blur-xl border border-white/15 rounded-xl shadow-2xl z-[60] overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200"
                            >
                                <div className="px-3 py-2 text-xs text-white/40 border-b border-white/10">可能@的内容</div>
                                {inputMedia.map((media, idx) => (
                                    <button
                                        key={idx}
                                        type="button"
                                        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-white/10 transition-colors text-left"
                                        onMouseDown={(e) => {
                                            e.preventDefault() // 阻止 textarea 失焦
                                            insertAtReference(media.name)
                                        }}
                                    >
                                        <div className="h-8 w-8 rounded-lg overflow-hidden bg-black/40 border border-white/10 shrink-0 flex items-center justify-center">
                                            {media.type === 'image' ? (
                                                <img src={media.dataUrl} alt="" className="h-full w-full object-cover" />
                                            ) : media.thumbnailUrl ? (
                                                <img src={media.thumbnailUrl} alt="" className="h-full w-full object-cover" />
                                            ) : (
                                                <Film className="h-4 w-4 text-purple-400" />
                                            )}
                                        </div>
                                        <span className="text-sm text-white/90">{media.name}</span>
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* 底部参数栏 + 发送按钮 */}
                    <div className={cn(
                        "flex items-center gap-2 transition-all duration-300",
                        isExpanded ? "border-t border-white/5 pt-3" : "pt-0"
                    )}>
                        <span className="h-9 rounded-lg bg-white/5 text-[11px] gap-1.5 shrink-0 flex items-center px-2.5 text-white/50 max-w-[180px] truncate" title={model}>
                            <Sparkles className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                            <span className="truncate">{model.replace('jimeng-video-', '').replace('-fast', ' ⚡')}</span>
                        </span>

                        <Select value={ratio} onValueChange={setRatio} onOpenChange={setSelectOpen}>
                            <SelectTrigger className="h-9 rounded-lg bg-white/5 border-transparent hover:bg-white/10 text-xs gap-1.5 w-[85px] shrink-0 transition-colors">
                                <div className="flex items-center gap-1.5 opacity-80 whitespace-nowrap">
                                    <Scaling className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                                    <SelectValue placeholder="比例" />
                                </div>
                            </SelectTrigger>
                            <SelectContent side="top" className="rounded-xl border-white/10 bg-black/90 backdrop-blur-xl mb-2">
                                {['1:1', '4:3', '3:4', '16:9', '9:16', '3:2', '2:3', '21:9'].map((item) => (
                                    <SelectItem key={item} value={item} className="rounded-lg focus:bg-white/10 cursor-pointer">{item}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>

                        {jobType === 'video' && (
                            <Select value={String(duration)} onValueChange={(value) => setDuration(Number(value))} onOpenChange={setSelectOpen}>
                                <SelectTrigger className="h-9 rounded-lg bg-white/5 border-transparent hover:bg-white/10 text-xs gap-1.5 w-[80px] shrink-0 transition-colors">
                                    <div className="flex items-center gap-1.5 opacity-80 whitespace-nowrap">
                                        <Clock className="h-3.5 w-3.5 shrink-0 text-rose-400" />
                                        <SelectValue placeholder="时长" />
                                    </div>
                                </SelectTrigger>
                                <SelectContent side="top" className="rounded-xl border-white/10 bg-black/90 backdrop-blur-xl mb-2">
                                    {durationOptions.map((item) => (
                                        <SelectItem key={item} value={String(item)} className="rounded-lg focus:bg-white/10 cursor-pointer">{item}s</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        )}

                        <div className="flex-1" />

                        <Button
                            onClick={handleGenerate}
                            disabled={!prompt.trim()}
                            className={cn(
                                "h-9 px-4 rounded-lg flex items-center gap-2 transition-all duration-300 text-xs font-medium shrink-0",
                                prompt.trim() 
                                    ? "bg-gradient-to-r from-emerald-500 to-teal-500 hover:shadow-lg hover:shadow-emerald-500/20 text-black border-none"
                                    : "bg-white/5 text-white/20 cursor-not-allowed border-transparent"
                            )}
                        >
                            <Send className="h-3.5 w-3.5" />
                            生成
                        </Button>
                    </div>
                </div>
            </div>

            <Dialog open={!!previewJob} onOpenChange={(open) => !open && setPreviewJob(null)}>
                <DialogContent className="max-w-[70vw] w-[1400px] h-[80vh] bg-[#0f1115]/95 backdrop-blur-2xl border-white/10 rounded-3xl p-0 overflow-hidden shadow-[0_0_50px_rgba(0,0,0,0.8)] flex flex-col md:flex-row focus:outline-none focus-visible:outline-none">
                    <DialogTitle className="sr-only">资产预览</DialogTitle>
                    <div className="flex-1 bg-black/60 relative flex items-center justify-center overflow-hidden border-r border-white/5 group">
                        {previewJob?.output_urls?.[previewIndex] || previewJob?.local_urls?.[previewIndex] ? (
                            previewJob.job_type === 'video' ? (
                                <video 
                                    src={previewJob.local_urls?.[previewIndex] || previewJob.output_urls?.[previewIndex]} 
                                    controls 
                                    autoPlay 
                                    loop 
                                    playsInline 
                                    className="w-full h-full object-contain focus:outline-none focus:ring-0" 
                                />
                            ) : (
                                <img 
                                    src={previewJob.local_urls?.[previewIndex] || previewJob.output_urls?.[previewIndex]} 
                                    alt="preview" 
                                    className="w-full h-full object-contain" 
                                />
                            )
                        ) : (
                            <Sparkles className="h-8 w-8 text-muted-foreground animate-pulse" />
                        )}
                        
                        {/* Image count corner indicator */}
                        {previewJob?.job_type === 'image' && previewJob.output_urls && previewJob.output_urls.length > 1 && (
                            <div className="absolute top-4 left-4 px-3 py-1.5 rounded-full bg-black/50 border border-white/10 backdrop-blur-md text-xs font-medium text-white/90 pointer-events-none">
                                {previewIndex + 1} / {previewJob.output_urls.length}
                            </div>
                        )}

                        {/* Left/Right controls for images */}
                        {previewJob?.job_type === 'image' && previewJob.output_urls && previewJob.output_urls.length > 1 && (
                            <>
                                <button 
                                    onClick={(e) => { e.stopPropagation(); setPreviewIndex(prev => Math.max(0, prev - 1)); }}
                                    className={cn(
                                        "absolute left-4 top-1/2 -translate-y-1/2 h-12 w-12 flex items-center justify-center rounded-full bg-black/50 border border-white/10 text-white/80 hover:bg-black/80 hover:text-white hover:scale-110 transition-all backdrop-blur-md opacity-0 group-hover:opacity-100",
                                        previewIndex === 0 && "hidden"
                                    )}
                                >
                                    <ChevronLeft className="h-7 w-7 pr-0.5" />
                                </button>
                                <button 
                                    onClick={(e) => { e.stopPropagation(); setPreviewIndex(prev => Math.min((previewJob.output_urls?.length || 1) - 1, prev + 1)); }}
                                    className={cn(
                                        "absolute right-4 top-1/2 -translate-y-1/2 h-12 w-12 flex items-center justify-center rounded-full bg-black/50 border border-white/10 text-white/80 hover:bg-black/80 hover:text-white hover:scale-110 transition-all backdrop-blur-md opacity-0 group-hover:opacity-100",
                                        previewIndex === (previewJob.output_urls?.length || 1) - 1 && "hidden"
                                    )}
                                >
                                    <ChevronRight className="h-7 w-7 pl-0.5" />
                                </button>
                                {/* Thumbnails at bottom overlay */}
                                <div className="absolute bottom-6 flex items-center gap-3 px-5 py-3 bg-black/50 backdrop-blur-xl rounded-2xl border border-white/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                                    {previewJob.output_urls.map((url, idx) => (
                                        <button
                                            key={idx}
                                            onClick={(e) => { e.stopPropagation(); setPreviewIndex(idx); }}
                                            className={cn(
                                                "h-14 w-14 shrink-0 rounded-xl overflow-hidden border-2 transition-all hover:scale-110",
                                                previewIndex === idx ? "border-emerald-500 shadow-[0_0_15px_rgba(52,211,153,0.4)] opacity-100 scale-110" : "border-transparent opacity-60 hover:opacity-100"
                                            )}
                                        >
                                            <img src={url} alt={`thumb-${idx}`} className="w-full h-full object-cover" />
                                        </button>
                                    ))}
                                </div>
                            </>
                        )}
                    </div>

                    {/* Right Side: Parameters & Prompt */}
                    <div className="w-full md:w-[360px] lg:w-[400px] shrink-0 bg-[#16181d] flex flex-col overflow-hidden">
                        <div className="p-6 border-b border-white/5 space-y-1 shrink-0">
                            <h3 className="text-xl font-bold text-white/90">生成详情</h3>
                            <p className="text-xs text-muted-foreground/60">{previewJob?.created_at ? new Date(previewJob.created_at).toLocaleString() : 'Just now'}</p>
                        </div>
                        
                        <div className="p-6 flex-1 flex flex-col gap-8">
                            <div className="space-y-3">
                                <span className="text-[11px] font-semibold text-white/40 uppercase tracking-widest pl-1">Prompt 提示词</span>
                                <div className="bg-black/40 border border-white/5 rounded-2xl p-4 text-[15px] text-white/80 leading-relaxed shadow-inner break-words h-[320px] overflow-y-auto">
                                    {previewJob?.prompt || '--'}
                                </div>
                            </div>
                            
                            <div className="space-y-3">
                                <span className="text-[11px] font-semibold text-white/40 uppercase tracking-widest pl-1">参数配置</span>
                                <div className="bg-black/40 border border-white/5 rounded-2xl p-5 grid gap-4 text-sm shadow-inner">
                                    <div className="flex justify-between items-center group">
                                        <span className="text-white/50 group-hover:text-white/70 transition-colors">设置模板</span>
                                        <span className="font-semibold text-emerald-400/90">{previewJob?.job_type === 'video' ? '视频生成' : '图片生成'}</span>
                                    </div>
                                    <div className="flex justify-between items-center group">
                                        <span className="text-white/50 group-hover:text-white/70 transition-colors">模型版本</span>
                                        <span className="font-medium text-white/80">{previewJob?.model || '--'}</span>
                                    </div>
                                    <div className="flex justify-between items-center group">
                                        <span className="text-white/50 group-hover:text-white/70 transition-colors">画面比例</span>
                                        <span className="font-medium text-white/80">{previewJob?.ratio || '--'}</span>
                                    </div>
                                    <div className="flex justify-between items-center group">
                                        <span className="text-white/50 group-hover:text-white/70 transition-colors">清晰度</span>
                                        <span className="font-medium text-white/80">{previewJob?.resolution || '--'}</span>
                                    </div>
                                    {previewJob?.duration && (
                                        <div className="flex justify-between items-center group">
                                            <span className="text-white/50 group-hover:text-white/70 transition-colors">视频时长</span>
                                            <span className="font-medium text-white/80">{previewJob?.duration}s</span>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* 错误信息 */}
                            {previewJob?.status === 'failed' && (previewJob?.error_message || previewJob?.remote_error_message) && (
                                <div className="space-y-3">
                                    <span className="text-[11px] font-semibold text-red-400/60 uppercase tracking-widest pl-1">❌ 错误信息</span>
                                    <div className="bg-red-500/5 border border-red-500/20 rounded-2xl p-4 text-sm text-red-300/90 leading-relaxed break-words max-h-[200px] overflow-y-auto">
                                        {previewJob?.error_message || previewJob?.remote_error_message}
                                    </div>
                                </div>
                            )}

                            {/* 操作按钮区 */}
                            <div className="mt-auto pt-4 pb-2 flex items-center gap-3">
                                <Button
                                    variant="outline"
                                    className="flex-1 h-11 rounded-xl border-white/10 bg-white/5 hover:bg-emerald-500/20 hover:border-emerald-500/30 hover:text-emerald-400 gap-2 transition-all"
                                    onClick={() => {
                                        if (previewJob) handleUsePrompt(previewJob)
                                        setPreviewJob(null)
                                    }}
                                >
                                    <Copy className="h-4 w-4" />
                                    同款生成
                                </Button>
                                <Button
                                    variant="outline"
                                    className="flex-1 h-11 rounded-xl border-white/10 bg-white/5 hover:bg-cyan-500/20 hover:border-cyan-500/30 hover:text-cyan-400 gap-2 transition-all"
                                    onClick={() => {
                                        const idx = previewIndex
                                        if (previewJob) handleDownload(previewJob.output_urls?.[idx], idx, previewJob.local_urls?.[idx])
                                    }}
                                    disabled={!previewJob?.output_urls?.[previewIndex] && !previewJob?.local_urls?.[previewIndex]}
                                >
                                    <Download className="h-4 w-4" />
                                    下载
                                </Button>
                                <Button
                                    variant="outline"
                                    className="h-11 w-11 rounded-xl border-white/10 bg-white/5 hover:bg-red-500/20 hover:border-red-500/30 hover:text-red-400 transition-all shrink-0"
                                    onClick={() => {
                                        if (previewJob) {
                                            handleDelete(previewJob.id)
                                            setPreviewJob(null)
                                        }
                                    }}
                                >
                                    <Trash2 className="h-4 w-4" />
                                </Button>
                            </div>
                        </div>
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    )
}
