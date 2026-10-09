"""Small native paging control shared by history and analytical tables."""

from tkinter import ttk
from typing import Callable


class TablePager(ttk.Frame):
    def __init__(self, parent, command: Callable[[], None], *, page_size: int = 100):
        super().__init__(parent, padding=(0, 8), style="Card.TFrame")
        self.command = command
        self.page_size = page_size
        self.offset = 0
        self.total = 0
        self.previous = ttk.Button(self, text="Previous", style="Secondary.TButton", command=lambda: self.move(-1))
        self.previous.pack(side="left")
        self.label = ttk.Label(self, padding=(12, 0), style="CardText.TLabel")
        self.label.pack(side="left")
        self.next = ttk.Button(self, text="Next", style="Secondary.TButton", command=lambda: self.move(1))
        self.next.pack(side="left")
        self.set_total(0)

    def set_total(self, total: int, *, reset: bool = False) -> None:
        self.total = total
        last = max(0, ((total - 1) // self.page_size) * self.page_size)
        self.offset = 0 if reset else min(self.offset, last)
        start = self.offset + 1 if total else 0
        end = min(self.offset + self.page_size, total)
        self.label.configure(text=f"{start:,}-{end:,} of {total:,}")
        self.previous.configure(state="normal" if self.offset else "disabled")
        self.next.configure(state="normal" if end < total else "disabled")

    def move(self, pages: int) -> None:
        self.offset = max(0, self.offset + pages * self.page_size)
        self.set_total(self.total)
        self.command()
