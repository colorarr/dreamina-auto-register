
import { useEffect, useState } from 'react'
import { CheckCircle2 } from 'lucide-react'
import { tasksApi, proxiesApi, Domain, CreateTaskData } from '../../services/api'
import { useLanguage } from '../../contexts/LanguageContext'
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select"
import { ScrollArea } from "@/components/ui/scroll-area"

interface CreateTaskModalProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    domains: Domain[]
    onSuccess: () => void
}

export function CreateTaskModal({ open, onOpenChange, domains, onSuccess }: CreateTaskModalProps) {
    const { t } = useLanguage()
    const [formData, setFormData] = useState<CreateTaskData>({
        total_count: 1,
        domain_mode: 'manual',
        domain_ids: [],
        proxy_strategy: 'round_robin',
        proxy_region: '',
        email_prefix_pattern: 'reg_{random6}',
        max_retries: 3,
        concurrency: 1,
        email_source: 'cloudflare'
    })
    const [proxyRegions, setProxyRegions] = useState<string[]>([])
    const [regionsLoading, setRegionsLoading] = useState(false)

    useEffect(() => {
        if (!open) return
        setRegionsLoading(true)
        proxiesApi.regions()
            .then(({ regions }) => {
                setProxyRegions(regions)
                setFormData(current => ({
                    ...current,
                    proxy_region: regions.includes(current.proxy_region) ? current.proxy_region : (regions[0] || ''),
                }))
            })
            .catch(() => setProxyRegions([]))
            .finally(() => setRegionsLoading(false))
    }, [open])

    const handleCreate = async () => {
        // Worker 模式不强制要求选择域名（Worker 会自动创建邮箱）
        try {
            await tasksApi.create(formData)
            onOpenChange(false)
            onSuccess()
        } catch (error: any) {
            console.error('Failed to create task:', error)
            const detail = error?.response?.data?.detail || error?.message || '未知错误'
            alert(`创建任务失败: ${detail}`)
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[480px] h-[min(760px,90vh)] flex flex-col bg-card text-card-foreground border-border shadow-2xl rounded-2xl p-0 overflow-hidden gap-0">
                <DialogHeader className="p-6 pb-2 shrink-0">
                    <DialogTitle className="text-xl font-bold tracking-tight">新建任务</DialogTitle>
                    <DialogDescription className="text-muted-foreground/50 text-xs">
                        配置注册自动化参数，开始批量任务
                    </DialogDescription>
                </DialogHeader>
                <div className="px-6 py-4 space-y-5 min-h-0 flex-1 overflow-y-auto">
                    <div className="space-y-2">
                        <label className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 ml-0.5">
                            {t('tasks.modal.nodes')}
                        </label>
                        <Input
                            id="total_count"
                            type="number"
                            className="h-11 bg-white/[0.03] border-white/5 focus-visible:ring-primary focus-visible:border-primary/50 transition-all rounded-xl"
                            value={formData.total_count}
                            onChange={e => setFormData({ ...formData, total_count: Number(e.target.value) })}
                            min={1} max={500}
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 ml-0.5">
                            国家或地区
                        </label>
                        <Select
                            value={formData.proxy_region}
                            onValueChange={(value) => setFormData({ ...formData, proxy_region: value })}
                            disabled={regionsLoading || proxyRegions.length === 0}
                        >
                            <SelectTrigger className="h-11 bg-white/[0.03] border-white/5 focus:ring-primary focus:border-primary/50 transition-all rounded-xl">
                                <SelectValue placeholder={regionsLoading ? '正在读取代理池地区…' : '代理池暂无可用地区'} />
                            </SelectTrigger>
                            <SelectContent className="bg-card border-white/10 rounded-xl overflow-hidden shadow-2xl">
                                {proxyRegions.map(region => (
                                    <SelectItem key={region} value={region} className="py-3">{region}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <p className="text-xs text-muted-foreground/60">仅显示代理池中已启用且检测可用的国家或地区</p>
                    </div>

                    <div className="space-y-2">
                        <label className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 ml-0.5">
                            {t('tasks.modal.strategy')}
                        </label>
                        <Select
                            value={formData.proxy_strategy}
                            onValueChange={(val) => setFormData({ ...formData, proxy_strategy: val as any })}
                        >
                            <SelectTrigger className="h-11 bg-white/[0.03] border-white/5 focus:ring-primary focus:border-primary/50 transition-all rounded-xl">
                                <SelectValue placeholder="Select strategy" />
                            </SelectTrigger>
                            <SelectContent className="bg-card border-white/10 rounded-xl overflow-hidden shadow-2xl">
                                <SelectItem value="round_robin" className="focus:bg-primary/10 hover:bg-primary/10 py-3">轮询 (Round Robin)</SelectItem>
                                <SelectItem value="random" className="focus:bg-primary/10 hover:bg-primary/10 py-3">随机 (Stochastic)</SelectItem>
                                <SelectItem value="least_used" className="focus:bg-primary/10 hover:bg-primary/10 py-3">最优路径 (Optimal Path)</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="space-y-2">
                        <label className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 ml-0.5">
                            并发数（最高 50）
                        </label>
                        <Input
                            id="concurrency"
                            type="number"
                            className="h-11 bg-white/[0.03] border-white/5 focus-visible:ring-primary focus-visible:border-primary/50 transition-all rounded-xl"
                            value={formData.concurrency}
                            onChange={e => setFormData({
                                ...formData,
                                concurrency: Math.min(50, Math.max(1, Number(e.target.value) || 1))
                            })}
                            min={1}
                            max={50}
                        />
                        <p className="text-xs text-muted-foreground/60">
                            实际并发不超过任务数；独立 IP 不足时整个批次立即停止
                        </p>
                    </div>

                    <div className="space-y-2">
                        <label className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 ml-0.5">
                            最大重试次数
                        </label>
                        <Input
                            id="max_retries"
                            type="number"
                            className="h-11 bg-white/[0.03] border-white/5 focus-visible:ring-primary focus-visible:border-primary/50 transition-all rounded-xl"
                            value={formData.max_retries}
                            onChange={e => setFormData({ ...formData, max_retries: Number(e.target.value) })}
                            min={0} max={10}
                        />
                    </div>

                    <div className="space-y-2">
                        <label className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 ml-0.5">
                            邮箱来源
                        </label>
                        <div className="grid grid-cols-3 gap-2">
                            <Button
                                type="button"
                                variant={formData.email_source === 'cloudflare' ? 'default' : 'outline'}
                                className="h-11 rounded-xl"
                                onClick={() => setFormData({ ...formData, email_source: 'cloudflare' })}
                            >
                                Cloudflare 域名
                            </Button>
                            <Button
                                type="button"
                                variant={formData.email_source === 'outlook' ? 'default' : 'outline'}
                                className="h-11 rounded-xl"
                                onClick={() => setFormData({ ...formData, email_source: 'outlook' })}
                            >
                                Outlook 邮箱池
                            </Button>
                            <Button
                                type="button"
                                variant={formData.email_source === 'generic_api' ? 'default' : 'outline'}
                                className="h-11 rounded-xl"
                                onClick={() => setFormData({ ...formData, email_source: 'generic_api' })}
                            >
                                通用 API
                            </Button>
                        </div>
                    </div>

                    {formData.email_source === 'cloudflare' ? (
                        <>
                            <div className="space-y-2">
                                <label className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground/60 ml-0.5">
                                    {t('tasks.modal.realms')}
                                </label>
                                <div className="rounded-xl border border-white/5 bg-white/[0.02] p-3">
                                    <ScrollArea className="h-[120px] w-full">
                                        <div className="space-y-1.5 pr-4">
                                            {domains.map(domain => (
                                                <div key={domain.id} className="group relative flex items-center space-x-3 p-2 rounded-lg hover:bg-white/[0.02] transition-all cursor-pointer"
                                                    onClick={() => {
                                                        const currentIds = formData.domain_ids || [];
                                                        const newIds = currentIds.includes(domain.id)
                                                            ? currentIds.filter(id => id !== domain.id)
                                                            : [...currentIds, domain.id];
                                                        setFormData({ ...formData, domain_ids: newIds });
                                                    }}
                                                >
                                                    <div className={cn(
                                                        "flex h-4 w-4 items-center justify-center rounded border transition-all",
                                                        (formData.domain_ids || []).includes(domain.id)
                                                            ? "bg-primary border-primary"
                                                            : "bg-white/5 border-white/10 group-hover:border-white/20"
                                                    )}>
                                                        {(formData.domain_ids || []).includes(domain.id) && <CheckCircle2 className="h-3 w-3 text-background" />}
                                                    </div>
                                                    <label className="text-sm font-medium leading-none cursor-pointer flex-1">
                                                        {domain.domain}
                                                    </label>
                                                    <Badge variant="outline" className="text-[9px] opacity-20 group-hover:opacity-40 transition-opacity">
                                                        可用
                                                    </Badge>
                                                </div>
                                            ))}
                                        </div>
                                    </ScrollArea>
                                </div>
                            </div>


                        </>
                    ) : (
                        <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 text-center">
                            <p className="text-sm text-muted-foreground">
                                将自动从{formData.email_source === 'generic_api' ? '通用 API' : ' Outlook'}邮箱池分配邮箱并使用对应策略取码。
                            </p>
                            <p className="text-xs text-muted-foreground opacity-70 mt-1">请确保对应类型的邮箱库存充足</p>
                        </div>
                    )}
                </div>
                <DialogFooter className="p-6 bg-muted/30 border-t border-border flex gap-3 shrink-0">
                    <Button
                        variant="ghost"
                        className="flex-1 h-11 rounded-xl text-muted-foreground hover:bg-white/5 hover:text-foreground"
                        onClick={() => onOpenChange(false)}
                    >
                        {t('common.abort')}
                    </Button>
                    <Button
                        className="flex-1 h-11 rounded-xl bg-foreground text-background font-bold hover:bg-foreground/90 transition-all shadow-lg shadow-black/20"
                        onClick={handleCreate}
                        disabled={!formData.proxy_region || regionsLoading}
                    >
                        {t('common.execute')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
