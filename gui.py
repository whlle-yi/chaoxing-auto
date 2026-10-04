"""cxauto 图形界面：点按钮完成配置、选课、刷课、看进度。

用法::

    python gui.py

界面结构：左侧为账号与选项，右侧为课程列表与进度区。
刷课在后台线程运行，界面不卡顿；「停止」按钮发出安全停止信号。
"""

from __future__ import annotations

import queue
import threading
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

sys.path.insert(0, str(Path(__file__).parent / "src"))

from loguru import logger  # noqa: E402

from cxauto.core.config import Config  # noqa: E402
from cxauto.core.runner import Runner  # noqa: E402

CONFIG_PATH = Path(__file__).parent / "config.ini"


class LogQueueSink:
    """把 loguru 日志转发到队列，供 GUI 线程安全地取用显示。"""

    def __init__(self, log_queue: queue.Queue) -> None:
        self.log_queue = log_queue

    def __call__(self, message) -> None:
        self.log_queue.put(str(message))


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("cxauto · 学习通刷课助手")
        root.geometry("880x620")
        root.minsize(760, 520)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.courses = []
        self.runner: Runner | None = None
        self.worker_thread: threading.Thread | None = None

        self._build_menu()
        self._build_layout()
        self._load_config_to_form()

        self.root.after(200, self._poll_log)
        self.root.after(500, self._poll_progress)

    # ------------------------------------------------------------------ 界面

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._show_help)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menubar)

    def _build_layout(self) -> None:
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 左侧：账号 + 选项 + 按钮
        left = ttk.Frame(paned, padding=6)
        paned.add(left, weight=1)

        group_account = ttk.LabelFrame(left, text=" 账号 ", padding=6)
        group_account.pack(fill=tk.X)
        ttk.Label(group_account, text="账号（手机号/学号）").grid(row=0, column=0, sticky="w")
        self.entry_user = ttk.Entry(group_account)
        self.entry_user.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(group_account, text="密码").grid(row=2, column=0, sticky="w")
        self.entry_pass = ttk.Entry(group_account, show="*")
        self.entry_pass.grid(row=3, column=0, sticky="ew", pady=(2, 2))
        group_account.columnconfigure(0, weight=1)

        group_opt = ttk.LabelFrame(left, text=" 选项 ", padding=6)
        group_opt.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(group_opt, text="同时刷几个视频").grid(row=0, column=0, sticky="w")
        self.spin_conc = ttk.Spinbox(group_opt, from_=1, to=3, width=5)
        self.spin_conc.set(2)
        self.spin_conc.grid(row=0, column=1, sticky="e", pady=(2, 4))
        ttk.Label(group_opt, text="视频倍速 (1.0~2.0)").grid(row=1, column=0, sticky="w")
        self.spin_speed = ttk.Spinbox(group_opt, from_=1.0, to=2.0, increment=0.5, width=5)
        self.spin_speed.set(1.0)
        self.spin_speed.grid(row=1, column=1, sticky="e")

        self.btn_login = ttk.Button(left, text="① 登录并获取课程列表", command=self.on_login)
        self.btn_login.pack(fill=tk.X, pady=(12, 4))
        self.btn_start = ttk.Button(left, text="② 开始刷课", command=self.on_start, state=tk.DISABLED)
        self.btn_start.pack(fill=tk.X, pady=4)
        self.btn_stop = ttk.Button(left, text="停止", command=self.on_stop, state=tk.DISABLED)
        self.btn_stop.pack(fill=tk.X, pady=4)

        self.label_state = ttk.Label(left, text="状态：未登录", foreground="gray")
        self.label_state.pack(anchor="w", pady=(8, 0))

        # 右侧上方：课程列表
        right = ttk.Frame(paned, padding=6)
        paned.add(right, weight=2)

        group_course = ttk.LabelFrame(right, text=" 课程列表（按住 Ctrl 可多选，不选=全部） ", padding=4)
        group_course.pack(fill=tk.BOTH, expand=True)
        self.course_list = tk.Listbox(group_course, selectmode=tk.MULTIPLE, height=8)
        self.course_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(group_course, command=self.course_list.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.course_list.config(yscrollcommand=scroll.set)

        # 右侧中部：工位进度条（行数跟随「同时刷几个视频」的设置）
        group_progress = ttk.LabelFrame(right, text=" 刷课进度 ", padding=6)
        group_progress.pack(fill=tk.X, pady=(8, 0))
        self.slots_frame = ttk.Frame(group_progress)
        self.slots_frame.pack(fill=tk.X)
        self.slot_bars: list[ttk.Progressbar] = []
        self.slot_labels: list[ttk.Label] = []
        self._rebuild_slots(2)
        self.label_summary = ttk.Label(group_progress, text="尚未开始")
        self.label_summary.pack(anchor="w")

        # 右侧下方：日志
        group_log = ttk.LabelFrame(right, text=" 运行日志 ", padding=4)
        group_log.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.log_text = ScrolledText(group_log, height=10, state=tk.DISABLED, font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------ 配置

    def _rebuild_slots(self, count: int) -> None:
        """按设置的并行数重建工位进度行。"""
        for child in self.slots_frame.winfo_children():
            child.destroy()
        self.slot_bars = []
        self.slot_labels = []
        for i in range(count):
            label = ttk.Label(self.slots_frame, text=f"工位{i + 1}：待机")
            label.pack(anchor="w")
            bar = ttk.Progressbar(self.slots_frame, maximum=100, length=300)
            bar.pack(fill=tk.X, pady=(0, 6))
            self.slot_labels.append(label)
            self.slot_bars.append(bar)

    def _load_config_to_form(self) -> None:
        if not CONFIG_PATH.exists():
            return
        try:
            config = Config.from_ini(CONFIG_PATH)
        except Exception:  # noqa: BLE001 —— 配置缺失/损坏时留空表单
            return
        self.entry_user.insert(0, config.username)
        self.entry_pass.insert(0, config.password)
        self.spin_conc.delete(0, tk.END)
        self.spin_conc.insert(0, str(config.concurrency))
        self.spin_speed.delete(0, tk.END)
        self.spin_speed.insert(0, str(config.speed))

    def _save_form_to_config(self, course_list: list[str]) -> Config:
        """把表单写回 config.ini 并返回 Config 对象。"""
        username = self.entry_user.get().strip()
        password = self.entry_pass.get().strip()
        if not username or not password:
            raise ValueError("请先填写账号和密码")
        concurrency = max(1, min(3, int(float(self.spin_conc.get()))))
        speed = min(2.0, max(1.0, float(self.spin_speed.get())))

        config = Config(
            username=username,
            password=password,
            course_list=course_list,
            concurrency=concurrency,
            speed=speed,
        )
        # 同步写回 config.ini，命令行方式也能复用
        lines = [
            "[common]",
            f"username = {username}",
            f"password = {password}",
            f"course_list = {', '.join(course_list)}",
            f"speed = {speed}",
            f"concurrency = {concurrency}",
            "job_types = video",
            "notopen_action = skip",
            "cookie_file = cookies.txt",
            "log_file = logs/cxauto.log",
            "log_level = INFO",
        ]
        CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return config

    # ------------------------------------------------------------------ 事件

    def on_login(self) -> None:
        """登录并拉取课程列表（后台线程，避免卡界面）。"""
        def work():
            try:
                config = self._save_form_to_config([])
                runner = Runner(config)
                courses = runner.course_api.get_course_list()
                self.root.after(0, self._show_courses, courses, True)
            except Exception as e:  # noqa: BLE001
                self.root.after(0, self._show_error, str(e))

        self._set_busy(True, "正在登录…")
        threading.Thread(target=work, daemon=True).start()

    def _show_courses(self, courses, ok: bool) -> None:
        self._set_busy(False, f"登录成功，共 {len(courses)} 门课" if ok else "登录失败")
        self.courses = courses
        self.course_list.delete(0, tk.END)
        for course in courses:
            self.course_list.insert(tk.END, course.name)
        if ok and courses:
            self.btn_start.config(state=tk.NORMAL)

    def on_start(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        selection = self.course_list.curselection()
        course_filter = [self.courses[i].name for i in selection]

        try:
            config = self._save_form_to_config(course_filter)
        except Exception as e:  # noqa: BLE001
            messagebox.showwarning("提示", str(e))
            return

        # 进度行数与本次并行数保持一致
        self._rebuild_slots(config.concurrency)

        def work():
            try:
                runner = Runner(config, show_panel=False)  # 进度展示由界面承担
                self.runner = runner
                runner.run()
                stats = runner.stats
                self.root.after(
                    0, messagebox.showinfo, "刷课完成",
                    f"完成 {stats.completed}，跳过 {stats.skipped}，"
                    f"失败 {stats.failed}，不支持 {stats.unsupported}",
                )
            except Exception as e:  # noqa: BLE001
                self.root.after(0, self._show_error, str(e))
            finally:
                self.root.after(0, self._finish_run)

        self._set_busy(True, "刷课中…")
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_start.config(state=tk.DISABLED)
        self.worker_thread = threading.Thread(target=work, daemon=True).start()

    def on_stop(self) -> None:
        if self.runner:
            self.runner.stop_event.set()
            self.label_state.config(text="正在停止（等当前心跳结束）…")
        self.btn_stop.config(state=tk.DISABLED)

    def _finish_run(self) -> None:
        self._set_busy(False, "已结束")
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.NORMAL)

    def _set_busy(self, busy: bool, state_text: str) -> None:
        self.btn_login.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.label_state.config(text=f"状态：{state_text}")

    def _show_error(self, text: str) -> None:
        self._set_busy(False, "出错")
        messagebox.showerror("出错了", text)

    # ------------------------------------------------------------------ 周期刷新

    def _poll_log(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, line)
            if not line.endswith("\n"):
                self.log_text.insert(tk.END, "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(200, self._poll_log)

    def _poll_progress(self) -> None:
        dashboard = self.runner.dashboard if self.runner else None
        if dashboard is not None:
            for i, slot in enumerate(dashboard.slots):
                if i >= len(self.slot_bars):
                    break
                if slot.status == "空闲":
                    self.slot_labels[i].config(text=f"工位{i + 1}：待机")
                    self.slot_bars[i]["value"] = 0
                else:
                    pct = (slot.play_seconds / slot.total_seconds * 100) if slot.total_seconds else 0
                    self.slot_labels[i].config(
                        text=f"工位{i + 1}：{slot.chapter_label} {slot.title} "
                             f"{slot.play_seconds}s / {slot.total_seconds}s"
                    )
                    self.slot_bars[i]["value"] = pct
            self.label_summary.config(
                text=f"已完成 {dashboard.completed}  失败 {dashboard.failed}  "
                     f"排队中 {dashboard.queue_remaining}/{dashboard.total_jobs}"
            )
        self.root.after(500, self._poll_progress)

    # ------------------------------------------------------------------ 帮助

    def _show_help(self) -> None:
        messagebox.showinfo(
            "使用说明",
            "1. 填写学习通账号密码，点「登录并获取课程列表」\n"
            "2. 在右侧列表选中要刷的课程（不选=全部）\n"
            "3. 点「开始刷课」，右侧可看实时进度\n"
            "4. 随时点「停止」，进度保存在服务端，下次自动续刷\n\n"
            "默认只刷视频，测验/文档等任务不会碰。",
        )

    def _show_about(self) -> None:
        messagebox.showinfo("关于", "cxauto 学习通刷课助手\n仅供学习网络协议分析与技术交流使用")


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass

    app = App(root)

    # 日志：DEBUG 全量进文件，INFO 进 GUI 日志窗
    logger.remove()
    logger.add(
        Path("logs/cxauto.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <7} | {name}:{function}:{line} | {message}",
        rotation="10 MB",
        encoding="utf-8",
    )
    logger.add(
        LogQueueSink(app.log_queue),
        level="INFO",
        format="{time:HH:mm:ss} | {level: <7} | {message}",
    )
    root.mainloop()


if __name__ == "__main__":
    main()
