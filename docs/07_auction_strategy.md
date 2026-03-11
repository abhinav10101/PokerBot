# Auction Strategy

> **File:** `player.py`  
> **Methods:** `Player._auction_bid()`, `Player._auction_info_value()`, `Player._infer_opp_bid()`  
> **Purpose:** Decide how much to bid in the auction and reconstruct the opponent's bid from the pot change after the auction resolves.

---

## The Auction Mechanic

Between the Turn and River, both players simultaneously submit a sealed bid. The **winner pays the loser's bid** (a second-price / Vickrey auction) and receives one of the opponent's hole cards revealed publicly for the rest of the hand.

Key properties of second-price auctions:
- The dominant strategy in theory is to bid your **true value** of the information
- Overbidding wastes chips; the winner always pays less than their bid
- Underbidding loses information to the opponent

The bot doesn't blindly follow "bid true value" — it profiles the opponent and bids just enough to win most auctions at minimum cost.

---

## `_auction_bid(state)` → `int`

```python
def _auction_bid(self, state: PokerState) -> int:
    cards = state.my_hand + state.board
    made, flush_draw, straight_draw = postflop_hand_strength(cards)
    pot = state.pot
    my_chips = state.my_chips

    if my_chips <= 0: return 0

    info_value = self._auction_info_value(made, flush_draw, straight_draw, pot)
    n_bids = len(self.opp_model.auction_bids)
    ...
```

### Step 1: Compute base information value

`_auction_info_value()` estimates how many chips the revealed card is worth in expected EV terms, based on the current hand strength and pot size.

### Step 2: Apply opponent profile adjustments

Three profile-based branches:

#### Spike bidder (cap at 80)
```python
if self.opp_model.is_spike_bidder and n_bids >= 10:
    info_value = min(info_value, 80)
```
An opponent who usually bids low but occasionally places very large bids (avg ≤ 50, max ≥ 100). Capping at 80 avoids being drawn into an arms race against those rare large bids while still winning most auctions.

#### Passive bidder (snipe just above p90)
```python
if n_bids >= 8 and self.opp_model.is_passive_bidder:
    safe_bid = min(self.opp_model.opp_bid_p90 + 2, info_value, my_chips)
    return max(1, safe_bid)
```
An opponent whose 75th percentile bid is ≤ 12 chips. Against this profile, the bot can win nearly every auction for just above p90 (often 15–20 chips) — getting information almost for free. The `+ 2` provides a small margin above the p90 to reliably outbid.

#### Sufficient data (bid p75 + 2)
```python
if n_bids >= 10:
    profile_bid = self.opp_model.opp_bid_p75 + 2
    bid = min(profile_bid, info_value)
    bid = max(10, bid)
    return min(bid, my_chips)
```
With 10+ observed bids, the bot targets the 75th percentile + 2. This means it wins approximately **75% of auctions** at the cheapest viable cost.

#### Cold start (< 10 bids)
```python
bid = max(10, min(info_value, my_chips))
return bid
```
With insufficient data, the bot bids its full information value without profile adjustment. The `max(10, ...)` prevents bidding zero (which would always lose).

---

## `_auction_info_value(made, flush_draw, straight_draw, pot)` → `int`

```python
def _auction_info_value(self, made, flush_draw, straight_draw, pot) -> int:
```

Estimates the chip value of winning the auction based on current hand strength.

### Value table

| Hand state | Pot fraction | Floor | Ceiling |
|-----------|---|---|---|
| Made ≥ 6 (boat/quads) | 15% of pot | 65 | 80 |
| Made = 5 (flush/straight) | 20% of pot | 65 | 110 |
| Made = 4 (trips/top pair) | 26% of pot | 65 | 150 |
| Made = 3 (two pair/2nd pair) | 23% of pot | 45 | 120 |
| Made = 2 (weak pair) | 18% of pot | 45 | 85 |
| Draw only (no made hand) | 16% of pot | 35 | 75 |
| Made = 1 (air) | 10% of pot | 25 | 50 |

### Why these values?

The information value is highest for **mid-strength hands** (made 3–5), not the strongest ones. Here's the reasoning:

- **Very strong hands (≥ 6):** You're going to bet heavily and win most of the time regardless of what the opponent holds. The revealed card adds marginal value — you mostly need to know if you're completely crushed, which is rare. Lower cap.
- **Medium hands (3–5):** You're uncertain whether you're ahead or behind. The revealed card directly resolves this uncertainty and changes bet sizing dramatically. Highest value.
- **Weak hands (1–2):** Even with the revealed card, you're likely behind. The information doesn't change the decision much. Lowest value.

The pot fraction scaling ensures bids grow proportionally with pot size — a 50-chip revealed-card advantage is worth more in a 500-chip pot than a 50-chip pot.

---

## `_infer_opp_bid(state)`

```python
def _infer_opp_bid(self, state: PokerState):
    payment = state.pot - self._pre_auction_pot
    we_won = len(state.opp_revealed_cards) > 0
    ...
```

Called once on the first postflop action after the auction. Reconstructs the opponent's bid from the observable pot change.

### Inference logic

Since the auction is second-price:
- **Winner pays loser's bid**
- Observable: `pot_change = state.pot - self._pre_auction_pot`

#### Case 1: Bot won the auction
```python
if we_won:
    opp_bid = payment          # We paid opponent's bid — this is exact
    self.opp_model.record_auction_bid(opp_bid)
    self._opp_bid_this_hand = opp_bid
```
The pot increased by exactly the opponent's bid (which we paid). This is a **precise inference** — no uncertainty.

#### Case 2: Bot lost the auction
```python
else:
    # We paid our own bid; opponent bid >= our bid
    self.opp_model.record_auction_bid(self._our_bid_this_hand)
    self._opp_bid_this_hand = self._our_bid_this_hand
    if self._our_bid_this_hand >= OPP_HIGH_BID_THRESHOLD:
        self._opp_high_bid_won = True
```
When we lose, the pot increases by our own bid (which the opponent collects). We know only that the opponent bid **at least** as much as us. The bot records our own bid as a lower-bound proxy.

**High-bid flag:** If our bid was ≥ 200 and the opponent still outbid us, their bid was also ≥ 200. This sets `_opp_high_bid_won`, activating conservative postflop play for the remainder of the hand.

---

## Full Auction Flow

```
[Auction street]
    1. was_in_auction_this_hand = True
    2. _pre_auction_pot = state.pot
    3. bid = _auction_bid(state)
           ├─ info_value = _auction_info_value(made, draws, pot)
           ├─ spike_bidder? → cap at 80
           ├─ passive_bidder? → bid p90 + 2
           ├─ n≥10 bids? → bid p75 + 2
           └─ cold start? → bid info_value
    4. _our_bid_this_hand = bid
    5. return ActionBid(bid)

[First postflop action after auction]
    1. Check opp_revealed_cards → _won_auction_this_hand flag
    2. _infer_opp_bid(state)
           ├─ won? → record exact opp bid
           └─ lost? → record our bid as proxy
                      + set _opp_high_bid_won if our bid ≥ 200
    3. _auction_recorded = True (prevent re-running)
```

---

## Strategic Impact

| Outcome | Immediate effect | Postflop effect |
|---------|-----------------|-----------------|
| Won auction | `_won_auction_this_hand = True` | Probe bets enabled; info edge in sizing |
| Lost, opp bid high | `_opp_high_bid_won = True` | Tighter calls on flop/turn; fold earlier |
| Lost, opp bid low | Normal | Minimal change; opponent didn't signal strength |
| Passive bidder found | Profile set | Future auctions won for ~p90 chips |
| Spike bidder found | Profile set | Future auctions capped at 80 chips |
