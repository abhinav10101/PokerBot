# Equity & Hand Strength Functions

> **File:** `player.py`  
> **Purpose:** Evaluate the strength of the current hand — both in absolute terms (preflop) and relative to the board and opponent (postflop).

---

## `eval_hand(my_hand, community, opp_known, iterations=48)`

```python
def eval_hand(my_hand, community, opp_known=None, iterations=48):
```

### What it does

Runs a **Monte Carlo equity simulation** to estimate the probability that the hero's hand wins at showdown. For each of `iterations` trials, it randomly deals the missing cards (opponent hole cards and remaining board cards) and compares hand scores using `eval7`.

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `my_hand` | `list[str]` | Hero's two hole cards, e.g. `["Ah", "Kd"]` |
| `community` | `list[str]` | Board cards seen so far (0–5 cards) |
| `opp_known` | `list[str]` | Opponent's revealed cards from auction (0–1 cards) |
| `iterations` | `int` | Number of random completions to sample (default: 48) |

### Return value

A float in `[0.0, 1.0]` representing win equity. A tie counts as `0.5`.

### Algorithm

```
1. dead = hero cards ∪ board ∪ known opponent cards
2. residual deck = all 52 cards − dead
3. need = (2 − len(opp_known)) + (5 − len(board))
4. for each trial:
     draw = random.sample(residual_deck, need)
     opp_hand = opp_known + draw[:opp_need]
     full_board = board + draw[opp_need:]
     score_hero = eval7.evaluate(hero + full_board)
     score_opp  = eval7.evaluate(opp + full_board)
     wins += 1.0 if hero wins, 0.5 if tie
5. return wins / iterations
```

### Fallback behaviour

If `eval7` is not installed, if the hand list is malformed, or if any exception occurs, the function returns `0.5` (dead-even). This prevents crashes in degraded environments — the bot will still act, just without simulation-based guidance.

### Why 48 iterations?

48 is a balance between speed and accuracy. At 48 samples:
- Standard error ≈ `0.5 / √48 ≈ 0.072` (about ±7 percentage points)
- Sufficient to distinguish strong equity (>0.65) from weak equity (<0.45) reliably
- Fast enough to run on every postflop action without lag

For higher-stakes or final-table scenarios, increasing to 200+ iterations would significantly improve accuracy.

### Strategic role

Every postflop call, fold, and raise decision uses this value as its primary signal. The raw equity is then modified by:
- `hidden_card_equity_discount()` — subtracts penalty when opponent holds an unknown strong card
- Danger discounts from `revealed_card_danger()` — subtracts up to 0.18 based on threat level

---

## `preflop_strength(cards)` → `int` ∈ `[1, 10]`

```python
def preflop_strength(cards: list[str]) -> int:
```

### What it does

Classifies the hero's two hole cards into a discrete strength score from **1 (weakest) to 10 (strongest)** before any community cards are seen. This is used instead of Monte Carlo simulation preflop because preflop equity is primarily determined by a well-understood hand hierarchy, and the lookup is orders of magnitude faster.

### Scoring criteria

The function extracts the two rank values and the suitedness flag, then applies a decision tree:

#### Pairs

| Hand | Score |
|------|-------|
| AA, KK, QQ, JJ | 10 |
| TT, 99, 88 | 9 |
| 77, 66, 55 | 8 |
| 44, 33, 22 | 7 |

#### Ace-X hands

| Hand | Score |
|------|-------|
| AK (any) | 10 |
| AQs | 9 |
| AQo | 8 |
| AJs | 8 |
| AJo | 7 |
| ATs | 7 |
| ATo | 6 |
| A9s | 6 |
| A9o | 5 |
| Ax suited | 5 |
| Ax offsuit | 4 |

#### Broadway and connectors

| Hand | Score |
|------|-------|
| KQs / KJs | 8 |
| KQo / KJo | 7 |
| KTo or QJo | 6 |
| QTs / JTs | 6–7 |
| Suited connectors (T+, gap ≤ 2) | 5 |
| Suited connectors (9+, gap ≤ 1) | 4 |
| T8+, medium broadways | 3–4 |
| Everything else | 2 |

### How scores drive preflop actions

| Score range | Default action |
|-------------|---------------|
| 9–10 | Open-raise 3× pot; re-raise all-in vs steal |
| 7–8 | Open-raise 2.5×; call or re-raise raises |
| 5–6 | Open-raise 2×; call cheap raises |
| 3–4 | Call only if cheap (≤ BB); fold to raises |
| 1–2 | Fold to any raise; check if free |

---

## `postflop_hand_strength(cards)` → `(int, bool, bool)`

```python
def postflop_hand_strength(cards: list[str]) -> tuple[int, bool, bool]:
```

### What it does

Classifies the hero's current made hand and detects drawing potential. The input `cards` is the **hero's hole cards concatenated with the board** (minimum 5 cards to be meaningful). Returns a 3-tuple:

- `made` — integer hand rank (1–7)
- `has_flush_draw` — True if 4+ cards of one suit are present
- `has_straight_draw` — True if 4 connected cards form a straight draw

### Made hand ranks

| Rank | Hand | Example |
|------|------|---------|
| 7 | Quads (four of a kind) | `AAAA x` |
| 6 | Full house | `AAA KK` |
| 5 | Flush or straight | `As Ks 9s 7s 2s` or `A K Q J T` |
| 4 | Trips **or** top pair (hole card pairs top board card) | `A A A x x` or hero has `Ah`, board top is `As` |
| 3 | Two pair **or** second pair | Two distinct pairs, or hero's hole card pairs board's second card |
| 2 | Weak pair (board pair or low hole-card pair) | Board shows `K K`, hero has unrelated cards |
| 1 | High card | No pair or better |

### Context-aware pair hierarchy

The pair classification is not just mechanical — it accounts for **who made the pair** and **how strong it is relative to the board**:

```
Pair detected:
  └─ Did one of hero's hole cards contribute?
       YES → Is the paired rank ≥ top board card?
              YES → rank = 4 (top pair — strong)
              NO  → rank = 3 (second pair — moderate)
       NO  (board-only pair) → rank = 2 (weak, shared pair)
```

**Why this matters:** A board-only pair (e.g., two kings on board) means the opponent "has" that pair too by default. The hero gets no advantage from it. Treating it as a strong made hand would cause over-calling with junk.

### Flush draw detection

```python
has_flush_draw = any(v >= 4 for v in suit_counts.values())
```

If any suit appears 4 or more times across all available cards, a flush draw is present. Note that 5+ of a suit means a **made flush** (`made = 5`) — the draw flag is still set but the made rank takes precedence.

### Straight draw detection

```python
def _has_straight_draw(rank_vals):
    uniq = sorted(set(rank_vals))
    if 14 in uniq: uniq.append(1)  # low ace for wheel draws
    for i in range(len(uniq) - 3):
        if uniq[i + 3] - uniq[i] == 3: return True
    return False
```

Scans for any 4 unique rank values that span exactly 3 (i.e., no gaps, or a single-gap gutshot). The low ace (1) is appended to detect wheel draws (A-2-3-4).

### Made straight detection

```python
def _is_made_straight(rank_vals):
    uniq = sorted(set(rank_vals))
    if 14 in uniq: uniq.append(1)
    for i in range(len(uniq) - 4):
        if uniq[i + 4] - uniq[i] == 4: return True
    return False
```

Checks for 5 consecutive unique rank values spanning exactly 4. Sets `made = 5` when true.

### How draws modify decisions

Draw flags widen the bot's calling and betting ranges significantly:

| Draw type | Max call (fraction of pot) |
|-----------|--------------------------|
| Flush draw + straight draw (combo) | 50% |
| Flush draw only | 38% |
| Straight draw only | 33% |
| Any draw | 28% |

Semi-bluff bets are also triggered when `has_draw` is True and effective equity ≥ 0.42 (not on the river, where the draw is dead).

---

## Summary: Function Interaction

```
preflop_strength(hand)
    └─► used in: _preflop_move(), _postflop_move() (is_premium flag)

postflop_hand_strength(hand + board)
    └─► made, flush_draw, straight_draw
            ├─► made  → main hand-rank gate for all postflop calls/bets
            ├─► flush_draw / straight_draw → draw call ranges, semi-bluffs
            └─► made == 4/5 + flush flags → non-nut flush caution

eval_hand(hand, board, opp_known)
    └─► raw_equity
            └─► equity = raw_equity − hidden_card_discount
                    └─► eff_equity = equity − danger_discounts
                            └─► compared against pot_odds + thresholds
```
