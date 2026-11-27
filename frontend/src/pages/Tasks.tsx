import { useEffect, useState } from 'react'
import { usePolling } from '../hooks/usePolling'
import {
    Plus,
    RefreshCw,
    CheckCircle2,
    AlertCircle,
    Trash2,
    ChevronDown,
    ChevronRight,
    Loader2,
} from 'lucide-react'
import { tasksApi, domainsApi, Task, Domain, BatchSummary } from '../services/api'
import { useLanguage } from '../contexts/LanguageContext'
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { CreateTaskModal } from "@/components/tasks/CreateTaskModal"
import { TaskTable } from "@/components/tasks/TaskTable"

// Module-level caches
let cachedBatches: BatchSummary[] = []
let cachedDomains: Domain[] = []

export default function Tasks() {
    const [batches, setBatches] = useState<BatchSummary[]>(cachedBatches)
    const [domains, setDomains] = useState<Domain[]>(cachedDomains)
    const [showModal, setShowModal] = useState(false)
    const [loading, setLoading] = useState(cachedBatches.length === 0)
    const [expandedBatch, setExpandedBatch] = useState<string | null>(null)
    const [batchTasks, setBatchTasks] = useState<Task[]>([])
    const [loadingTasks, setLoadingTasks] = useState(false)
    const { t } = useLanguage()

    const fetchData = async () => {
        try {
            const [batchesData, domainsData] = await Promise.all([
                tasksApi.listBatches(),
                domainsApi.list()
            ])
            cachedBatches = batchesData
            cachedDomains = domainsData.filter(d => d.is_available)
            setBatches(batchesData)
            setDomains(cachedDomains)
        } catch (error) {
            console.error('Failed to fetch data:', error)
        } finally {
            setLoading(false)
        }
    }

    const fetchBatchTasks = async (batchId: string) => {
        setLoadingTasks(true)
        try {
            const tasks = await tasksApi.getBatchTasks(batchId)
            setBatchTasks(tasks)
        } catch (error) {
            console.error('Failed to fetch batch tasks:', error)
        } finally {
            setLoadingTasks(false)
        }
    }

    const toggleBatch = (batchId: string) => {
        if (expandedBatch === batchId) {
            setExpandedBatch(null)
            setBatchTasks([])
        } else {
            setExpandedBatch(batchId)
            fetchBatchTasks(batchId)
        }
    }

    useEffect(() => {
        fetchData()
    }, [])

    usePolling(fetchData, 5000)

    // Auto-refresh expanded batch tasks
    usePolling(async () => {
        if (expandedBatch) {
            const tasks = await tasksApi.getBatchTasks(expandedBatch)
            setBatchTasks(tasks)
        }
    }, 5000)

    const handleClearTasks = async () => {
        if (!confirm('确定要清空所有已完成/失败/取消的任务记录吗？运行中的任务不会被删除。')) return
        try {
            await tasksApi.clear(false)
            fetchData()
            setExpandedBatch(null)
            setBatchTasks([])
        } catch (error) {
            console.error('Clear tasks failed:', error)
        }
    }

    const handleDeleteBatch = async (e: React.MouseEvent, batchId: string) => {
        e.stopPropagation()
        if (!confirm('确定要删除此批次的所有任务吗？运行中的任务不会被删除。')) return
        try {
            await tasksApi.deleteBatch(batchId)
            if (expandedBatch === batchId) {
                setExpandedBatch(null)
                setBatchTasks([])
            }
            fetchData()
        } catch (error) {
            console.error('Delete batch failed:', error)
        }
    }

    const handleAction = async (taskId: string, action: 'pause' | 'cancel' | 'delete') => {
        if (action === 'delete' && !confirm(t('common.confirm'))) return
        try {
            switch (action) {
                case 'pause': await tasksApi.pause(taskId); break
                case 'cancel': await tasksApi.cancel(taskId); break
                case 'delete': await tasksApi.delete(taskId); break
            }
            fetchData()
            if (expandedBatch) fetchBatchTasks(expandedBatch)
        } catch (error) {
            console.error(`Action ${action} failed:`, error)
        }
    }

    const stats = {
        total: batches.reduce((sum, b) => sum + b.total_tasks, 0),
        success: batches.reduce((sum, b) => sum + b.success_count, 0),
        failed: batches.reduce((sum, b) => sum + b.failure_count, 0)
    }


    const getStatusLabel = (status: string) => {
        switch (status) {
            case 'running': return '进行中'
            case 'completed': return '已完成'
            case 'failed': return '有失败'
            default: return '等待中'
        }
    }

    const getProgressBarColor = (status: string) => {
        switch (status) {
            case 'running': return 'bg-primary'
            case 'completed': return 'bg-emerald-500'
            case 'failed': return 'bg-destructive'
            default: return 'bg-muted-foreground/30'
        }
    }

    return (
        <div className="flex-1 space-y-8 animate-in fade-in duration-500">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h2 className="text-4xl font-extrabold tracking-tight bg-gradient-to-r from-foreground to-foreground/50 bg-clip-text text-transparent">
                        {t('tasks.title')}
                    </h2>
                    <p className="text-muted-foreground mt-1 text-lg">
                        {t('tasks.subtitle')}
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={fetchData} disabled={loading}>
                        <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                        {t('tasks.sync')}
                    </Button>
                    <Button variant="outline" size="sm" onClick={handleClearTasks} disabled={batches.length === 0}>
                        <Trash2 className="mr-2 h-4 w-4" />
                        清空任务
                    </Button>
                    <Button size="sm" onClick={() => setShowModal(true)}>
                        <Plus className="mr-2 h-4 w-4" />
                        {t('tasks.deploy')}
                    </Button>
                </div>
            </div>

            {/* Stats */}
            <div className="grid gap-4 md:grid-cols-3">
                <Card className="bg-card/40 border-border/30">
                    <CardContent className="pt-4 pb-3 px-5">
                        <div className="text-xs font-medium text-muted-foreground/60 uppercase tracking-wider">总任务数</div>
                        <div className="text-2xl font-bold mt-1">{stats.total}</div>
                    </CardContent>
                </Card>
                <Card className="bg-card/40 border-border/30">
                    <CardContent className="pt-4 pb-3 px-5">
                        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground/60 uppercase tracking-wider">
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />成功注册
                        </div>
                        <div className="text-2xl font-bold text-emerald-500 mt-1">{stats.success}</div>
                    </CardContent>
                </Card>
                <Card className="bg-card/40 border-border/30">
                    <CardContent className="pt-4 pb-3 px-5">
                        <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground/60 uppercase tracking-wider">
                            <AlertCircle className="h-3.5 w-3.5 text-destructive" />触发拦截
                        </div>
                        <div className="text-2xl font-bold text-destructive mt-1">{stats.failed}</div>
                    </CardContent>
                </Card>
            </div>

            {/* Batch Cards */}
            <div className="space-y-3">
                {batches.length === 0 ? (
                    <Card className="bg-card/20 border-border/30">
                        <CardContent className="py-12 text-center text-muted-foreground">
                            暂无任务批次，点击「新建任务」开始
                        </CardContent>
                    </Card>
                ) : (
                    batches.map((batch) => {
                        const isExpanded = expandedBatch === batch.batch_id
                        return (
                            <div key={batch.batch_id} className="space-y-0">
                                {/* Batch Card */}
                                <Card
                                    className={`bg-card/30 border-border/30 cursor-pointer transition-all hover:bg-card/50 ${isExpanded ? 'rounded-b-none border-b-0' : ''}`}
                                    onClick={() => toggleBatch(batch.batch_id)}
                                >
                                    <CardContent className="py-4 px-5">
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-3 flex-1 min-w-0">
                                                {isExpanded ?
                                                    <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" /> :
                                                    <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
                                                }
                                                <div className="min-w-0 flex-1">
                                                    <div className="flex items-center gap-3">
                                                        <span className="font-semibold truncate">{batch.batch_name}</span>
                                                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${
                                                            batch.status === 'running' ? 'border-primary/30 bg-primary/10 text-primary' :
                                                            batch.status === 'completed' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-500' :
                                                            batch.status === 'failed' ? 'border-destructive/30 bg-destructive/10 text-destructive' :
                                                            'border-border bg-muted/20 text-muted-foreground'
                                                        }`}>
                                                            {getStatusLabel(batch.status)}
                                                        </span>
                                                    </div>
                                                    {/* Progress bar */}
                                                    <div className="mt-2 flex items-center gap-3">
                                                        <div className="flex-1 h-2 rounded-full bg-secondary/50 overflow-hidden">
                                                            <div
                                                                className={`h-full transition-all duration-700 ease-out rounded-full ${getProgressBarColor(batch.status)}`}
                                                                style={{ width: `${batch.progress}%` }}
                                                            />
                                                        </div>
                                                        <span className="text-xs font-mono text-muted-foreground/80 w-10 text-right">
                                                            {Math.round(batch.progress)}%
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Stats + Actions */}
                                            <div className="flex items-center gap-6 ml-4 shrink-0">
                                                <div className="flex items-center gap-4 text-xs">
                                                    <span className="text-muted-foreground">
                                                        共 <span className="font-mono font-medium text-foreground">{batch.total_tasks}</span>
                                                    </span>
                                                    <span className="text-emerald-500">
                                                        ✓ <span className="font-mono font-medium">{batch.success_count}</span>
                                                    </span>
                                                    <span className="text-destructive">
                                                        ✗ <span className="font-mono font-medium">{batch.failure_count}</span>
                                                    </span>
                                                </div>
                                                <span className="text-xs text-muted-foreground/50">
                                                    {new Date(batch.created_at).toLocaleString('zh-CN', { hour12: false })}
                                                </span>
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="h-7 w-7"
                                                    onClick={(e) => handleDeleteBatch(e, batch.batch_id)}
                                                >
                                                    <Trash2 className="h-3.5 w-3.5" />
                                                </Button>
                                            </div>
                                        </div>
                                    </CardContent>
                                </Card>

                                {/* Expanded Task List */}
                                {isExpanded && (
                                    <div className="border border-t-0 border-border/30 rounded-b-xl overflow-hidden bg-card/10">
                                        {loadingTasks ? (
                                            <div className="py-8 flex items-center justify-center gap-2 text-muted-foreground">
                                                <Loader2 className="h-4 w-4 animate-spin" /> 加载中...
                                            </div>
                                        ) : (
                                            <TaskTable tasks={batchTasks} onAction={handleAction} />
                                        )}
                                    </div>
                                )}
                            </div>
                        )
                    })
                )}
            </div>

            {/* Create Task Modal */}
            <CreateTaskModal
                open={showModal}
                onOpenChange={setShowModal}
                domains={domains}
                onSuccess={fetchData}
            />
        </div>
    )
}
