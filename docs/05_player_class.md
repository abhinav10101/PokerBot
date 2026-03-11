# `Player` Class — Overview & Lifecycle

> **File:** `player.py`  
> **Purpose:** The central decision-making agent. Inherits from `BaseBot` and implements all game callbacks, per-hand state management, and top-level action routing.

---

## Class Declaration

```python
class Player(BaseBot):
```

`Player` extends `BaseBot`, which provides the interface contract (`get_move`, `on_hand_start`, `on_hand_end`) and abstracts the network I/O layer. `Player` only needs to implement the game logic.

---

## Per-Hand State Variables

These variables are instance attributes that are **reset at the start of every hand** in `on_hand_start()`. They track hand-scoped context that must not bleed from one hand to the next.

```python
def __init__(self):
    self.opp_model = OpponentModel()
    self.hand_count = 0
    self.start_chips = CHIPS_PER_ROUND
    self.was_in_auction_this_hand = False
    self.lost_auction_this_hand = False
    self._opp_raised_preflop_this_hand = False
    self._pre_auction_pot = 0
    self._our_bid_this_hand = 0
    self._auction_recorded = False
    self._opp_high_bid_won = False
    self._opp_bid_this_hand = 0
    self._won_auction_this_hand = False
    self._probe_bet_street = None
    self._opp_called_probe = False
```

### Variable reference

| Variable | Reset value | Purpose |
|----------|-------------|---------|
| `opp_model` | *(persists across hands)* | The opponent model — the only state that survives hand boundaries |
| `hand_count` | *(increments)* | Total hands played, for diagnostics |
| `start_chips` | `CHIPS_PER_ROUND` | Stack at hand start, updated each hand |
| `was_in_auction_this_hand` | `False` | True once the auction street is entered |
| `lost_auction_this_hand` | `False` | True if opponent outbid us |
| `_opp_raised_preflop_this_hand` | `False` | Ensures the first preflop raise per hand is recorded exactly once |
| `_pre_auction_pot` | `0` | Pot size just before the auction; used to infer opponent's bid from the pot change |
| `_our_bid_this_hand` | `0` | The bid we submitted, needed for inference when we lose |
| `_auction_recorded` | `False` | Prevents `_infer_opp_bid()` being called more than once per hand |
| `_opp_high_bid_won` | `False` | Activated when opponent is inferred to have bid ≥ 200 |
| `_opp_bid_this_hand` | `0` | Inferred opponent bid (exact or lower bound) |
| `_won_auction_this_hand` | `False` | True once `opp_revealed_cards` is non-empty post-auction |
| `_probe_bet_street` | `None` | Stores the street on which we made an information probe bet |
| `_opp_called_probe` | `False` | True if the opponent called our probe bet; suppresses further bluffs with weak hands |

### Why separate per-hand and cross-hand state?

Mixing them is a common bug in game-playing agents. For example, if `_opp_high_bid_won` were never reset, a single large auction loss would make the bot play defensively for the rest of the match. Each hand is an independent event (in terms of cards); the opponent model is the only component that legitimately accumulates across hands.

---

## `on_hand_start(game_info, current_state)`

```python
def on_hand_start(self, game_info: GameInfo, current_state: PokerState) -> None:
    self.hand_count += 1
    self.opp_model.hand_start()
    self.start_chips = current_state.my_chips
    # ... reset all per-hand flags to False / 0 / None
```

### What it does

Called by the engine framework at the beginning of every new hand. Performs three tasks:

1. **Increments counters** — `hand_count` (local) and `opp_model.hands` (in OpponentModel)
2. **Captures starting stack** — `current_state.my_chips` is saved as `start_chips`, which could be used for stack-depth calculations
3. **Resets all per-hand flags** — ensures a clean state for every hand

---

## `on_hand_end(game_info, current_state, observation)`

```python
def on_hand_end(self, game_info: GameInfo, current_state: PokerState, observation=None) -> None:
    if self.was_in_auction_this_hand:
        won = len(current_state.opp_revealed_cards) > 0
        self.opp_model.record_auction_outcome(won)
        self.lost_auction_this_hand = not won
```

### What it does

Called once at the end of every hand. If an auction occurred:
- Determines whether we won (by checking whether `opp_revealed_cards` is non-empty — only populated if we won)
- Records the outcome in `OpponentModel` for win-rate tracking
- Sets `lost_auction_this_hand` (though the hand is already over, this is a belt-and-suspenders safety)

---

## `get_move(game_info, current_state)`

```python
def get_move(self, game_info: GameInfo, current_state: PokerState):
    try:
        return self._get_move_safe(game_info, current_state)
    except Exception:
        try:
            if current_state.can_act(ActionCheck): return ActionCheck()
            if current_state.can_act(ActionFold):  return ActionFold()
            if current_state.can_act(ActionCall):  return ActionCall()
        except Exception:
            pass
        return ActionFold()
```

### What it does

The **top-level entry point** called by the engine for every action decision. It is a pure safety wrapper: all real logic is delegated to `_get_move_safe()`. If any unhandled exception propagates, the fallback returns actions in this priority:

```
Check → Fold → Call → Fold (last resort)
```

### Why this matters

In a competitive game engine, a crash or uncaught exception typically results in forfeiting the hand or the match. The two-layer try/catch ensures the bot always returns a valid action object, even if the inner logic failed catastrophically. The outer catch handles logic failures; the inner try/catch handles the edge case where even calling `can_act()` somehow throws.

---

## `_get_move_safe(game_info, current_state)`

```python
def _get_move_safe(self, game_info: GameInfo, current_state: PokerState):
    street = current_state.street.lower()

    if street == "auction":
        self.was_in_auction_this_hand = True
        self._pre_auction_pot = current_state.pot
        bid = self._auction_bid(current_state)
        self._our_bid_this_hand = bid
        return ActionBid(bid)

    if self.was_in_auction_this_hand and not self._won_auction_this_hand:
        if len(current_state.opp_revealed_cards) > 0:
            self._won_auction_this_hand = True

    if street in ("preflop", "pre-flop"):
        return self._preflop_move(current_state, game_info)

    if self.was_in_auction_this_hand and not self._auction_recorded:
        self._infer_opp_bid(current_state)
        self._auction_recorded = True

    return self._postflop_move(current_state, game_info, street)
```

### What it does

Routes the decision to the correct handler based on the current street. Also performs two important one-time side effects:

1. **Auction entry recording** — Sets `was_in_auction_this_hand = True`, records the pre-auction pot size, submits a bid, and saves it.

2. **Auction win detection** — On the first postflop action after the auction, checks if `opp_revealed_cards` is non-empty. If so, the bot won and `_won_auction_this_hand` is set. This flag controls probe-bet behaviour throughout the rest of the hand.

3. **Bid inference** — On the first postflop action after auction, calls `_infer_opp_bid()` exactly once (guarded by `_auction_recorded`). This reconstructs the opponent's bid from the change in pot size.

### Street routing

| Street value | Handler |
|---|---|
| `"auction"` | `_auction_bid()` → `ActionBid` |
| `"preflop"` / `"pre-flop"` | `_preflop_move()` |
| `"flop"`, `"turn"` | `_postflop_move()` |
| `"river"` | `_postflop_move()` → internally routes to `_river_decision()` |

---

## Control Flow Diagram

```
Engine calls get_move()
    │
    └─► try: _get_move_safe()
            │
            ├── street == "auction"
            │       └─► _auction_bid() → ActionBid(n)
            │
            ├── street == "preflop"
            │       └─► _preflop_move()
            │
            └── street == flop/turn/river
                    ├── [one-time] _infer_opp_bid()
                    └─► _postflop_move()
                                └── street == "river" + cost > 0
                                            └─► _river_decision()
        │
        └─► except: fallback Check/Fold/Call
```
