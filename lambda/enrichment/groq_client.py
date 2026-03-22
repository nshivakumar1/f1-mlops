"""
AI commentary client — uses Groq (Llama 3.3 70B) for live race strategy insights.
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


def _get_api_key() -> str:
    now = time.time()
    if _api_key_cache.get("key") and now - _api_key_cache.get("fetched_at", 0) < _KEY_TTL:
        return _api_key_cache["key"]
    resp = _sm.get_secret_value(SecretId=_GROQ_SECRET_NAME)
    raw = resp["SecretString"]
    try:
        key = json.loads(raw)["api_key"]
    except (json.JSONDecodeError, KeyError):
        key = raw.strip()
    _api_key_cache["key"] = key
    _api_key_cache["fetched_at"] = now
    return key


def generate_race_commentary(predictions: list, safety_car: bool, session_key: str) -> str:
    """
    Generate a 2-sentence race strategy commentary using Llama 3.3 70B via Groq.
    Uses top-3 highest-probability predictions as context.
    Returns commentary string, or "" on failure (non-blocking).
    """
    if not predictions:
        return ""
    try:
        key = _get_api_key()
        client = Groq(api_key=key)

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
            driver_lines.append(
                f"  P{rank} {driver} ({team}): {prob:.0f}% pitstop probability, "
                f"{tyre} tyres aged {age} laps"
            )

        sc_note = " Safety car is currently deployed." if safety_car else ""
        prompt = (
            f"You are an F1 race strategist providing live commentary during session {session_key}.{sc_note}\n"
            f"Current pitstop predictions:\n" + "\n".join(driver_lines) + "\n\n"
            "In exactly 2 sentences, give sharp tactical commentary: who is most likely to pit and why, "
            "and what the strategic implication is for the race. Be specific and direct, as if speaking live on TV."
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"AI commentary failed (non-critical): {e}")
        return ""
