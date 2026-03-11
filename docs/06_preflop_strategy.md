# Preflop Strategy — `_preflop_move()`

> **File:** `player.py`  
> **Method:** `Player._preflop_move(state, game_info)`  
> **Purpose:** Decide whether to fold, call, or raise before the flop, using hand strength, opponent profile, and pot economics.

---

## Overview

The preflop decision is a layered priority tree. Each layer is checked in order; the first matching condition produces the action. The layers are:

```
1. All-in pressure (jam-shove situations)
2. Steal-heavy opponent detected
3. Moderate raiser detected
4. Large raise (> 300 chips)
5. Normal raise (> BB)
6. No raise (open/limp)
7. Default fallback
```

---

## Setup

```python
strength = preflop_strength(state.my_hand)
cost = state.cost_to_call
my_chips = state.my_chips
```

Before anything else:
- `strength` is the discrete 1–10 hand score from `preflop_strength()`
- A preflop raise by the opponent is recorded (once per hand) into `OpponentModel`:

```python
if cost > BIG_BLIND and not self._opp_raised_preflop_this_hand:
    self._opp_raised_preflop_this_hand = True
    self.opp_model.record_preflop_raise(cost)
```

The `_opp_raised_preflop_this_hand` guard ensures this fires only on the first raise — not on subsequent re-raises — so the frequency count isn't double-inflated.

---

## Layer 1: All-In Pressure

```python
if self._is_allin_pressure(state):
    ...
```

`_is_allin_pressure()` returns True when the cost to call is ≥ 70% of the bot's stack, or ≥ 1500 chips absolute. In these spots, calling is a major commitment and the normal "call if equity is good" logic becomes inappropriate — the decision is binary.

### Against a `jam_bot` (avg raise ≥ 1500 chips)

| Strength | Action |
|----------|--------|
| 10 | Call |
| 9 + cost ≤ 60% stack | Call |
| Anything else | Fold |

The `is_jam_bot` path is intentionally tighter. A jam-bot pushes preflop constantly, so its range includes many weak hands. However, the bot should still only call with a genuine advantage — not with "decent" hands that are coin-flip or slightly behind.

### Against general all-in pressure (not jam-bot)

| Strength | Action |
|----------|--------|
| ≥ 9 | Call (or raise min if possible) |
| ≥ 8 + cost ≤ 60% stack | Call |
| Anything else | Fold |

---

## Layer 2: Steal-Heavy Opponent (`_defend_vs_steal`)

```python
if self.opp_model.is_steal_heavy and cost > BIG_BLIND:
    return self._defend_vs_steal(state, strength, cost, my_chips)
```

Triggered when the opponent raises preflop at > 30% frequency over ≥ 20 hands. The idea: a player raising this often is not exclusively raising strong hands. The bot should **widen its 3-bet range** and call more liberally.

```python
def _defend_vs_steal(self, state, strength, cost, my_chips):
    raise_in_bb = cost / BIG_BLIND
```

| Strength | Condition | Action |
|----------|-----------|--------|
| ≥ 8 | Any | 3-bet to 3.5× raise size |
| ≥ 6 | raise ≤ 5BB | 3-bet to 3× raise size |
| ≥ 4 | Any | Call |
| ≥ 3 | raise ≤ 3.5BB | Call |
| ≥ 2 | `is_very_steal_heavy` + raise ≤ 3.5BB | Call |
| < 2 | Any | Fold |

**Why 3-bet sizes of 3–3.5×?** Against a loose raiser, 3-betting too small invites them to call with a wide range; 3-betting large forces them to commit chips as a bluff or fold weak hands. The multipliers are calibrated to be unprofitable for the opponent to continue with speculative holdings.

**Why call with strength 2 against `is_very_steal_heavy`?** When an opponent raises > 45% of hands, calling with any two reasonable cards becomes positive EV because the opponent's range is so diluted that even a marginal hand has enough equity.

---

## Layer 3: Moderate Raiser

```python
if self.opp_model.is_moderate_raiser and cost > BIG_BLIND:
    raise_in_bb = cost / BIG_BLIND
    if raise_in_bb <= 4.0:
        # Small raise: call with strength ≥ 5
        ...
    else:
        # Bigger raise: need strength ≥ 6
        ...
```

A moderate raiser (18–50% frequency, ≥ 15 hands) deserves differentiated treatment based on raise size:

| Raise size | Call threshold |
|------------|---------------|
| ≤ 4BB (standard open) | Strength ≥ 5 |
| > 4BB (strong raise signal) | Strength ≥ 6 |

Larger raise sizes from a moderately aggressive opponent carry more information — they're more likely to hold a real hand — so the bot requires a stronger holding to continue.

---

## Layer 4: Large Raise (> 300 chips)

```python
if cost > 300:
    if strength >= 9: raise all-in or call
    if strength >= 7: call
    return fold
```

A raise over 300 chips (15BB) signals a very strong hand or a large bluff. The bot:
- Goes all-in with premium hands (strength 9–10) to maximise value
- Calls with strong hands (7–8) that have good equity but don't warrant a shove
- Folds everything else

---

## Layer 5: Standard Raise (> BB)

```python
if cost > BIG_BLIND:
    if strength >= 9:
        target = min(int(cost * 3), raise_bounds[1])
        return ActionRaise(...)   # 3-bet
    if strength >= 7:
        if cost <= 100:
            target = min(int(cost * 2.8), ...)
            return ActionRaise(...)  # 3-bet smaller
        return ActionCall()
    if strength >= 5: return ActionCall()
    return ActionFold()
```

The standard response to a typical open raise:

| Strength | Action |
|----------|--------|
| ≥ 9 | 3-bet to 3× raise |
| ≥ 7 + raise ≤ 100 chips | 3-bet to 2.8× raise |
| ≥ 7 + raise > 100 chips | Call |
| ≥ 5 | Call |
| < 5 | Fold |

The 3-bet size of 3× is a standard in-position 3-bet. When the original raise was larger (> 100), a proportional 3× bet might put too many chips in, so the bot calls instead and plays postflop.

---

## Layer 6: No Raise (Open / Limp Situation)

```python
if cost == 0:
    if state.can_act(ActionRaise):
        if strength >= 8: return ActionRaise(self._choose_raise_size(state, 3.0))
        if strength >= 6: return ActionRaise(self._choose_raise_size(state, 2.5))
        if strength >= 5: return ActionRaise(self._choose_raise_size(state, 2.0))
    if state.can_act(ActionCheck): return ActionCheck()
```

When no one has raised (or the bot is first to act), it uses a straightforward open-raise strategy:

| Strength | Open-raise size |
|----------|----------------|
| ≥ 8 | 3.0× pot |
| ≥ 6 | 2.5× pot |
| ≥ 5 | 2.0× pot |
| < 5 | Check |

The declining multipliers reflect that weaker opening hands should raise smaller to risk less when they don't hit the flop.

---

## Layer 7: Default (Limp Call)

```python
if state.can_act(ActionRaise):
    if strength >= 8: return ActionRaise(...)
    if strength >= 6: return ActionRaise(...)
if state.can_act(ActionCall):
    if strength >= 4: return ActionCall()
    if cost <= BIG_BLIND: return ActionCall()
    return ActionFold()
if state.can_act(ActionCheck): return ActionCheck()
return ActionFold()
```

The final fallback handles edge cases (limped pots, etc.):
- Raise with strong hands
- Call with strength ≥ 4 or if the cost is just the big blind
- Fold otherwise

---

## Preflop Decision Summary

```
All-in pressure?
    ├─ jam_bot → call only 9–10
    └─ general → call 8–9+, fold rest

Steal-heavy opp?
    └─ 3-bet 8+, call 3–6, fold rest

Moderate raiser?
    └─ size-dependent: call 5+ (small) or 6+ (big)

No profile yet / default:
    ├─ Large raise (>300): call 7+, fold rest
    ├─ Normal raise: 3-bet 9+, call 5+, fold rest
    └─ No raise: open 3× with 8+, 2.5× with 6+, check otherwise
```
