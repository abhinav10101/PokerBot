# Helper Methods

> **File:** `player.py`  
> **Methods:** `Player._choose_raise_size()`, `Player._is_allin_pressure()`  
> **Purpose:** Small utility methods used throughout the decision logic to abstract common calculations.

---

## `_choose_raise_size(state, factor)` → `int`

```python
def _choose_raise_size(self, state: PokerState, factor: float) -> int:
    min_raise, max_raise = state.raise_bounds
    target = int(state.pot * factor)
    if target < min_raise: return min_raise
    if target > max_raise: return max_raise
    return target
```

### What it does

Computes a raise/bet size as a **fraction of the current pot**, then clamps it to the legal raise bounds provided by the game engine.

The formula:
```
target = floor(pot × factor)
result = clip(target, min_raise, max_raise)
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `state` | `PokerState` | Current game state; provides `pot` and `raise_bounds` |
| `factor` | `float` | Desired bet as a fraction of the pot (e.g., `0.65` = 65% pot) |

### Return value

An integer chip count that is the nearest legal bet to `factor × pot`.

### Factor reference

Every call to `_choose_raise_size` uses a different factor depending on the situation. Here is the complete list:

| Factor | Context |
|--------|---------|
| `3.0` | Premium preflop open-raise (3× pot) |
| `2.5` | Good preflop open-raise |
| `2.0` | Thin preflop open-raise with weak-but-playable hands |
| `size_mult + 0.3` ≈ `1.15` | Monster postflop hand (≥ 6) with information edge |
| `size_mult` = `0.85` | Strong postflop hand with information edge |
| `size_mult` = `0.65` | Standard postflop value bet (no information edge) |
| `size_mult − 0.1` ≈ `0.55` | Moderate value bet (made 4) |
| `1.0` | Re-raise with monster (made ≥ 6) facing a bet |
| `0.85` | Re-raise with strong flush facing a bet |
| `0.45` | Thin value bet (two pair / second pair) |
| `0.40` | Probe bet (information gathering after winning auction) |
| `0.35` | Semi-bluff with draw |

### Why pot-relative sizing?

Pot-relative bet sizing is standard in modern poker strategy because:
1. The bet communicates a consistent message to the opponent regardless of pot size
2. It scales naturally with the effective stack depth — large pots imply large stacks committed
3. It is harder for the opponent to exploit a consistent geometric sizing pattern

The `raise_bounds` clamp ensures the engine never receives an illegal action, which would result in a default fold in most frameworks.

---

## `_is_allin_pressure(state)` → `bool`

```python
def _is_allin_pressure(self, state: PokerState) -> bool:
    cost = state.cost_to_call
    if cost <= 0: return False
    if state.my_chips <= 0: return True
    return cost >= state.my_chips * 0.70 or cost >= 1500
```

### What it does

Determines whether the current calling decision is effectively an **all-in commitment** — meaning that calling would put most or all of the bot's chips at risk, and the decision framework should switch to a simplified binary call/fold evaluation.

### Logic

| Condition | Result | Reasoning |
|-----------|--------|-----------|
| `cost <= 0` | `False` | No cost to act; no pressure |
| `my_chips <= 0` | `True` | Bot is already all-in |
| `cost >= 0.70 × my_chips` | `True` | Calling commits ≥ 70% of remaining stack |
| `cost >= 1500 chips` | `True` | Absolute large-bet threshold regardless of stack fraction |

### Why two thresholds?

The **percentage threshold** (70%) catches situations where the pot-relative pressure is high even with a large stack. For example, if the bot has 3000 chips and faces a 2200-chip bet, `2200 / 3000 = 73%` triggers the flag.

The **absolute threshold** (1500) catches situations where even a moderate stack fraction represents a huge absolute number of chips. For example, a 5000-chip stack facing a 1500-chip bet is only 30% of stack — but 1500 chips is a material commitment that deserves the tighter call/fold evaluation.

### Effect on decision making

When `_is_allin_pressure` returns `True`, the normal layered postflop logic (with its pot-fraction call thresholds) is bypassed entirely in favour of the simplified table:

```
made ≥ 6           → Call (monster hand)
made = 5           → Call if equity ≥ 0.60 (or 0.55 on river)
made = 4 + premium → Call if equity ≥ 0.53–0.58
Everything else    → Fold
```

This prevents the bot from calling 2000-chip turn shoves with second pair just because `equity = 0.52 > pot_odds = 0.45`.

---

## Why These Methods Exist as Helpers

Both methods are called from **multiple places** in the codebase:

- `_choose_raise_size` is called in `_preflop_move`, `_postflop_move`, and `_defend_vs_steal`
- `_is_allin_pressure` is called at the top of both `_preflop_move` and `_postflop_move`

Centralising them ensures:
1. **Consistency** — every raise uses the same clamping logic; every all-in check uses the same thresholds
2. **Maintainability** — changing the all-in threshold from 70% to 65% requires one edit
3. **Readability** — call sites read as intent (`_is_allin_pressure(state)`) rather than implementation detail (`cost >= state.my_chips * 0.70 or cost >= 1500`)
