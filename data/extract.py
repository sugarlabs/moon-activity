#!/usr/bin/python3
# quick hack to extract data from web.archive.org copy of nasa web page
# by quozl@laptop.org 2026-08-09
import sys
from datetime import datetime

month_map = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4,
    'May': 5, 'Jun': 6, 'Jul': 7, 'Aug': 8,
    'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
}

filt = int(sys.argv[1])  # which column to extract

def nob(text, cols):
    global year

    if cols != filt:
        return

    if text.strip() == '':
        return

    # Jan 24  13:07
    # 0123456789012

    m = text[0:3]
    if m not in month_map:
        return

    m = month_map[m]
    d = int(text[4:6])
    y = int(year)

    h = int(text[8:10])
    i = int(text[11:13])
    u = text[14]
    if u == ' ' or u == '':
        if cols == 0 or cols == 2:
            u = '_'
        else:
            u = ''

    dt = datetime(y, m, d, h, i)

    print('            "' + dt.strftime('%Y-%m-%d %H:%M') + u + '",')


state = 0

for line in sys.stdin.readlines():
    if 'prehead' in line:
        state = 1

    if 'Back to ' in line:
        state = 0

    if state == 0:
        continue

    if '<' in line:
        continue

#          1         2         3         4         5         6         7         8
#012345678901234567890123456789012345678901234567890123456789012345678901234567890123456789
#
# 2001                     Jan  2  22:31     Jan  9  20:24 t   Jan 16  12:35      00h01m
#        Jan 24  13:07     Feb  1  14:02     Feb  8  07:12     Feb 15  03:24    

    text = line[1:5]
    if text == '':
        continue

    if text != '    ':
        year = int(text)

    if year < 2026:
        continue

    nob(line[8:26], 0)
    nob(line[26:44], 1)
    nob(line[44:62], 2)
    nob(line[62:77], 3)
