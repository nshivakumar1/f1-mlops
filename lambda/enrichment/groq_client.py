"""
AI commentary client — uses Groq (Llama 3.1 8B Instant) for live race strategy insights.
Free tier: 14,400 req/day, no credit card required (console.groq.com).
API key stored in Secrets Manager: f1-mlops/gemini-api-key (name kept for backward compat).
Secret name configurable via GROQ_SECRET_NAME env var.
Cached at module level with 1hr TTL.
"""
import json
import logging
import os
import time
import boto3
from groq import Groq

logger = logging.getLogger(__name__)

_GROQ_SECRET_NAME = os.environ.get("GROQ_SECRET_NAME", "f1-mlops/gemini-api-key")
_AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

_sm = boto3.client("secretsmanager", region_name=_AWS_REGION)

_api_key_cache: dict = {}
_KEY_TTL = 3600


def _get_client() -> Groq:
    """Return a cached Groq client, refreshing when the API key TTL expires."""
    now = time.time()
    if _api_key_cache.get("key") and now - _api_key_cache.get("fetched_at", 0) < _KEY_TTL:
        return _api_key_cache["client"]
    resp = _sm.get_secret_value(SecretId=_GROQ_SECRET_NAME)
    raw = resp["SecretString"]
    try:
        key = json.loads(raw)["api_key"]
    except (json.JSONDecodeError, KeyError):
        key = raw.strip()
    _api_key_cache["key"] = key
    _api_key_cache["fetched_at"] = now
    _api_key_cache["client"] = Groq(api_key=key)
    return _api_key_cache["client"]


def generate_race_commentary(predictions: list, safety_car: bool, session_key: str) -> str:
    """
    Generate a 2-sentence race strategy commentary using Llama 3.3 70B via Groq.
    Uses top-3 highest-probability predictions as context.
    Returns commentary string, or "" on failure (non-blocking).
    """
    if not predictions:
        return ""
    try:
        client = _get_client()

        top = sorted(
            predictions,
            key=lambda p: p.get("prediction", {}).get("pitstop_probability", 0),
            reverse=True,
        )[:3]

        driver_lines = []
        for rank, p in enumerate(top, start=1):
            driver = p.get("driver_name", p.get("driver", "Unknown"))
            team = p.get("team", "")
            prob = p.get("prediction", {}).get("pitstop_probability", 0) * 100
            tyre = p.get("tyre_compound", "?")
            features = p.get("features") or []
            age = features[0] if features else "?"
            lap = p.get("lap_number", "?")
            pits = p.get("pits_completed", 0)
            last_stop = p.get("last_pit_duration")
            gap = features[2] if len(features) > 2 else 0
            drs = p.get("drs_active", False)
            speed = p.get("speed", 0)

            line = (
                f"  {driver} ({team}): {prob:.0f}% pit probability, "
                f"lap {lap}, {tyre} tyres {age} laps old, "
                f"{pits} stop{'s' if pits != 1 else ''} taken"
            )
            if last_stop:
                line += f", last stop {last_stop:.1f}s"
            if gap > 0:
                line += f", +{gap:.1f}s to leader"
            if speed:
                line += f", {speed}km/h {'DRS open' if drs else ''}"
            driver_lines.append(line)

        # Include race-wide context
        all_laps = [p.get("lap_number", 0) for p in predictions if p.get("lap_number")]
        current_lap = max(all_laps) if all_laps else 0
        sc_note = " SAFETY CAR IS DEPLOYED — pit window is now open for everyone." if safety_car else ""
        context_lines = [f"Race lap: {current_lap}.{sc_note}"]

        prompt = (
            f"You are an F1 race strategist providing live TV commentary. Session {session_key}.\n"
            + "\n".join(context_lines) + "\n"
            f"Top pitstop candidates right now:\n" + "\n".join(driver_lines) + "\n\n"
            "In exactly 2 sentences, give sharp tactical insight: who is most likely to pit immediately and why, "
            "and the strategic consequence for the race. Reference lap count, tyre age, and gaps. "
            "Be specific and direct, as if speaking live on Sky Sports F1."
        )

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"AI commentary failed (non-critical): {e}")
        return ""
