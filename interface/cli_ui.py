from __future__ import annotations

import os
import time

from core.settings import BANNER, BOOT_LINES, GREEN, ORANGE, RESET, VERSION, WHITE


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def loading_line(text: str, width: int = 50) -> None:
    print(f"{GREEN}{text}", end="", flush=True)

    dots = max(1, width - len(text))
    for _ in range(dots):
        print(".", end="", flush=True)
        time.sleep(0.006)

    time.sleep(0.15)
    print(f" OK{RESET}")


def print_boot_sequence() -> None:
    print(f"{ORANGE}{BANNER}{RESET}", end="")
    print(f"{GREEN}[BOOTING SYSTEM...]{RESET}\n")

    for line in BOOT_LINES:
        loading_line(line)

    print(f"\n{GREEN}-----------------------------------------------")
    print("STATUS: ONLINE")
    print(f"VERSION: {VERSION}")
    print("USER: AUTHORIZED")
    print("-----------------------------------------------" + RESET + "\n")

    print(f"\n{GREEN}> Awaiting your command...{RESET}")


def input_with_cursor(prompt: str = "you > ") -> str:
    if os.name != "nt":
        return input(f"{WHITE}{prompt}{RESET}")

    import msvcrt

    user_input = ""
    print(f"{WHITE}{prompt}{RESET}", end="", flush=True)

    while True:
        if msvcrt.kbhit():
            char = msvcrt.getwch()

            if char == "\r":
                print()
                return user_input

            if char == "\b":
                user_input = user_input[:-1]
                print("\r" + " " * 100 + "\r", end="")
                print(f"{WHITE}{prompt}{user_input}_{RESET}", end="", flush=True)
                continue

            user_input += char
            print("\r" + " " * 100 + "\r", end="")
            print(f"{WHITE}{prompt}{user_input}_{RESET}", end="", flush=True)
