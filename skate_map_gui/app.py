#!/usr/bin/env python3
"""
Skate 3 Map → Unreal  (friendly one-page GUI)

Flow:
  1. Pick Xbox 360 Skate 3 ISO
  2. Extract with latest extract-xiso (downloaded at runtime)
  3. Choose a map from the list
  4. Convert .big → .skate → Unreal-ready folder
  5. Optionally copy into your UE project Content folder
"""
from __future__ import annotations

import queue
import threading
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pipeline import (
    GIT_DOWNLOAD_URL,
    app_runtime_dir,
    convert_big_to_skate,
    convert_skate_to_unreal,
    copy_to_ue_content,
    ensure_engine,
    extract_iso,
    find_game_root,
    find_git,
    git_version,
    list_map_bigs,
    map_display_name,
)


APP_TITLE = "Skate 3 Map → Unreal"
PAD = 12


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(720, 640)
        self.geometry("820x700")

        self.iso_path = tk.StringVar()
        self.extract_dir = tk.StringVar(
            value=str(app_runtime_dir() / "extracted")
        )
        self.game_root: Path | None = None
        self.map_paths: list[Path] = []
        self.selected_map = tk.StringVar()
        self.skate_out = tk.StringVar(
            value=str(app_runtime_dir() / "skate_out")
        )
        self.ue_export = tk.StringVar(
            value=str(app_runtime_dir() / "ue_export")
        )
        self.ue_content = tk.StringVar()
        self.status = tk.StringVar(value="Ready — select your Xbox 360 Skate 3 ISO to begin.")
        self._busy = False
        self._log_q: queue.Queue[str] = queue.Queue()

        self._build_ui()
        self.after(100, self._pump_log)
        self.after(300, self._check_git_on_startup)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=PAD)
        root.pack(fill="both", expand=True)

        title = ttk.Label(root, text=APP_TITLE, font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w")

        note = ttk.Label(
            root,
            text=(
                "Use an Xbox 360 disc image (.iso).  "
                "PlayStation dumps are not supported by extract-xiso."
            ),
            foreground="#555",
            wraplength=760,
        )
        note.pack(anchor="w", pady=(4, 10))

        # --- Step 1: ISO ---
        box1 = ttk.LabelFrame(root, text=" 1. Skate 3 ISO (Xbox 360) ", padding=10)
        box1.pack(fill="x", pady=4)
        row = ttk.Frame(box1)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self.iso_path).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        ttk.Button(row, text="Browse…", command=self._browse_iso).pack(side="left")

        row2 = ttk.Frame(box1)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="Extract to:").pack(side="left")
        ttk.Entry(row2, textvariable=self.extract_dir).pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(row2, text="Browse…", command=self._browse_extract).pack(side="left")
        ttk.Button(box1, text="Extract ISO", command=self._start_extract).pack(
            anchor="e", pady=(10, 0)
        )

        # --- Step 2: Maps ---
        box2 = ttk.LabelFrame(root, text=" 2. Choose a map ", padding=10)
        box2.pack(fill="both", expand=False, pady=4)
        self.map_list = tk.Listbox(box2, height=8, exportselection=False)
        self.map_list.pack(fill="both", expand=True)
        self.map_list.bind("<<ListboxSelect>>", self._on_map_select)
        ttk.Button(box2, text="Refresh map list", command=self._refresh_maps).pack(
            anchor="e", pady=(8, 0)
        )

        # --- Step 3: Output ---
        box3 = ttk.LabelFrame(root, text=" 3. Output folders ", padding=10)
        box3.pack(fill="x", pady=4)

        r = ttk.Frame(box3)
        r.pack(fill="x")
        ttk.Label(r, text=".skate output:", width=18).pack(side="left")
        ttk.Entry(r, textvariable=self.skate_out).pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(r, text="Browse…", command=lambda: self._browse_dir(self.skate_out)).pack(
            side="left"
        )

        r = ttk.Frame(box3)
        r.pack(fill="x", pady=(6, 0))
        ttk.Label(r, text="Unreal export:", width=18).pack(side="left")
        ttk.Entry(r, textvariable=self.ue_export).pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(r, text="Browse…", command=lambda: self._browse_dir(self.ue_export)).pack(
            side="left"
        )

        r = ttk.Frame(box3)
        r.pack(fill="x", pady=(6, 0))
        ttk.Label(r, text="UE Content folder:", width=18).pack(side="left")
        ttk.Entry(r, textvariable=self.ue_content).pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(r, text="Browse…", command=self._browse_ue_content).pack(side="left")

        ttk.Label(
            box3,
            text="UE Content is optional — e.g. …/YourProject/Content  (map is copied there when set)",
            foreground="#555",
        ).pack(anchor="w", pady=(6, 0))

        # --- Run ---
        run_row = ttk.Frame(root)
        run_row.pack(fill="x", pady=10)
        self.btn_run = ttk.Button(
            run_row,
            text="Convert selected map → Unreal",
            command=self._start_convert,
        )
        self.btn_run.pack(side="left")
        ttk.Label(run_row, textvariable=self.status, wraplength=500).pack(
            side="left", padx=12
        )

        # --- Log ---
        box_log = ttk.LabelFrame(root, text=" Log ", padding=6)
        box_log.pack(fill="both", expand=True, pady=4)
        self.log_text = tk.Text(box_log, height=12, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(box_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # ------------------------------------------------------------------ helpers
    def log(self, msg: str) -> None:
        self._log_q.put(msg)

    def _pump_log(self) -> None:
        try:
            while True:
                msg = self._log_q.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._pump_log)

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.btn_run.configure(state=state)
        if status:
            self.status.set(status)

    def _browse_iso(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select Skate 3 Xbox 360 ISO",
            filetypes=[
                ("Xbox 360 ISO", "*.iso"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.iso_path.set(path)

    def _browse_extract(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Extract ISO to folder")
        if path:
            self.extract_dir.set(path)

    def _browse_dir(self, var: tk.StringVar) -> None:
        path = filedialog.askdirectory(parent=self, title="Select folder")
        if path:
            var.set(path)

    def _browse_ue_content(self) -> None:
        path = filedialog.askdirectory(
            parent=self,
            title="Select Unreal project Content folder",
        )
        if path:
            self.ue_content.set(path)

    def _on_map_select(self, _evt=None) -> None:
        sel = self.map_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.map_paths):
            self.selected_map.set(str(self.map_paths[idx]))

    def _refresh_maps(self) -> None:
        roots = []
        if self.game_root:
            roots.append(self.game_root)
        ed = Path(self.extract_dir.get())
        if ed.is_dir():
            roots.append(ed)
        # App folder (extract-xiso sometimes writes Skate_3 next to the exe/cwd)
        roots.append(Path(__file__).resolve().parent)

        game = find_game_root(*roots, log=self.log)
        found: list[Path] = []
        if game is not None:
            self.game_root = game
            found = list_map_bigs(game)

        self.map_paths = found
        self.map_list.delete(0, "end")
        for p in found:
            self.map_list.insert("end", map_display_name(p))
        if found:
            self.map_list.selection_set(0)
            self.selected_map.set(str(found[0]))
            self.status.set(f"Found {len(found)} maps in {self.game_root}")
            self.log(f"Maps under {self.game_root / 'data' / 'content'}:")
            for p in found:
                self.log(f"  • {p.name}")
        else:
            self.status.set("No worldDIST_*.big maps found — extract an ISO first.")

    # ------------------------------------------------------------------ workers
    def _start_extract(self) -> None:
        if self._busy:
            return
        iso = self.iso_path.get().strip()
        if not iso:
            messagebox.showwarning(APP_TITLE, "Please select a Skate 3 Xbox 360 ISO.")
            return
        out = self.extract_dir.get().strip()
        if not out:
            messagebox.showwarning(APP_TITLE, "Please choose an extract folder.")
            return

        def work() -> None:
            try:
                self._set_busy(True, "Downloading extract-xiso / extracting ISO…")
                root = extract_iso(Path(iso), Path(out), self.log)
                self.game_root = root
                self.after(0, self._refresh_maps)
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        APP_TITLE,
                        f"ISO extracted.\n\nGame folder:\n{root}\n\n"
                        "Select a map below, set output folders, then click Convert.",
                    ),
                )
                self._set_busy(False, "ISO ready — select a map and convert.")
            except Exception as e:
                self.log(f"ERROR: {e}")
                self._set_busy(False, "Extraction failed.")
                self.after(0, lambda: messagebox.showerror(APP_TITLE, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _check_git_on_startup(self) -> None:
        git = find_git()
        ver = git_version(git)
        if git and ver:
            self.log(f"Git OK: {ver}  ({git})")
            return
        self.log("Git not found — required to download the map converter engine.")
        self._prompt_install_git(
            "Git was not found on this PC.\n\n"
            "Git is needed once to download the map converter engine "
            "(skate-3-rust-engine).\n\n"
            "Open the Git for Windows download page now?"
        )

    def _prompt_install_git(self, message: str) -> bool:
        """Show dialog; return True if user wants to continue after installing."""
        answer = messagebox.askyesno(
            APP_TITLE,
            message
            + "\n\nAfter installing Git, restart this app so PATH updates apply.",
            icon="warning",
        )
        if answer:
            self.log(f"Opening {GIT_DOWNLOAD_URL}")
            webbrowser.open(GIT_DOWNLOAD_URL)
        return False

    def _ensure_git_or_prompt(self) -> bool:
        """Return True if git is available; otherwise prompt and return False."""
        if find_git():
            return True
        self._prompt_install_git(
            "Git is required before converting a map, but it is not installed "
            "(or not on PATH).\n\n"
            "Open the official Git for Windows download page?"
        )
        return False

    def _start_convert(self) -> None:
        if self._busy:
            return
        sel = self.selected_map.get().strip()
        if not sel:
            messagebox.showwarning(APP_TITLE, "Select a map from the list first.")
            return
        big = Path(sel)
        if not big.is_file():
            messagebox.showerror(APP_TITLE, f"Map file missing:\n{big}")
            return

        if not self._ensure_git_or_prompt():
            self.status.set("Install Git, restart the app, then convert again.")
            return

        skate_out = Path(self.skate_out.get())
        ue_export = Path(self.ue_export.get())
        ue_content = self.ue_content.get().strip()

        def work() -> None:
            try:
                self._set_busy(True, "Cloning engine (first run) / converting…")
                engine = ensure_engine(self.log)

                self._set_busy(True, "Converting .big → .skate (this can take a while)…")
                skate = convert_big_to_skate(big, skate_out, engine, self.log)

                self._set_busy(True, "Building Unreal export (mesh + textures)…")
                export_folder = convert_skate_to_unreal(skate, ue_export, self.log)

                final_path = export_folder
                if ue_content:
                    self._set_busy(True, "Copying into Unreal Content folder…")
                    final_path = copy_to_ue_content(
                        export_folder, Path(ue_content), self.log
                    )

                msg = (
                    "Map is ready for Unreal Engine!\n\n"
                    f"Export folder:\n{final_path}\n\n"
                    "To import materials + mesh in UE 5.4:\n\n"
                    "  1. Open your project in Unreal Editor\n"
                    "  2. Enable plugin:  Python Editor Script Plugin\n"
                    "  3. Menu:  Tools → Execute Python Script…\n"
                    "     (or File → Execute Python Script)\n"
                    "  4. Select:\n"
                    f"     {final_path / 'import_to_unreal.py'}\n\n"
                    "Use FORWARD SLASHES if you run from the Output Log:\n"
                    '  py "C:/path/to/import_to_unreal.py"'
                )
                self.log("=" * 60)
                self.log(msg)
                self._set_busy(False, "Done — map ready for Unreal.")
                self.after(0, lambda: messagebox.showinfo(APP_TITLE, msg))
            except Exception as e:
                self.log(f"ERROR: {e}")
                self._set_busy(False, "Conversion failed — see log.")
                self.after(0, lambda: messagebox.showerror(APP_TITLE, str(e)))

        threading.Thread(target=work, daemon=True).start()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
