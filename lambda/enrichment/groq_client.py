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


def generate_race_summary(predictions: list, session_key: str) -> str:
    """
    Generate a post-race summary once the chequered flag is shown.
    Sorted by win_probability to derive the final podium order.
    Returns summary string, or "" on failure (non-blocking).
    """
    if not predictions:
        return ""
    try:
        client = _get_client()

        # Sort by win_probability descending to get podium order
        standings = sorted(predictions, key=lambda p: p.get("win_probability", 0), reverse=True)

        podium_lines = []
        for pos, p in enumerate(standings[:3], start=1):
            driver = p.get("driver_name", "Unknown")
            team = p.get("team", "")
            features = p.get("features") or []
            tyre = p.get("tyre_compound", "?")
            pits = p.get("pits_completed", 0)
            gap = features[2] if len(features) > 2 else 0
            gap_str = "Winner" if pos == 1 else f"+{gap:.3f}s"
            podium_lines.append(
                f"  P{pos}: {driver} ({team}) — {gap_str}, {tyre} tyres, {pits} stop{'s' if pits != 1 else ''}"
            )

        prompt = (
            f"You are a Sky Sports F1 commentator. The race (session {session_key}) has just finished — the chequered flag is out.\n\n"
            f"Final podium:\n" + "\n".join(podium_lines) + "\n\n"
            "In 2-3 sentences: (1) congratulate the race winner and name the podium, "
            "(2) briefly describe the key strategic or on-track factor that decided the race outcome. "
            "Be specific, celebratory, and direct — as if live on air at the chequered flag."
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Race summary generation failed (non-critical): {e}")
        return ""


def generate_race_commentary(predictions: list, safety_car: bool, session_key: str) -> str:
    """
    Generate race commentary using Llama 3.3 70B via Groq.
    Covers race standings (who is winning), pit strategy, and tactical consequences.
    Returns commentary string, or "" on failure (non-blocking).
    """
    if not predictions:
        return ""
    try:
        client = _get_client()

        all_laps = [p.get("lap_number", 0) for p in predictions if p.get("lap_number")]
        current_lap = max(all_laps) if all_laps else 0

        # Build race standings: sort by gap_to_leader ascending (0 = leader)
        def gap_val(p):
            features = p.get("features") or []
            g = features[2] if len(features) > 2 else None
            if g is None or g == 0:
                return -1  # leader sorts first
            try:
                return float(g)
            except (TypeError, ValueError):
                return 999

        standings = sorted(predictions, key=gap_val)

        standings_lines = []
        for pos, p in enumerate(standings[:5], start=1):
            driver = p.get("driver_name", "Unknown")
            team = p.get("team", "")
            features = p.get("features") or []
            gap = features[2] if len(features) > 2 else 0
            win_pct = round(p.get("win_probability", 0) * 100, 1)
            tyre = p.get("tyre_compound", "?")
            age = features[0] if features else "?"
            pits = p.get("pits_completed", 0)
            gap_str = "LEADER" if pos == 1 else f"+{gap:.3f}s"
            standings_lines.append(
                f"  P{pos}: {driver} ({team}) — {gap_str}, {win_pct}% win prob, "
                f"{tyre} tyres {age} laps old, {pits} stop{'s' if pits != 1 else ''}"
            )

        # Top pit candidates
        pit_candidates = sorted(
            predictions,
            key=lambda p: p.get("prediction", {}).get("pitstop_probability", 0),
            reverse=True,
        )[:3]

        pit_lines = []
        for p in pit_candidates:
            driver = p.get("driver_name", "Unknown")
            prob = p.get("prediction", {}).get("pitstop_probability", 0) * 100
            features = p.get("features") or []
            tyre = p.get("tyre_compound", "?")
            age = features[0] if features else "?"
            gap = features[2] if len(features) > 2 else 0
            gap_str = f"+{gap:.3f}s to leader" if gap else "leads"
            pit_lines.append(
                f"  {driver}: {prob:.0f}% pit probability, {tyre} L{age}, {gap_str}"
            )

        sc_note = " SAFETY CAR DEPLOYED — undercut opportunity for everyone." if safety_car else ""
        prompt = (
            f"You are a Sky Sports F1 commentator. Session {session_key}, lap {current_lap}.{sc_note}\n\n"
            f"Current race standings (top 5):\n" + "\n".join(standings_lines) + "\n\n"
            f"Imminent pit stop candidates:\n" + "\n".join(pit_lines) + "\n\n"
            "In 3 sentences: (1) name the race leader and whether their lead is secure, "
            "(2) identify who is about to pit and the strategic reason, "
            "(3) explain how that pit stop could change the race outcome. "
            "Be specific, dramatic, and direct — as if live on air."
        )

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"AI commentary failed (non-critical): {e}")
        return ""
