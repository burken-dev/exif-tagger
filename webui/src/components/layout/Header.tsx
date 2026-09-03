import React from 'react';
import { Tag, Sun, Moon } from 'lucide-react';
import { useTheme } from '@/context/ThemeContext';
import { useProcessing } from '@/hooks/useProcessing';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';

interface HeaderProps {
  statusText?: string;
}

export const Header: React.FC<HeaderProps> = ({ statusText: propStatusText }) => {
  const { theme, setTheme } = useTheme();
  const { statusText: hookStatusText } = useProcessing();

  const statusText = propStatusText ?? hookStatusText ?? 'Idle';

  const getStatusBadgeStyle = (status: string) => {
    switch (status.toLowerCase()) {
      case 'running':
        return 'bg-amber-500/10 text-amber-500 border-amber-500/30 animate-pulse';
      case 'stopping...':
        return 'bg-orange-500/10 text-orange-500 border-orange-500/30 animate-pulse';
      case 'paused':
        return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
      case 'completed':
        return 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30';
      case 'completed with errors':
        return 'bg-rose-500/10 text-rose-500 border-rose-500/30';
      case 'idle':
      default:
        return 'bg-slate-500/10 text-slate-400 border-slate-500/30';
    }
  };

  const getStatusDotColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'running':
        return 'bg-amber-500';
      case 'stopping...':
        return 'bg-orange-500';
      case 'paused':
        return 'bg-amber-400';
      case 'completed':
        return 'bg-emerald-500';
      case 'completed with errors':
        return 'bg-rose-500';
      case 'idle':
      default:
        return 'bg-slate-400';
    }
  };

  return (
    <header className="border-b border-border bg-card/80 backdrop-blur-md sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10 text-primary">
            <Tag className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-foreground tracking-tight">
              EXIF Tagger Dashboard
            </h1>
            <p className="text-xs text-muted-foreground hidden sm:block">
              AI-Powered Image Metadata Tagging System
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground hidden md:inline">Status:</span>
            <Badge
              variant="outline"
              className={`px-2.5 py-1 text-xs font-medium border rounded-full flex items-center gap-1.5 ${getStatusBadgeStyle(
                statusText
              )}`}
            >
              <span className={`w-2 h-2 rounded-full ${getStatusDotColor(statusText)}`} />
              {statusText}
            </Badge>
          </div>

          <div className="h-4 w-[1px] bg-border" />

          <div className="flex items-center gap-2">
            <Sun className={`w-4 h-4 ${theme === 'light' ? 'text-amber-500' : 'text-muted-foreground'}`} />
            <Switch
              checked={theme === 'dark'}
              onCheckedChange={(checked) => setTheme(checked ? 'dark' : 'light')}
              aria-label="Toggle theme"
            />
            <Moon className={`w-4 h-4 ${theme === 'dark' ? 'text-indigo-400' : 'text-muted-foreground'}`} />
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;
