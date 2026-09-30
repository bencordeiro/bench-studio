import { useState } from "react";
import { Card } from "@/components/ui";
import { fmtScore } from "@/lib/format";
import type { IndexEntry } from "@/types";

const COLORS = ["#c97c63", "#398bfa", "#8b79de", "#ec762c", "#28a879", "#c64f92", "#198eac"];
function modelColor(model: string) {
  let hash = 0;
  for (const char of model) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return COLORS[hash % COLORS.length];
}

export default function IndexChart({ entries }: { entries: IndexEntry[] }) {
  const [limit, setLimit] = useState(25);
  const ranked = [...entries].sort((a, b) => b.index_score - a.index_score || a.model.localeCompare(b.model));
  const shown = limit ? ranked.slice(0, limit) : ranked;
  const width = Math.max(640, shown.length * 70 + 100);
  const left = 80, top = 24, plotHeight = 280;
  const baseline = top + plotHeight;
  const step = (width - left - 20) / shown.length;
  const barWidth = Math.min(46, step * 0.72);
  return (
    <Card className="mt-6">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-lg font-medium text-white">Index scores</h2>
          <p className="text-xs text-gray-400 mt-1">{shown.length} of {entries.length} eligible models · score out of 100</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-gray-400">Show
          <select className="bg-bg-elev border border-border rounded px-2 py-1 text-gray-200"
            aria-label="Models shown in Index chart" value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
            <option value={10}>Top 10</option><option value={25}>Top 25</option><option value={0}>All models</option>
          </select>
        </label>
      </div>
      <div className="overflow-x-auto">
        <svg role="img" aria-label="Index score comparison chart" width={width} height={480}
          className="block mx-auto" style={{ minWidth: width }}>
          <title>Index scores, highest to lowest</title>
          <desc>Equal-weight benchmark averages. Only models completing every selected suite appear. The vertical scale runs from zero to one hundred.</desc>
          {[0, 25, 50, 75, 100].map((value) => {
            const y = baseline - value / 100 * plotHeight;
            return <g key={value}>
              <line x1={left} x2={width - 20} y1={y} y2={y} stroke="#475569" strokeDasharray={value ? "3 5" : undefined} />
              <text x={left - 10} y={y + 4} textAnchor="end" fill="#94a3b8" fontSize={11}>{value}</text>
            </g>;
          })}
          {shown.map((entry, i) => {
            const center = left + step * (i + 0.5);
            const height = Math.max(0, Math.min(100, entry.index_score)) / 100 * plotHeight;
            const label = entry.model.length > 26 ? `${entry.model.slice(0, 23)}…` : entry.model;
            return <g key={entry.model} tabIndex={0} aria-label={`${entry.model}: ${fmtScore(entry.index_score)} out of 100`}>
              <title>{entry.model}: {fmtScore(entry.index_score)} / 100</title>
              <rect x={center - barWidth / 2} y={baseline - height} width={barWidth} height={height} rx={4} fill={modelColor(entry.model)} />
              <text x={center} y={height >= 32 ? baseline - height / 2 + 4 : baseline - height - 8}
                textAnchor="middle" fill={height >= 32 ? "#ffffff" : "#e2e8f0"} fontSize={12} fontWeight={600}>{fmtScore(entry.index_score)}</text>
              <text x={center} y={baseline + 20} transform={`rotate(-55 ${center} ${baseline + 20})`}
                textAnchor="end" fill="#cbd5e1" fontSize={12}>{label}</text>
            </g>;
          })}
        </svg>
      </div>
    </Card>
  );
}
