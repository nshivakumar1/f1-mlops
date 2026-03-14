"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { fetchLatestSession, fetchDriverPositions, getTeamColor, getTyreColor, type SessionData, type DriverPosition } from "@/lib/api";

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
  const isHot = pct >= 70;
  return (
    <div className={`bg-[#1a1a1a] rounded-xl p-4 border transition-all ${isHot ? "border-[#e10600] shadow-[0_0_12px_rgba(225,6,0,0.2)]" : "border-[#2a2a2a]"}`}>
      <div className="flex items-center gap-3 mb-3">
        <span className="text-gray-500 text-sm w-4">{rank}</span>
        <div className="w-1 h-8 rounded-full" style={{ backgroundColor: teamColor }} />
        <div className="flex-1">
          <div className="font-bold text-sm">{p.driver_name}</div>
          <div className="text-xs text-gray-500">{p.team}</div>
        </div>
        <TyreBadge compound={p.tyre_compound} age={p.tyre_age} />
        {isHot && <span className="text-xs text-[#e10600] font-bold animate-pulse">PIT SOON</span>}
      </div>
      <ProbabilityBar value={p.pitstop_probability} />
    </div>
  );
}

const MAP_W = 700;
const MAP_H = 400;
const MAP_PAD = 30;

function RaceMap({ sessionKey, predictions }: { sessionKey: string; predictions: SessionData["predictions"] }) {
  const [driverPositions, setDriverPositions] = useState<Map<number, { x: number; y: number }>>(new Map());
  const trackPointsRef = useRef<{ x: number; y: number }[]>([]);
  const [bounds, setBounds] = useState<{ minX: number; maxX: number; minY: number; maxY: number } | null>(null);
  const [trackSnapshot, setTrackSnapshot] = useState<{ x: number; y: number }[]>([]);

  useEffect(() => {
    const poll = async () => {
      const data: DriverPosition[] = await fetchDriverPositions(sessionKey);
      if (data.length === 0) return;

      const newPos = new Map<number, { x: number; y: number }>();
      for (const d of data) newPos.set(d.driver_number, { x: d.x, y: d.y });
      setDriverPositions(newPos);

      const incoming = data.map((d) => ({ x: d.x, y: d.y }));
      const seen = new Set(trackPointsRef.current.map((p) => `${Math.round(p.x / 10)},${Math.round(p.y / 10)}`));
      const fresh = incoming.filter((p) => {
        const k = `${Math.round(p.x / 10)},${Math.round(p.y / 10)}`;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
      if (fresh.length > 0) {
        trackPointsRef.current = [...trackPointsRef.current, ...fresh];
        const pts = trackPointsRef.current;
        const xs = pts.map((p) => p.x);
        const ys = pts.map((p) => p.y);
        setBounds({ minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) });
        setTrackSnapshot([...pts]);
      }
    };

    poll();
    const t = setInterval(poll, 5000);
    return () => clearInterval(t);
  }, [sessionKey]);

  const toSVG = (x: number, y: number) => {
    if (!bounds) return { sx: MAP_PAD, sy: MAP_PAD };
    const rangeX = bounds.maxX - bounds.minX || 1;
    const rangeY = bounds.maxY - bounds.minY || 1;
    return {
      sx: MAP_PAD + ((x - bounds.minX) / rangeX) * (MAP_W - 2 * MAP_PAD),
      sy: MAP_PAD + ((y - bounds.minY) / rangeY) * (MAP_H - 2 * MAP_PAD),
    };
  };

  const colorMap = Object.fromEntries(predictions.map((p) => [p.driver_number, getTeamColor(p.team)]));

  return (
    <div className="bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] p-4">
      <div className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-3">Live Circuit Map</div>
      <svg width="100%" viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="w-full">
        {bounds && trackSnapshot.map((p, i) => {
          const { sx, sy } = toSVG(p.x, p.y);
          return <circle key={i} cx={sx} cy={sy} r={1.5} fill="#333" />;
        })}
        {bounds && Array.from(driverPositions.entries()).map(([num, pos]) => {
          const { sx, sy } = toSVG(pos.x, pos.y);
          const color = colorMap[num] || "#888";
          return (
            <g key={num}>
              <circle cx={sx} cy={sy} r={7} fill={color} opacity={0.9} />
              <text x={sx} y={sy + 4} textAnchor="middle" fontSize={7} fill="#000" fontWeight="bold">{num}</text>
            </g>
          );
        })}
      </svg>
      {driverPositions.size === 0 && (
        <div className="text-center text-gray-600 text-xs py-6">Waiting for position data…</div>
      )}
    </div>
  );
}

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
              Session {data.session_key} · {data.safety_car_active && <span className="text-yellow-400 font-bold">🟡 SAFETY CAR · </span>}
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
          <RaceMap sessionKey={data.session_key} predictions={data.predictions} />
          <div className="space-y-3">
            {data.predictions.map((p, i) => <DriverCard key={p.driver_number} p={p} rank={i + 1} />)}
          </div>
        </div>
      )}
    </div>
  );
}
