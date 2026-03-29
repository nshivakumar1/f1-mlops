"use client";

import { useEffect, useState, useCallback, useMemo, memo } from "react";
import { fetchLatestSession, fetchDriverPositions, fetchTrackLayout, getTeamColor, getTyreColor, type SessionData, type DriverPosition, type TrackLayout } from "@/lib/api";

const REFRESH_INTERVAL = 30_000;

function ProbabilityBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "#e10600" : pct >= 45 ? "#ff8000" : "#22c55e";
  return (
    <div className="flex items-center gap-3 flex-1">
      <div className="flex-1 bg-[#2a2a2a] rounded-full h-2 overflow-hidden">
        <div className="h-2 rounded-full probability-bar" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-sm font-bold w-10 text-right" style={{ color }}>{pct}%</span>
    </div>
  );
}

function TyreBadge({ compound, age }: { compound: string; age: number }) {
  const color = getTyreColor(compound);
  return (
    <span className="text-xs font-bold px-2 py-0.5 rounded border" style={{ color, borderColor: color }}>
      {compound?.[0] ?? "?"} L{age}
    </span>
  );
}

function DriverCard({ p, rank }: { p: SessionData["predictions"][0]; rank: number }) {
  const teamColor = getTeamColor(p.team);
  const pct = Math.round(p.pitstop_probability * 100);
  const winPct = Math.round((p.win_probability ?? 0) * 100);
  const isHot = pct >= 70;
  const isLeader = rank === 1;
  const gap = p.gap_to_leader;
  return (
    <div className={`bg-[#1a1a1a] rounded-xl p-4 border transition-all ${isLeader ? "border-[#ffd700] shadow-[0_0_14px_rgba(255,215,0,0.15)]" : isHot ? "border-[#e10600] shadow-[0_0_12px_rgba(225,6,0,0.2)]" : "border-[#2a2a2a]"}`}>
      <div className="flex items-center gap-3 mb-3">
        <span className={`text-sm font-bold w-5 ${isLeader ? "text-[#ffd700]" : "text-gray-500"}`}>P{rank}</span>
        <div className="w-1 h-8 rounded-full" style={{ backgroundColor: teamColor }} />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm">{p.driver_name}</span>
            {isLeader && <span className="text-[10px] font-black text-[#ffd700] bg-[#ffd70020] px-1.5 py-0.5 rounded uppercase tracking-widest">Leader</span>}
          </div>
          <div className="text-xs text-gray-500">{p.team}{gap > 0 ? <span className="ml-2 text-gray-600">+{gap.toFixed(3)}s</span> : null}</div>
        </div>
        <TyreBadge compound={p.tyre_compound} age={p.tyre_age} />
        {isHot && <span className="text-xs text-[#e10600] font-bold animate-pulse">PIT SOON</span>}
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-600 w-14 uppercase tracking-wide">Pit</span>
          <ProbabilityBar value={p.pitstop_probability} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gray-600 w-14 uppercase tracking-wide">Win</span>
          <div className="flex items-center gap-3 flex-1">
            <div className="flex-1 bg-[#2a2a2a] rounded-full h-2 overflow-hidden">
              <div className="h-2 rounded-full" style={{ width: `${winPct}%`, backgroundColor: "#ffd700" }} />
            </div>
            <span className="text-sm font-bold w-10 text-right text-[#ffd700]">{winPct}%</span>
          </div>
        </div>
      </div>
    </div>
  );
}
const MAP_W = 800;
const MAP_H = 420;
const MAP_PAD = 32;

const RaceMap = memo(function RaceMap({ circuitKey, sessionKey, predictions }: { circuitKey: string; sessionKey: string; predictions: SessionData["predictions"] }) {
  const [track, setTrack] = useState<TrackLayout | null>(null);
  const [driverPositions, setDriverPositions] = useState<Map<number, { x: number; y: number }>>(new Map());
  const [trackError, setTrackError] = useState(false);

  useEffect(() => {
    if (!circuitKey) return;
    setTrack(null);
    setTrackError(false);
    fetchTrackLayout(circuitKey).then((t) => {
      if (t) setTrack(t);
      else setTrackError(true);
    });
  }, [circuitKey]);

  useEffect(() => {
    const controller = new AbortController();
    const poll = async () => {
      const data: DriverPosition[] = await fetchDriverPositions(sessionKey);
      if (controller.signal.aborted) return;
      if (!data.length) return;
      const m = new Map<number, { x: number; y: number }>();
      for (const d of data) m.set(d.driver_number, { x: d.x, y: d.y });
      setDriverPositions(m);
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => { clearInterval(t); controller.abort(); };
  }, [sessionKey]);

  const colorMap = useMemo(
    () => Object.fromEntries(predictions.map((p) => [p.driver_number, getTeamColor(p.team)])),
    [predictions]
  );

  const bounds = track && track.x.length > 0
    ? { minX: Math.min(...track.x), maxX: Math.max(...track.x), minY: Math.min(...track.y), maxY: Math.max(...track.y) }
    : null;

  const toSVG = (x: number, y: number) => {
    if (!bounds) return { sx: 0, sy: 0 };
    const scaleX = (MAP_W - 2 * MAP_PAD) / (bounds.maxX - bounds.minX || 1);
    const scaleY = (MAP_H - 2 * MAP_PAD) / (bounds.maxY - bounds.minY || 1);
    const scale = Math.min(scaleX, scaleY);
    const offsetX = MAP_PAD + ((MAP_W - 2 * MAP_PAD) - (bounds.maxX - bounds.minX) * scale) / 2;
    const offsetY = MAP_PAD + ((MAP_H - 2 * MAP_PAD) - (bounds.maxY - bounds.minY) * scale) / 2;
    return {
      sx: offsetX + (x - bounds.minX) * scale,
      sy: offsetY + (y - bounds.minY) * scale,
    };
  };

  const trackPoints = bounds && track
    ? track.x.map((px, i) => { const { sx, sy } = toSVG(px, track.y[i]); return `${sx},${sy}`; }).join(" ")
    : "";

  return (
    <div className="bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-4">
      <div className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-3">
        Live Circuit Map{track ? ` — ${track.circuit_name} ${track.year}` : ""}
      </div>
      <svg role="img" aria-label="Live circuit map" width="100%" viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="w-full">
        {trackPoints && (
          <polyline points={trackPoints} fill="none" stroke="#333" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
        )}
        {bounds && Array.from(driverPositions.entries()).map(([num, pos]) => {
          const { sx, sy } = toSVG(pos.x, pos.y);
          const color = colorMap[num] || "#888";
          return (
            <g key={num}>
              <circle cx={sx} cy={sy} r={8} fill={color} stroke="#000" strokeWidth={1.5} opacity={0.95} />
              <text x={sx} y={sy + 4} textAnchor="middle" fontSize={7} fill="#000" fontWeight="bold">{num}</text>
            </g>
          );
        })}
      </svg>
      {!track && !trackError && <div className="text-center text-gray-600 text-xs py-4">Loading circuit…</div>}
      {trackError && <div className="text-center text-gray-600 text-xs py-4">Circuit layout unavailable</div>}
      {track && driverPositions.size === 0 && (
        <div className="text-center text-gray-600 text-xs pt-2">Awaiting live position data…</div>
      )}
    </div>
  );
});

export default function LivePage() {
  const [data, setData] = useState<SessionData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL / 1000);

  const refresh = useCallback(async () => {
    try {
      const result = await fetchLatestSession();
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
      setCountdown(REFRESH_INTERVAL / 1000);
    }
  }, []);

  useEffect(() => { refresh(); const i = setInterval(refresh, REFRESH_INTERVAL); return () => clearInterval(i); }, [refresh]);
  useEffect(() => { const t = setInterval(() => setCountdown((c) => Math.max(0, c - 1)), 1000); return () => clearInterval(t); }, []);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-black"><span className="text-[#e10600]">LIVE</span> Pitstop Predictions</h1>
          {data && (
            <p className="text-gray-500 text-sm mt-1">
              Session {data.session_key} · {data.race_finished && <span className="text-[#ffd700] font-bold">FINISHED · </span>}{data.safety_car_active && !data.race_finished && <span className="text-yellow-400 font-bold">⚠️ SAFETY CAR · </span>}
              {data.predictions[0] && <span className="text-[#ffd700] font-bold">P1: {data.predictions[0].driver_name} · </span>}
              Updated {lastUpdated?.toLocaleTimeString()}
            </p>
          )}
        </div>
        <div className="text-right">
          <div className="text-xs text-gray-500">Refreshing in</div>
          <div className="text-lg font-mono font-bold text-[#e10600]">{countdown}s</div>
        </div>
      </div>

      <div className="flex gap-4 text-xs text-gray-500 mb-6">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#e10600] inline-block" /> ≥70% pit soon</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#ff8000] inline-block" /> 45–69% watch</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#22c55e] inline-block" /> &lt;45% safe</span>
      </div>

      {loading && (
        <div className="text-center py-20 text-gray-500"><div className="text-4xl mb-3">🏎️</div><div>Loading predictions...</div></div>
      )}
      {error && !loading && (
        <div className="text-center py-20 text-gray-500">
          <div className="text-4xl mb-3">🔴</div>
          <div className="text-sm">No live session data yet.</div>
          <div className="text-xs mt-1 text-gray-600">Predictions appear once the session starts.</div>
          <button onClick={refresh} className="mt-4 px-4 py-2 bg-[#e10600] rounded-lg text-sm font-bold hover:bg-red-700 transition-colors">Retry</button>
        </div>
      )}
      {data && !loading && (
        <div className="space-y-4">
          {data.commentary && (
            <div className="bg-[#0f0f1a] border border-[#3671c6] rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-bold text-[#3671c6] uppercase tracking-widest">AI Strategy Insight</span>
                <span className="text-xs text-gray-600">· AI · Live</span>
              </div>
              <p className="text-sm text-gray-200 leading-relaxed italic">{data.commentary}</p>
            </div>
          )}
          {data.circuit_key && (
            <RaceMap circuitKey={data.circuit_key} sessionKey={String(data.session_key)} predictions={data.predictions} />
          )}
          <div className="space-y-3">
            {data.predictions.map((p, i) => <DriverCard key={p.driver_number} p={p} rank={i + 1} />)}
          </div>
        </div>
      )}
    </div>
  );
}
