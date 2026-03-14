const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://xwmgxkj0r4.execute-api.us-east-1.amazonaws.com/v1";

export interface Prediction {
  driver_number: number;
  driver_name: string;
  team: string;
  tyre_compound: string;
  tyre_age: number;
  pitstop_probability: number;
  confidence: number;
}

export interface SessionData {
  session_key: string;
  prediction_time: string;
  safety_car_active: boolean;
  processing_time_ms?: number;
  predictions: Prediction[];
  commentary?: string;
}

export async function fetchLatestSession(): Promise<SessionData> {
  const res = await fetch(`${API_URL}/sessions/latest`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function fetchSessions(): Promise<string[]> {
  const res = await fetch(`${API_URL}/sessions`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  const data = await res.json();
  return data.sessions || [];
}

export async function fetchSession(sessionKey: string): Promise<SessionData> {
  const res = await fetch(`${API_URL}/predict/positions/${sessionKey}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const TEAM_COLORS: Record<string, string> = {
  "McLaren":       "#FF8000",
  "Ferrari":       "#E8002D",
  "Mercedes":      "#00D2BE",
  "Red Bull":      "#3671C6",
  "Williams":      "#64C4FF",
  "Aston Martin":  "#006F62",
  "Alpine":        "#FF87BC",
  "Haas":          "#B6BABD",
  "Racing Bulls":  "#6692FF",
  "Audi":          "#BB0000",
  "Cadillac":      "#1B3D6F",
};

export const TYRE_COLORS: Record<string, string> = {
  SOFT: "#e8002d",
  MEDIUM: "#ffd700",
  HARD: "#f0f0f0",
  INTERMEDIATE: "#39b54a",
  WET: "#0067ff",
};

export function getTeamColor(team: string): string {
  return TEAM_COLORS[team] || "#666666";
}

export function getTyreColor(compound: string): string {
  return TYRE_COLORS[compound?.toUpperCase()] || "#666666";
}

export interface DriverPosition {
  driver_number: number;
  x: number;
  y: number;
  date: string;
}

export async function fetchDriverPositions(sessionKey: string): Promise<DriverPosition[]> {
  const since = new Date(Date.now() - 30000).toISOString();
  try {
    const res = await fetch(
      `https://api.openf1.org/v1/position?session_key=${sessionKey}&date>=${since}`,
      { cache: "no-store" }
    );
    if (!res.ok) return [];
    const data: any[] = await res.json();
    if (!Array.isArray(data)) return [];
    const latest = new Map<number, DriverPosition>();
    for (const p of data) {
      const existing = latest.get(p.driver_number);
      if (!existing || p.date > existing.date) {
        latest.set(p.driver_number, {
          driver_number: p.driver_number,
          x: p.x,
          y: p.y,
          date: p.date,
        });
      }
    }
    return Array.from(latest.values());
  } catch {
    return [];
  }
}
