# Poker Bot – SneakPeek Hold’em Agent

This repository contains my submission for the **IIT Pokerbots Competition**, where autonomous agents compete in a variant of heads-up Texas Hold’em called **SneakPeek Hold’em**.

The bot combines **opponent modeling, probabilistic hand evaluation, and rule-based decision logic** to make decisions during play.

Detailed explanations of the bot architecture and strategy are provided in the `docs/` directory.

---

## Repository Structure
```
poker-bots-competition
|
├── bots
│   └── submission.py        # Final bot implementation
│
├── engine                   # Game engine provided by competition
│   ├── engine.py
│   ├── example_bot.py
│   └── pkbot
│
├── evaluation
│   └── tournament.py        # Script for running automated matches
│
├── docs                     # Detailed documentation
│   ├── architecture.md
│   ├── strategy.md
│   └── features.md
│
├── logs                     # Game logs
└── requirements.txt
```
---

## Installation

Install the required dependencies:

pip install -r requirements.txt

---

## Running the Engine

To run a match between bots using the game engine:

cd engine
python engine.py

---

## Running Tournament Evaluations

To run automated matches between bots:

python evaluation/tournament.py

---

## Documentation

Further documentation about the bot design and implementation can be found in the `docs/` folder:

* `architecture.md` – system architecture and decision pipeline
* `strategy.md` – poker strategy and gameplay logic
* `features.md` – implementation details and core modules

---

## Author

Abhinav Chhabra
