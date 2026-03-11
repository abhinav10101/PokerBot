# Constants & Global Configuration

> **File:** `player.py` — top-level scope  
> **Purpose:** Define the numeric constants and card-rank mapping that every other component depends on.

---

## `RANK_TO_VALUE`

```python
RANK_TO_VALUE = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9,
    "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}
```

### What it does

Maps each card rank character (as a string) to a comparable integer. This is used everywhere a numerical comparison between card ranks is needed — for example, determining whether one card outranks another, whether a set of cards forms a straight, or how far apart two ranks are.

### Why it matters

Without a canonical integer representation, rank comparisons require messy conditional chains. By mapping once at module load, every function can do clean arithmetic like `abs(r1 - r2)` to compute rank gaps, or `sorted(rank_vals)` to order cards reliably. Ace (`A`) is assigned `14` — the highest value — which means the ace-high straight (broadway) is naturally handled. The low-ace (wheel: A-2-3-4-5) requires special handling elsewhere and is explicitly added as `1` in straight-detection helpers.

---

## `BIG_BLIND`

```python
BIG_BLIND = 20
```

### What it does

Defines the size of the big blind in chips. This is the fundamental unit of bet sizing used throughout the preflop decision tree.

### Why it matters

All raise-size comparisons in preflop logic are expressed as multiples of the big blind (e.g., "a 4BB raise"). By centralising this value, adjusting the game's blind level requires changing only one constant. For example:

- `cost / BIG_BLIND` converts any call cost into a BB-denominated raise size
- The preflop logic checks `raise_in_bb <= 4.0` to decide whether a raise is "small" or "large"

---

## `CHIPS_PER_ROUND`

```python
CHIPS_PER_ROUND = 5000
```

### What it does

Records the expected starting stack for each round. Used to initialise `Player.start_chips` at the beginning of each hand.

### Why it matters

Stack depth affects nearly every decision in poker. The all-in pressure threshold (`_is_allin_pressure`) uses an absolute chip threshold of **1500 chips** — roughly 30% of this starting stack — to identify when a bet commits a significant fraction of the effective stack, even before the 70%-of-stack percentage check fires. Tracking the starting stack also makes it straightforward to compute chip gains or losses per hand for future diagnostics.

---

## `OPP_HIGH_BID_THRESHOLD`

```python
OPP_HIGH_BID_THRESHOLD = 200
```

### What it does

The chip level at which an opponent's inferred auction bid is classified as a **"high bid"** — indicating the opponent believed their hole cards were strong enough to pay a premium for information.

### Why it matters

In a second-price auction, a player only bids aggressively when they believe their hand's value justifies it. A bid of ≥ 200 chips is a strong signal that the opponent holds a premium hand. When the bot loses an auction to a bid at or above this threshold, it sets the `_opp_high_bid_won` flag, which tightens postflop call thresholds on the flop and turn — preventing the bot from calling large bets with marginal holdings against a likely strong opponent range.

**Tuning:** Lowering this value (e.g., to 100) makes the bot more cautious after any medium-to-large auction loss. Raising it (e.g., to 300) makes the bot less reactive to moderately high bids.

---

## Summary

| Constant | Value | Scope of influence |
|----------|-------|--------------------|
| `RANK_TO_VALUE` | `{str: int}` | Hand evaluation, straight/pair detection, all rank comparisons |
| `BIG_BLIND` | `20` | Preflop sizing, raise-in-BB calculations |
| `CHIPS_PER_ROUND` | `5000` | Stack tracking, all-in pressure baseline |
| `OPP_HIGH_BID_THRESHOLD` | `200` | Postflop caution trigger after auction loss |
