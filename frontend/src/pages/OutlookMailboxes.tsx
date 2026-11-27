
import { useEffect, useState } from 'react'
import { Mail, Plus, RefreshCw, Trash2, ToggleLeft, ToggleRight } from 'lucide-react'
import { outlookMailboxesApi, OutlookMailbox } from '../services/api'
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select"

// Module-level caches to prevent UI clear flickering during navigations
let cachedMailboxes: OutlookMailbox[] = []
let cachedTotal = 0

export default function OutlookMailboxes() {
    const [mailboxes, setMailboxes] = useState<OutlookMailbox[]>(cachedMailboxes)
    const [total, setTotal] = useState(cachedTotal)
    const [loading, setLoading] = useState(cachedMailboxes.length === 0)
    const [showImport, setShowImport] = useState(false)
    const [importText, setImportText] = useState('')
    const [providerType, setProviderType] = useState<'outlook' | 'generic_api'>('outlook')
    const [importing, setImporting] = useState(false)
    const [importResult, setImportResult] = useState('')

    const fetchData = async () => {
        try {
            const data = await outlookMailboxesApi.list(1, 200)
            cachedMailboxes = data.items
            cachedTotal = data.total
            setMailboxes(data.items)
            setTotal(data.total)
        } catch (error) {
            console.error('Failed to fetch outlook mailboxes:', error)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchData()
    }, [])

    const handleToggle = async (mailbox: OutlookMailbox) => {
        try {
            await outlookMailboxesApi.toggle(mailbox.id, !mailbox.is_enabled)
            await fetchData()
        } catch (error) {
            console.error('Toggle failed:', error)
        }
    }

    const handleDelete = async (mailbox: OutlookMailbox) => {
        if (!confirm(`确认删除邮箱 ${mailbox.email}？`)) return
        try {
            await outlookMailboxesApi.delete(mailbox.id)
            await fetchData()
        } catch (error) {
            console.error('Delete failed:', error)
        }
    }

    const handleImport = async () => {
        const entries = importText
            .split('\n')
            .map(e => e.trim())
            .filter(Boolean)

        if (entries.length === 0) return

        setImporting(true)
        try {
            const result = await outlookMailboxesApi.batchCreate(entries, providerType)
            setImportResult(result.message)
            setShowImport(false)
            setImportText('')
            await fetchData()
        } catch (error) {
            console.error('Import failed:', error)
        } finally {
            setImporting(false)
        }
    }

    const available = mailboxes.filter(m => m.is_enabled).length
    const disabled = mailboxes.filter(m => !m.is_enabled).length

    return (
        <div className="flex-1 space-y-8 animate-in fade-in duration-500">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                    <h2 className="text-4xl font-extrabold tracking-tight bg-gradient-to-r from-foreground to-foreground/50 bg-clip-text text-transparent">
                        邮箱池
                    </h2>
                    <p className="text-muted-foreground mt-1 text-lg">
                        管理 Outlook 与通用 API 取码邮箱
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={fetchData} disabled={loading}>
                        <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                        刷新
                    </Button>
                    <Button size="sm" onClick={() => setShowImport(true)}>
                        <Plus className="mr-2 h-4 w-4" />
                        批量导入
                    </Button>
                </div>
            </div>

            {/* Stats */}
            <div className="grid gap-4 md:grid-cols-3">
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">总邮箱数</CardTitle>
                        <Mail className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold">{total}</div>
                    </CardContent>
                </Card>
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">可用邮箱</CardTitle>
                        <ToggleRight className="h-4 w-4 text-green-500" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold text-green-500">{available}</div>
                    </CardContent>
                </Card>
                <Card>
                    <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                        <CardTitle className="text-sm font-medium">已用/禁用</CardTitle>
                        <ToggleLeft className="h-4 w-4 text-muted-foreground" />
                    </CardHeader>
                    <CardContent>
                        <div className="text-2xl font-bold text-muted-foreground">{disabled}</div>
                    </CardContent>
                </Card>
            </div>

            {/* Mailbox Table */}
            <Card>
                <CardContent className="p-0">
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-border text-muted-foreground">
                                    <th className="text-left p-4 font-medium">邮箱地址</th>
                                    <th className="text-left p-4 font-medium">类型</th>
                                    <th className="text-left p-4 font-medium">状态</th>
                                    <th className="text-left p-4 font-medium">使用次数</th>
                                    <th className="text-left p-4 font-medium">最近使用</th>
                                    <th className="text-left p-4 font-medium">备注</th>
                                    <th className="text-right p-4 font-medium">操作</th>
                                </tr>
                            </thead>
                            <tbody>
                                {loading ? (
                                    <tr>
                                        <td colSpan={7} className="text-center py-12 text-muted-foreground">
                                            加载中...
                                        </td>
                                    </tr>
                                ) : mailboxes.length === 0 ? (
                                    <tr>
                                        <td colSpan={7} className="text-center py-12 text-muted-foreground">
                                            <Mail className="h-10 w-10 mx-auto mb-3 opacity-20" />
                                            <p>暂无邮箱，点击「批量导入」添加</p>
                                        </td>
                                    </tr>
                                ) : (
                                    mailboxes.map(mailbox => (
                                        <tr
                                            key={mailbox.id}
                                            className="border-b border-border hover:bg-muted/40 transition-colors"
                                        >
                                            <td className="p-4 font-mono text-sm">{mailbox.email}</td>
                                            <td className="p-4">
                                                <Badge variant="outline">
                                                    {mailbox.provider_type === 'generic_api' ? '通用 API' : 'Outlook'}
                                                </Badge>
                                            </td>
                                            <td className="p-4">
                                                <Badge
                                                    variant={mailbox.is_enabled ? "default" : "secondary"}
                                                    className={mailbox.is_enabled
                                                        ? "bg-green-500/10 text-green-400 border-green-500/20"
                                                        : "bg-muted/50 text-muted-foreground"
                                                    }
                                                >
                                                    {mailbox.is_enabled ? '可用' : '已禁用'}
                                                </Badge>
                                            </td>
                                            <td className="p-4 text-muted-foreground">{mailbox.usage_count}</td>
                                            <td className="p-4 text-muted-foreground text-xs">
                                                {mailbox.last_used_at
                                                    ? new Date(mailbox.last_used_at).toLocaleString('zh-CN')
                                                    : '—'
                                                }
                                            </td>
                                            <td className="p-4 text-muted-foreground text-xs">{mailbox.note || '—'}</td>
                                            <td className="p-4 text-right">
                                                <div className="flex items-center justify-end gap-1">
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        className="h-8 px-2 text-muted-foreground hover:text-foreground"
                                                        onClick={() => handleToggle(mailbox)}
                                                    >
                                                        {mailbox.is_enabled ? (
                                                            <ToggleRight className="h-4 w-4 text-green-500" />
                                                        ) : (
                                                            <ToggleLeft className="h-4 w-4" />
                                                        )}
                                                    </Button>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        className="h-8 px-2 text-muted-foreground hover:text-destructive"
                                                        onClick={() => handleDelete(mailbox)}
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                    </Button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </CardContent>
            </Card>

            {/* Import Dialog */}
            <Dialog open={showImport} onOpenChange={setShowImport}>
                <DialogContent className="sm:max-w-[480px] bg-popover text-popover-foreground border-border rounded-2xl">
                    <DialogHeader>
                        <DialogTitle>批量导入邮箱</DialogTitle>
                        <DialogDescription className="text-muted-foreground text-xs">
                            选择取码策略后按对应格式逐行导入
                        </DialogDescription>
                    </DialogHeader>
                    <div className="py-2">
                        <div className="mb-3 space-y-2">
                            <label className="text-sm font-medium">导入类型</label>
                            <Select value={providerType} onValueChange={(value) => {
                                setProviderType(value as 'outlook' | 'generic_api')
                                setImportText('')
                                setImportResult('')
                            }}>
                                <SelectTrigger className="bg-background border-input">
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent className="bg-popover text-popover-foreground border-border">
                                    <SelectItem value="outlook">Outlook 邮箱池</SelectItem>
                                    <SelectItem value="generic_api">通用 API 取码邮箱</SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                        <Textarea
                            value={importText}
                            onChange={e => setImportText(e.target.value)}
                            placeholder={providerType === 'outlook'
                                ? "example1@outlook.com\nexample2@hotmail.com"
                                : "邮箱----取码地址\nuser@example.com----https://mail.example.com/code?token=TOKEN"}
                            className="min-h-[200px] font-mono text-sm bg-background text-foreground border-input resize-none"
                        />
                        <p className="text-xs text-muted-foreground mt-2">
                            已识别 {importText.split('\n').filter(e => e.trim()).length} 行
                        </p>
                        {importResult && <p role="status" className="mt-2 text-xs text-emerald-600">{importResult}</p>}
                    </div>
                    <DialogFooter className="gap-3">
                        <Button
                            variant="ghost"
                            className="flex-1 rounded-xl"
                            onClick={() => setShowImport(false)}
                        >
                            取消
                        </Button>
                        <Button
                            className="flex-1 rounded-xl"
                            onClick={handleImport}
                            disabled={importing || importText.split('\n').filter(e => e.trim()).length === 0}
                        >
                            {importing ? '导入中...' : '确认导入'}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    )
}
