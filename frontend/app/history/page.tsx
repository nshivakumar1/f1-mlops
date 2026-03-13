import { fetchSessions, fetchSession } from "@/lib/api";

export const revalidate = 60;

export default async function HistoryPage() {
  let sessions: string[] = [];
  try { sessions = await fetchSessions(); } catch {}

  const sessionData = await Promise.all(
    sessions.slice(0, 10).map(async (sk) => {
      try { return { key: sk, data: await fetchSession(sk) }; }
      catch { return { key: sk, data: null }; }
    })
  );

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-black mb-2">Race <span className="text-[#e10600]">History</span></h1>
      <p className="text-gray-500 text-sm mb-8">Past session predictions — predicted pitstop probability vs actual strategy.</p>

      {sessions.length === 0 ? (
        <div className="text-center py-20 text-gray-500">
          <div className="text-4xl mb-3">📭</div>
          <div className="text-sm">No sessions recorded yet.</div>
          <div className="text-xs mt-1 text-gray-600">Data will appear after the first live session.</div>
        </div>
      ) : (
        <div className="space-y-6">
          {sessionData.map(({ key, data }) => (
            <div key={key} className="bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] overflow-hidden">
              <div className="px-5 py-3 border-b border-[#2a2a2a] flex items-center justify-between">
                <span className="font-bold text-sm">Session {key}</span>
                {data && <span className="text-xs text-gray-500">{new Date(data.prediction_time).toLocaleString()}</span>}
              </div>
              {data ? (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 border-b border-[#2a2a2a]">
                      <th className="px-5 py-2 text-left">Driver</th>
                      <th className="px-5 py-2 text-left">Team</th>
                      <th className="px-5 py-2 text-left">Tyre</th>
                      <th className="px-5 py-2 text-right">Pit Prob</th>
                      <th className="px-5 py-2 text-right">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.predictions.map((p) => (
                      <tr key={p.driver_number} className="border-b border-[#1f1f1f] hover:bg-[#222] transition-colors">
                        <td className="px-5 py-2 font-medium">{p.driver_name}</td>
                        <td className="px-5 py-2 text-gray-400 text-xs">{p.team}</td>
                        <td className="px-5 py-2 text-xs">{p.tyre_compound} L{p.tyre_age}</td>
                        <td className="px-5 py-2 text-right">
                          <span className={`font-bold ${p.pitstop_probability >= 0.7 ? "text-[#e10600]" : p.pitstop_probability >= 0.45 ? "text-[#ff8000]" : "text-[#22c55e]"}`}>
                            {Math.round(p.pitstop_probability * 100)}%
                          </span>
                        </td>
                        <td className="px-5 py-2 text-right text-gray-400">{Math.round(p.confidence * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="px-5 py-4 text-gray-600 text-sm">Failed to load session data.</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
