from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


def _resource_path(*parts: str) -> Path:
    """Возвращает путь к ресурсу проекта или PyInstaller без зависимости от CWD."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).joinpath(*parts)
    return Path(__file__).resolve().parents[1].joinpath(*parts)


def _get_json(url: str, timeout: float = 1.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, Any], timeout: float = 3.0) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass
class AreaChoice:
    id: int
    name: str


class DesktopController:
    """Небольшая Windows-оболочка вокруг локального веб-сервера."""

    def __init__(self, *, port: int, app_name: str, request_shutdown: Callable[[], None]):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.app_name = app_name
        self.request_shutdown = request_shutdown
        self._closing = False
        self._tray_icon = None
        self._tray_thread = None
        self._areas: list[AreaChoice] = []
        self._active_tournament_id: int | None = None

        root = tk.Tk()
        self.root = root
        root.title(f"{app_name} - сервер")
        self._window_icon = None
        self._apply_window_icon()
        # Оставляем нижние кнопки видимыми даже при масштабе Windows 125–150%,
        # используя доступную высоту обычного Full HD-дисплея.
        available_height = max(560, root.winfo_screenheight() - 100)
        initial_height = min(820, available_height)
        root.geometry(f"800x{initial_height}")
        root.minsize(720, min(680, initial_height))
        root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        style = ttk.Style(root)
        try:
            style.theme_use("vista")
        except Exception:
            pass

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text=app_name, font=("Segoe UI", 18, "bold")).pack(side="left")
        self.status_dot = tk.Canvas(head, width=16, height=16, highlightthickness=0)
        self.status_dot.pack(side="right", padx=(8, 0))
        self.status_label = ttk.Label(head, text="Запуск сервера…", font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side="right")

        ttk.Separator(outer).pack(fill="x", pady=10)

        links = ttk.LabelFrame(outer, text="Быстрый запуск экранов", padding=10)
        links.pack(fill="x")
        row1 = ttk.Frame(links)
        row1.pack(fill="x", pady=3)
        ttk.Button(row1, text="Организатор", command=lambda: self.open_url("/admin")).pack(side="left", padx=(0, 7))
        ttk.Button(row1, text="Общий экран", command=self.open_public).pack(side="left", padx=(0, 7))
        ttk.Button(row1, text="Секретарь площадки", command=self.open_secretary).pack(side="left", padx=(0, 7))
        ttk.Button(row1, text="Табло площадки", command=self.open_board).pack(side="left")

        row2 = ttk.Frame(links)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Label(row2, text="Площадка:").pack(side="left")
        self.area_var = tk.StringVar(value="")
        self.area_combo = ttk.Combobox(row2, textvariable=self.area_var, state="readonly", width=36)
        self.area_combo.pack(side="left", padx=(7, 0))

        db_frame = ttk.LabelFrame(outer, text="Рабочая база данных", padding=10)
        db_frame.pack(fill="x", pady=(10, 0))
        self.db_path_var = tk.StringVar(value="Определение текущей БД…")
        ttk.Label(db_frame, textvariable=self.db_path_var, font=("Consolas", 9)).pack(side="left", fill="x", expand=True)
        ttk.Button(db_frame, text="Выбрать БД…", command=self.choose_database).pack(side="right", padx=(10, 0))

        net = ttk.LabelFrame(outer, text="Доступ в локальной сети", padding=10)
        net.pack(fill="x", pady=(10, 0))
        self.local_label = ttk.Label(net, text=f"На этом компьютере: {self.base}")
        self.local_label.pack(anchor="w")
        self.network_text = tk.Text(net, height=4, wrap="word", font=("Consolas", 9), borderwidth=0, background=root.cget("bg"))
        self.network_text.pack(fill="x", pady=(6, 0))
        self.network_text.configure(state="disabled")

        conn = ttk.LabelFrame(outer, text="Подключённые экраны", padding=8)
        conn.pack(fill="both", expand=True, pady=(10, 0))
        cols = ("ip", "screen", "area", "since")
        self.tree = ttk.Treeview(conn, columns=cols, show="headings", height=6)
        self.tree.heading("ip", text="Компьютер / IP")
        self.tree.heading("screen", text="Экран")
        self.tree.heading("area", text="Площадка")
        self.tree.heading("since", text="Подключён")
        self.tree.column("ip", width=150)
        self.tree.column("screen", width=180)
        self.tree.column("area", width=150)
        self.tree.column("since", width=110)
        self.tree.pack(fill="both", expand=True)
        self.connections_label = ttk.Label(conn, text="Нет подключений")
        self.connections_label.pack(anchor="w", pady=(6, 0))

        foot = ttk.Frame(outer)
        foot.pack(fill="x", pady=(12, 0))
        ttk.Button(foot, text="Свернуть в трей", command=self.minimize_to_tray).pack(side="left")
        ttk.Button(foot, text="Полностью выключить", command=self.exit_app).pack(side="right")

        self._set_status(False)
        self._start_tray()
        self.root.after(500, self._poll)

    def _set_status(self, online: bool) -> None:
        self.status_dot.delete("all")
        color = "#23a55a" if online else "#d28b28"
        self.status_dot.create_oval(3, 3, 13, 13, fill=color, outline=color)
        self.status_label.configure(text="Сервер работает" if online else "Запуск / переподключение…")

    def open_url(self, path: str) -> None:
        webbrowser.open(f"{self.base}{path}")

    def _selected_area(self) -> AreaChoice | None:
        idx = self.area_combo.current()
        return self._areas[idx] if 0 <= idx < len(self._areas) else (self._areas[0] if self._areas else None)

    def open_secretary(self) -> None:
        area = self._selected_area()
        self.open_url(f"/mat/{area.id}" if area else "/admin")

    def open_board(self) -> None:
        area = self._selected_area()
        self.open_url(f"/board/{area.id}" if area else "/admin")

    def open_public(self) -> None:
        self.open_url(f"/public/{self._active_tournament_id}" if self._active_tournament_id else "/admin")

    def choose_database(self) -> None:
        initial_dir = None
        current = self.db_path_var.get().strip()
        if current and current != "Определение текущей БД…":
            try:
                from pathlib import Path
                initial_dir = str(Path(current).expanduser().resolve().parent)
            except Exception:
                initial_dir = None
        path = self.filedialog.askopenfilename(
            title="Выберите базу данных Turnirium",
            initialdir=initial_dir,
            filetypes=[("SQLite database", "*.db *.sqlite *.sqlite3"), ("Все файлы", "*.*")],
        )
        if not path:
            return
        try:
            result = _post_json(f"{self.base}/api/databases/select", {"path": path})
            self.db_path_var.set(str(result.get("db_path") or path))
            self._active_tournament_id = None
            self._areas = []
            self.area_combo["values"] = []
            self.area_var.set("")
            self._refresh_areas()
        except urllib.error.HTTPError as exc:
            message = f"HTTP {exc.code}"
            try:
                data = json.loads(exc.read().decode("utf-8"))
                message = data.get("detail") or message
            except Exception:
                pass
            self.messagebox.showerror("Не удалось выбрать БД", message)
        except Exception as exc:
            self.messagebox.showerror("Не удалось выбрать БД", str(exc))

    def _write_network(self, rows: list[dict[str, Any]]) -> None:
        lines = []
        area = self._selected_area()
        for row in rows:
            base = row.get("base_url", "")
            lines.append(f"{row.get('name','')}: {base}/admin")
            if self._active_tournament_id:
                lines.append(f"  общий экран: {base}/public/{self._active_tournament_id}")
            if area:
                lines.append(f"  секретарь: {base}/mat/{area.id}    табло: {base}/board/{area.id}")
        if not lines:
            lines = ["LAN-адрес не найден. Проверьте подключение к сети."]
        self.network_text.configure(state="normal")
        self.network_text.delete("1.0", "end")
        self.network_text.insert("1.0", "\n".join(lines))
        self.network_text.configure(state="disabled")

    def _refresh_areas(self) -> None:
        try:
            tournaments = _get_json(f"{self.base}/api/tournaments")
            active = [t for t in tournaments if t.get("status") != "completed"]
            self._active_tournament_id = active[0]["id"] if active else (tournaments[0]["id"] if tournaments else None)
            if not self._active_tournament_id:
                self._areas = []
            else:
                data = _get_json(f"{self.base}/api/tournaments/{self._active_tournament_id}/areas")
                self._areas = [AreaChoice(int(a["id"]), str(a["name"])) for a in data]
            old = self.area_var.get()
            values = [a.name for a in self._areas]
            self.area_combo["values"] = values
            if old in values:
                self.area_combo.set(old)
            elif values:
                self.area_combo.current(0)
            else:
                self.area_var.set("")
        except Exception:
            pass

    def _refresh_connections(self, clients: list[dict[str, Any]]) -> None:
        names = {"organizer": "Организатор", "secretary": "Секретарь", "board": "Табло площадки", "public": "Общий экран", "unknown": "Неизвестный экран"}
        area_names = {a.id: a.name for a in self._areas}
        for item in self.tree.get_children():
            self.tree.delete(item)
        for c in clients:
            area = area_names.get(c.get("area_id"), "—")
            since = str(c.get("connected_at") or "").replace("T", " ")[:19]
            self.tree.insert("", "end", values=(c.get("ip") or "—", names.get(c.get("screen"), c.get("screen") or "—"), area, since[11:] if len(since) > 11 else since))
        self.connections_label.configure(text=f"Активных WebSocket-экранов: {len(clients)}")

    def _poll(self) -> None:
        if self._closing:
            return
        try:
            runtime = _get_json(f"{self.base}/api/system/runtime", timeout=.7)
            system = _get_json(f"{self.base}/api/system", timeout=.7)
            self._set_status(True)
            self.db_path_var.set(str(system.get("db_path") or "—"))
            self._refresh_areas()
            self._write_network(runtime.get("interfaces") or [])
            self._refresh_connections(runtime.get("clients") or [])
        except Exception:
            self._set_status(False)
        self.root.after(2000, self._poll)

    def minimize_to_tray(self) -> None:
        if self._tray_icon is None:
            self.root.iconify()
        else:
            self.root.withdraw()

    def restore(self) -> None:
        try:
            self.root.after(0, self._restore_on_ui)
        except Exception:
            pass

    def _restore_on_ui(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def exit_app(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.status_label.configure(text="Остановка сервера…")
        try:
            if self._tray_icon:
                self._tray_icon.stop()
        except Exception:
            pass
        self.request_shutdown()
        self.root.after(250, self.root.destroy)

    def _apply_window_icon(self) -> None:
        """Устанавливает фирменную иконку Turnirium для нативного окна."""
        png_path = _resource_path("assets", "turnirium_icon.png")
        ico_path = _resource_path("assets", "turnirium.ico")
        try:
            # Метод iconbitmap надёжнее всего задаёт значок заголовка и панели задач Windows.
            if sys.platform == "win32" and ico_path.exists():
                self.root.iconbitmap(default=str(ico_path))
        except Exception:
            pass
        try:
            # Храним ссылку на PhotoImage весь срок жизни корневого Tk-окна.
            if png_path.exists():
                self._window_icon = self.tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, self._window_icon)
        except Exception:
            pass

    def _tray_icon_image(self):
        from PIL import Image, ImageDraw

        png_path = _resource_path("assets", "turnirium_icon.png")
        try:
            with Image.open(png_path) as source:
                return source.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        except Exception:
            # Резервный вариант для разработки повторяет красно-серый знак TR с чёрными буквами.
            image = Image.new("RGBA", (64, 64), (142, 149, 157, 255))
            draw = ImageDraw.Draw(image)
            draw.polygon(
                [(0, 0), (50, 0), (46, 8), (40, 9), (39, 16),
                 (32, 18), (31, 26), (24, 27), (23, 35), (15, 37),
                 (14, 44), (0, 49)],
                fill=(190, 38, 51, 255),
            )
            draw.rounded_rectangle((1, 1, 62, 62), radius=11, outline=(36, 40, 46, 255), width=3)
            try:
                from PIL import ImageFont
                font = ImageFont.truetype("DejaVuSerif-Bold.ttf", 28)
            except Exception:
                font = None
            draw.text((10, 18), "TR", fill=(12, 14, 16, 255), font=font, stroke_width=1, stroke_fill=(0, 0, 0, 255))
            return image

    def _start_tray(self) -> None:
        try:
            import pystray
        except Exception:
            return

        def invoke(fn):
            return lambda icon=None, item=None: self.root.after(0, fn)

        menu = pystray.Menu(
            pystray.MenuItem("Развернуть", invoke(self.restore), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Организатор", invoke(lambda: self.open_url("/admin"))),
            pystray.MenuItem("Общий экран", invoke(self.open_public)),
            pystray.MenuItem("Секретарь площадки", invoke(self.open_secretary)),
            pystray.MenuItem("Табло площадки", invoke(self.open_board)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Полностью выйти", invoke(self.exit_app)),
        )
        self._tray_icon = pystray.Icon("local_tournament", self._tray_icon_image(), self.app_name, menu)
        self._tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True, name="tray-icon")
        self._tray_thread.start()

    def run(self) -> None:
        self.root.mainloop()
