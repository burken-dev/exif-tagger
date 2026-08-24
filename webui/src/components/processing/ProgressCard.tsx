import React from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Activity, CheckCircle2, AlertTriangle, Loader2, Pause } from 'lucide-react';

export interface ProgressCardProps {
  processedCount: number;
  totalCount: number;
  progressPct: number;
  statusText: string;
  isRunning: boolean;
  isPaused?: boolean;
  summary?: { failed: number; errors?: any[] } | null;
}

export const ProgressCard: React.FC<ProgressCardProps> = ({
  processedCount,
  totalCount,
  progressPct,
  statusText,
  isRunning,
  isPaused = false,
  summary,
}) => {
  const roundedPct = Math.min(100, Math.max(0, Math.round(progressPct || 0)));

  return (
    <Card className="border-border shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-primary" />
            <CardTitle>Session Progress</CardTitle>
          </div>
          <Badge
            variant="outline"
            className={`px-2.5 py-0.5 text-xs font-medium ${
              isRunning && !isPaused
                ? 'bg-amber-500/10 text-amber-500 border-amber-500/30'
                : isPaused
                ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                : statusText === 'Completed'
                ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30'
                : statusText === 'Completed with errors'
                ? 'bg-rose-500/10 text-rose-500 border-rose-500/30'
                : 'bg-slate-500/10 text-slate-400 border-slate-500/30'
            }`}
          >
            {isRunning && !isPaused && <Loader2 className="w-3 h-3 mr-1 inline animate-spin" />}
            {isPaused && <Pause className="w-3 h-3 mr-1 inline" />}
            {statusText}
          </Badge>
        </div>
        <CardDescription>
          Real-time execution status and image tagging throughput.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between text-sm font-medium">
          <span className="text-foreground font-mono">
            {processedCount} / {totalCount} images processed ({roundedPct}%)
          </span>
          <span className="text-xs text-muted-foreground font-mono">
            {roundedPct}% Complete
          </span>
        </div>

        <div className="h-3 w-full rounded-full bg-slate-800 overflow-hidden">
          <div
            className="h-full bg-primary rounded-full transition-all duration-300 ease-out"
            style={{ width: `${roundedPct}%` }}
          />
        </div>

        {summary && (
          <div className="mt-2 text-xs flex items-center gap-4">
            {summary.failed > 0 ? (
              <span className="text-rose-400 flex items-center gap-1 font-medium">
                <AlertTriangle className="w-3.5 h-3.5" />
                {summary.failed} image(s) failed
              </span>
            ) : (
              <span className="text-emerald-400 flex items-center gap-1 font-medium">
                <CheckCircle2 className="w-3.5 h-3.5" />
                All images processed successfully
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default ProgressCard;
