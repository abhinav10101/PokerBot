# `OpponentModel` Class

> **File:** `player.py`  
> **Purpose:** Accumulate and expose statistics about the opponent's tendencies over many hands, enabling the bot to adapt its strategy dynamically.

---

## Overview

`OpponentModel` is the bot's **memory**. Without it, the bot would treat every hand identically regardless of what it has observed. By tracking raise frequency, bet sizing, and auction behaviour over dozens of hands, the bot can:

- Widen its re-raising range against a loose-aggressive opponent
- Fold more against a jam-heavy opponent to avoid being exploited
- Calibrate auction bids to win information cheaply against passive bidders
- Stop overbidding in auctions when a spike-bidder pattern is detected

---

## Initialisation

```python
def __init__(self):
    self.hands = 0
    self.preflop_raise_count = 0
    self.preflop_raise_sizes = []
    self.auction_bids = []
    self.auction_attempts = 0
    self.auction_wins = 0
```

All counters start at zero. Lists are unbounded at init but are pruned by the recording methods to maintain rolling windows.

---

## State Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `hands` | `int` | Total hands observed. Denominator for all rate calculations. |
| `preflop_raise_count` | `int` | Number of hands where the opponent raised preflop. |
| `preflop_raise_sizes` | `list[int]` | Rolling window (max 60) of observed raise sizes in chips. |
| `auction_bids` | `list[int]` | Rolling window (max 80) of inferred opponent auction bids. |
| `auction_attempts` | `int` | Hands where the auction street was reached. |
| `auction_wins` | `int` | Hands where the bot won the auction (opponent's card was revealed). |

### Why rolling windows?

A rolling window (rather than a full-history average) means the model responds to **recent behaviour changes**. If an opponent starts the session tight and becomes looser, the model will detect this within ~60 hands rather than remaining anchored to the early tight profile.

---

## Methods

### `hand_start()`

```python
def hand_start(self):
    self.hands += 1
```

Called once at the start of every hand. Increments the hand counter so all frequency-based properties remain correctly denominated. Without this, `raise_frequency` would divide by zero or produce inflated rates.

---

### `record_preflop_raise(size)`

```python
def record_preflop_raise(self, size: int):
    self.preflop_raise_count += 1
    self.preflop_raise_sizes.append(size)
    if len(self.preflop_raise_sizes) > 60:
        self.preflop_raise_sizes.pop(0)
```

Records a preflop raise of `size` chips. The size list is pruned to the last 60 entries.

**What "recording a raise" enables:**
- `preflop_raise_count` feeds `raise_frequency` → drives steal-heavy classification
- `preflop_raise_sizes` feeds `avg_raise_size` → drives jam-bot classification

**Note:** The bot calls this in `_preflop_move` only on the **first raise per hand** (guarded by `_opp_raised_preflop_this_hand`). This prevents double-counting re-raises and inflating the raise frequency.

---

### `record_auction_bid(bid)`

```python
def record_auction_bid(self, bid: int):
    self.auction_bids.append(bid)
    if len(self.auction_bids) > 80:
        self.auction_bids.pop(0)
```

Appends an inferred opponent bid to the rolling window, capped at 80 entries.

**How bids are inferred:** See [`docs/07_auction_strategy.md`](./07_auction_strategy.md) for the inference algorithm. The bid may be exact (when we won the auction) or a lower-bound proxy (when we lost).

---

### `record_auction_outcome(we_won)`

```python
def record_auction_outcome(self, we_won: bool):
    self.auction_attempts += 1
    if we_won:
        self.auction_wins += 1
```

Updates the win/loss tally for the auction. Currently feeds `auction_win_rate`, which is available as a diagnostic but not yet used in decision logic.

---

## Computed Properties

### `raise_frequency`

```python
@property
def raise_frequency(self) -> float:
    return self.preflop_raise_count / max(1, self.hands) if self.hands >= 5 else 0.2
```

The fraction of hands where the opponent raised preflop.

- Returns a neutral default of `0.2` until at least 5 hands have been observed, preventing early over-reaction to a single aggressive hand.
- At 5+ hands, this becomes the live frequency used by all the steal/raiser flags.

**Contribution to winning:** This single number drives a large branch of the preflop decision tree. A frequency above 0.30 triggers steal-defence; above 0.45 triggers hyper-aggressive defence.

---

### `is_steal_heavy` / `is_very_steal_heavy`

```python
@property
def is_steal_heavy(self) -> bool:
    return self.raise_frequency > 0.30 and self.hands >= 20

@property
def is_very_steal_heavy(self) -> bool:
    return self.raise_frequency > 0.45 and self.hands >= 20
```

| Flag | Threshold | Required sample | Effect |
|------|-----------|-----------------|--------|
| `is_steal_heavy` | freq > 30% | ≥ 20 hands | Trigger `_defend_vs_steal` |
| `is_very_steal_heavy` | freq > 45% | ≥ 20 hands | Call even strength-2 hands vs small raises |

The 20-hand minimum prevents false classification during the cold-start phase when only a handful of raises have been seen. An opponent who raises 3/3 hands has `raise_frequency = 1.0` but shouldn't be classified as steal-heavy until the pattern persists.

---

### `is_moderate_raiser`

```python
@property
def is_moderate_raiser(self) -> bool:
    return 0.18 <= self.raise_frequency <= 0.50 and self.hands >= 15
```

Identifies an opponent who raises at a realistic but non-extreme frequency. When true, the preflop logic applies a **size-aware filter**: small raises (≤ 4BB) permit wider calls; larger raises require stronger holdings. This handles the large middle-ground of opponents who are neither nits nor maniacs.

---

### `avg_raise_size` / `is_jam_bot`

```python
@property
def avg_raise_size(self) -> float:
    return sum(self.preflop_raise_sizes) / len(self.preflop_raise_sizes) \
           if self.preflop_raise_sizes else 60.0

@property
def is_jam_bot(self) -> bool:
    return self.avg_raise_size >= 1500 and len(self.preflop_raise_sizes) >= 5
```

`is_jam_bot` identifies an opponent that always (or nearly always) shoves preflop. Against such an opponent:
- The bot only calls with hands rated **9–10** (premium holdings)
- Strength 9 calls are further gated on the cost being ≤ 60% of stack
- Everything else folds

**Why 1500 chips?** With a 5000-chip starting stack, a 1500-chip average raise represents a 30%+ stack commitment — effectively a push/fold strategy. Calling this range with marginal hands is a losing play against any reasonable range.

---

### Auction Bid Statistics

#### `opp_bid_p75` / `opp_bid_p90`

```python
@property
def opp_bid_p75(self) -> int:
    if not self.auction_bids: return 50
    sb = sorted(self.auction_bids)
    return sb[int(len(sb) * 0.75)]

@property
def opp_bid_p90(self) -> int:
    if not self.auction_bids: return 60
    sb = sorted(self.auction_bids)
    return sb[int(len(sb) * 0.90)]
```

The 75th and 90th percentile of the opponent's inferred bid distribution.

- **p75** is used as the primary bid ceiling in `_auction_bid()` when ≥ 10 bids have been seen. Bidding just above p75 means the bot wins ~75% of auctions at minimum cost.
- **p90** is used for passive bidders — the extra headroom ensures winning almost every auction against an opponent who rarely bids high.

Default values (50 and 60) represent a neutral prior before any data is collected.

---

#### `opp_bid_avg`

```python
@property
def opp_bid_avg(self) -> float:
    return sum(self.auction_bids) / len(self.auction_bids) \
           if self.auction_bids else 30.0
```

Mean bid. Used only in `is_spike_bidder` to detect a pattern where the average is low but occasional large bids occur.

---

#### `is_passive_bidder`

```python
@property
def is_passive_bidder(self) -> bool:
    return len(self.auction_bids) >= 8 and self.opp_bid_p75 <= 12
```

An opponent who almost never bids more than 12 chips at the 75th percentile. Against this profile, the bot can win almost every auction for just above p90 — often as little as 13–15 chips — and gain an enormous information edge at near-zero cost.

---

#### `is_spike_bidder`

```python
@property
def is_spike_bidder(self) -> bool:
    if len(self.auction_bids) < 10: return False
    return self.opp_bid_avg <= 50 and max(self.auction_bids) >= 100
```

An opponent who usually bids low but occasionally places a very large bid. If the bot naively targets p75, it might encounter one of these spikes and overpay. The response is to **cap the bot's own bid at 80 chips** regardless of information value — accepting that some auctions will be lost rather than being drawn into an arms race.

---

#### `auction_win_rate`

```python
@property
def auction_win_rate(self) -> float:
    return self.auction_wins / max(1, self.auction_attempts)
```

Historical auction win fraction. Available as a diagnostic metric. Not currently used directly in decision logic, but available for future features such as dynamic bid scaling based on observed win rate.

---

## Data Flow Summary

```
hand_start()
    └─► hands += 1

_preflop_move() observes raise
    └─► record_preflop_raise(size)
            └─► raise_frequency
                    ├─► is_steal_heavy → _defend_vs_steal()
                    ├─► is_very_steal_heavy → call weaker hands
                    ├─► is_moderate_raiser → size-aware preflop filter
                    └─► is_jam_bot → strict all-in calling range

_infer_opp_bid() after auction
    └─► record_auction_bid(inferred_bid)
            └─► opp_bid_p75/p90
                    ├─► is_passive_bidder → snipe just above p90
                    ├─► is_spike_bidder → cap bid at 80
                    └─► n≥10 bids → bid p75 + 2

on_hand_end()
    └─► record_auction_outcome(we_won)
            └─► auction_win_rate (diagnostic)
```
