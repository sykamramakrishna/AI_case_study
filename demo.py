import sys

from compiler_agent.agent import Agent, CompilationError
from compiler_agent.executor import ExecutionError

COMMANDS = [
    "take a screenshot and paste it into the word document",
    "open notepad and type hello from the compiler agent, this is the project review",
    "open notepad and copy and paste into notepad",
    "open youtube and search for compiler design lexical analysis",
    "press tab 3 times and wait 2 seconds and wait 1 second",
    "if test_output.txt does not exist then create test_output.txt otherwise delete test_output.txt",
    "create test_output.txt and if test_output.txt exists then type it worked end if and delete test_output.txt",
    "repeat 12 times press down end repeat",
]

INVALID = [
    "paste into word",
    "delete notes.txt and delete notes.txt",
    "press control banana",
    "repeat 500 times press tab",
    "open notepad otherwise close notepad",
]


def run(agent, cmd):
    print("\n" + "=" * 70)
    print(f"COMMAND: {cmd}")
    print("=" * 70)
    try:
        agent.run(cmd, verbose=True)
    except CompilationError as e:
        print(f"\nCOMPILE ERROR: {e}")
    except ExecutionError as e:
        print(f"\nEXECUTION ERROR: {e}")


def main():
    live = "--live" in sys.argv
    for cmd in COMMANDS:
        run(Agent(dry_run=not live), cmd)
    print("\n\n##### Commands the compiler rejects before touching the computer #####")
    for cmd in INVALID:
        run(Agent(dry_run=True), cmd)


if __name__ == "__main__":
    main()
