import subprocess
import re
import json

ENGINE_CMD = ["python", "../engine/engine.py"]
CONFIG_FILE = "../engine/config.py"


def write_config(bot1_name, bot1_file, bot2_name, bot2_file):
    content = f"""
PYTHON_CMD = "python"

BOT_1_NAME = '{bot1_name}'
BOT_1_FILE = '{bot1_file}'

BOT_2_NAME = '{bot2_name}'
BOT_2_FILE = '{bot2_file}'

GAME_LOG_FOLDER = '../logs'
"""
    with open(CONFIG_FILE, "w") as f:
        f.write(content)


def run_match():

    result = subprocess.run(
        ENGINE_CMD,
        capture_output=True,
        text=True
    )

    output = result.stdout

    pattern = r"Stats for (.+?):\n\s+Total Bankroll:\s*(-?\d+)"
    matches = re.findall(pattern, output)

    scores = {}
    for name, bankroll in matches:
        scores[name] = int(bankroll)

    return scores

def run_n_matches(bot1_file, bot2_file, n_matches=50):

    bot1_name = "BotA"
    bot2_name = "BotB"

    write_config(bot1_name, bot1_file, bot2_name, bot2_file)

    total_a = 0
    total_b = 0

    wins_a = 0
    wins_b = 0
    ties = 0

    for i in range(n_matches):

        scores = run_match()

        a = scores.get(bot1_name, 0)
        b = scores.get(bot2_name, 0)

        total_a += a
        total_b += b

        if a > b:
            wins_a += 1
        elif b > a:
            wins_b += 1
        else:
            ties += 1

        print(f"Match {i+1}: {bot1_name}={a}, {bot2_name}={b}")

    print("\n===== FINAL METRICS =====")

    print(f"Matches played: {n_matches}")

    print(f"{bot1_name} total bankroll: {total_a}")
    print(f"{bot2_name} total bankroll: {total_b}")

    print(f"{bot1_name} avg EV: {total_a/n_matches:.2f}")
    print(f"{bot2_name} avg EV: {total_b/n_matches:.2f}")

    print(f"{bot1_name} wins: {wins_a}")
    print(f"{bot2_name} wins: {wins_b}")
    print(f"Ties: {ties}")


if __name__ == "__main__":

    BOT1 = "../bots/submission.py"
    BOT2 = "../engine/example_bot.py"

    run_n_matches(BOT1, BOT2, n_matches=1)