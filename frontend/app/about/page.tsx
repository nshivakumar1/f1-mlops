export default function AboutPage() {
  const stack = [
    { layer: "Data Source", tech: "OpenF1 API", detail: "Live telemetry — tyre age, gaps, compounds, safety car" },
    { layer: "Prediction Engine", tech: "XGBoost on AWS SageMaker", detail: "Serverless endpoint, 11 engineered features, updated every 30s" },
    { layer: "Commentary", tech: "Gemini 2.5 Pro", detail: "Natural language race strategy insights generated per lap" },
    { layer: "Orchestration", tech: "AWS Lambda + EventBridge", detail: "4 Lambda functions, enrichment fires every 60s during sessions" },
    { layer: "Storage", tech: "S3 + Elasticsearch", detail: "Raw predictions in S3, real-time indexing via Logstash → ELK" },
    { layer: "Alerts", tech: "CloudWatch → SNS → AWS Chatbot", detail: "Slack alerts for model drift, Lambda errors, billing cap" },
    { layer: "CI/CD", tech: "AWS CodePipeline + GitHub Actions", detail: "5-stage pipeline: Test → Plan → Approve → Deploy via Terraform" },
    { layer: "Frontend", tech: "Next.js → Vercel", detail: "Live predictions, race history, Gemini commentary — updates every 30s" },
  ];

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-black mb-2">About this <span className="text-[#e10600]">Project</span></h1>
      <p className="text-gray-400 text-sm mb-10 leading-relaxed">
        An end-to-end MLOps system that predicts F1 pitstops in real-time during each session. Two XGBoost models run live — one predicts pitstop probability per driver per lap, one predicts race outcome probabilities. Gemini 2.5 Pro generates natural language strategy commentary from the raw predictions.
      </p>

      {/* Architecture */}
      <h2 className="text-lg font-bold mb-4 text-gray-300">Architecture</h2>
      <div className="bg-[#1a1a1a] rounded-xl border border-[#2a2a2a] overflow-hidden mb-10">
        <div className="px-5 py-3 border-b border-[#2a2a2a] text-xs text-gray-500 font-mono">
          OpenF1 → Lambda → SageMaker → S3 / ELK → API Gateway → This UI
        </div>
        <div className="divide-y divide-[#2a2a2a]">
          {stack.map((s) => (
            <div key={s.layer} className="px-5 py-3 flex gap-4">
              <div className="w-36 text-xs text-gray-500 pt-0.5 shrink-0">{s.layer}</div>
              <div>
                <div className="text-sm font-semibold text-white">{s.tech}</div>
                <div className="text-xs text-gray-500 mt-0.5">{s.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Model */}
      <h2 className="text-lg font-bold mb-4 text-gray-300">Model Details</h2>
      <div className="grid grid-cols-2 gap-4 mb-10">
        {[
          { label: "Algorithm", value: "XGBoost (gradient boosted trees)" },
          { label: "Features", value: "11 engineered (tyre age², heat degradation, wet stint, sector delta)" },
          { label: "Target", value: "Pitstop probability in next 3 laps" },
          { label: "Inference", value: "SageMaker Serverless, ~30ms p99" },
          { label: "Training data", value: "2022–2025 F1 seasons via FastF1" },
          { label: "Drift detection", value: "CloudWatch alarm if confidence < 0.65" },
        ].map((item) => (
          <div key={item.label} className="bg-[#1a1a1a] rounded-xl p-4 border border-[#2a2a2a]">
            <div className="text-xs text-gray-500 mb-1">{item.label}</div>
            <div className="text-sm font-medium">{item.value}</div>
          </div>
        ))}
      </div>

      {/* Links */}
      <h2 className="text-lg font-bold mb-4 text-gray-300">Links</h2>
      <div className="flex gap-3">
        <a href="https://github.com/nshivakumar1/f1-mlops" target="_blank" rel="noopener noreferrer"
          className="px-4 py-2 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg text-sm hover:border-white transition-colors">
          GitHub →
        </a>
      </div>
    </div>
  );
}
