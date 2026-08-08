#!/bin/bash
INPUT="NASA - Moon Phases_ 2001 to 2100.html"

(
    echo "        self.new_moon_array = ("
    python3 extract.py 0 < "$INPUT"
    echo "        )"
) > extract-new-moon.tmp

(
    echo "        self.first_quarter_array = ("
    python3 extract.py 1 < "$INPUT"
    echo "        )"
) > extract-first-quarter.tmp

(
    echo "        self.full_moon_array = ("
    python3 extract.py 2 < "$INPUT"
    echo "        )"
) > extract-full-moon.tmp

(
    echo "        self.last_quarter_array = ("
    python3 extract.py 3 < "$INPUT"
    echo "        )"
) > extract-last-quarter.tmp
