# Danger & Board Texture Functions

> **File:** `player.py`  
> **Purpose:** Assess how threatening the board and the opponent's (partially revealed) hole cards are, and apply equity adjustments accordingly.

---

## Overview

When an auction occurs, information asymmetry is introduced:

- If the bot **wins** the auction: one of the opponent's hole cards is revealed. The hidden card is unknown but the bot can estimate its threat level.
- If the bot **loses** the auction: one opponent card is revealed to both players. This card may directly threaten the bot's hand.

These four functions convert those information states into actionable numeric scores that feed directly into call/fold thresholds.

---

## `revealed_card_danger(revealed_cards, board, my_hand)` → `int` ∈ `[0, 3]`

```python
def revealed_card_danger(revealed_cards: list[str], board: list[str], my_hand: list[str] = None) -> int:
```

### What it does

When the bot loses the auction, the opponent's revealed card is publicly known. This function scores how much of a threat that card poses to the bot's current holding. A higher score means the bot should be more defensive (fold sooner to bets, discount equity more heavily).

### Scoring components

Each component adds points, and the total is capped at **3**:

#### 1. Board-rank pairing (+2)

```python
if board_ranks.count(rev_rank) >= 1:
    danger += 2
```

If the revealed card's rank already appears on the board, the opponent may hold **trips or quads**. This is the most severe danger because it completely dominates two-pair and straight holdings. The +2 weight reflects how catastrophically this changes the hand matchup.

**Example:** Board is `K♠ K♦ 7♣`. Revealed card is `K♥`. The opponent holds `K?` — nearly certainly quads or a monster full house.

#### 2. Flush suit (+1)

```python
if board_suits.count(rev_suit) >= 2:
    danger += 1
```

If the revealed card's suit already appears ≥ 2 times on board, the opponent may be completing a flush on the turn or river. Combined with a flush draw on the board, this is a credible threat.

#### 3. Straight connectivity (+1)

```python
if sum(1 for bv in board_vals if abs(bv - rev_val) <= 2) >= 2:
    danger += 1
```

If 2+ board cards are within 2 pips of the revealed card, the opponent may have strong straight connectivity. This catches both open-ended draws and gutshots.

#### 4. High overcard (+1)

```python
if rev_val >= 13 and rev_val not in board_vals:
    if my_hand:
        my_made, _, _ = postflop_hand_strength(my_hand + board)
        if my_made < 2:
            danger += 1
```

If the revealed card is a King or Ace not already on the board, and the bot currently has no pair or better, the opponent's high card may dominate entirely. The `my_hand` guard ensures this only fires when the bot is genuinely behind.

### How danger is used downstream

| Danger level | Effect on equity | Additional fold triggers |
|---|---|---|
| 0 | None | None |
| 1 | None (numeric only) | `made == 2`: fold to any bet |
| 2 | `eff_equity -= 0.10` | `made == 2` + bet > 50% pot: fold; `made == 3`: fold to any bet |
| 3 | `eff_equity -= 0.18` | All of the above, plus river `made == 4`: fold |

---

## `hidden_card_equity_discount(revealed_cards)` → `float`

```python
def hidden_card_equity_discount(revealed_cards: list[str]) -> float:
```

### What it does

When the bot **wins** the auction, it sees one of the opponent's cards but the other remains hidden. This function estimates a downward equity correction to account for the possibility that the hidden card is strong.

### Logic

```python
rev_val = RANK_TO_VALUE.get(revealed_cards[0][0], 0)
if rev_val <= 5:   return 0.10
if rev_val <= 7:   return 0.07
if rev_val <= 9:   return 0.03
return 0.0
```

| Revealed card rank | Discount | Reasoning |
|---|---|---|
| 2–5 (very low) | −0.10 | Low visible card → hidden card is likely high; strong range |
| 6–7 (low) | −0.07 | Moderately low → some chance of hidden high card |
| 8–9 (medium) | −0.03 | Balanced; hidden card could go either way |
| T–A (high) | −0.00 | High visible card → hidden card is more likely low; minimal threat |

### Why this works

In a second-price auction, a player bids proportionally to how strong they believe their hand to be. If the revealed card is low (e.g., `2♣`), and the opponent bid enough to win the auction, the hidden card is probably the strong one. The discount corrects for the systematic overestimation of equity that would occur if the bot treated the hidden card as a random draw.

This discount is applied before the danger discount:

```
raw_equity = eval_hand(...)
equity = raw_equity − hidden_card_equity_discount(opp_revealed)
eff_equity = equity − (0.10 if danger >= 2 else 0) − (0.08 if danger >= 3 else 0)
```

---

## `board_has_fullhouse_danger(board)` → `bool`

```python
def board_has_fullhouse_danger(board: list[str]) -> bool:
    if not board: return False
    return max(Counter(c[0] for c in board).values()) >= 2
```

### What it does

Returns `True` if any rank appears at least twice on the board (i.e., the board is **paired**).

### Why it matters

A paired board radically changes the value of a flush. Normally a flush is a very strong hand (rank 5), but on a paired board, the opponent may hold a matching rank card that makes a **full house**, which beats any flush. The bot applies specific caution logic:

- **When holding a flush on a paired board** (with `made == 4` or more precisely triggered when `fh_danger` is constructed): bets and raises on the turn and river are suppressed
- **Call thresholds are tightened**: for `made == 4` with `fh_danger` and bet > 50% pot → fold

```python
fh_danger = board_has_fullhouse_danger(state.board) and made == 4 and len(opp_revealed) < 2
```

The `len(opp_revealed) < 2` guard means full-house danger is only applied when the opponent has at most one revealed card — if both cards were somehow known, the full-house threat would be directly assessable.

---

## `get_flush_info(my_hand, board)` → `(bool, bool)`

```python
def get_flush_info(my_hand: list[str], board: list[str]) -> tuple[bool, bool]:
```

### What it does

Returns two booleans:
- `i_have_flush` — True if a 5-card flush exists using the hero's cards
- `i_have_nut_flush` — True if the hero holds the **highest card** of the flush suit

### Algorithm

```python
for suit, count in suit_counts.items():
    if count >= 5:
        my_suited = [c for c in my_hand if c[1] == suit]
        if not my_suited: return False, False  # board-only flush, hero not participating
        all_suited_vals = sorted([RANK_TO_VALUE[c[0]] for c in all_cards if c[1] == suit], reverse=True)
        my_top = max(RANK_TO_VALUE[c[0]] for c in my_suited)
        return True, (my_top == all_suited_vals[0])
```

The nut flush is determined by comparing the hero's highest suited card to the highest card of that suit across all cards. If they match, it's the nuts.

### Why the nut/non-nut distinction is critical

> **A non-nut flush is one of the most dangerous traps in NLHE.** One higher suited card held by the opponent results in a complete reversal — the stronger-seeming hand (flush) loses entirely to the nut flush.

The bot applies aggressive restrictions for `i_have_non_nut_flush`:

| Situation | Restriction |
|-----------|------------|
| All-in pressure | Fold unless equity ≥ 0.58 |
| Normal postflop: `made == 5`, non-nut | Max call = 45% of pot |
| River non-nut flush | Max call = 40% of pot |
| River all-in | Fold unless equity ≥ 0.60 |
| Proactive bet | Suppressed even with equity ≥ 0.65 |

The asymmetry is intentional: the bot will call a reasonable bet in position but will not build a large pot with a hand that loses to a single specific card the opponent might reasonably hold.

---

## Combined Danger Pipeline

```
Auction result known
│
├─ Bot WON auction (opp card revealed to us)
│       └─► hidden_card_equity_discount(revealed)
│                   └─► equity -= discount (0.00–0.10)
│
└─ Bot LOST auction (opp card revealed to all)
        ├─► revealed_card_danger(revealed, board, hand)
        │           └─► danger score 0–3
        │                   ├─► eff_equity -= 0.10 if danger ≥ 2
        │                   ├─► eff_equity -= 0.08 if danger ≥ 3
        │                   └─► additional fold triggers at danger 1/2/3
        │
        ├─► board_has_fullhouse_danger(board)
        │           └─► fh_danger → suppress bets, tighten calls with flush
        │
        └─► get_flush_info(hand, board)
                    └─► i_have_non_nut_flush → strict call/raise limits
```
