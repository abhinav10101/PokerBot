from __future__ import annotations
from collections import Counter
import random
import sys
import os
try:
    import eval7
except Exception:
    eval7 = None
from pathlib import Path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from engine.pkbot.actions import ActionFold, ActionCall, ActionCheck, ActionRaise, ActionBid
from engine.pkbot.states import GameInfo, PokerState
from engine.pkbot.base import BaseBot
from engine.pkbot.runner import parse_args, run_bot


RANK_TO_VALUE = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}

BIG_BLIND = 20
CHIPS_PER_ROUND = 5000
OPP_HIGH_BID_THRESHOLD = 200 

class OpponentModel:

    def __init__(self):
        self.hands = 0
        self.preflop_raise_count = 0
        self.preflop_raise_sizes = []
        self.auction_bids = []       
        self.auction_attempts = 0
        self.auction_wins = 0

    def hand_start(self):
        self.hands += 1

    def record_preflop_raise(self, size: int):
        self.preflop_raise_count += 1
        self.preflop_raise_sizes.append(size)
        if len(self.preflop_raise_sizes) > 60:
            self.preflop_raise_sizes.pop(0)

    def record_auction_bid(self, bid: int):
        self.auction_bids.append(bid)
        if len(self.auction_bids) > 80:
            self.auction_bids.pop(0)

    def record_auction_outcome(self, we_won: bool):
        self.auction_attempts += 1
        if we_won:
            self.auction_wins += 1

    @property
    def raise_frequency(self) -> float:
        return self.preflop_raise_count / max(1, self.hands) if self.hands >= 5 else 0.2

    @property
    def is_steal_heavy(self) -> bool:
        return self.raise_frequency > 0.30 and self.hands >= 20

    @property
    def is_very_steal_heavy(self) -> bool:
        return self.raise_frequency > 0.45 and self.hands >= 20

    @property
    def is_moderate_raiser(self) -> bool:
        return 0.18 <= self.raise_frequency <= 0.50 and self.hands >= 15

    @property
    def avg_raise_size(self) -> float:
        return sum(self.preflop_raise_sizes) / len(self.preflop_raise_sizes) if self.preflop_raise_sizes else 60.0

    @property
    def is_jam_bot(self) -> bool:
        return self.avg_raise_size >= 1500 and len(self.preflop_raise_sizes) >= 5

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

    @property
    def opp_bid_avg(self) -> float:
        return sum(self.auction_bids) / len(self.auction_bids) if self.auction_bids else 30.0

    @property
    def is_passive_bidder(self) -> bool:
        return len(self.auction_bids) >= 8 and self.opp_bid_p75 <= 12

    @property
    def is_spike_bidder(self) -> bool:
        if len(self.auction_bids) < 10: return False
        return self.opp_bid_avg <= 50 and max(self.auction_bids) >= 100

    @property
    def auction_win_rate(self) -> float:
        return self.auction_wins / max(1, self.auction_attempts)


def eval_hand(my_hand, community, opp_known=None, iterations=48):
    if eval7 is None or not my_hand or len(my_hand) != 2:
        return 0.5
    opp_known = opp_known or []
    try:
        hero = [eval7.Card(c) for c in my_hand]
        board = [eval7.Card(c) for c in community]
        opp_cards = [eval7.Card(c) for c in opp_known]
        opp_need = 2 - len(opp_cards)
        board_need = 5 - len(board)
        if opp_need < 0 or board_need < 0: return 0.5
        dead = set(hero + board + opp_cards)
        deck = [c for c in eval7.Deck().cards if c not in dead]
        need = opp_need + board_need
        if need > len(deck): return 0.5
        wins = 0.0
        for _ in range(iterations):
            draw = random.sample(deck, need)
            opp = opp_cards + draw[:opp_need]
            runout = board + draw[opp_need:]
            h = eval7.evaluate(hero + runout)
            o = eval7.evaluate(opp + runout)
            if h > o: wins += 1.0
            elif h == o: wins += 0.5
        return wins / iterations
    except Exception:
        return 0.5


def preflop_strength(cards: list[str]) -> int:
    if len(cards) < 2: return 1
    r1, r2 = sorted([RANK_TO_VALUE[c[0]] for c in cards], reverse=True)
    suited = cards[0][1] == cards[1][1]
    gap = r1 - r2
    if r1 == r2:
        if r1 >= 11: return 10
        if r1 >= 8:  return 9
        if r1 >= 5:  return 8
        return 7
    if r1 == 14 and r2 >= 13: return 10
    if r1 == 14 and r2 >= 12: return 9 if suited else 8
    if r1 == 14 and r2 >= 11: return 8 if suited else 7
    if r1 == 14 and r2 >= 10: return 7 if suited else 6
    if r1 == 14 and r2 >= 9:  return 6 if suited else 5
    if r1 == 14:               return 5 if suited else 4
    if r1 >= 13 and r2 >= 11: return 8 if suited else 7
    if r1 >= 13 and r2 >= 10: return 7 if suited else 6
    if r1 >= 12 and r2 >= 10: return 7 if suited else 6
    if r1 >= 11 and r2 >= 10: return 6 if suited else 5
    if suited and r1 >= 10 and gap <= 2: return 5
    if r1 >= 13 and r2 >= 8: return 5
    if suited and r1 >= 9 and gap <= 1: return 4
    if r1 >= 10 and r2 >= 8: return 4
    if r1 >= 10 and r2 >= 6: return 3
    return 2


def postflop_hand_strength(cards: list[str]) -> tuple[int, bool, bool]:
    if not cards or len(cards) < 5:
        return 1, False, False

    ranks = [c[0] for c in cards]
    suits = [c[1] for c in cards]
    rank_vals = sorted([RANK_TO_VALUE[r] for r in ranks], reverse=True)
    rank_counts = Counter(ranks)
    suit_counts = Counter(suits)

    has_flush_draw = any(v >= 4 for v in suit_counts.values())
    has_straight_draw = _has_straight_draw(rank_vals)
    is_flush = any(v >= 5 for v in suit_counts.values())
    is_straight = _is_made_straight(rank_vals)
    counts = sorted(rank_counts.values(), reverse=True)

    if counts[0] == 4:
        made = 7
    elif counts[0] == 3 and len(counts) > 1 and counts[1] >= 2:
        made = 6
    elif is_flush:
        made = 5
    elif is_straight:
        made = 5
    elif counts[0] == 3:
        made = 4  
    elif counts[0] == 2 and len(counts) > 1 and counts[1] == 2:
        made = 3  
    elif counts[0] == 2:
        pair_rank = [r for r, c in rank_counts.items() if c == 2][0]
        hole_ranks = [cards[0][0], cards[1][0]]
        board_cards = cards[2:]
        board_only_ranks = [c[0] for c in board_cards]
        board_only_vals = sorted([RANK_TO_VALUE[r] for r in board_only_ranks], reverse=True)

        pair_val = RANK_TO_VALUE[pair_rank]
        hole_contributed = pair_rank in hole_ranks  

        if hole_contributed:
            if pair_val >= board_only_vals[0]:
                made = 4  
            else:
                made = 3  
        else:
            if pair_val == board_only_vals[0]:
                made = 3  
            elif len(board_only_vals) > 1 and pair_val == board_only_vals[1]:
                made = 2 
            else:
                made = 2 
    else:
        made = 1

    return made, has_flush_draw, has_straight_draw


def _has_straight_draw(rank_vals):
    uniq = sorted(set(rank_vals))
    if 14 in uniq: uniq.append(1)
    for i in range(len(uniq) - 3):
        if uniq[i + 3] - uniq[i] == 3: return True
    return False


def _is_made_straight(rank_vals):
    uniq = sorted(set(rank_vals))
    if 14 in uniq: uniq.append(1)
    for i in range(len(uniq) - 4):
        if uniq[i + 4] - uniq[i] == 4: return True
    return False


def revealed_card_danger(revealed_cards: list[str], board: list[str], my_hand: list[str] = None) -> int:
    if not revealed_cards or not board: return 0
    rev = revealed_cards[0]
    rev_rank, rev_suit = rev[0], rev[1]
    rev_val = RANK_TO_VALUE.get(rev_rank, 0)
    board_ranks = [c[0] for c in board]
    board_suits = [c[1] for c in board]
    board_vals = [RANK_TO_VALUE[r] for r in board_ranks]

    danger = 0
    if board_ranks.count(rev_rank) >= 1:
        danger += 2  
    if board_suits.count(rev_suit) >= 2:
        danger += 1  
    if sum(1 for bv in board_vals if abs(bv - rev_val) <= 2) >= 2:
        danger += 1  
    if rev_val >= 13 and rev_val not in board_vals:
        if my_hand:
            my_made, _, _ = postflop_hand_strength(my_hand + board)
            if my_made < 2:
                danger += 1
        else:
            danger += 1

    return min(danger, 3)


def hidden_card_equity_discount(revealed_cards: list[str]) -> float:
    if not revealed_cards: return 0.0
    rev_val = RANK_TO_VALUE.get(revealed_cards[0][0], 0)
    if rev_val <= 5: return 0.10   
    if rev_val <= 7: return 0.07   
    if rev_val <= 9: return 0.03   
    return 0.0


def board_has_fullhouse_danger(board: list[str]) -> bool:
    if not board: return False
    return max(Counter(c[0] for c in board).values()) >= 2


def get_flush_info(my_hand: list[str], board: list[str]) -> tuple[bool, bool]:
    if not my_hand or not board: return False, False
    all_cards = my_hand + board
    suit_counts = Counter(c[1] for c in all_cards)
    for suit, count in suit_counts.items():
        if count >= 5:
            my_suited = [c for c in my_hand if c[1] == suit]
            if not my_suited: return False, False
            all_suited_vals = sorted([RANK_TO_VALUE[c[0]] for c in all_cards if c[1] == suit], reverse=True)
            my_top = max(RANK_TO_VALUE[c[0]] for c in my_suited)
            return True, (my_top == all_suited_vals[0])
    return False, False


class Player(BaseBot):

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
        self._won_auction_this_hand = False
        self._probe_bet_street = None      
        self._opp_called_probe = False     

    def on_hand_start(self, game_info: GameInfo, current_state: PokerState) -> None:
        self.hand_count += 1
        self.opp_model.hand_start()
        self.start_chips = current_state.my_chips
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

    def on_hand_end(self, game_info: GameInfo, current_state: PokerState, observation=None) -> None:
        if self.was_in_auction_this_hand:
            won = len(current_state.opp_revealed_cards) > 0
            self.opp_model.record_auction_outcome(won)
            self.lost_auction_this_hand = not won

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

    def _infer_opp_bid(self, state: PokerState):
        try:
            payment = state.pot - self._pre_auction_pot
            if payment < 0: return
            we_won = len(state.opp_revealed_cards) > 0
            if we_won:
                opp_bid = payment  # we paid opp's bid (second price)
                self.opp_model.record_auction_bid(opp_bid)
                self._opp_bid_this_hand = opp_bid
            else:
                # We lost: we paid our own bid. Opp's bid >= our bid.
                self.opp_model.record_auction_bid(self._our_bid_this_hand)
                self._opp_bid_this_hand = self._our_bid_this_hand
                # FIX K: If opp won AND inferred bid >= threshold → high bid danger
                if self._our_bid_this_hand >= OPP_HIGH_BID_THRESHOLD:
                    self._opp_high_bid_won = True
        except Exception:
            pass

    def _preflop_move(self, state: PokerState, game_info: GameInfo):
        strength = preflop_strength(state.my_hand)
        cost = state.cost_to_call
        my_chips = state.my_chips

        if my_chips <= 0:
            return ActionFold() if state.can_act(ActionFold) else ActionCheck()

        if cost > BIG_BLIND and not self._opp_raised_preflop_this_hand:
            self._opp_raised_preflop_this_hand = True
            self.opp_model.record_preflop_raise(cost)
        
        if self._is_allin_pressure(state):
            if self.opp_model.is_jam_bot:
                if strength >= 10: return ActionCall() if state.can_act(ActionCall) else ActionFold()
                if strength == 9 and cost <= my_chips * 0.6: return ActionCall() if state.can_act(ActionCall) else ActionFold()
                return ActionFold() if state.can_act(ActionFold) else ActionCheck()
            if strength >= 9: return ActionCall() if state.can_act(ActionCall) else ActionRaise(state.raise_bounds[0])
            if strength >= 8 and cost <= my_chips * 0.6: return ActionCall() if state.can_act(ActionCall) else ActionFold()
            return ActionFold() if state.can_act(ActionFold) else ActionCheck()

        if self.opp_model.is_steal_heavy and cost > BIG_BLIND:
            return self._defend_vs_steal(state, strength, cost, my_chips)

        if self.opp_model.is_moderate_raiser and cost > BIG_BLIND:
            raise_in_bb = cost / BIG_BLIND
            if raise_in_bb <= 4.0:           # small raise (≤4BB): fold weak
                if strength >= 7: return ActionCall() if state.can_act(ActionCall) else ActionFold()
                if strength >= 5: return ActionCall() if state.can_act(ActionCall) else ActionFold()
                return ActionFold() if state.can_act(ActionFold) else ActionCheck()
            else:                             # bigger raise: tighten further
                if strength >= 8: return ActionCall() if state.can_act(ActionCall) else ActionFold()
                if strength >= 6: return ActionCall() if state.can_act(ActionCall) else ActionFold()
                return ActionFold() if state.can_act(ActionFold) else ActionCheck()


        if cost > 300:
            if strength >= 9:
                if state.can_act(ActionRaise):
                    return ActionRaise(min(state.raise_bounds[1], my_chips))
                return ActionCall() if state.can_act(ActionCall) else ActionFold()
            if strength >= 7: return ActionCall() if state.can_act(ActionCall) else ActionFold()
            return ActionFold() if state.can_act(ActionFold) else ActionCheck()

        if cost > BIG_BLIND:
            if strength >= 9:
                if state.can_act(ActionRaise):
                    target = min(int(cost * 3), state.raise_bounds[1])
                    return ActionRaise(max(target, state.raise_bounds[0]))
                return ActionCall() if state.can_act(ActionCall) else ActionFold()
            if strength >= 7:
                if state.can_act(ActionRaise) and cost <= 100:
                    target = min(int(cost * 2.8), state.raise_bounds[1])
                    return ActionRaise(max(target, state.raise_bounds[0]))
                return ActionCall() if state.can_act(ActionCall) else ActionFold()
            if strength >= 5: return ActionCall() if state.can_act(ActionCall) else ActionFold()
            return ActionFold() if state.can_act(ActionFold) else ActionCheck()

        if cost == 0:
            if state.can_act(ActionRaise):
                if strength >= 8: return ActionRaise(self._choose_raise_size(state, 3.0))
                if strength >= 6: return ActionRaise(self._choose_raise_size(state, 2.5))
                if strength >= 5: return ActionRaise(self._choose_raise_size(state, 2.0))
            if state.can_act(ActionCheck): return ActionCheck()

        if state.can_act(ActionRaise):
            if strength >= 8: return ActionRaise(self._choose_raise_size(state, 3.0))
            if strength >= 6: return ActionRaise(self._choose_raise_size(state, 2.5))
        if state.can_act(ActionCall):
            if strength >= 4: return ActionCall()
            if cost <= BIG_BLIND: return ActionCall()
            return ActionFold()
        if state.can_act(ActionCheck): return ActionCheck()
        return ActionFold()

    def _defend_vs_steal(self, state: PokerState, strength: int, cost: int, my_chips: int):
        raise_in_bb = cost / BIG_BLIND
        if strength >= 8:
            if state.can_act(ActionRaise):
                target = min(int(cost * 3.5), state.raise_bounds[1])
                return ActionRaise(max(target, state.raise_bounds[0]))
            return ActionCall() if state.can_act(ActionCall) else ActionFold()
        if strength >= 6:
            if state.can_act(ActionRaise) and raise_in_bb <= 5:
                target = min(int(cost * 3.0), state.raise_bounds[1])
                return ActionRaise(max(target, state.raise_bounds[0]))
            return ActionCall() if state.can_act(ActionCall) else ActionFold()
        if strength >= 4: return ActionCall() if state.can_act(ActionCall) else ActionFold()
        if strength >= 3 and raise_in_bb <= 3.5: return ActionCall() if state.can_act(ActionCall) else ActionFold()
        if self.opp_model.is_very_steal_heavy and raise_in_bb <= 3.5 and strength >= 2:
            return ActionCall() if state.can_act(ActionCall) else ActionFold()
        return ActionFold() if state.can_act(ActionFold) else ActionCheck()


    def _auction_bid(self, state: PokerState) -> int:
        cards = state.my_hand + state.board
        made, flush_draw, straight_draw = postflop_hand_strength(cards)
        pot = state.pot
        my_chips = state.my_chips

        if my_chips <= 0: return 0

        info_value = self._auction_info_value(made, flush_draw, straight_draw, pot)

        n_bids = len(self.opp_model.auction_bids)


        if self.opp_model.is_spike_bidder and n_bids >= 10:
            info_value = min(info_value, 80)

        if n_bids >= 8 and self.opp_model.is_passive_bidder:
            safe_bid = min(self.opp_model.opp_bid_p90 + 2, info_value, my_chips)
            return max(1, safe_bid)

        if n_bids >= 10:
            profile_bid = self.opp_model.opp_bid_p75 + 2
            bid = min(profile_bid, info_value)
            bid = max(10, bid)
            return min(bid, my_chips)

        bid = max(10, min(info_value, my_chips))
        return bid

    def _auction_info_value(self, made: int, flush_draw: bool, straight_draw: bool, pot: int) -> int:
        
        if made >= 6:   base = max(65,  min(80,  int(pot * 0.15)))
        elif made == 5: base = max(65,  min(110, int(pot * 0.20)))
        elif made == 4: base = max(65,  min(150, int(pot * 0.26)))
        elif made == 3: base = max(45,  min(120, int(pot * 0.23)))
        elif made == 2: base = max(45,  min(85,  int(pot * 0.18)))
        elif flush_draw or straight_draw: base = max(35, min(75, int(pot * 0.16)))
        else:           base = max(25,  min(50,  int(pot * 0.10)))  
        return base

    def _postflop_move(self, state: PokerState, game_info: GameInfo, street: str):
        cards = state.my_hand + state.board
        made, flush_draw, straight_draw = postflop_hand_strength(cards)
        cost = state.cost_to_call
        pot = state.pot
        my_chips = state.my_chips
        has_draw = flush_draw or straight_draw
        opp_revealed = list(state.opp_revealed_cards)

        if my_chips <= 0:
            return ActionCheck() if state.can_act(ActionCheck) else ActionFold()

        raw_equity = eval_hand(state.my_hand, state.board, opp_known=opp_revealed, iterations=48)

        equity_discount = hidden_card_equity_discount(opp_revealed)
        equity = raw_equity - equity_discount

        pf_str = preflop_strength(state.my_hand)
        is_premium = pf_str >= 7

        danger = revealed_card_danger(opp_revealed, state.board, state.my_hand) if opp_revealed else 0

        i_have_flush, i_have_nut_flush = get_flush_info(state.my_hand, state.board)
        i_have_non_nut_flush = i_have_flush and not i_have_nut_flush

        fh_danger = board_has_fullhouse_danger(state.board) and made == 4 and len(opp_revealed) < 2

        opp_paid_high = self._opp_high_bid_won
        we_lost_auction = self.lost_auction_this_hand

        if self._is_allin_pressure(state):
            if made >= 6: return ActionCall() if state.can_act(ActionCall) else ActionFold()
            if made == 5:
                if i_have_non_nut_flush and equity < 0.58:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if equity >= 0.60: return ActionCall() if state.can_act(ActionCall) else ActionFold()
            if made == 4 and equity >= 0.58 and danger <= 1 and not fh_danger:
                return ActionCall() if state.can_act(ActionCall) else ActionFold()
            if is_premium and equity >= 0.53 and danger <= 1:
                return ActionCall() if state.can_act(ActionCall) else ActionFold()
            return ActionFold() if state.can_act(ActionFold) else ActionCheck()

        pot_odds = cost / (pot + cost) if cost > 0 else 0

        if street == "river" and cost > 0:
            return self._river_decision(state, made, equity, danger, cost, pot,
                                         is_premium, has_draw, i_have_non_nut_flush, fh_danger)

        eff_equity = equity
        if danger >= 2: eff_equity -= 0.10
        if danger >= 3: eff_equity -= 0.08

        if opp_paid_high and cost > 0:
            pot_frac = cost / pot if pot > 0 else 1.0
            if street == 'flop':
                if pot_frac >= 0.80 and made < 5:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if pot_frac >= 0.40 and made < 4:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if pot_frac >= 0.40 and made == 4 and eff_equity < 0.55:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
            if street == 'turn' and pot_frac >= 0.60:
                if made < 4: return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if made == 4 and eff_equity < 0.58:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()

        if cost > 0:
            if street == "turn":
                if cost > 1500 and made < 6:
                    if is_premium and eff_equity >= 0.48: pass
                    else: return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if cost > 600 and made < 5 and danger >= 2:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if cost > 800 and made < 5:
                    if is_premium and eff_equity >= 0.48: pass
                    else: return ActionFold() if state.can_act(ActionFold) else ActionCheck()

            if made < 4 and not has_draw:
                if eff_equity < pot_odds + 0.05:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()

            if made == 2 and danger >= 2 and cost > pot * 0.5:
                return ActionFold() if state.can_act(ActionFold) else ActionCheck()

            if made == 3 and danger >= 2:
                return ActionFold() if state.can_act(ActionFold) else ActionCheck()

        if state.can_act(ActionRaise):
            lost_to_high_bid = we_lost_auction and self._opp_bid_this_hand >= OPP_HIGH_BID_THRESHOLD
            skip_lead = lost_to_high_bid and cost == 0 and made < 4 and street in ('flop', 'turn')

            if self._opp_called_probe and cost == 0 and made < 4 and not has_draw:
                pass 
            elif not skip_lead:
                info_edge = len(opp_revealed) > 0 and danger <= 1
                size_mult = 0.85 if info_edge else 0.65

                if cost == 0:
                    if self._won_auction_this_hand and street != 'river' and not opp_paid_high:
                        if made >= 4 and not (fh_danger and street in ('turn', 'river')):
                            bet_size = self._choose_raise_size(state, size_mult)
                            self._probe_bet_street = street
                            return ActionRaise(bet_size)
                        elif made >= 1 and danger <= 1:
                            probe_size = self._choose_raise_size(state, 0.40)
                            self._probe_bet_street = street
                            return ActionRaise(probe_size)

                    if made >= 6:
                        return ActionRaise(self._choose_raise_size(state, size_mult + 0.3))
                    if made == 5 and equity >= 0.65:
                        if not i_have_non_nut_flush:
                            return ActionRaise(self._choose_raise_size(state, size_mult))
                    if made >= 4:
                        if fh_danger and street in ('turn', 'river'):
                            pass  
                        else:
                            return ActionRaise(self._choose_raise_size(state, size_mult - 0.1))
                    if made == 3 and eff_equity >= 0.52 and not opp_paid_high:
                        return ActionRaise(self._choose_raise_size(state, 0.45))
                    if has_draw and eff_equity >= 0.42 and street != 'river':
                        return ActionRaise(self._choose_raise_size(state, 0.35))
                else:
                    
                    if self._probe_bet_street and street != self._probe_bet_street:
                        self._opp_called_probe = True  

                    if made >= 6 and cost <= pot * 0.6:
                        return ActionRaise(self._choose_raise_size(state, 1.0))
                    if made == 5 and eff_equity >= 0.72 and cost <= pot * 0.5:
                        if not i_have_non_nut_flush:
                            return ActionRaise(self._choose_raise_size(state, 0.85))

        if state.can_act(ActionCall):
            if cost <= 0:
                return ActionCheck() if state.can_act(ActionCheck) else ActionCall()

            if made >= 6: return ActionCall()

            if made == 5:
                if i_have_non_nut_flush:
                    if cost <= pot * 0.45: return ActionCall()
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if eff_equity >= 0.58 and cost <= pot * 1.5: return ActionCall()
                if cost <= pot * 0.4: return ActionCall()

            if made == 4:
                if fh_danger and cost > pot * 0.5:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if danger >= 2 and cost > pot * 0.5:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if eff_equity >= 0.52 and cost <= pot: return ActionCall()
                if cost <= pot * 0.3: return ActionCall()

            if made == 3:
                if danger >= 2: return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if cost <= pot * 0.25: return ActionCall()

            if made == 2:
                if danger >= 1: return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if is_premium and eff_equity >= 0.50 and cost <= pot * 0.5: return ActionCall()
                if cost <= pot * 0.15: return ActionCall()

            if has_draw and danger <= 1:
                if flush_draw and straight_draw and cost <= pot * 0.50: return ActionCall()
                if flush_draw and cost <= pot * 0.38: return ActionCall()
                if straight_draw and cost <= pot * 0.33: return ActionCall()
                if cost <= pot * 0.28: return ActionCall()

            return ActionFold()

        if state.can_act(ActionCheck): return ActionCheck()
        return ActionFold()

    def _river_decision(self, state, made, equity, danger, cost, pot,
                         is_premium, has_draw, i_have_non_nut_flush, fh_danger):
        is_river_allin = cost >= 2500 or (state.my_chips > 0 and cost >= state.my_chips * 0.65)
        if is_river_allin:
            if made >= 6: return ActionCall() if state.can_act(ActionCall) else ActionFold()
            if made == 5:
                if i_have_non_nut_flush and equity < 0.60:
                    return ActionFold() if state.can_act(ActionFold) else ActionCheck()
                if equity >= 0.55: return ActionCall() if state.can_act(ActionCall) else ActionFold()
            return ActionFold() if state.can_act(ActionFold) else ActionCheck()

        if made >= 6:
            if cost <= pot * 2.0: return ActionCall() if state.can_act(ActionCall) else ActionFold()
        if made == 5:
            if i_have_non_nut_flush:
                if cost <= pot * 0.4: return ActionCall() if state.can_act(ActionCall) else ActionFold()
                return ActionFold() if state.can_act(ActionFold) else ActionCheck()
            if danger <= 1 and equity >= 0.62 and cost <= pot * 1.2:
                return ActionCall() if state.can_act(ActionCall) else ActionFold()
        if made == 4:
            if fh_danger or danger >= 1:
                return ActionFold() if state.can_act(ActionFold) else ActionCheck()
            if equity >= 0.70 and cost <= pot * 0.55:
                return ActionCall() if state.can_act(ActionCall) else ActionFold()
        if made == 3:
            if danger == 0 and equity >= 0.75 and cost <= pot * 0.30:
                return ActionCall() if state.can_act(ActionCall) else ActionFold()
        return ActionFold() if state.can_act(ActionFold) else ActionCheck()

    def _choose_raise_size(self, state: PokerState, factor: float) -> int:
        min_raise, max_raise = state.raise_bounds
        target = int(state.pot * factor)
        if target < min_raise: return min_raise
        if target > max_raise: return max_raise
        return target

    def _is_allin_pressure(self, state: PokerState) -> bool:
        cost = state.cost_to_call
        if cost <= 0: return False
        if state.my_chips <= 0: return True
        return cost >= state.my_chips * 0.70 or cost >= 1500


if __name__ == "__main__":
    run_bot(Player(), parse_args())
