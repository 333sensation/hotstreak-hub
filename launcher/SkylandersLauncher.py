#!/usr/bin/env python3
"""Skylanders SuperChargers Racing - roster launcher.

A launcher window: it holds the mod image, rolls a new cast of opponents every
boot with the real in-game portraits, writes the roster into the disc and starts
the game. Everything the window shows comes from the disc itself (see
`tools/extract_art.py`), nothing is stock art.

    python3 launcher/SkylandersLauncher.py
"""
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font as tkfont

from PIL import Image, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pipeline as P  # noqa: E402
import platforms as PF  # noqa: E402
import sessions as SESS  # noqa: E402
import toys as TOYS  # noqa: E402

BG = "#080b12"
PANEL = "#0e1420"
CARD = "#131b2a"
CARD_HI = "#1d2942"
LINE = "#1c2740"
INK = "#e8eefc"
DIM = "#7f8ca8"
ACCENT = "#ffb400"
ACCENT2 = "#3fc6ff"
TERRAIN_COLOR = {"air": "#3fc6ff", "land": "#7ee36b", "sea": "#ff7ad1"}
TERRAIN_TITLE = {"air": "AIR", "land": "LAND", "sea": "SEA"}
LOGO = os.path.join(HERE, "assets", "bg", "ICON_GameTitle_DA.png")


def hexmix(a, b, t):
    a = a.lstrip("#")
    b = b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(int(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))


class Images:
    """Portrait cache: 64px cards and 48px picker thumbs."""

    def __init__(self):
        self._small = {}
        self._tiny = {}

    def _load(self, rel, size, store):
        if rel is None:
            return None
        if rel in store:
            return store[rel]
        path = os.path.join(HERE, "assets", rel)
        try:
            with Image.open(path) as im:
                im = im.convert("RGBA").resize(size, Image.LANCZOS)
                photo = ImageTk.PhotoImage(im)
        except OSError:
            photo = None
        store[rel] = photo
        return photo

    def small(self, rel):
        return self._load(rel, (112, 112), self._small)

    def tiny(self, rel):
        return self._load(rel, (48, 48), self._tiny)


class RoundButton(tk.Canvas):
    """Flat rounded button that keeps the launcher looking like one app."""

    def __init__(self, master, text, command, width=260, height=58,
                 fill=ACCENT, ink="#151a24", font=None):
        super().__init__(master, width=width, height=height, bg=PANEL,
                         highlightthickness=0, bd=0)
        self.command = command
        self.fill = fill
        self.ink = ink
        self.w, self.h = width, height
        self.text = text
        self.font = font or (PF.UI, 15, "bold")
        self._draw(self.fill)
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self._draw(hexmix(self.fill, "#ffffff", 0.18)))
        self.bind("<Leave>", lambda e: self._draw(self.fill))
        self.configure(cursor=PF.HAND)

    def _draw(self, fill):
        self.delete("all")
        r = self.h // 2
        self.create_oval(0, 0, self.h, self.h, fill=fill, outline=fill)
        self.create_oval(self.w - self.h, 0, self.w, self.h, fill=fill, outline=fill)
        self.create_rectangle(self.h / 2, 0, self.w - self.h / 2, self.h,
                              fill=fill, outline=fill)
        self.create_text(self.w / 2, self.h / 2 + 1, text=self.text,
                         fill=self.ink, font=self.font)

    def set_text(self, text):
        self.text = text
        self._draw(self.fill)


class PortraitCard(tk.Frame):
    def __init__(self, master, images, on_click=None):
        super().__init__(master, bg=CARD, highlightthickness=1,
                         highlightbackground=LINE)
        self.images = images
        self.fig = None
        # pixel-sized slot: tk.Label sizes in characters once the image is set,
        # which blew the card up to 64 characters wide
        self.frame = tk.Frame(self, bg=CARD, width=112, height=112)
        self.frame.pack(padx=6, pady=(6, 2))
        self.frame.pack_propagate(False)
        self.art = tk.Label(self.frame, bg=CARD)
        self.art.pack(fill="both", expand=True)
        self.name = tk.Label(self, bg=CARD, fg=INK, font=(PF.UI, 9),
                             width=15, anchor="center")
        self.name.pack(pady=(0, 4))
        for w in (self, self.frame, self.art, self.name):
            w.bind("<Button-1>", lambda e: on_click(self.fig) if on_click else None)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _paint(self, bg, border):
        for w in (self, self.frame, self.art, self.name):
            w.configure(bg=bg)
        self.configure(highlightbackground=border)

    def _enter(self, _e=None):
        self._paint(CARD_HI, ACCENT2)

    def _leave(self, _e=None):
        self._paint(CARD, ACCENT if (self.fig and self.fig["pinned"]) else LINE)

    def set_figure(self, fig):
        self.fig = fig
        photo = self.images.small(fig["art"]) if fig["art"] else None
        if photo is None:
            self.art.configure(image="", text=fig["display"][:2].upper(),
                               fg=DIM, font=(PF.UI, 26, "bold"))
        else:
            self.art.configure(image=photo, text="")
            self.art.image = photo
        label = fig["display"]
        if len(label) > 15:
            label = label[:14] + "\u2026"
        self.name.configure(text=("\u2605 " if fig["pinned"] else "") + label)
        self._paint(CARD, ACCENT if fig["pinned"] else LINE)


class RosterPicker(tk.Toplevel):
    """Pick the figures that must be in every cast."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Pin figures")
        self.configure(bg=BG)
        self.geometry("940x760")
        self.transient(app.root)

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(top, text="PIN A FIGURE", bg=BG, fg=INK,
                 font=(PF.UI, 16, "bold")).pack(side="left")
        self.query = tk.Entry(top, bg=PANEL, fg=INK, insertbackground=INK,
                              relief="flat", font=(PF.UI, 12), width=26)
        self.query.pack(side="right", ipady=6, padx=(10, 0))
        self.query.bind("<KeyRelease>", lambda e: self.refresh())
        tk.Label(top, text="search", bg=BG, fg=DIM,
                 font=(PF.UI, 10)).pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=6)
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        bar = tk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta), "units"))
        if PF.IS_LINUX:      # X11 reports the wheel as buttons 4 and 5
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=18, pady=12)
        self.status = tk.Label(bottom, bg=BG, fg=DIM, font=(PF.UI, 10))
        self.status.pack(side="left")
        RoundButton(bottom, "DONE", self.destroy, width=150, height=44).pack(side="right")

        self.cards = []
        self.refresh()

    def refresh(self):
        for w in self.inner.winfo_children():
            w.destroy()
        q = self.query.get().strip().lower()
        figs = [f for f in self.app.session.figures
                if not q or q in f["display"].lower()]
        per_row = 9
        for i, f in enumerate(figs):
            card = tk.Frame(self.inner, bg=CARD, highlightthickness=1,
                            highlightbackground=ACCENT if f["display"] in self.app.session.pins else LINE)
            photo = self.app.images.tiny(f["art"]) if f["art"] else None
            art = tk.Label(card, bg=CARD, image=photo, text="" if photo else f["display"][:2].upper(),
                           fg=DIM, font=(PF.UI, 16, "bold"))
            art.image = photo
            art.pack(padx=4, pady=(4, 0))
            name = tk.Label(card, bg=CARD, fg=INK, font=(PF.UI, 8),
                            text=(f["display"][:12] + "\u2026" if len(f["display"]) > 12
                                  else f["display"]), width=13)
            name.pack(pady=(0, 3))
            for w in (card, art, name):
                w.bind("<Button-1>", lambda e, fig=f, c=card: self.toggle(fig, c))
            card.grid(row=i // per_row, column=i % per_row, padx=3, pady=3)
        self.status.configure(text="%d figures  \u00b7  %d pinned" %
                                   (len(figs), len(self.app.session.pins)))

    def toggle(self, fig, card):
        on = self.app.session.toggle_pin(fig["display"])
        card.configure(highlightbackground=ACCENT if on else LINE)
        self.status.configure(text="%d pinned" % len(self.app.session.pins))
        self.app.refresh_roster(repaint=True)


class ToyPicker(tk.Toplevel):
    """Choose the Skylander and the vehicle that go on the portal.

    The figure you race as is not in the pkz - the game reads it from the Portal
    of Power, and Dolphin emulates one. So picking here writes the toy's real
    1024-byte tag image into Dolphin's collection folder (live: the portal window
    can swap it while the game runs) and turns the emulated portal on.
    """

    TABS = (("figure", "SKYLANDERS"), ("vehicle", "VEHICLES"))

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Your Skylander")
        self.configure(bg=BG)
        self.geometry("1040x800")
        self.transient(app.root)
        self.pair = dict(app.toys)
        self.tab = "figure"
        self._art = {}

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(top, text="YOUR SKYLANDER", bg=BG, fg=INK,
                 font=(PF.UI, 16, "bold")).pack(side="left")
        self.query = tk.Entry(top, bg=PANEL, fg=INK, insertbackground=INK,
                              relief="flat", font=(PF.UI, 12), width=26)
        self.query.pack(side="right", ipady=6, padx=(10, 0))
        self.query.bind("<KeyRelease>", lambda e: self.refresh())
        tk.Label(top, text="search", bg=BG, fg=DIM, font=(PF.UI, 10)).pack(side="right")

        tabs = tk.Frame(self, bg=BG)
        tabs.pack(fill="x", padx=18, pady=(6, 0))
        self.tab_btns = {}
        for kind, label in self.TABS:
            btn = RoundButton(tabs, label, lambda k=kind: self.set_tab(k),
                              width=170, height=38, fill=CARD_HI if kind == "figure" else CARD,
                              ink=INK, font=(PF.UI, 10, "bold"))
            btn.pack(side="left", padx=(0, 8))
            self.tab_btns[kind] = btn

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=6)
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        bar = tk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta), "units"))
        if PF.IS_LINUX:
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=18, pady=12)
        self.status = tk.Label(bottom, bg=BG, fg=DIM, font=(PF.UI, 10), anchor="w",
                               justify="left")
        self.status.pack(side="left")
        RoundButton(bottom, "DONE", self.destroy, width=150, height=44).pack(side="right")

        self.refresh()

    # ------------------------------------------------------------------ drawing
    def set_tab(self, kind):
        self.tab = kind
        for k, btn in self.tab_btns.items():
            btn.fill = CARD_HI if k == kind else CARD
        self.canvas.yview_moveto(0)
        self.refresh()

    def _toy_art(self, toy):
        if toy.label in self._art:
            return self._art[toy.label]
        art = None
        if toy.kind in ("figure", "mini"):
            try:
                import assets as A
                import roster as R
                if not hasattr(self, "_art_index"):
                    self._art_index = A._art_index()
                art = A._pick(self._art_index, R.display(toy.base))
            except Exception:  # noqa: BLE001 - art is decoration, never fatal
                art = None
        self._art[toy.label] = art
        return art

    def refresh(self):
        for w in self.inner.winfo_children():
            w.destroy()
        q = self.query.get().strip().lower()
        kind = self.tab
        if kind == "figure":
            toys = [t for t in TOYS.figures()]
        else:
            toys = TOYS.vehicles()
        if q:
            toys = [t for t in toys if q in t.label.lower()]
        toys.sort(key=lambda t: t.label.lower())
        chosen = self.pair.get(kind)
        per_row = 9
        for i, toy in enumerate(toys):
            on = chosen is not None and chosen.name == toy.name
            card = tk.Frame(self.inner, bg=CARD, highlightthickness=1,
                            highlightbackground=ACCENT if on else LINE)
            art = self._toy_art(toy)
            photo = self.app.images.tiny(art) if art else None
            img = tk.Label(card, bg=CARD, image=photo,
                           text="" if photo else toy.label[:2].upper(),
                           fg=DIM, font=(PF.UI, 14, "bold"))
            img.image = photo
            img.pack(padx=4, pady=(4, 0))
            name = tk.Label(card, bg=CARD, fg=INK, font=(PF.UI, 8),
                            text=(toy.label[:14] + "\u2026" if len(toy.label) > 14
                                  else toy.label), width=14)
            name.pack(pady=(0, 3))
            for w in (card, img, name):
                w.bind("<Button-1>", lambda e, t=toy: self.pick(t))
            card.grid(row=i // per_row, column=i % per_row, padx=3, pady=3)
        self.update_status(len(toys))

    def update_status(self, shown):
        fig = self.pair.get("figure")
        veh = self.pair.get("vehicle")
        self.status.configure(text="%d shown  \u00b7  on the portal: %s%s" % (
            shown,
            fig.label if fig else "nothing",
            (" + " + veh.label) if veh else ""))

    # ------------------------------------------------------------------- picking
    def pick(self, toy):
        self.pair[toy.kind] = toy
        try:
            TOYS.install(self.pair)
            TOYS.save_selection(self.pair)
            note = TOYS.enable_portal()
        except Exception as exc:  # noqa: BLE001
            note = "could not write the toy: %s" % exc
        self.app.set_toys(self.pair, note)
        self.refresh()


class NetplayDialog(tk.Toplevel):
    """Two machines, one race: Dolphin netplay over the game's split-screen 2P.

    Netplay refuses to start unless both sides run the exact same disc, and this
    disc's roster is random per boot - so both players derive the roster from the
    session code. Same code, same figures, byte-identical image.
    """

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Play with a friend")
        self.configure(bg=BG)
        self.geometry("640x760")
        self.transient(app.root)
        self.q = queue.Queue()
        self.code = tk.StringVar(value=P.new_code())
        self.info = {}
        self._session_rows = []

        # LAN session browser: hosts announce, everyone on the network sees it
        self.discovery = SESS.Discovery()
        self.discovery.start()
        self.beacon = None
        self.protocol("WM_DELETE_WINDOW", self.close)

        tk.Label(self, text="PLAY WITH A FRIEND", bg=BG, fg=INK,
                 font=(PF.UI, 18, "bold")).pack(anchor="w", padx=22, pady=(20, 2))
        tk.Label(self, text="Dolphin netplay \u00b7 two machines \u00b7 the game's own split-screen 2P\n"
                            "The session code makes both discs byte-identical, so netplay's\n"
                            "game check passes and both players see the same cast.",
                 bg=BG, fg=DIM, font=self.app.f_small, justify="left").pack(anchor="w", padx=22)

        lan = tk.Frame(self, bg=BG)
        lan.pack(fill="x", padx=22, pady=(14, 2))
        tk.Label(lan, text="ACTIVE SESSIONS ON YOUR NETWORK", bg=BG, fg=DIM,
                 font=PF.ui_font(9, bold=True)).pack(anchor="w")
        self.lan_box = tk.Frame(lan, bg=PANEL)
        self.lan_box.pack(fill="x", pady=(4, 0))
        self.lan_empty = tk.Label(self.lan_box, text="looking for sessions ...", bg=PANEL,
                                  fg=DIM, font=PF.ui_font(10), anchor="w", padx=10, pady=8)
        self.lan_empty.pack(fill="x")

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=22, pady=(16, 6))
        tk.Label(row, text="SESSION CODE", bg=BG, fg=DIM,
                 font=(PF.UI, 9, "bold")).pack(anchor="w")
        entry = tk.Entry(row, textvariable=self.code, bg=PANEL, fg=INK, insertbackground=INK,
                         relief="flat", font=(PF.MONO, 22, "bold"), width=8, justify="center")
        entry.pack(side="left", ipady=6, pady=(4, 0))
        RoundButton(row, "HOST", lambda: self.start("host"), width=120, height=48).pack(
            side="left", padx=(12, 6), pady=(4, 0))
        RoundButton(row, "JOIN", lambda: self.start("join"), width=120, height=48,
                    fill="#243250", ink=INK).pack(side="left", pady=(4, 0))

        self.status = tk.Label(self, text="host a session or type your friend's code and join",
                               bg=BG, fg=ACCENT2, font=self.app.f_small, wraplength=560,
                               justify="left")
        self.status.pack(anchor="w", padx=22, pady=(14, 6))

        self.detail = tk.Label(self, text="", bg=PANEL, fg=INK, font=(PF.MONO, 10),
                               justify="left", anchor="nw", wraplength=560, padx=14, pady=12)
        self.detail.pack(fill="both", expand=True, padx=22, pady=6)

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=22, pady=(4, 18))
        self.copy_btn = RoundButton(actions, "COPY CODE", self.copy_code, width=170, height=44,
                                    fill="#1a2334", ink=INK)
        self.copy_btn.pack(side="left")
        self.open_btn = RoundButton(actions, "OPEN DOLPHIN", self.open_dolphin, width=190,
                                    height=44, fill="#1a2334", ink=INK)
        self.open_btn.pack(side="left", padx=10)
        self.after(80, self._pump)
        self._tick_sessions()

    # --------------------------------------------------------------- sessions
    def _tick_sessions(self):
        """Refresh the browser; a session row fills in the code when clicked."""
        try:
            found = self.discovery.active()
        except Exception:  # noqa: BLE001 - a dead socket must not kill the window
            found = []
        if [s.get("code") for s in found] != [s.get("code") for s in self._session_rows]:
            for child in self.lan_box.winfo_children():
                child.destroy()
            self._session_rows = found
            if not found:
                self.lan_empty = tk.Label(self.lan_box, text="no session on your network yet \u2014 "
                                                             "host one, or type a code below",
                                          bg=PANEL, fg=DIM, font=PF.ui_font(10),
                                          anchor="w", padx=10, pady=8)
                self.lan_empty.pack(fill="x")
            for info in found:
                row = tk.Frame(self.lan_box, bg=PANEL, cursor=PF.HAND)
                row.pack(fill="x")
                left = tk.Label(row, text=info["code"], bg=PANEL, fg=ACCENT,
                                font=PF.mono_font(12, bold=True), padx=10, pady=6)
                left.pack(side="left")
                mid = tk.Label(row, text="%s \u00b7 %s:%s \u00b7 %d/%d" % (
                    info.get("host", "?"), info.get("addr", "?"),
                    info.get("port", P.NETPLAY_PORT), info.get("players", 2), 2),
                    bg=PANEL, fg=INK, font=PF.ui_font(10), anchor="w")
                mid.pack(side="left")
                for w in (row, left, mid):
                    w.bind("<Button-1>", lambda e, i=info: self.pick(i))
        self.after(1000, self._tick_sessions)

    def pick(self, info):
        self.code.set(info["code"])
        self.status.configure(text="session %s by %s selected \u2014 press JOIN"
                                   % (info["code"], info.get("host", "?")))

    def close(self):
        try:
            if self.beacon:
                self.beacon.stop()
            self.discovery.stop()
        finally:
            self.destroy()

    # ------------------------------------------------------------------ actions
    def copy_code(self):
        self.clipboard_clear()
        self.clipboard_append(self.code.get().strip().upper())
        self.status.configure(text="code copied \u2014 send it to your friend")

    def open_dolphin(self):
        try:
            self.app.pipe.launch()
            self.status.configure(text="Dolphin starting \u2014 Tools \u2192 Start Netplay")
        except Exception as exc:  # noqa: BLE001
            self.status.configure(text="could not start Dolphin: %s" % exc)

    def start(self, role):
        try:
            code = self.code.get().strip().upper()
            seed = P.seed_from_code(code)
        except ValueError:
            self.status.configure(text="that code has characters a code cannot contain")
            return
        self.status.configure(text="building the disc for code %s ..." % code)
        self.detail.configure(text="")
        self.app.session.roll(seed=seed, use_pins=False)
        self.app.refresh_roster(repaint=True)
        import threading

        def work():
            try:
                data, changed = self.app.session.patched_bytes()
                self.app.pipe.patch_tree(data)
                self.app.pipe.patch_cups(seed)   # same code -> same cups on both sides
                self.app.pipe.build_image()
                md5 = P.image_md5()
                self.q.put((role, code, md5, changed))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", str(exc), "", 0))

        threading.Thread(target=work, daemon=True).start()

    def _pump(self):
        try:
            while True:
                role, code, md5, changed = self.q.get_nowait()
                if role == "error":
                    self.status.configure(text="failed: %s" % code)
                    continue
                self.info = {"role": role, "code": code, "md5": md5}
                if role == "host":
                    if self.beacon:
                        self.beacon.stop()
                    self.beacon = SESS.Beacon(code, P.NETPLAY_PORT)
                    self.beacon.start()
                self.status.configure(text=
                    "ready \u00b7 %d racer records \u00b7 both discs must show the same hash" % changed)
                ip = P.local_ip()
                if role == "host":
                    text = ("HOST\n"
                            "code      %s\n"
                            "address   %s:%d\n"
                            "game md5  %s\n\n"
                            "In Dolphin: Tools \u2192 Start Netplay \u2192 Host, pick\n"
                            "  %s\n"
                            "as the game, port %d. Send your friend the code and\n"
                            "your address (port-forward %d if you are not on the same LAN).\n\n"
                            "Then in game: player 2 presses a button on the second\n"
                            "controller for split-screen.")
                    self.detail.configure(text=text % (
                        code, ip, P.NETPLAY_PORT, md5, os.path.basename(P.IMAGE),
                        P.NETPLAY_PORT, P.NETPLAY_PORT))
                else:
                    text = ("JOIN\n"
                            "code      %s\n"
                            "game md5  %s\n\n"
                            "In Dolphin: Tools \u2192 Start Netplay \u2192 Connect, enter the\n"
                            "host's address and port, and pick\n"
                            "  %s\n"
                            "as the game.\n\n"
                            "If Dolphin says the game versions differ, the code was\n"
                            "typed wrong \u2014 the hash must be the host's hash.\n\n"
                            "Then in game: player 2 presses a button on the second\n"
                            "controller for split-screen.")
                    self.detail.configure(text=text % (
                        code, md5, os.path.basename(P.IMAGE)))
        except Exception:  # queue.Empty
            pass
        self.after(120, self._pump)


class LauncherApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Hotstreak Hub \u2014 Skylanders SuperChargers Racing")
        self.root.configure(bg=BG)
        w, h = 1460, 880
        x = max(0, (self.root.winfo_screenwidth() - w) // 2)
        y = max(0, (self.root.winfo_screenheight() - h) // 3)
        self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        self.root.minsize(1280, 760)

        self.images = Images()
        self.session = P.Session()
        self.pipe = P.Pipeline(log=self.log)
        self.cards = {t: [] for t in P.TERRAINS}
        self.busy = False
        self.q = queue.Queue()
        self._history = []
        self.toys, _saved = TOYS.load_selection()

        self._fonts()
        self._layout()
        self.refresh_roster()
        self.set_toys(self.toys)
        self.root.after(80, self._pump)
        self.log("ready \u00b7 %d figures \u00b7 %d racer slots"
                 % (len(self.session.figures), len(self.session.slots)))

    # ------------------------------------------------------------------- fonts
    def _fonts(self):
        self.f_head = (PF.UI, 13, "bold")
        self.f_small = (PF.UI, 10)
        self.f_tiny = (PF.UI, 9)

    # ------------------------------------------------------------------ layout
    def _layout(self):
        head = tk.Frame(self.root, bg=BG, height=126)
        head.pack(fill="x", padx=26, pady=(18, 6))
        head.pack_propagate(False)

        try:
            with Image.open(LOGO) as im:
                h = 104
                w = int(im.width * h / im.height)
                self.logo_img = ImageTk.PhotoImage(im.convert("RGBA").resize((w, h), Image.LANCZOS))
            tk.Label(head, bg=BG, image=self.logo_img).pack(side="left")
        except OSError:
            tk.Label(head, bg=BG, fg=INK, text="SKYLANDERS SUPERCHARGERS RACING",
                     font=(PF.UI, 26, "bold")).pack(side="left")

        right = tk.Frame(head, bg=BG)
        right.pack(side="right", anchor="e")
        tk.Label(right, text="ROSTER LAUNCHER", bg=BG, fg=ACCENT,
                 font=(PF.UI, 11, "bold")).pack(anchor="e")
        tk.Label(right, text="a new cast every boot", bg=BG, fg=DIM,
                 font=self.f_small).pack(anchor="e")
        self.image_state = tk.Label(right, text="", bg=BG, fg=DIM, font=self.f_tiny)
        self.image_state.pack(anchor="e", pady=(6, 0))

        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x", padx=26, pady=(4, 10))

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=26, pady=(0, 8))

        # left: the cast, one terrain at a time
        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)

        tabs = tk.Frame(left, bg=BG)
        tabs.pack(fill="x", pady=(0, 4))
        self.tab_btns = {}
        for terrain in P.TERRAINS:
            btn = tk.Label(tabs, text=TERRAIN_TITLE[terrain], bg=BG, fg=DIM,
                           font=(PF.UI, 15, "bold"), padx=16, pady=8,
                           cursor=PF.HAND)
            btn.pack(side="left", padx=(0, 4))
            btn.bind("<Button-1>", lambda e, t=terrain: self.select_terrain(t))
            self.tab_btns[terrain] = btn
        tk.Label(left, text="click a portrait to pin it for every cast", bg=BG,
                 fg=DIM, font=self.f_tiny).pack(anchor="w", pady=(0, 12))

        self.grid_area = tk.Frame(left, bg=BG)
        self.grid_area.pack(fill="both", expand=True)
        self.panels, self.cards = {}, {t: [] for t in P.TERRAINS}
        for terrain in P.TERRAINS:
            panel = tk.Frame(self.grid_area, bg=BG)
            self.panels[terrain] = panel
            n = len(self.session.groups()[terrain])
            per_row = 8
            for i in range(n):
                card = PortraitCard(panel, self.images, on_click=self.toggle_pin)
                card.grid(row=i // per_row, column=i % per_row, padx=4, pady=4)
                self.cards[terrain].append(card)
        self.foot = tk.Label(left, text="", bg=BG, fg=DIM, font=self.f_tiny)
        self.foot.pack(anchor="w", pady=(10, 0))
        self.terrain = None
        self.select_terrain("air")

        # right: controls. The column is taller than a short screen allows, so
        # it scrolls instead of losing the status box at the bottom.
        holder = tk.Frame(body, bg=PANEL, width=330)
        holder.pack(side="right", fill="y", padx=(18, 0))
        holder.pack_propagate(False)
        side_canvas = tk.Canvas(holder, bg=PANEL, highlightthickness=0, width=310)
        side_bar = tk.Scrollbar(holder, orient="vertical", command=side_canvas.yview)
        side_canvas.configure(yscrollcommand=side_bar.set)
        side_bar.pack(side="right", fill="y")
        side_canvas.pack(side="left", fill="both", expand=True)
        side = tk.Frame(side_canvas, bg=PANEL)
        side_canvas.create_window((0, 0), window=side, anchor="nw", width=312)
        side.bind("<Configure>",
                  lambda e: side_canvas.configure(scrollregion=side_canvas.bbox("all")))

        def _wheel(e, step=2):
            side_canvas.yview_scroll(-step if e.delta > 0 else step, "units")

        def _grab(e):
            holder.bind_all("<MouseWheel>", _wheel)
            holder.bind_all("<Button-4>", lambda ev: side_canvas.yview_scroll(-step_wheel, "units"))
            holder.bind_all("<Button-5>", lambda ev: side_canvas.yview_scroll(step_wheel, "units"))

        step_wheel = 3
        holder.bind("<Enter>", _grab)
        holder.bind("<Leave>", lambda e: [holder.unbind_all(s) for s in
                                          ("<MouseWheel>", "<Button-4>", "<Button-5>")])

        tk.Label(side, text="NEXT CAST", bg=PANEL, fg=DIM,
                 font=(PF.UI, 10, "bold")).pack(anchor="w", padx=22, pady=(20, 2))
        self.counts = tk.Label(side, text="", bg=PANEL, fg=INK,
                               font=(PF.UI, 12), justify="left")
        self.counts.pack(anchor="w", padx=22)

        self.play_btn = RoundButton(side, "\u25b6  PLAY", self.play, width=286, height=72,
                                    fill=ACCENT, ink="#141821",
                                    font=(PF.UI, 20, "bold"))
        self.play_btn.pack(padx=22, pady=(22, 8))

        self.roll_btn = RoundButton(side, "ROLL NEW CAST", self.roll, width=286, height=46,
                                    fill="#243250", ink=INK, font=(PF.UI, 12, "bold"))
        self.roll_btn.pack(padx=22, pady=4)

        self.pin_btn = RoundButton(side, "PIN FIGURES", self.open_picker, width=286, height=46,
                                   fill="#1a2334", ink=INK, font=(PF.UI, 12, "bold"))
        self.pin_btn.pack(padx=22, pady=4)

        self.netplay_btn = RoundButton(side, "PLAY WITH A FRIEND", self.open_netplay, width=286,
                                       height=46, fill="#1a2334", ink=INK,
                                       font=(PF.UI, 12, "bold"))
        self.netplay_btn.pack(padx=22, pady=4)

        self.toys_btn = RoundButton(side, "YOUR SKYLANDER", self.open_toys, width=286,
                                    height=46, fill="#1a2334", ink=INK,
                                    font=(PF.UI, 12, "bold"))
        self.toys_btn.pack(padx=22, pady=4)

        self.toys_label = tk.Label(side, text="", bg=PANEL, fg=DIM, font=self.f_tiny,
                                   wraplength=280, justify="left")
        self.toys_label.pack(anchor="w", padx=22, pady=(4, 0))

        self.export_btn = RoundButton(side, "EXPORT TO SD CARD", self.export, width=286, height=46,
                                      fill="#1a2334", ink=INK, font=(PF.UI, 12, "bold"))
        self.export_btn.pack(padx=22, pady=4)

        self.auto = tk.BooleanVar(value=True)
        chk = tk.Checkbutton(side, text="new cast every launch", variable=self.auto,
                             bg=PANEL, fg=INK, selectcolor=BG, activebackground=PANEL,
                             activeforeground=INK, font=self.f_small, bd=0,
                             highlightthickness=0)
        chk.pack(anchor="w", padx=20, pady=(14, 0))

        self.cups = tk.BooleanVar(value=True)
        cups_chk = tk.Checkbutton(side, text="new cup tracks every launch", variable=self.cups,
                                  bg=PANEL, fg=INK, selectcolor=BG, activebackground=PANEL,
                                  activeforeground=INK, font=self.f_small, bd=0,
                                  highlightthickness=0)
        cups_chk.pack(anchor="w", padx=20)

        self.pins_label = tk.Label(side, text="", bg=PANEL, fg=DIM, font=self.f_tiny,
                                   wraplength=280, justify="left")
        self.pins_label.pack(anchor="w", padx=22, pady=(6, 0))

        tk.Frame(side, bg=LINE, height=1).pack(fill="x", padx=22, pady=14)
        tk.Label(side, text="STATUS", bg=PANEL, fg=DIM,
                 font=(PF.UI, 9, "bold")).pack(anchor="w", padx=22)
        self.status = tk.Label(side, text="idle", bg=PANEL, fg=ACCENT2, wraplength=286,
                               justify="left", font=self.f_small)
        self.status.pack(anchor="w", padx=22, pady=(2, 0))
        self.logbox = tk.Label(side, text="", bg=PANEL, fg=DIM, wraplength=286,
                               justify="left", font=(PF.UI, 9))
        self.logbox.pack(anchor="w", padx=22, pady=(8, 16))

    def select_terrain(self, terrain):
        for name, panel in self.panels.items():
            if name != terrain:
                panel.pack_forget()
        self.panels[terrain].pack(fill="both", expand=True)
        for name, btn in self.tab_btns.items():
            btn.configure(fg=TERRAIN_COLOR[name] if name == terrain else DIM,
                          bg=PANEL if name == terrain else BG)
        self.terrain = terrain

    # ----------------------------------------------------------------- actions
    def refresh_roster(self, repaint=False):
        groups = self.session.groups()
        for terrain in P.TERRAINS:
            figs = groups[terrain]
            for i, card in enumerate(self.cards[terrain]):
                if i < len(figs):
                    card.grid()
                    card.set_figure(figs[i])
                else:
                    card.grid_remove()
            self.tab_btns[terrain].configure(
                text="%s %d" % (TERRAIN_TITLE[terrain], len(figs)))
        self.foot.configure(
            text="%d racer slots across %d figures \u00b7 the engine draws the field from these"
                 % (len(self.session.slots), len(self.session.figures)))
        counts = self.session.data["terrain_counts"]
        self.counts.configure(text="\n".join(
            "%s  %d" % (TERRAIN_TITLE[t], counts[t]) for t in P.TERRAINS)
            + "\n%d figures in the pool" % len(self.session.figures))
        pins = self.session.pins
        self.pins_label.configure(
            text=("pinned: " + ", ".join(pins)) if pins else "no pins \u2014 a full random cast")
        if repaint:
            self.root.update_idletasks()

    def toggle_pin(self, fig):
        if not fig:
            return
        self.session.toggle_pin(fig["display"])
        self.refresh_roster(repaint=True)

    def open_picker(self):
        RosterPicker(self)

    def open_toys(self):
        ToyPicker(self)

    def set_toys(self, pair, note=None):
        self.toys = dict(pair)
        fig = self.toys.get("figure")
        veh = self.toys.get("vehicle")
        line = "on the portal: %s" % (fig.label if fig else "nothing")
        if veh:
            line += " + %s" % veh.label
        if note:
            line += "\n%s" % note
        self.toys_label.configure(text=line)

    def open_netplay(self):
        NetplayDialog(self)

    def log(self, line):
        """Status line. Safe from the build thread: the window only ever updates
        from `_pump`, which runs on the main loop."""
        self.q.put(("log", line))

    def _pump(self):
        try:
            while True:
                kind, value = self.q.get_nowait()
                if kind == "log":
                    self.status.configure(text=value)
                    self._history = (self._history + [value])[-4:]
                    self.logbox.configure(text="\n".join(self._history[:-1]))
                elif kind == "busy":
                    self._set_busy(value)
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def roll(self):
        if self.busy:
            return
        self.session.roll()
        self.refresh_roster(repaint=True)
        self.log("new cast rolled")

    def _set_busy(self, busy):
        self.busy = busy
        self.root.configure(cursor="watch" if busy else "")
        color = "#3a3324" if busy else ACCENT
        self.play_btn.fill = color
        self.play_btn.set_text("WORKING ..." if busy else "\u25b6  PLAY")

    def play(self):
        if self.busy:
            return
        if self.auto.get():
            self.session.roll()
            self.refresh_roster(repaint=True)
        self._set_busy(True)
        self.log("patching the roster into BaseGameplay.pkz")

        def work():
            try:
                data, changed = self.session.patched_bytes()
                self.pipe.patch_tree(data)
                self.log("%d racer records rewritten" % changed)
                if self.cups.get():
                    self.pipe.patch_cups(self.session.seed)
                else:
                    self.pipe.restore_cups()
                self.pipe.build_image()
                self.log(TOYS.enable_portal())
                if self.toys:
                    TOYS.install(self.toys)
                    fig = self.toys.get("figure")
                    veh = self.toys.get("vehicle")
                    self.log("on the portal: %s%s" % (
                        fig.label if fig else "nothing",
                        (" + " + veh.label) if veh else ""))
                self.pipe.launch()
                self.log("Dolphin started \u2014 have fun")
            except Exception as exc:  # noqa: BLE001 - surface it in the window
                self.log("failed: %s" % exc)
            finally:
                self.q.put(("busy", False))

        threading.Thread(target=work, daemon=True).start()

    def export(self):
        if self.busy:
            return
        dest = filedialog.askdirectory(title="Pick the SD card / USB drive root")
        if not dest:
            return
        self._set_busy(True)
        self.log("building the image for hardware")

        def work():
            try:
                data, changed = self.session.patched_bytes()
                self.pipe.patch_tree(data)
                if self.cups.get():
                    self.pipe.patch_cups(self.session.seed)
                else:
                    self.pipe.restore_cups()
                self.pipe.build_image()
                target = self.pipe.export(dest)
                self.log("exported to %s" % target)
            except Exception as exc:  # noqa: BLE001
                self.log("failed: %s" % exc)
            finally:
                self.q.put(("busy", False))

        threading.Thread(target=work, daemon=True).start()

    def run(self):
        img = P.IMAGE
        try:
            size = os.path.getsize(img) / 1e9
            self.image_state.configure(text="%s  \u00b7  %.2f GB" % (os.path.basename(img), size))
        except OSError:
            self.image_state.configure(text="no image yet")
        self.root.mainloop()


def check():
    """`python3 SkylandersLauncher.py --check` - what this machine is missing."""
    import sessions as SESS
    print("platform      %s" % PF.platform_name())
    print("python        %s" % sys.version.split()[0])
    print("dolphin       %s" % (PF.dolphin() or "NOT FOUND \u2014 set DOLPHIN"))
    print("wit           %s" % (PF.wit() or "NOT FOUND \u2014 set WIT (needed to rebuild the image)"))
    print("game image    %s" % (P.IMAGE if os.path.exists(P.IMAGE) else "missing \u2014 build once from the tree"))
    print("disc tree     %s" % (P.TREE if os.path.isdir(P.TREE) else "MISSING \u2014 extract the disc first"))
    print("netplay lan   %s:%d" % (SESS.local_ip(), SESS.PORT))
    try:
        toys = TOYS.all_toys()
        print("toy library   %d toys (%d figures, %d vehicles)"
              % (len(toys), len(TOYS.figures()), len(TOYS.vehicles())))
    except Exception as exc:  # noqa: BLE001 - a missing library is worth seeing
        print("toy library   MISSING (%s)" % exc)
    print("portal folder %s (%d on it)" % (TOYS.PORTAL, len(TOYS.installed())))
    print("dolphin ini   %s" % (PF.dolphin_ini() or "no config dir for this OS"))
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    LauncherApp().run()
