#!/usr/bin/env python3
"""
Reference implementation of the NationalBettingAssociation stats model.

This is NOT part of the pipeline. Nothing imports it and no ingest script
calls it. Its only job is to be the source of truth for "what number should
the agent have produced?" so that when the Agent Builder agent shows its work
in the thinking trace, we can check its arithmetic against something instead
of eyeballing it.

Run it with no arguments to print the expected values for the sample docs in
mappings/sample_docs.md:

    python3 scripts/reference_model.py

No third-party dependencies -- stdlib only, so it runs anywhere.

See docs/model.md for the reasoning behind every constant below.
"""

import math

# --- Model constants. Keep these in sync with docs/model.md, the ES|QL in
# --- esql/, and the agent instructions in agent_builder/setup.md. If you tune
# --- one, tune all four.
NET_RATING_WEIGHT = 0.5
RECENT_FORM_WEIGHT = 30.0
HOME_COURT_BONUS = 5.0

# The logistic scale (a.k.a. temperature). raw_score is not in units of
# anything meaningful, so the gap between two raw_scores has to be divided by
# something before it goes through a logistic, or the result saturates at
# 0%/100%. See the "Calibrating the conversion" section of docs/model.md for
# why this is 10 and how to retune it live.
LOGISTIC_SCALE = 10.0

# Flag a game as interesting when the model and the market disagree by at
# least this much, in probability points.
MISMATCH_THRESHOLD = 0.08


def last_10_win_pct(last_10_wins, last_10_losses):
    """Recent-form win rate, guarded against a team with no last-10 record.

    A team with 0 wins and 0 losses in its last 10 (preseason, or a team the
    ingest hasn't backfilled yet) would divide by zero and poison the whole
    score. We fall back to 0.5 -- "no information, assume average" -- rather
    than 0.0, which would silently punish the team for missing data.
    """
    played = last_10_wins + last_10_losses
    if played == 0:
        return 0.5
    return last_10_wins / played


def raw_score(net_rating, last_10_wins, last_10_losses, is_home):
    """The weighted heuristic from docs/model.md. Higher is better."""
    form = last_10_win_pct(last_10_wins, last_10_losses)
    return (
        net_rating * NET_RATING_WEIGHT
        + form * RECENT_FORM_WEIGHT
        + (HOME_COURT_BONUS if is_home else 0.0)
    )


def win_probability(score_a, score_b, scale=LOGISTIC_SCALE):
    """Convert two raw_scores into P(team_a wins).

    Mathematically this is the two-class softmax from docs/model.md,
    exp(a) / (exp(a) + exp(b)), rewritten as the equivalent logistic
    1 / (1 + exp(-(a - b) / scale)). The rewrite matters for two reasons:

      1. It makes the scale divisor an explicit, tunable knob. Without it the
         function saturates -- see the demo matchup below, where an unscaled
         softmax returns 1.0000 for Boston.
      2. exp() of a raw_score around 35 is ~1.6e15, which is fine in float64
         but is exactly the kind of number an LLM computing this in its head
         gets wrong. The difference form keeps the exponent small.
    """
    return 1.0 / (1.0 + math.exp(-(score_a - score_b) / scale))


def devig(implied_a, implied_b):
    """Normalize two implied probabilities so they sum to 1.0.

    Raw 1/odds_decimal probabilities always sum to slightly more than 1.0;
    the excess is the bookmaker's margin. Comparing our model against
    un-normalized numbers biases every single delta in the same direction,
    which would make the whole tool look like it has a systematic edge it
    doesn't have.

    This duplicates devig() in ingest/fetch_odds.py on purpose. That one
    normalizes at write time; this one is a safety net for documents that
    were written without it -- including the sample docs in
    mappings/sample_docs.md, whose implied_probability values sum to 1.045.
    Applying this to already-de-vigged input is a no-op, so it is always safe
    to run.
    """
    total = implied_a + implied_b
    if total <= 0:
        return implied_a, implied_b
    return implied_a / total, implied_b / total


def analyze_matchup(home, away, market=None):
    """Score both sides of a matchup and, if given market odds, the deltas.

    `home` and `away` are dicts shaped like an nba_team_stats document.
    `market` maps team name -> de-vigged implied probability.
    """
    home_score = raw_score(
        home["net_rating"], home["last_10_wins"], home["last_10_losses"], True
    )
    away_score = raw_score(
        away["net_rating"], away["last_10_wins"], away["last_10_losses"], False
    )
    home_prob = win_probability(home_score, away_score)

    result = {
        "home": home["team"],
        "away": away["team"],
        "home_score": home_score,
        "away_score": away_score,
        "home_prob": home_prob,
        "away_prob": 1.0 - home_prob,
    }

    if market:
        raw_home = market.get(home["team"])
        raw_away = market.get(away["team"])
        if raw_home is not None and raw_away is not None:
            result["home_market_raw"] = raw_home
            result["away_market_raw"] = raw_away
            result["vig"] = raw_home + raw_away - 1.0
            home_mkt, away_mkt = devig(raw_home, raw_away)
            result["home_market"] = home_mkt
            result["away_market"] = away_mkt
            result["home_delta"] = home_prob - home_mkt
            result["away_delta"] = (1.0 - home_prob) - away_mkt

    return result


# --- The sample docs, copied verbatim from mappings/sample_docs.md so this
# --- file stays runnable with no cluster attached.

SAMPLE_CELTICS = {
    "team": "Boston Celtics",
    "net_rating": 12.2,
    "last_10_wins": 8,
    "last_10_losses": 2,
}

SAMPLE_KNICKS = {
    "team": "New York Knicks",
    "net_rating": 2.3,
    "last_10_wins": 6,
    "last_10_losses": 4,
}

SAMPLE_MARKET = {
    "Boston Celtics": 0.637,
    "New York Knicks": 0.408,
}


def _pct(x):
    return f"{x * 100:.1f}%"


def main():
    print("Expected values for the sample BOS/NYK matchup")
    print("(mappings/sample_docs.md, Boston at home)")
    print()

    r = analyze_matchup(SAMPLE_CELTICS, SAMPLE_KNICKS, SAMPLE_MARKET)

    print(f"  {r['home']:<20} raw_score {r['home_score']:>7.2f}  (incl. +5 home court)")
    print(f"  {r['away']:<20} raw_score {r['away_score']:>7.2f}")
    print(f"  score gap            {r['home_score'] - r['away_score']:>7.2f}")
    print()
    print(
        f"  market raw    P(BOS) {_pct(r['home_market_raw']):>7} "
        f"P(NYK) {_pct(r['away_market_raw']):>7}   "
        f"sum {r['home_market_raw'] + r['away_market_raw']:.3f} "
        f"(vig {r['vig'] * 100:.1f}pp)"
    )
    print()
    print(f"  model   P(BOS) {_pct(r['home_prob']):>7}     P(NYK) {_pct(r['away_prob']):>7}")
    print(f"  market  P(BOS) {_pct(r['home_market']):>7}     P(NYK) {_pct(r['away_market']):>7}  (de-vigged)")
    print(
        f"  delta   BOS    {r['home_delta'] * 100:>+6.1f}pp    NYK    "
        f"{r['away_delta'] * 100:>+6.1f}pp"
    )
    print()

    flagged = abs(r["home_delta"]) >= MISMATCH_THRESHOLD
    print(
        f"  mismatch flagged: {flagged} "
        f"(threshold {_pct(MISMATCH_THRESHOLD)})"
    )
    print()

    # The reason LOGISTIC_SCALE exists at all. Leave this in the output -- it
    # is the fastest way to re-justify the constant to anyone who asks why the
    # formula in docs/model.md grew a divisor.
    gap = r["home_score"] - r["away_score"]
    print("Why the scale divisor exists -- same matchup at different scales:")
    for scale in (1, 5, 6.5, 10, 15, 20):
        p = 1.0 / (1.0 + math.exp(-gap / scale))
        marker = "   <-- current" if scale == LOGISTIC_SCALE else ""
        print(f"    scale {scale:>4}   P(BOS) {_pct(p):>7}{marker}")
    print()
    print(
        "  Scale 1 is the literal softmax in the original docs/model.md. It\n"
        "  returns 100.0% for Boston, which is both wrong and unusable on\n"
        "  stage -- every game would read as a massive value mismatch."
    )


if __name__ == "__main__":
    main()
