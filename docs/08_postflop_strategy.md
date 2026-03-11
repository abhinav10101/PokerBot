# Postflop & River Strategy

> **File:** `player.py`  
> **Methods:** `Player._postflop_move()`, `Player._river_decision()`  
> **Purpose:** Make bet/call/fold decisions on the flop, turn, and river, integrating hand strength, Monte Carlo equity, danger assessment, and auction context.

---

## Overview

Postflop play is the most complex part of the bot's decision making. Every action combines:

1. **Made hand rank** (1–7) from `postflop_hand_strength()`
2. **Monte Carlo equity** from `eval_hand()`, adjusted by danger and hidden-card discounts
3. **Opponent model flags** — has a high bid won? Is there a dangerous revealed card?
4. **Probe/information bet state** — did we win the auction? Did the opponent call our probe?
5. **Pot-fraction economics** — is the call size reasonable relative to the pot?

---

## `_postflop_move(state, game_info, street)`

### Input Computation

```python
cards = state.my_hand + state.board
made, flush_draw, straight_draw = postflop_hand_strength(cards)
raw_equity = eval_hand(state.my_hand, state.board, opp_known=opp_revealed, iterations=48)
equity_discount = hidden_card_equity_discount(opp_revealed)
equity = raw_equity - equity_discount
pf_str = preflop_strength(state.my_hand)
is_premium = pf_str >= 7
danger = revealed_card_danger(opp_revealed, state.board, state.my_hand) if opp_revealed else 0
i_have_flush, i_have_nut_flush = get_flush_info(state.my_hand, state.board)
i_have_non_nut_flush = i_have_flush and not i_have_nut_flush
fh_danger = board_has_fullhouse_danger(state.board) and made == 4 and len(opp_revealed) < 2
```

All postflop logic is grounded in these values. The layered adjustments from raw to effective equity:

```
raw_equity = Monte Carlo simulation
equity     = raw_equity − hidden_card_discount
eff_equity = equity − (0.10 if danger ≥ 2 else 0) − (0.08 if danger ≥ 3 else 0)
```

---

## Priority Layer 1: All-In Pressure

```python
if self._is_allin_pressure(state):
    ...
```

When the cost to call is ≥ 70% of the bot's stack or ≥ 1500 chips, normal pot-fraction logic breaks down. The decision becomes binary — either the bot commits or it folds.

| Made hand | Condition | Action |
|-----------|-----------|--------|
| ≥ 6 | Always | Call |
| 5 (non-nut flush) | equity < 0.58 | Fold |
| 5 (nut flush / straight) | equity ≥ 0.60 | Call |
| 4 | equity ≥ 0.58 + danger ≤ 1 + no FH risk | Call |
| Premium preflop hand | equity ≥ 0.53 + danger ≤ 1 | Call |
| Anything else | — | Fold |

---

## Priority Layer 2: River Delegation

```python
if street == "river" and cost > 0:
    return self._river_decision(...)
```

River decisions when facing a bet are handled by a dedicated method (see below). River check-and-bet logic follows the normal postflop flow.

---

## Priority Layer 3: Effective Equity Calculation

```python
eff_equity = equity
if danger >= 2: eff_equity -= 0.10
if danger >= 3: eff_equity -= 0.08
```

Applies danger-level discounts to the simulation equity. A danger-3 spot applies a combined **−0.18** penalty, reflecting that the revealed card very likely improves the opponent into a dominant hand.

---

## Priority Layer 4: Opponent High-Bid Postflop Adjustments

When `_opp_high_bid_won` is True (opponent bid ≥ 200 and won the auction), the bot assumes a premium opponent range and applies tighter fold thresholds:

### Flop adjustments

| Bet size (fraction of pot) | Bot's hand | Action |
|---|---|---|
| ≥ 80% | made < 5 | Fold |
| ≥ 40% | made < 4 | Fold |
| ≥ 40% | made = 4 + eff_equity < 0.55 | Fold |

### Turn adjustments

| Bet size | Bot's hand | Action |
|---|---|---|
| ≥ 60% | made < 4 | Fold |
| ≥ 60% | made = 4 + eff_equity < 0.58 | Fold |

**Why?** An opponent willing to spend 200+ chips to see our card believes they have a very strong holding. Their range on the flop and turn is compressed toward premium hands — large bets from this range deserve more respect than the same bet from an unknown range.

---

## Priority Layer 5: Large Turn Bet Protection

```python
if street == "turn":
    if cost > 1500 and made < 6: fold (unless premium + equity ≥ 0.48)
    if cost > 800 and made < 5: fold (unless premium + equity ≥ 0.48)
    if cost > 600 and made < 5 and danger >= 2: fold
```

Turn bets above these thresholds represent a very heavy commitment. The guards allow premium preflop hands (strength ≥ 7) with reasonable equity to continue — but otherwise fold even medium-strength hands.

---

## Priority Layer 6: Standard Equity Folds

```python
if made < 4 and not has_draw:
    if eff_equity < pot_odds + 0.05:
        return ActionFold()
```

`pot_odds = cost / (pot + cost)` — the minimum equity to break even on a call. The bot requires **5 percentage points above pot odds** as a margin before calling with weak hands without a draw. This small buffer accounts for the simulation error in equity estimates.

Additional quick folds:
- `made == 2 + danger ≥ 2 + bet > 50% pot` → fold (weak pair threatened)
- `made == 3 + danger ≥ 2` → fold (two pair is vulnerable)

---

## Priority Layer 7: Betting Logic (When Facing No Cost)

When `cost == 0`, the bot evaluates whether to bet. This is either:
- A **probe/information bet** (after winning the auction), or
- A **standard value/semi-bluff bet**

### Probe bets (auction winner)

```python
if self._won_auction_this_hand and street != 'river' and not opp_paid_high:
    if made >= 4 and not fh_danger:
        bet_size = self._choose_raise_size(state, size_mult)
        self._probe_bet_street = street
        return ActionRaise(bet_size)
    elif made >= 1 and danger <= 1:
        probe_size = self._choose_raise_size(state, 0.40)
        self._probe_bet_street = street
        return ActionRaise(probe_size)
```

After winning the auction, the bot has a revealed card to guide its play. It bets with:
- **Made ≥ 4:** Full value bet (size_mult × pot)
- **Any hand, low danger:** Small probe (40% pot) to gather information and potentially push the opponent off weak holdings

The `_probe_bet_street` is recorded. If the opponent calls and the bot is on a later street (`_opp_called_probe = True`), it stops bluffing with weak hands on that later street.

### Information-edge size multiplier

```python
info_edge = len(opp_revealed) > 0 and danger <= 1
size_mult = 0.85 if info_edge else 0.65
```

When the bot has an information edge (it knows one of the opponent's cards and that card isn't dangerous), it bets slightly larger (0.85 vs 0.65 × pot). The logic: when you know your equity is high, extract more value.

### Standard value and semi-bluff bets

| Made hand | Condition | Bet size |
|-----------|-----------|----------|
| ≥ 6 (monsters) | Always | `(size_mult + 0.3)` × pot |
| 5 (flush/straight) | equity ≥ 0.65, not non-nut flush | `size_mult` × pot |
| ≥ 4 (trips/top pair) | Not FH-dangerous | `(size_mult − 0.1)` × pot |
| 3 (two pair) | equity ≥ 0.52, not opp-paid-high | `0.45` × pot |
| Draw (flush/straight) | equity ≥ 0.42, not river | `0.35` × pot |

**Note on suppressed bets:**
- Non-nut flush: never bet proactively (fear of being raised by nut flush)
- Full-house danger on turn/river with made=4: check back to avoid building pot vs. full house
- `_opp_called_probe` on a later street with made < 4: stop bluffing

### Re-raise logic (facing a bet)

When the bot faces a bet AND has a raising opportunity:

| Made hand | Condition | Action |
|-----------|-----------|--------|
| ≥ 6 | cost ≤ 60% pot | Raise to 1.0 × pot |
| 5 | equity ≥ 0.72, cost ≤ 50% pot, not non-nut flush | Raise to 0.85 × pot |

Only very strong hands raise for value when facing a bet — the rest call or fold.

---

## Priority Layer 8: Calling Logic

```python
if state.can_act(ActionCall):
    if cost <= 0: return ActionCheck()
    ...
```

Calls are evaluated by a made-hand rank gate followed by a pot-fraction test:

| Made hand | Max call size | Extra conditions |
|-----------|---|---|
| ≥ 6 | Unconditional | Always call |
| 5 (nut flush/straight) | 1.5× pot | equity ≥ 0.58; else 40% if non-nut |
| 4 (trips/top pair) | 1.0× pot | equity ≥ 0.52; fold if FH risk or danger ≥ 2 and bet > 50% |
| 3 (two pair) | 25% of pot | Fold if danger ≥ 2 |
| 2 (weak pair) | 15% of pot | Fold if danger ≥ 1; call only if premium + equity ≥ 0.50 |
| Draw (combo) | 50% of pot | flush + straight |
| Draw (flush) | 38% of pot | |
| Draw (straight) | 33% of pot | |
| Any draw | 28% of pot | |

If none of these match, the bot folds.

---

## `_river_decision(state, made, equity, ...)`

The river is handled separately from the flop/turn because:
- No more cards to come: implied odds are zero; pot odds are the only consideration
- Missed draws are dead weight — folding is almost always correct with no made hand
- Bet sizes tend to be larger (players polarise on the river)

### River all-in threshold

```python
is_river_allin = cost >= 2500 or (state.my_chips > 0 and cost >= state.my_chips * 0.65)
```

This is slightly lower than the preflop/turn threshold (65% of stack vs 70%) because the river is the last street — there is no future to protect chips for.

| Hand | Condition | Action |
|------|-----------|--------|
| ≥ 6 | Any | Call |
| 5 non-nut flush | equity < 0.60 | Fold |
| 5 (nut/straight) | equity ≥ 0.55 | Call |
| Anything else | — | Fold |

### Normal river calls (non-all-in)

| Made | Condition | Max bet to call |
|------|-----------|----------------|
| ≥ 6 | Always | 2× pot |
| 5 (nut) | danger ≤ 1 + equity ≥ 0.62 | 1.2× pot |
| 5 (non-nut) | Always | 40% of pot |
| 4 | No FH risk + no danger + equity ≥ 0.70 | 55% of pot |
| 3 | danger = 0 + equity ≥ 0.75 | 30% of pot |
| < 3 | — | Fold |

**Why the tight thresholds on the river?** The river is a **read-and-react** street. The opponent's bet communicates strong information about their hand. The bot requires high equity thresholds (0.70–0.75) for medium hands because these equity estimates come with ≈7% simulation error — a "0.68 equity" hand might be a 0.61 in reality, which is below the 0.70 call threshold.

---

## Complete Postflop Decision Flow

```
_postflop_move()
│
├─1─ All-in pressure → simplified call/fold table
├─2─ River + cost > 0 → _river_decision()
├─3─ Apply danger discounts to equity
├─4─ Opp high bid won → tighter fold thresholds
├─5─ Large turn bets → fold guards
├─6─ Weak hand below pot odds → fold
│
├─7─ can_act(Raise) and cost == 0:
│       ├─ Won auction → probe bet
│       └─ Standard value/semi-bluff bet table
│
├─7─ can_act(Raise) and cost > 0:
│       └─ Re-raise with ≥ 6 or strong flush
│
├─8─ can_act(Call):
│       └─ Made-hand rank × pot-fraction table
│
└─9─ Check / Fold (default)
```
