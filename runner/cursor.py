import curses
from curses import wrapper


def main(stdscr):
    # Clear screen
    # curses.curs_set(False)
    curses.init_pair(1, curses.COLOR_RED, curses.COLOR_BLACK)
    stdscr.clear()
    stdscr.addstr(0, 0, "Current mode: Typing mode\n", curses.color_pair(1))

    stdscr.refresh()
    # This raises ZeroDivisionError when i == 10.
    stdscr.addstr('{}, {}'.format(curses.COLS, curses.LINES))
    for i in range(0, 11):
        stdscr.addstr('10 divided by {} is {}\n')
    stdscr.refresh()
    while True:

        stdscr.addstr('{}\n'.format(stdscr.getkey()))
        stdscr.refresh()


wrapper(main)
