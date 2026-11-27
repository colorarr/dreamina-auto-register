import { useEffect, useState } from 'react'
import {
    Loader2,
    Languages,
    Lock,
    Zap,
    Cpu,
    Cloud
} from 'lucide-react'
import { settingsApi, Settings } from '../services/api'
import { useLanguage } from '../contexts/LanguageContext'
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"


export default function SettingsPage() {
    const [settings, setSettings] = useState<Settings | null>(null)
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const { language, setLanguage, t } = useLanguage()

    const [secrets, setSecrets] = useState({
        clash_secret: '',
        cf_api_token: ''
    })

    useEffect(() => {
        fetchSettings()
    }, [])

    const fetchSettings = async () => {
        try {
            const data = await settingsApi.get()
            setSettings(data)
            setSecrets({
                clash_secret: data.clash_secret || '',
                cf_api_token: data.cf_api_token || ''
            })
        } catch (error) {
            console.error('Failed to fetch settings:', error)
        } finally {
            setLoading(false)
        }
    }

    const handleSave = async () => {
        if (!settings) return
        setSaving(true)
        try {
            await settingsApi.update({
                ...settings,
                ...secrets
            })
        } catch (error) {
            console.error('Save failed:', error)
        } finally {
            setSaving(false)
        }
    }

    if (loading || !settings) {
        return (
            <div className="flex h-[50vh] items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-3xl font-bold tracking-tight">{t('settings.title')}</h2>
                    <p className="text-muted-foreground">{t('settings.subtitle')}</p>
                </div>
                <Button onClick={handleSave} disabled={saving}>
                    {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    {t('settings.commit')}
                </Button>
            </div>

            <Tabs defaultValue="general" className="space-y-4">
                <TabsList>
                    <TabsTrigger value="general">{t('settings.tabs.general')}</TabsTrigger>
                    <TabsTrigger value="engine">{t('settings.tabs.engine')}</TabsTrigger>
                    <TabsTrigger value="proxy">{t('settings.tabs.proxy')}</TabsTrigger>
                    <TabsTrigger value="cloud">{t('settings.tabs.cloud')}</TabsTrigger>
                </TabsList>

                <TabsContent value="general" className="space-y-4">
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Languages className="h-5 w-5" />
                                {t('settings.language')}
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="grid gap-6">
                            <div className="grid grid-cols-2 gap-4">
                                <Button
                                    variant={language === 'en' ? 'default' : 'outline'}
                                    className="h-24 flex flex-col gap-2"
                                    onClick={() => setLanguage('en')}
                                >
                                    <span className="text-2xl">🇺🇸</span>
                                    <span>{t('settings.lang.en')}</span>
                                </Button>
                                <Button
                                    variant={language === 'zh' ? 'default' : 'outline'}
                                    className="h-24 flex flex-col gap-2"
                                    onClick={() => setLanguage('zh')}
                                >
                                    <span className="text-2xl">🇨🇳</span>
                                    <span>{t('settings.lang.zh')}</span>
                                </Button>
                            </div>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Lock className="h-5 w-5" />
                                {t('settings.account_gen')}
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="grid gap-2">
                                <Label>{t('settings.pwd_len')}</Label>
                                <Input
                                    type="number"
                                    value={settings.password_length}
                                    onChange={e => setSettings({ ...settings, password_length: Number(e.target.value) })}
                                />
                            </div>
                            <div className="flex items-center justify-between rounded-lg border p-4">
                                <div className="space-y-0.5">
                                    <Label className="text-base">{t('settings.include_special')}</Label>
                                    <p className="text-sm text-muted-foreground">
                                        {t('settings.include_special_desc')}
                                    </p>
                                </div>
                                <Switch
                                    checked={settings.password_include_special}
                                    onCheckedChange={(checked) => setSettings({ ...settings, password_include_special: checked })}
                                />
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="engine" className="space-y-4">
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Zap className="h-5 w-5" />
                                {t('settings.engine')}
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="grid gap-4 md:grid-cols-2">
                            <div className="space-y-2">
                                <Label>{t('settings.rest_url')}</Label>
                                <Input
                                    value={settings.dreamina_url}
                                    onChange={e => setSettings({ ...settings, dreamina_url: e.target.value })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>{t('settings.proc_timeout')}</Label>
                                <Input
                                    type="number"
                                    value={settings.register_timeout}
                                    onChange={e => setSettings({ ...settings, register_timeout: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>{t('settings.chal_buffer')}</Label>
                                <Input
                                    type="number"
                                    value={settings.verification_timeout}
                                    onChange={e => setSettings({ ...settings, verification_timeout: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>{t('settings.fault_thresh')}</Label>
                                <Input
                                    type="number"
                                    value={settings.max_retry_count}
                                    onChange={e => setSettings({ ...settings, max_retry_count: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>{t('settings.reg_int_min')}</Label>
                                <Input
                                    type="number"
                                    value={settings.register_interval_min}
                                    onChange={e => setSettings({ ...settings, register_interval_min: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>{t('settings.reg_int_max')}</Label>
                                <Input
                                    type="number"
                                    value={settings.register_interval_max}
                                    onChange={e => setSettings({ ...settings, register_interval_max: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>{t('settings.max_conc')}</Label>
                                <Input
                                    type="number"
                                    min={1}
                                    max={50}
                                    value={settings.max_concurrency || 1}
                                    onChange={e => setSettings({ ...settings, max_concurrency: Math.min(50, Math.max(1, Number(e.target.value))) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>图片异步轮询间隔（秒）</Label>
                                <Input
                                    type="number"
                                    min={1}
                                    value={settings.gen_image_async_poll_interval}
                                    onChange={e => setSettings({ ...settings, gen_image_async_poll_interval: Math.max(1, Number(e.target.value)) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>视频异步轮询间隔（秒）</Label>
                                <Input
                                    type="number"
                                    min={1}
                                    value={settings.gen_video_async_poll_interval}
                                    onChange={e => setSettings({ ...settings, gen_video_async_poll_interval: Math.max(1, Number(e.target.value)) })}
                                />
                            </div>
                            <div className="flex items-center justify-between rounded-lg border p-4 md:col-span-2">
                                <div className="space-y-0.5">
                                    <Label className="text-base">异步生成</Label>
                                    <p className="text-sm text-muted-foreground">
                                        默认启用。关闭后会等待远端生成完成再返回结果。
                                    </p>
                                </div>
                                <Switch
                                    checked={settings.gen_async_enabled}
                                    onCheckedChange={(checked) => setSettings({ ...settings, gen_async_enabled: checked })}
                                />
                            </div>
                            <div className="flex items-center justify-between rounded-lg border border-destructive/30 bg-destructive/5 p-4 md:col-span-2">
                                <div className="space-y-0.5">
                                    <Label className="text-base text-destructive">🗑️ 用完即删模式</Label>
                                    <p className="text-sm text-muted-foreground">
                                        开启后，账号积分耗尽时将<strong>直接从数据库删除</strong>，而非停用。适合白嫖新号首次免费额度场景。
                                    </p>
                                </div>
                                <Switch
                                    checked={settings.gen_auto_delete_account ?? false}
                                    onCheckedChange={(checked) => setSettings({ ...settings, gen_auto_delete_account: checked })}
                                />
                            </div>
                            <div className="flex items-center justify-between rounded-lg border p-4 md:col-span-2">
                                <div className="space-y-0.5">
                                    <Label className="text-base">{t('settings.browser_headless')}</Label>
                                    <p className="text-sm text-muted-foreground">
                                        {t('settings.browser_headless_desc')}
                                    </p>
                                </div>
                                <Switch
                                    checked={settings.browser_headless}
                                    onCheckedChange={(checked) => setSettings({ ...settings, browser_headless: checked })}
                                />
                            </div>
                            <div className="flex items-center justify-between rounded-lg border p-4 md:col-span-2">
                                <div className="space-y-0.5">
                                    <Label className="text-base">拦截音视频</Label>
                                    <p className="text-sm text-muted-foreground">
                                        开启后浏览器将屏蔽所有音视频资源，可加速注册并节省流量
                                    </p>
                                </div>
                                <Switch
                                    checked={settings.browser_block_media ?? true}
                                    onCheckedChange={(checked) => setSettings({ ...settings, browser_block_media: checked })}
                                />
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="proxy" className="space-y-4">
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Cpu className="h-5 w-5" />
                                {t('settings.proxy_layer')}
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="space-y-2">
                                <Label>本地代理端口</Label>
                                <p className="text-sm text-muted-foreground">
                                    浏览器注册时通过此端口连接代理（如 Clash/V2Ray 的本地端口）
                                </p>
                                <Input
                                    type="number"
                                    placeholder="7890"
                                    value={settings.clash_proxy_port}
                                    onChange={e => setSettings({ ...settings, clash_proxy_port: Number(e.target.value) })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>代理组名称</Label>
                                <p className="text-sm text-muted-foreground">
                                    FlClash 中用于注册的代理组名称，系统将从此组中获取节点进行自动轮换
                                </p>
                                <Input
                                    placeholder="节点选择"
                                    value={settings.clash_proxy_group || ''}
                                    onChange={e => setSettings({ ...settings, clash_proxy_group: e.target.value })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>外部控制器地址</Label>
                                <p className="text-sm text-muted-foreground">
                                    FlClash 外部控制器的 API 地址（用于自动切换节点）
                                </p>
                                <Input
                                    placeholder="http://127.0.0.1:9090"
                                    value={settings.clash_controller_url || ''}
                                    onChange={e => setSettings({ ...settings, clash_controller_url: e.target.value })}
                                />
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>

                <TabsContent value="cloud" className="space-y-4">
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <Cloud className="h-5 w-5" />
                                邮箱 Worker 配置
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <p className="text-sm text-muted-foreground">
                                通过现有的 Cloudflare Email Worker 接收验证码，无需 Account ID 和 API Token。
                            </p>
                            <a
                                href="https://linux.do/t/topic/1666961"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
                            >
                                📖 不会搭建？点击查看详细搭建教程
                                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                            </a>
                            <div className="space-y-2">
                                <Label>Worker 域名</Label>
                                <Input
                                    placeholder="如 apimail.example.com"
                                    value={settings.cf_worker_domain || ''}
                                    onChange={e => setSettings({ ...settings, cf_worker_domain: e.target.value })}
                                />
                                <p className="text-xs text-muted-foreground">
                                    在教程页面 Ctrl+F 搜索「配置自定义域」，即你设置的后端域名，如 apimail.你的域名.com
                                </p>
                            </div>
                            <div className="space-y-2">
                                <Label>Admin 密码</Label>
                                <Input
                                    type="password"
                                    placeholder="Worker 的 x-admin-auth 密码"
                                    value={settings.cf_worker_admin_password || ''}
                                    onChange={e => setSettings({ ...settings, cf_worker_admin_password: e.target.value })}
                                />
                                <p className="text-xs text-muted-foreground">
                                    在教程页面 Ctrl+F 搜索「ADMIN_PASSWORDS」，即你配置的管理后台密码
                                </p>
                            </div>
                            <div className="space-y-2">
                                <Label>邮箱域名（逗号分隔）</Label>
                                <Input
                                    placeholder="如 example.com,example2.com"
                                    value={settings.cf_email_domains || ''}
                                    onChange={e => setSettings({ ...settings, cf_email_domains: e.target.value })}
                                />
                                <p className="text-xs text-muted-foreground">
                                    在教程页面 Ctrl+F 搜索「单个域名示例」，即你配置的临时邮箱域名
                                </p>
                            </div>
                        </CardContent>
                    </Card>
                </TabsContent>
            </Tabs>
        </div>
    )
}
