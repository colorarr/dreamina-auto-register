import {
    ChevronDown,
    ChevronRight,
    Pause,
    StopCircle,
    TerminalSquare,
    Trash2,
} from 'lucide-react'
import { Fragment, useEffect, useRef, useState } from 'react'
import { Task, TaskLogEntry, tasksApi } from '../../services/api'
import { useLanguage } from '../../contexts/LanguageContext'
import { Button } from "@/components/ui/button"
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table"
import { toast } from 'sonner'


interface TaskTableProps {
    tasks: Task[]
    onAction: (taskId: string, action: 'pause' | 'cancel' | 'delete') => void
}

export function TaskTable({ tasks, onAction }: TaskTableProps) {
    const { t } = useLanguage()
    const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null)

    const getProgressDisplay = (task: Task) => {
        const isFailed = task.status === 'failed';
        const isRunning = task.status === 'running';
        const isSuccess = task.status === 'completed';
        const isPaused = task.status === 'paused';

        const colorClass = isFailed ? "bg-destructive" : isSuccess ? "bg-emerald-500" : isRunning ? "bg-primary" : "bg-muted-foreground/30";
        const textClass = isFailed ? "text-destructive" : isSuccess ? "text-emerald-500 font-bold" : isRunning ? "text-primary font-bold" : "text-muted-foreground";

        return (
            <div className="w-[120px] space-y-1.5 pt-1">
                <div className="flex items-center justify-between text-[11px] px-0.5">
                    <span className={`uppercase tracking-wider ${textClass}`}>
                        {isFailed ? "失败" : isSuccess ? "成功" : isPaused ? "暂停" : isRunning ? "运行中" : "已创建"}
                    </span>
                    <span className="font-mono font-medium text-muted-foreground/80">
                        {Math.round(task.progress || 0)}%
                    </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-secondary/50 overflow-hidden">
                    <div
                        className={`h-full transition-all duration-500 ease-out ${colorClass}`}
                        style={{ width: `${task.progress || 0}%` }}
                    />
                </div>
                {isFailed && task.current_step && (
                    <span
                        className="block text-[10px] text-red-400/80 max-w-[120px] truncate cursor-pointer hover:text-red-300 transition-colors"
                        onClick={(e) => {
                            e.stopPropagation()
                            navigator.clipboard.writeText(task.current_step!)
                            toast.success('失败原因已复制')
                        }}
                        title="点击复制完整失败原因"
                    >
                        {task.current_step}
                    </span>
                )}
            </div>
        )
    }



    return (
        <div className="bg-card/20 rounded-xl border border-border/30 overflow-hidden">
            <Table>
                <TableHeader className="bg-muted/10">
                    <TableRow className="hover:bg-transparent border-border/20">
                        <TableHead className="w-[100px] text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 py-4">{t('tasks.table.id')}</TableHead>
                        <TableHead className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 py-4">{t('tasks.table.target')}</TableHead>

                        <TableHead className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 py-4">{t('tasks.table.status')}</TableHead>
                        <TableHead className="text-right text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 py-4">Attempts</TableHead>
                        <TableHead className="text-right text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 py-4">{t('tasks.table.created')}</TableHead>
                        <TableHead className="text-right text-[10px] font-bold uppercase tracking-widest text-muted-foreground/50 py-4">{t('common.actions')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {tasks.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={6} className="h-24 text-center">
                                {t('common.none')}
                            </TableCell>
                        </TableRow>
                    ) : (
                        tasks.map((task) => (
                            <Fragment key={task.task_id}>
                            <TableRow>
                                <TableCell className="font-medium">#{task.task_id.slice(0, 8)}</TableCell>
                                <TableCell>{task.assigned_email || <span className="text-muted-foreground italic">Unassigned</span>}</TableCell>

                                <TableCell>{getProgressDisplay(task)}</TableCell>
                                <TableCell className="text-right font-mono text-xs">
                                    {task.status === 'created' ? '-' :
                                        `${(task.retry_count || 0) + 1} / ${(task.max_retries ?? 3) + 1}`}
                                </TableCell>
                                <TableCell className="text-right">{new Date(task.created_at).toLocaleString('zh-CN', { hour12: false })}</TableCell>
                                <TableCell className="text-right">
                                    <div className="flex justify-end gap-2">
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            title="查看实时注册日志"
                                            onClick={() => setExpandedTaskId(current => current === task.task_id ? null : task.task_id)}
                                        >
                                            {expandedTaskId === task.task_id ? <ChevronDown className="h-4 w-4" /> : <TerminalSquare className="h-4 w-4" />}
                                        </Button>
                                        {task.status === 'running' && (
                                            <Button variant="ghost" size="icon" onClick={() => onAction(task.task_id, 'pause')}>
                                                <Pause className="h-4 w-4" />
                                            </Button>
                                        )}
                                        {task.status !== 'completed' && task.status !== 'cancelled' && (
                                            <Button variant="ghost" size="icon" onClick={() => onAction(task.task_id, 'cancel')}>
                                                <StopCircle className="h-4 w-4 text-destructive" />
                                            </Button>
                                        )}
                                        <Button variant="ghost" size="icon" onClick={() => onAction(task.task_id, 'delete')} disabled={task.status === 'running'}>
                                            <Trash2 className="h-4 w-4" />
                                        </Button>
                                    </div>
                                </TableCell>
                            </TableRow>
                            {expandedTaskId === task.task_id && (
                                <TableRow className="hover:bg-transparent">
                                    <TableCell colSpan={6} className="p-0">
                                        <TaskLogPanel task={task} />
                                    </TableCell>
                                </TableRow>
                            )}
                            </Fragment>
                        ))
                    )}
                </TableBody>
            </Table>
        </div>
    )
}

function TaskLogPanel({ task }: { task: Task }) {
    const [logs, setLogs] = useState<TaskLogEntry[]>([])
    const [connected, setConnected] = useState(false)
    const endRef = useRef<HTMLDivElement | null>(null)

    useEffect(() => {
        let active = true
        tasksApi.logs(task.task_id)
            .then(items => active && setLogs(items))
            .catch(() => active && setLogs([]))

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const socket = new WebSocket(`${protocol}//${window.location.host}/ws/task/${task.task_id}`)
        socket.onopen = () => active && setConnected(true)
        socket.onclose = () => active && setConnected(false)
        socket.onmessage = event => {
            try {
                const entry = JSON.parse(event.data) as TaskLogEntry
                if (active && entry.type === 'log') {
                    setLogs(current => [...current, entry].slice(-300))
                }
            } catch {
                // 心跳或非日志消息无需展示
            }
        }
        return () => {
            active = false
            socket.close()
        }
    }, [task.task_id])

    useEffect(() => {
        endRef.current?.scrollIntoView({ block: 'nearest' })
    }, [logs])

    const levelColor = (level: string) => {
        const normalized = level.toUpperCase()
        if (normalized === 'ERROR') return 'text-red-400'
        if (normalized === 'WARNING') return 'text-amber-400'
        if (normalized === 'SUCCESS') return 'text-emerald-400'
        return 'text-sky-400'
    }

    return (
        <div className="border-t border-border/30 bg-zinc-950 text-zinc-200">
            <div className="flex items-center justify-between border-b border-white/10 px-4 py-2 text-xs">
                <div className="flex items-center gap-2">
                    <ChevronRight className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="font-mono">任务 #{task.task_id.slice(0, 8)}</span>
                    <span className="text-zinc-500">{task.assigned_email}</span>
                </div>
                <span className={connected ? 'text-emerald-400' : 'text-zinc-500'}>
                    {connected ? '● 实时连接' : '○ 历史日志'}
                </span>
            </div>
            <div className="h-64 overflow-y-auto px-4 py-3 font-mono text-xs leading-6">
                {logs.length === 0 ? (
                    <div className="text-zinc-500">暂无日志，当前步骤：{task.current_step || '等待执行'}</div>
                ) : logs.map((log, index) => (
                    <div key={`${log.id || log.timestamp || 'live'}-${index}`} className="grid grid-cols-[80px_64px_1fr] gap-2">
                        <span className="text-zinc-600">
                            {log.timestamp ? new Date(log.timestamp).toLocaleTimeString('zh-CN', { hour12: false }) : '--:--:--'}
                        </span>
                        <span className={levelColor(log.level)}>{log.level.toUpperCase()}</span>
                        <span className="whitespace-pre-wrap break-words text-zinc-300">{log.message}</span>
                    </div>
                ))}
                <div ref={endRef} />
            </div>
        </div>
    )
}
