import { useEffect, useState, useMemo } from 'react'
import {
    RefreshCw,
    Zap,
    Signal,
    SignalHigh,
    SignalMedium,
    SignalLow,
    ArrowUpDown,
    Loader2,
    Plus
} from 'lucide-react'
import { toast } from 'sonner'
import { proxiesApi, ProxyNode } from '../services/api'
import { cn } from "@/lib/utils"
import { useLanguage } from '@/contexts/LanguageContext'
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"

// Module-level caches to prevent UI clear flickering during navigations
let cachedProxies: ProxyNode[] = []
let cachedPoolStatus = { total: 0, active: 0, idle: 0 }

// 动态国家名称映射（用于筛选器显示，按需扩展）
const getRegionDisplay = (code: string): { flag: string; label: string } => ({
    flag: `https://flagcdn.com/w40/${code.toLowerCase()}.png`,
    label: code,
})


export default function Proxies() {
    const [nodes, setNodes] = useState<ProxyNode[]>(cachedProxies)
    const [poolStatus, setPoolStatus] = useState(cachedPoolStatus)
    const [testing, setTesting] = useState(false)
    const [restarting, setRestarting] = useState(false)
    const [importOpen, setImportOpen] = useState(false)
    const [importText, setImportText] = useState('')
    const [importing, setImporting] = useState(false)
    const [nodeOperations, setNodeOperations] = useState<Record<number, 'testing' | 'toggling'>>({})
    const { t } = useLanguage()

    const [filters, setFilters] = useState({ type: 'all', region: 'all', enabled: 'all' })
    const [bulkMode, setBulkMode] = useState(false)
    const [selectedIds, setSelectedIds] = useState<Record<number, boolean>>({})
    const [bulkApplying, setBulkApplying] = useState(false)
    const [sortBy, setSortBy] = useState<'usage' | 'latency' | 'name'>('name')
    const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
    const [page, setPage] = useState(1)
    const [pages, setPages] = useState(1)
    const [total, setTotal] = useState(0)
    const [nodeTypes, setNodeTypes] = useState<string[]>([])
    const [regionOptions, setRegionOptions] = useState<string[]>([])
    const pageSize = 100

    useEffect(() => {
        fetchData()
    }, [page, filters, sortBy, sortDir])

    const fetchData = async () => {
        try {
            const [proxiesData, poolData, facets] = await Promise.all([
                proxiesApi.list({
                    page,
                    page_size: pageSize,
                    node_type: filters.type,
                    region: filters.region,
                    enabled: filters.enabled,
                    sort_by: sortBy,
                    sort_dir: sortDir,
                }),
                proxiesApi.getPoolStatus(),
                proxiesApi.facets(),
            ])
            cachedProxies = proxiesData.items
            cachedPoolStatus = poolData
            setNodes(proxiesData.items)
            setTotal(proxiesData.total)
            setPages(proxiesData.pages)
            setPoolStatus(poolData)
            setNodeTypes(facets.types)
            setRegionOptions(facets.regions)
        } catch (error) {
            console.error('Failed to fetch data:', error)
        }
    }

    const handleTestAll = async () => {
        setTesting(true)
        try {
            await proxiesApi.testLatency()
            toast.success('延迟测试完成')
            await fetchData()
        } catch (error: any) {
            toast.error(error.message || '延迟测试失败')
        } finally {
            setTesting(false)
        }
    }

    const handleImport = async () => {
        if (!importText.trim()) return
        setImporting(true)
        try {
            const result = await proxiesApi.import(importText)
            const failed = result.errors.length ? `，失败 ${result.errors.length} 条` : ''
            toast.success(`已导入 ${result.inserted} 个，重复 ${result.duplicates} 个${failed}`)
            setImportText('')
            setImportOpen(false)
            await fetchData()
        } catch (error: any) {
            toast.error(error.message || '导入失败')
        } finally {
            setImporting(false)
        }
    }

    const handleToggle = async (id: number) => {
        setNodeOperations(prev => ({ ...prev, [id]: 'toggling' }))
        try {
            await proxiesApi.toggle(id)
            toast.success('节点状态已更新')
            await fetchData()
        } catch (error: any) {
            toast.error(error.message || '更新失败')
        } finally {
            setNodeOperations(prev => {
                const next = { ...prev }
                delete next[id]
                return next
            })
        }
    }

    const selectedCount = useMemo(
        () => Object.values(selectedIds).filter(Boolean).length,
        [selectedIds]
    )

    const toggleSelection = (id: number) => {
        setSelectedIds(prev => ({ ...prev, [id]: !prev[id] }))
    }

    const clearSelection = () => {
        setSelectedIds({})
    }

    const handleSelectAllVisible = () => {
        const next: Record<number, boolean> = {}
        filteredNodes.forEach(n => {
            if (filters.enabled === 'all' || n.is_enabled === (filters.enabled === 'true')) {
                next[n.id] = true
            }
        })
        setSelectedIds(next)
    }

    const handleBulkToggle = async (isEnabled: boolean) => {
        const ids = Object.keys(selectedIds)
            .filter(id => selectedIds[Number(id)])
            .map(id => Number(id))
        if (ids.length === 0) {
            toast.error('请至少选择一个节点')
            return
        }
        setBulkApplying(true)
        try {
            await proxiesApi.batchToggle(ids, isEnabled)
            toast.success(`已更新 ${ids.length} 个节点`)
            await fetchData()
            clearSelection()
        } catch (error: any) {
            toast.error(error.message || '批量操作失败')
        } finally {
            setBulkApplying(false)
        }
    }

    const handleRestartPool = async () => {
        if (!confirm('确定要重启代理池吗？')) return
        setRestarting(true)
        try {
            await proxiesApi.reloadPool()
            toast.success('代理池已重启')
            await fetchData()
        } catch (error: any) {
            toast.error(error.message || '重启代理池失败')
        } finally {
            setRestarting(false)
        }
    }

    const handleTestNode = async (id: number) => {
        setNodeOperations(prev => ({ ...prev, [id]: 'testing' }))
        try {
            await proxiesApi.testNodeLatency(id)
            toast.success('节点测速完成')
            await fetchData()
        } catch (error: any) {
            toast.error(error.message || '测速失败')
        } finally {
            setNodeOperations(prev => {
                const next = { ...prev }
                delete next[id]
                return next
            })
        }
    }

    const toggleSort = (field: 'usage' | 'latency' | 'name') => {
        setPage(1)
        if (sortBy === field) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
        } else {
            setSortBy(field); setSortDir('asc')
        }
    }

    const filteredNodes = nodes

    const getLatencyIcon = (latency: number | null) => {
        if (latency === null) return <Signal className="h-4 w-4 text-muted-foreground" />
        if (latency < 200) return <SignalHigh className="h-4 w-4 text-green-500" />
        if (latency < 500) return <SignalMedium className="h-4 w-4 text-yellow-500" />
        return <SignalLow className="h-4 w-4 text-red-500" />
    }

    return (
        <div className="flex-1 space-y-8 animate-in fade-in duration-500">
            <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div className="space-y-1">
                    <h1 className="text-2xl font-bold tracking-tight">{t('proxies.title')}</h1>
                    <p className="text-muted-foreground text-sm">
                        {t('proxies.subtitle')}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" onClick={() => setImportOpen(true)}>
                        <Plus className="mr-2 h-4 w-4" />
                        批量导入
                    </Button>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={handleRestartPool}
                        disabled={restarting}
                    >
                        <RefreshCw className={cn("mr-2 h-4 w-4", restarting && "animate-spin")} />
                        {t('proxies.restart_pool')}
                    </Button>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={handleTestAll}
                        disabled={testing}
                    >
                        <Zap className={cn("mr-2 h-4 w-4", testing && "animate-ping")} />
                        {t('proxies.test')}
                    </Button>
                </div>
            </div>

            <Dialog open={importOpen} onOpenChange={setImportOpen}>
                <DialogContent className="sm:max-w-[620px]">
                    <DialogHeader>
                        <DialogTitle>批量导入代理池</DialogTitle>
                        <DialogDescription>
                            每行一个代理。导入后自动检测可用性、出口 IP 和国家地区。
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4 py-2">
                        <div className="space-y-2">
                            <Label htmlFor="proxy-import">代理列表</Label>
                            <Textarea
                                id="proxy-import"
                                value={importText}
                                onChange={(event) => setImportText(event.target.value)}
                                className="min-h-[220px] font-mono text-sm"
                                placeholder={'HOST:PORT\nHOST:PORT:USER:PASS\nhttp://HOST:PORT\nsocks5://USER:PASS@HOST:PORT'}
                            />
                            <p className="text-xs text-muted-foreground">
                                支持 HTTP、HTTPS、SOCKS5；导入后自动识别出口国家或地区，账号密码不在列表中明文展示。
                            </p>
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setImportOpen(false)} disabled={importing}>取消</Button>
                        <Button onClick={handleImport} disabled={importing || !importText.trim()}>
                            {importing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                            确认导入
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <div className="grid grid-cols-1 gap-6">
                <Card className="bg-card/30 border-border/50 overflow-hidden group hover:border-primary/20 transition-all">
                    <CardHeader className="pb-2">
                        <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground/50 flex items-center gap-2">
                            <Signal className="h-4 w-4 text-amber-500" />
                            {t('proxies.pool_status')}
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <div className="flex items-end gap-2">
                            <div className="text-2xl font-bold">{poolStatus.total}</div>
                            <div className="text-xs text-muted-foreground mb-1">
                                活跃: {poolStatus.active} | 空闲: {poolStatus.idle}
                            </div>
                        </div>
                    </CardContent>
                </Card>
            </div>

            <div className="flex flex-col md:flex-row gap-4">
                <div className="w-full md:w-[200px]">
                    <Select value={filters.type} onValueChange={(v) => { setPage(1); setFilters({ ...filters, type: v }) }}>
                        <SelectTrigger>
                            <SelectValue placeholder={t('proxies.filter.protocol')} />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">{t('proxies.filter.all')}</SelectItem>
                            {nodeTypes.map(type => (
                                <SelectItem key={type} value={type}>{type}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
                <div className="w-full md:w-[200px]">
                    <Select value={filters.region} onValueChange={(v) => { setPage(1); setFilters({ ...filters, region: v }) }}>
                        <SelectTrigger>
                            <SelectValue placeholder={t('proxies.filter.region')} />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">{t('proxies.filter.all_regions')}</SelectItem>
                            {regionOptions.map(code => {
                                const { flag, label } = getRegionDisplay(code)
                                return (
                                    <SelectItem key={code} value={code}>
                                        <div className="flex items-center gap-2">
                                            <img src={flag} className="w-4 h-3 object-contain" alt={code} />
                                            <span>{label}</span>
                                        </div>
                                    </SelectItem>
                                )
                            })}
                        </SelectContent>
                    </Select>
                </div>
                <div className="w-full md:w-[200px]">
                    <Select value={filters.enabled} onValueChange={(v) => { setPage(1); setFilters({ ...filters, enabled: v }) }}>
                        <SelectTrigger>
                            <SelectValue placeholder={t('proxies.filter.status')} />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="all">{t('proxies.filter.all_status')}</SelectItem>
                            <SelectItem value="true">{t('proxies.filter.active')}</SelectItem>
                            <SelectItem value="false">{t('proxies.filter.disabled')}</SelectItem>
                        </SelectContent>
                    </Select>
                </div>
            </div>

            <div className="flex flex-col md:flex-row md:items-center gap-3">
                <div className="flex items-center gap-3">
                    <Switch checked={bulkMode} onCheckedChange={setBulkMode} />
                    <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">批量模式</span>
                </div>
                {bulkMode && (
                    <div className="flex flex-wrap items-center gap-2">
                        <Button variant="outline" size="sm" onClick={handleSelectAllVisible}>
                            选择全部可见
                        </Button>
                        <Button variant="outline" size="sm" onClick={clearSelection}>
                            取消选择
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleBulkToggle(true)}
                            disabled={bulkApplying}
                        >
                            批量启用（{selectedCount}）
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleBulkToggle(false)}
                            disabled={bulkApplying}
                        >
                            批量禁用（{selectedCount}）
                        </Button>
                    </div>
                )}
            </div>

            <div className="rounded-md border bg-card">
                <Table>
                    <TableHeader className="bg-muted/50">
                        <TableRow className="hover:bg-transparent border-border/50">
                            {bulkMode && (
                                <TableHead className="w-[40px] text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50 text-center">Sel</TableHead>
                            )}
                            <TableHead className="w-[40px] text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50 text-center">{t('proxies.table.health')}</TableHead>
                            <TableHead className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50 cursor-pointer" onClick={() => toggleSort('name')}>
                                {t('proxies.table.node')} <ArrowUpDown className="ml-2 h-4 w-4 inline-block" />
                            </TableHead>
                            <TableHead className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50 text-center">{t('proxies.table.protocol')}</TableHead>
                            <TableHead className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50">{t('proxies.table.geo')}</TableHead>
                            <TableHead className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50 cursor-pointer" onClick={() => toggleSort('latency')}>
                                {t('proxies.table.latency')} <ArrowUpDown className="ml-2 h-4 w-4 inline-block" />
                            </TableHead>
                            <TableHead className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50 cursor-pointer text-center" onClick={() => toggleSort('usage')}>
                                {t('proxies.table.usage')} <ArrowUpDown className="ml-2 h-4 w-4 inline-block" />
                            </TableHead>
                            <TableHead className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50">{t('proxies.table.status')}</TableHead>
                            <TableHead className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/50 text-right">{t('common.actions')}</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {filteredNodes.length === 0 ? (
                            <TableRow>
                                <TableCell colSpan={8} className="h-24 text-center">
                                    没有找到匹配的节点
                                </TableCell>
                            </TableRow>
                        ) : (
                            filteredNodes.map(node => {
                                return (
                                    <TableRow key={node.id}>
                                        {bulkMode && (
                                            <TableCell className="text-center">
                                                <input
                                                    type="checkbox"
                                                    checked={!!selectedIds[node.id]}
                                                    onChange={() => toggleSelection(node.id)}
                                                />
                                            </TableCell>
                                        )}
                                        <TableCell className="text-center">
                                            <div className="flex items-center justify-center">
                                                <div className={`w-3 h-3 rounded-full ${node.is_healthy === true ? 'bg-green-500' :
                                                    node.is_healthy === false ? 'bg-red-500' : 'bg-gray-400'
                                                    }`} />
                                            </div>
                                        </TableCell>
                                        <TableCell className="font-medium">
                                            <div className="flex flex-col">
                                                <div className="flex items-center gap-2">
                                                    <span>{node.name}</span>
                                                    {node.source === 'external' && (
                                                        <Badge variant="outline" className="text-[10px] h-4 px-1 bg-blue-500/10 text-blue-500 border-blue-500/20">
                                                            External
                                                        </Badge>
                                                    )}
                                                </div>
                                                <span className="text-[10px] text-muted-foreground font-mono">ID: {node.id}</span>
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-center">
                                            <Badge variant="secondary">{node.node_type}</Badge>
                                        </TableCell>
                                        <TableCell>
                                            {node.region_tag && node.region_tag !== 'UN' ? (
                                                <div className="flex items-center gap-2">
                                                    <img
                                                        src={`https://flagcdn.com/w40/${node.region_tag.toLowerCase()}.png`}
                                                        className="w-5 h-4 object-contain rounded-sm"
                                                        alt={node.region_tag}
                                                        onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                                                    />
                                                    <span className="text-xs font-mono font-semibold">{node.region_tag}</span>
                                                </div>
                                            ) : '--'}
                                        </TableCell>
                                        <TableCell>
                                            <div className="flex items-center gap-2">
                                                {nodeOperations[node.id] === 'testing' ? (
                                                    <>
                                                        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                                                        <span className="text-muted-foreground italic">测速中...</span>
                                                    </>
                                                ) : (
                                                    <>
                                                        {getLatencyIcon(node.latency ?? null)}
                                                        <span>{node.latency ? `${node.latency}ms` : 'N/A'}</span>
                                                    </>
                                                )}
                                            </div>
                                        </TableCell>
                                        <TableCell className="text-center">
                                            <span className="font-mono text-xs">{node.usage_count || 0}</span>
                                        </TableCell>
                                        <TableCell>
                                            {nodeOperations[node.id] === 'toggling' ? (
                                                <div className="flex items-center gap-1.5 opacity-70">
                                                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                                                </div>
                                            ) : (
                                                <Switch
                                                    checked={node.is_enabled}
                                                    onCheckedChange={() => handleToggle(node.id)}
                                                    className="scale-110"
                                                />
                                            )}
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <div className="flex items-center justify-end gap-2">
                                                <Button
                                                    variant="ghost"
                                                    size="icon"
                                                    className="h-8 w-8 hover:bg-blue-500/10 hover:text-blue-500"
                                                    onClick={() => handleTestNode(node.id)}
                                                    disabled={nodeOperations[node.id] === 'testing' || testing}
                                                >
                                                    {nodeOperations[node.id] === 'testing' ? (
                                                        <Loader2 className="h-4 w-4 animate-spin" />
                                                    ) : (
                                                        <Zap className="h-4 w-4" />
                                                    )}
                                                </Button>
                                            </div>
                                        </TableCell>
                                    </TableRow >
                                )
                            })
                        )}
                    </TableBody >
                </Table >
            </div >
            <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>共 {total} 条 · 第 {page}/{pages} 页 · 每页 {pageSize} 条</span>
                <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(value => value - 1)}>
                        上一页
                    </Button>
                    <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(value => value + 1)}>
                        下一页
                    </Button>
                </div>
            </div>
        </div >
    )
}
