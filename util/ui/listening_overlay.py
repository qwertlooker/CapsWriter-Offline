"""
桌面倾听覆盖层

在录音开始后显示一个位于屏幕底部中央的图片帧动画，
识别最终结果返回后隐藏。窗口为鼠标穿透的透明覆盖层。
"""

from __future__ import annotations

import ctypes
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Optional

import tkinter as tk

from . import logger


GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080


@dataclass
class _OverlayStyle:
    width: int = 230
    height: int = 42
    bottom_margin: int = 108
    frame_interval_ms: int = 42
    transparent_color: str = "#010203"


class ListeningOverlayManager:
    """桌面倾听覆盖层单例管理器。"""

    _instance: Optional["ListeningOverlayManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ListeningOverlayManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._initialized = True
        self._queue: "Queue[str]" = Queue()
        self._style = _OverlayStyle()
        self._frames = []
        self._frame_index = 0
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="ListeningOverlayThread",
        )
        self._thread.start()

    def show(self) -> None:
        self._queue.put("show")

    def hide(self) -> None:
        self._queue.put("hide")

    def shutdown(self) -> None:
        self._queue.put("shutdown")

    def _run(self) -> None:
        self._root = tk.Tk()
        self._root.withdraw()
        self._window: Optional[tk.Toplevel] = None
        self._label: Optional[tk.Label] = None
        self._visible = False
        self._anim_job: Optional[str] = None
        self._create_window()
        self._poll_commands()
        self._root.mainloop()

    def _create_window(self) -> None:
        style = self._style

        self._window = tk.Toplevel(self._root)
        self._window.withdraw()
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._window.attributes("-transparentcolor", style.transparent_color)
        self._window.configure(bg=style.transparent_color)
        self._window.resizable(False, False)

        self._load_frames()

        self._label = tk.Label(
            self._window,
            width=style.width,
            height=style.height,
            bd=0,
            highlightthickness=0,
            bg=style.transparent_color,
        )
        self._label.pack()

        if self._frames:
            self._label.configure(image=self._frames[0])

        self._position_window()
        self._enable_click_through()

    def _load_frames(self) -> None:
        frame_dir = Path(__file__).resolve().parents[2] / "assets" / "listening_frames"
        frame_paths = sorted(frame_dir.glob("frame_*.png"))
        if not frame_paths:
            logger.warning(f"未找到倾听动画帧: {frame_dir}")
            return

        try:
            self._frames = [tk.PhotoImage(file=str(path)) for path in frame_paths]
            logger.debug(f"已加载倾听动画帧: {len(self._frames)}")
        except Exception as exc:
            self._frames = []
            logger.warning(f"加载倾听动画帧失败: {exc}")

    def _position_window(self) -> None:
        if not self._window:
            return

        style = self._style
        screen_width = self._window.winfo_screenwidth()
        screen_height = self._window.winfo_screenheight()
        x = int((screen_width - style.width) / 2)
        y = max(0, int(screen_height - style.height - style.bottom_margin))
        self._window.geometry(f"{style.width}x{style.height}+{x}+{y}")

    def _enable_click_through(self) -> None:
        if not self._window:
            return

        try:
            hwnd = ctypes.windll.user32.GetParent(self._window.winfo_id())
            ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ex_style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
        except Exception as exc:
            logger.warning(f"设置倾听覆盖层鼠标穿透失败: {exc}")

    def _poll_commands(self) -> None:
        try:
            while True:
                command = self._queue.get_nowait()
                if command == "show":
                    self._show_now()
                elif command == "hide":
                    self._hide_now()
                elif command == "shutdown":
                    self._shutdown_now()
                    return
        except Empty:
            pass

        self._root.after(50, self._poll_commands)

    def _show_now(self) -> None:
        if not self._window:
            return

        self._position_window()
        self._frame_index = 0
        self._window.deiconify()
        self._visible = True
        if self._frames and self._label:
            self._label.configure(image=self._frames[0])
        if self._anim_job is None:
            self._animate()

    def _hide_now(self) -> None:
        self._visible = False
        if self._anim_job and self._window:
            self._window.after_cancel(self._anim_job)
            self._anim_job = None
        if self._window:
            self._window.withdraw()

    def _shutdown_now(self) -> None:
        self._hide_now()
        if self._window:
            self._window.destroy()
            self._window = None
        self._root.quit()

    def _animate(self) -> None:
        if self._visible and self._frames and self._label:
            self._frame_index = (self._frame_index + 1) % len(self._frames)
            self._label.configure(image=self._frames[self._frame_index])

        if self._visible and self._window:
            self._anim_job = self._window.after(self._style.frame_interval_ms, self._animate)
        else:
            self._anim_job = None
