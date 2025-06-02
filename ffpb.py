#!/usr/bin/env python
# coding: utf-8

# Copyright (c) 2017-2021 Martin Larralde <martin.larralde@ens-paris-saclay.fr>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE
# OR OTHER DEALINGS IN THE SOFTWARE.

"""A colored progress bar for `ffmpeg` using `tqdm`.
"""

from __future__ import unicode_literals
from __future__ import print_function

import locale
import os
import re
import signal
import sys
import subprocess

if sys.version_info < (3, 0):
    import Queue as queue
    input = raw_input
else:
    import queue
    unicode = str

from tqdm import tqdm


class Colors:
    """ANSI color codes for terminal output"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # Standard colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Background colors
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'


class ColoredProgressNotifier(object):

    _DURATION_RX = re.compile(rb"Duration: (\d{2}):(\d{2}):(\d{2})\.\d{2}")
    _PROGRESS_RX = re.compile(rb"time=(\d{2}):(\d{2}):(\d{2})\.\d{2}")
    _SOURCE_RX = re.compile(rb"from '(.*)':")
    _FPS_RX = re.compile(rb"(\d{2}\.\d{2}|\d{2}) fps")

    @staticmethod
    def _seconds(hours, minutes, seconds):
        return (int(hours) * 60 + int(minutes)) * 60 + int(seconds)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.pbar is not None:
            self.pbar.close()

    def __init__(self, file=None, encoding=None, tqdm=tqdm, use_colors=True):
        self.lines = []
        self.line_acc = bytearray()
        self.duration = None
        self.source = None
        self.started = False
        self.pbar = None
        self.fps = None
        self.file = file or sys.stderr
        self.encoding = encoding or locale.getpreferredencoding() or 'UTF-8'
        self.tqdm = tqdm
        self.use_colors = use_colors and self._supports_color()
        self.colors = Colors() if self.use_colors else None

    def _supports_color(self):
        """Check if terminal supports color output"""
        if os.name == 'nt':
            # Enable color support on Windows 10+
            try:
                import colorama
                colorama.init()
                return True
            except ImportError:
                # Try to enable ANSI escape sequences on Windows
                try:
                    import ctypes
                    kernel32 = ctypes.windll.kernel32
                    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                    return True
                except:
                    return False
        else:
            # Unix-like systems
            return hasattr(self.file, 'isatty') and self.file.isatty()

    def _colorize_filename(self, filename):
        """Apply color to filename, trimming to 30 characters if needed"""
        if len(filename) > 30:
            filename = filename[:27] + "..."  # Trim to 27 chars + add "..." (total 30)
        if not self.use_colors:
            return filename
        return f"{self.colors.BRIGHT_CYAN}{self.colors.BOLD}{filename}{self.colors.RESET}"

    def _get_progress_color(self, percentage):
        """Get color based on progress percentage"""
        if not self.use_colors:
            return ""
        
        if percentage < 25:
            return self.colors.BRIGHT_RED
        elif percentage < 50:
            return self.colors.BRIGHT_YELLOW
        elif percentage < 75:
            return self.colors.BRIGHT_BLUE
        elif percentage < 95:
            return self.colors.BRIGHT_GREEN
        else:
            return self.colors.GREEN + self.colors.BOLD

    def __call__(self, char, stdin=None):
        if isinstance(char, unicode):
            char = char.encode('ascii')
        if char in b"\r\n":
            line = self.newline()
            if self.duration is None:
                self.duration = self.get_duration(line)
            if self.source is None:
                self.source = self.get_source(line)
            if self.fps is None:
                self.fps = self.get_fps(line)
            self.progress(line)
        else:
            self.line_acc.extend(char)
            if self.line_acc[-6:] == bytearray(b"[y/N] "):
                prompt_text = self.line_acc.decode(self.encoding)
                if self.use_colors:
                    # Color the prompt
                    colored_prompt = f"{self.colors.BRIGHT_YELLOW}{self.colors.BOLD}{prompt_text}{self.colors.RESET}"
                    print(colored_prompt, end="", file=self.file)
                else:
                    print(prompt_text, end="", file=self.file)
                self.file.flush()
                if stdin:
                    stdin.put(input() + "\n")
                self.newline()

    def newline(self):
        line = bytes(self.line_acc)
        self.lines.append(line)
        self.line_acc = bytearray()
        return line

    def get_fps(self, line):
        search = self._FPS_RX.search(line)
        if search is not None:
            return round(float(search.group(1)))
        return None

    def get_duration(self, line):
        search = self._DURATION_RX.search(line)
        if search is not None:
            return self._seconds(*search.groups())
        return None

    def get_source(self, line):
        search = self._SOURCE_RX.search(line)
        if search is not None:
            return os.path.basename(search.group(1).decode(self.encoding))
        return None

    def progress(self, line):
        search = self._PROGRESS_RX.search(line)
        if search is not None:

            total = self.duration
            current = self._seconds(*search.groups())
            unit = " seconds"

            if self.fps is not None:
                unit = " frames"
                current *= self.fps
                if total:
                    total *= self.fps

            if self.pbar is None:
                # Create colored description
                desc = self.source
                if self.use_colors and desc:
                    desc = self._colorize_filename(desc)
                
                # Create progress bar with custom format
                bar_format = None
                if self.use_colors:
                    bar_format = (
                        f'{self.colors.BRIGHT_WHITE}{{desc}}: '
                        f'{self.colors.BRIGHT_GREEN}{{percentage:3.0f}}%'
                        f'{self.colors.RESET}|{self.colors.BRIGHT_BLUE}{{bar}}{self.colors.RESET}| '
                        f'{self.colors.WHITE}{{n_fmt}}/{{total_fmt}}'
                        f'{self.colors.BRIGHT_YELLOW} [{{elapsed}}<{{remaining}}, {{rate_fmt}}]'
                        f'{self.colors.RESET}'
                    )

                self.pbar = self.tqdm(
                    desc=desc,
                    file=self.file,
                    total=total,
                    dynamic_ncols=True,
                    unit=unit,
                    ncols=0,
                    #ascii=os.name == "nt" and not self.use_colors,  # use unicode if colors are supported
                    ascii='          ▒',
                    bar_format=bar_format,
                    colour='green' if self.use_colors else None,
                )

            # Update progress bar with color changes based on percentage
            if total and self.use_colors:
                percentage = (current / total) * 100
                color = self._get_progress_color(percentage)
                # Update the bar color dynamically
                self.pbar.colour = 'green'

            self.pbar.update(current - self.pbar.n)


def main(argv=None, stream=sys.stderr, encoding=None, tqdm=tqdm, use_colors=True):
    argv = argv or sys.argv[1:]

    try:
        with ColoredProgressNotifier(file=stream, encoding=encoding, tqdm=tqdm, use_colors=use_colors) as notifier:

            cmd = ["ffmpeg"] + argv
            p = subprocess.Popen(cmd, stderr=subprocess.PIPE)

            while True:
                out = p.stderr.read(1)
                if out == b"" and p.poll() != None:
                    break
                if out != b"":
                    notifier(out)

    except KeyboardInterrupt:
        if use_colors and hasattr(stream, 'isatty') and stream.isatty():
            print(f"{Colors.BRIGHT_RED}{Colors.BOLD}Exiting.{Colors.RESET}", file=stream)
        else:
            print("Exiting.", file=stream)
        return signal.SIGINT + 128  # POSIX standard

    except Exception as err:
        if use_colors and hasattr(stream, 'isatty') and stream.isatty():
            print(f"{Colors.BRIGHT_RED}Unexpected exception: {Colors.BRIGHT_WHITE}{err}{Colors.RESET}", file=stream)
        else:
            print("Unexpected exception:", err, file=stream)
        return 1

    else:
        if p.returncode != 0:
            error_msg = notifier.lines[-1].decode(notifier.encoding)
            if use_colors and hasattr(stream, 'isatty') and stream.isatty():
                print(f"{Colors.BRIGHT_RED}{error_msg}{Colors.RESET}", file=stream)
            else:
                print(error_msg, file=stream)
        return p.returncode


if __name__ == "__main__":
    sys.exit(main())