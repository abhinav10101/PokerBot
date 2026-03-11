# Strategic Summary — How Every Component Contributes to Winning

> This document ties together all of the bot's components into a coherent picture of **how and why** the design choices produce a winning agent.

---

## The Core Problem

A poker bot must solve a decision problem under **multi-dimensional uncertainty**:

1. **Card uncertainty** — which cards will come next?
2. **Range uncertainty** — what does the opponent hold?
3. **Intent uncertainty** — is the opponent's bet a bluff or value?
4. **Auction uncertainty** — how much should information cost?

Each component of the bot addresses one or more of these uncertainties.

---

## Component-by-Component Contribution

### `RANK_TO_VALUE` and constants

**Problem addressed:** Card uncertainty (representation layer)

Without a canonical integer representation of ranks, every comparison requires conditional logic, introducing bugs and limiting the use of arithmetic shortcuts. The mapping enables clean straight-detection, pair-detection, and overcard identification throughout the codebase.

`OPP_HIGH_BID_THRESHOLD` addresses **intent uncertainty** — an opponent who bids ≥ 200 in the auction has revealed strong intent, and the bot adjusts accordingly.

---

### `OpponentModel`

**Problems addressed:** Range uncertainty, intent uncertainty

This is the bot's primary tool for exploiting opponent tendencies. Without it, the bot has no choice but to play a "default" strategy. With it, the bot can:

| Observation | Adaptation | EV impact |
|---|---|---|
| High raise frequency | Widen 3-bet range, defend more | Win chips from loose openers |
| Very high frequency (>45%) | Call with weak holdings | Prevent being blinded out by steal-raises |
| Jam-bot detected | Fold except premiums | Avoid calling off stack as a marginal favourite |
| Passive auction bidder | Win auctions for near-zero | Get information almost for free |
| Spike bidder detected | Cap bids | Avoid being exploited by random large bids |

The rolling windows (60 for raises, 80 for bids) mean the model **adapts to style changes mid-session** rather than being anchored to early-game data.

---

### `eval_hand()` (Monte Carlo equity)

**Problem addressed:** Card uncertainty

Pure heuristics ("I have top pair, so I should bet") fail on complex boards. For example:
- Top pair on a flush board with a dangerous revealed card
- An overpair on a double-paired board when the opponent may have a full house
- A straight on a three-flush board

Monte Carlo simulation handles all these cases automatically. By sampling 48 random completions of the board and opponent's hand, the equity estimate correctly reflects the probability of winning in the actual situation — not just the nominal hand strength.

**Key limitation:** 48 iterations gives ≈7% standard error. This is why all call thresholds include a buffer above pot odds rather than calling at exactly break-even equity.

---

### `preflop_strength()`

**Problem addressed:** Card uncertainty (preflop range construction)

Preflop equity is determined by a well-studied hand hierarchy. Running Monte Carlo at every preflop decision would be redundant and slow. The 1–10 score efficiently captures:
- Pair strength (pocket aces vs. pocket deuces)
- Connectedness (suited connectors have implied odds)
- Domination risk (A2 offsuit is easily dominated by AK)

This enables the preflop decision tree to make correct fold/call/raise decisions in milliseconds.

---

### `postflop_hand_strength()`

**Problem addressed:** Card uncertainty (made-hand classification)

This function bridges the gap between "I know my cards and the board" and "here is a decision-ready strength score." The context-aware pair hierarchy is especially important:

> A board-only pair (two queens on board) gives the opponent the same "pair" by default. Treating it as a strong made hand leads to over-calling with essentially garbage.

By correctly classifying top pair vs. second pair vs. board pair, the bot avoids one of the most common mistakes in recreational poker: falling in love with a pair that is likely dominated or tied.

---

### `revealed_card_danger()`

**Problem addressed:** Range uncertainty (auction loser context)

When the bot loses the auction, it knows one of the opponent's cards. This function converts that card into an **actionable threat level** by checking three things:
1. Does it pair the board? (→ trips/quads threat)
2. Does it continue a flush draw? (→ flush threat)
3. Is it connected to board cards? (→ straight threat)

Without this function, the bot would naively treat the revealed card as just "one card" and continue betting into hands it is likely losing. With it, the bot recognises when a revealed card completely changes the matchup and folds accordingly.

---

### `hidden_card_equity_discount()`

**Problem addressed:** Range uncertainty (auction winner context)

When the bot wins the auction, it has partial information — one revealed card, one hidden. The discount corrects a systematic bias: **when one hole card is low, the hidden card is more likely to be high**. Without this correction, the Monte Carlo simulation would underestimate the opponent's strength in these situations.

The magnitude of the discount (0–10%) is conservative — it applies only when the visible card is very low — but it prevents the bot from overbetting into spots where the opponent is likely holding a concealed monster.

---

### `board_has_fullhouse_danger()` and `get_flush_info()`

**Problems addressed:** Card uncertainty (board texture), range uncertainty (flush vs. full house)

These two functions protect against one of the highest-chip-loss situations in NLHE: **building a huge pot with a dominated flush**.

- `board_has_fullhouse_danger()` detects when a flush can be beaten by a full house
- `get_flush_info()` distinguishes nut vs. non-nut flush (the latter can be beaten by a higher flush)

Together, they cause the bot to **slow down dramatically** when holding a flush on threatening boards:
- Suppress proactive bets on paired boards
- Fold to large bets with non-nut flushes
- Fold river all-ins with non-nut flush unless equity is very high

This avoids the classic mistake of stacking off with `J♠ 5♠` on a `K♠ Q♠ 9♠ K♣` board.

---

### `_preflop_move()`

**Problems addressed:** Range uncertainty, intent uncertainty

Preflop is where the bot constructs its playing range. The layered decision tree ensures:
- Premium hands extract maximum value (3-bets, re-raises)
- Exploitable opponents are punished (steal-defence, wide calling vs. jam-bots)
- Marginal hands avoid over-committing (fold to large raises without profile data)

The opponent profiling makes a material difference here: against a 45% raise-frequency opponent, calling with `Q5o` becomes correct (positive EV). Against a 15% frequency opponent, it's a clear fold.

---

### `_auction_bid()` and `_infer_opp_bid()`

**Problem addressed:** Auction uncertainty

These two methods jointly solve the calibration problem for the auction:
- `_auction_info_value()` computes *what the information is worth*
- Profile-based adjustments compute *what bid will actually win*
- `_infer_opp_bid()` uses post-auction pot data to update the profile

The result: the bot **wins the auction at approximately the minimum required cost** against profiled opponents, rather than always bidding maximum or always underbidding. Against a passive bidder, this can mean winning information for 15 chips that might have cost 100+ with naive bidding.

---

### `_postflop_move()` and `_river_decision()`

**Problems addressed:** All four uncertainties simultaneously

These methods are where everything comes together. The layered priority structure means:

1. **Stack-commitment decisions** (all-in pressure) are evaluated first — wrong here loses everything
2. **Opponent auction context** is applied next — a high-bidding opponent gets respected
3. **Equity-based decisions** follow — simulation results determine calls and folds
4. **Probe-bet logic** exploits the information edge from a won auction
5. **Conservative river logic** prevents bluff-catching with marginal hands at the end of the line

The probe-bet system is particularly elegant: win the auction → gather information cheaply → if opponent calls, stop bluffing and only bet for value. This mimics how a skilled human player adjusts based on observed strength signals.

---

## How Winning is Produced

```
Session start
│
├─ Hand 1–20: Cold start
│       ├─ Bid full info value in auctions (no profile)
│       ├─ Play default preflop ranges
│       └─ Equity-based postflop decisions
│
├─ Hand 20–60: Profile emerges
│       ├─ is_steal_heavy / is_moderate_raiser flags active
│       ├─ Auction bids calibrated to opponent p75
│       └─ Post-auction danger logic refines postflop
│
└─ Hand 60+: Full exploitation
        ├─ Preflop 3-bet range widened vs. loose opener
        ├─ Auction bids minimised (passive) or capped (spike)
        ├─ Post-auction logic maximally exploits information
        └─ Avoid stack-off errors with non-nut hands on dangerous boards
```

The bot is designed to **lose minimally in the cold start** and **gain maximally once the profile stabilises**. The 20-hand minimums on profiling flags prevent early over-reactions. The rolling windows ensure the profile stays current if the opponent's style changes.

---

## Known Limitations & Potential Improvements

| Limitation | Potential improvement |
|---|---|
| 48 MC iterations → ~7% equity error | Increase to 200 on critical streets (river, all-in) |
| No multi-street planning | Add fold-equity estimation for semi-bluffs |
| Auction inference is lower-bounded when we lose | Use bet sizing on post-auction streets to refine opp range |
| Probe bet detection only checks one street back | Extend to full street history |
| River bet sizing not implemented | Add value bets on the river when checked to |
| No position awareness | Adjust ranges based on who acts first |
