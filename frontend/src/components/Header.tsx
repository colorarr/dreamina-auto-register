import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { useLanguage } from "@/contexts/LanguageContext";
import { Button } from "@/components/ui/button";
import { useLocation } from "react-router-dom";
import { routes } from "@/config/routes";

export function Header() {
    const { pathname } = useLocation();
    const { language } = useLanguage();
    const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
    const label = language === "zh" ? "夜间模式" : "Night mode";
    const hint = dark
        ? (language === "zh" ? "切换到日间模式" : "Switch to day mode")
        : (language === "zh" ? "切换到夜间模式" : "Switch to night mode");

    const toggleTheme = () => {
        const nextDark = !dark;
        document.documentElement.classList.toggle("dark", nextDark);
        setDark(nextDark);
        try { localStorage.setItem("app_theme", nextDark ? "dark" : "light"); } catch {
            // The current page can still use the selected theme.
        }
    };

    const getPageTitle = () => {
        const route = routes.find(r => r.path === pathname);
        return route ? route.title : 'Jimeng Auto';
    };

    return (
        <header className="sticky top-0 z-50 w-full border-b border-border/10 bg-background/80 backdrop-blur-sm">
            <div className="flex h-16 items-center px-8">
                <h2 className="text-xl font-bold tracking-tight">{getPageTitle()}</h2>
                <div className="ml-auto flex items-center space-x-4">
                    <Button type="button" variant="ghost" size="icon"
                        aria-label={label} aria-pressed={dark} title={hint} onClick={toggleTheme}>
                        {dark ? <Moon aria-hidden="true" className="h-4 w-4" />
                              : <Sun aria-hidden="true" className="h-4 w-4" />}
                    </Button>
                </div>
            </div>
        </header>
    );
}
