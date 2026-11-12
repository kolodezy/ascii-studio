import threading
import time
from functools import lru_cache
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

try:
    import cv2
except ImportError:
    cv2 = None


class AsciiStudio:
    BACKGROUND = (11, 14, 19)
    LIGHT_TEXT = (216, 226, 238)
    CELL_WIDTH = 9
    CELL_HEIGHT = 16
    FONT_SIZE = 14

    CHARACTER_SETS = {
        "Стандартный": " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",
        "Плотный": "  .,:;irsXA253hMHGS#9B&@",
        "Блоки": " ░▒▓█",
        "Минимальный": " .:-=+*#@",
    }

    VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
    IMAGE_FILETYPES = [
        ("Медиафайлы", "*.png *.jpg *.jpeg *.bmp *.webp *.mp4 *.avi *.mov *.mkv *.webm"),
        ("Изображения", "*.png *.jpg *.jpeg *.bmp *.webp"),
        ("Видео", "*.mp4 *.avi *.mov *.mkv *.webm"),
        ("Все файлы", "*.*"),
    ]

    def __init__(self, root):
        self.root = root
        self.root.title("ASCII Studio")
        self.root.geometry("1180x780")
        self.root.minsize(900, 620)
        self.root.configure(bg="#10141c")

        self.source_image = None
        self.source_path = None
        self.output_image = None
        self.ascii_text = ""
        self.preview_photo = None

        self.zoom = 1.0
        self.video_capture = None
        self.video_thread = None
        self.video_stop_event = threading.Event()
        self.video_running = False
        self.video_frame_index = 0
        self.video_frame_count = 0
        self.video_fps = 30.0

        self.render_generation = 0
        self.render_after_id = None

        self.width_var = tk.IntVar(value=120)
        self.charset_var = tk.StringVar(value="Стандартный")
        self.color_var = tk.BooleanVar(value=True)
        self.invert_var = tk.BooleanVar(value=False)
        self.zoom_var = tk.DoubleVar(value=1.0)
        self.status_var = tk.StringVar(value="Откройте изображение или видео")

        self._configure_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    @staticmethod
    @lru_cache(maxsize=4)
    def _load_font(size):
        candidates = (
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "DejaVuSansMono.ttf",
        )
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return ImageFont.load_default()

    @staticmethod
    @lru_cache(maxsize=512)
    def _glyph_mask(char, size, cell_width, cell_height):
        font = AsciiStudio._load_font(size)
        mask = Image.new("L", (cell_width, cell_height), 0)
        draw = ImageDraw.Draw(mask)

        bounds = draw.textbbox((0, 0), char, font=font)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]

        x = max(0, (cell_width - text_width) // 2 - bounds[0])
        y = max(0, (cell_height - text_height) // 2 - bounds[1])
        draw.text((x, y), char, fill=255, font=font)

        return mask

    def _configure_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground="#1b2330",
            background="#1b2330",
            foreground="#e8edf5",
            arrowcolor="#e8edf5",
            bordercolor="#303b4d",
        )
        style.configure(
            "Horizontal.TScale",
            background="#1a202b",
            troughcolor="#2a3443",
        )

    def _build_ui(self):
        header = tk.Frame(self.root, bg="#10141c", padx=24, pady=18)
        header.pack(fill="x")

        tk.Label(
            header,
            text="ASCII STUDIO",
            bg="#10141c",
            fg="#f0f4fa",
            font=("Segoe UI", 22, "bold"),
        ).pack(side="left")

        tk.Label(
            header,
            text="Конвертер изображений и видео",
            bg="#10141c",
            fg="#8c99aa",
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(16, 0), pady=(8, 0))

        toolbar = tk.Frame(self.root, bg="#171d27", padx=16, pady=12)
        toolbar.pack(fill="x", padx=20)

        self._button(toolbar, "Открыть файл", self.open_file, primary=True).pack(side="left")
        self._button(toolbar, "Сохранить PNG/JPEG", self.export_image).pack(side="left", padx=8)
        self._button(toolbar, "Сохранить текст", self.export_text).pack(side="left")
        self._button(toolbar, "Сохранить кадр", self.export_video_frame).pack(side="left", padx=8)

        body = tk.Frame(self.root, bg="#10141c", padx=20, pady=16)
        body.pack(fill="both", expand=True)

        settings = tk.Frame(body, bg="#171d27", width=265, padx=18, pady=18)
        settings.pack(side="left", fill="y")
        settings.pack_propagate(False)

        tk.Label(
            settings,
            text="НАСТРОЙКИ",
            bg="#171d27",
            fg="#e8edf5",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 18))

        tk.Label(
            settings,
            text="Ширина арта, символов",
            bg="#171d27",
            fg="#aab5c4",
        ).pack(anchor="w")

        width_row = tk.Frame(settings, bg="#171d27")
        width_row.pack(fill="x", pady=(7, 18))

        tk.Scale(
            width_row,
            from_=30,
            to=240,
            orient="horizontal",
            variable=self.width_var,
            command=lambda _value: self._schedule_render(),
            bg="#171d27",
            fg="#e8edf5",
            troughcolor="#2a3443",
            highlightthickness=0,
            bd=0,
            length=180,
        ).pack(side="left", fill="x", expand=True)

        self.width_label = tk.Label(
            width_row,
            text="120",
            width=4,
            bg="#171d27",
            fg="#58d6b0",
        )
        self.width_label.pack(side="right")

        tk.Label(
            settings,
            text="Набор символов",
            bg="#171d27",
            fg="#aab5c4",
        ).pack(anchor="w")

        charset_box = ttk.Combobox(
            settings,
            textvariable=self.charset_var,
            state="readonly",
            values=tuple(self.CHARACTER_SETS.keys()),
        )
        charset_box.pack(fill="x", pady=(7, 16))
        charset_box.bind("<<ComboboxSelected>>", lambda _event: self._schedule_render())

        tk.Checkbutton(
            settings,
            text="Сохранить цвета",
            variable=self.color_var,
            command=self._schedule_render,
            bg="#171d27",
            fg="#d8e0eb",
            selectcolor="#252e3c",
            activebackground="#171d27",
            activeforeground="#d8e0eb",
        ).pack(anchor="w", pady=3)

        tk.Checkbutton(
            settings,
            text="Инвертировать яркость",
            variable=self.invert_var,
            command=self._schedule_render,
            bg="#171d27",
            fg="#d8e0eb",
            selectcolor="#252e3c",
            activebackground="#171d27",
            activeforeground="#d8e0eb",
        ).pack(anchor="w", pady=3)

        tk.Label(
            settings,
            text="Масштаб предпросмотра",
            bg="#171d27",
            fg="#aab5c4",
        ).pack(anchor="w", pady=(22, 3))

        zoom_row = tk.Frame(settings, bg="#171d27")
        zoom_row.pack(fill="x")

        ttk.Scale(
            zoom_row,
            from_=0.25,
            to=2.5,
            variable=self.zoom_var,
            command=self.set_zoom,
        ).pack(side="left", fill="x", expand=True)

        self.zoom_label = tk.Label(
            zoom_row,
            text="100%",
            width=5,
            bg="#171d27",
            fg="#58d6b0",
        )
        self.zoom_label.pack(side="right")

        tk.Label(
            settings,
            text="ВИДЕО",
            bg="#171d27",
            fg="#e8edf5",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(24, 8))

        video_row = tk.Frame(settings, bg="#171d27")
        video_row.pack(fill="x")

        self._button(video_row, "▶", self.play_video, compact=True).pack(
            side="left", fill="x", expand=True
        )
        self._button(video_row, "Ⅱ", self.pause_video, compact=True).pack(
            side="left", fill="x", expand=True, padx=6
        )
        self._button(video_row, "↺", self.restart_video, compact=True).pack(
            side="left", fill="x", expand=True
        )

        self.video_progress = ttk.Scale(
            settings,
            from_=0,
            to=100,
            orient="horizontal",
            command=self.seek_video,
        )
        self.video_progress.pack(fill="x", pady=(12, 0))

        workspace = tk.Frame(body, bg="#10141c")
        workspace.pack(side="left", fill="both", expand=True, padx=(16, 0))

        preview_card = tk.Frame(workspace, bg="#171d27", padx=12, pady=12)
        preview_card.pack(fill="both", expand=True)

        preview_header = tk.Frame(preview_card, bg="#171d27")
        preview_header.pack(fill="x", pady=(0, 10))

        tk.Label(
            preview_header,
            text="ПРЕДПРОСМОТР",
            bg="#171d27",
            fg="#e8edf5",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")

        self.dimensions_label = tk.Label(
            preview_header,
            text="—",
            bg="#171d27",
            fg="#7f8c9d",
            font=("Segoe UI", 9),
        )
        self.dimensions_label.pack(side="right")

        self.canvas = tk.Canvas(
            preview_card,
            bg="#0b0e13",
            highlightthickness=1,
            highlightbackground="#283241",
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self._draw_preview())

        statusbar = tk.Frame(self.root, bg="#171d27", padx=20, pady=9)
        statusbar.pack(fill="x", side="bottom")

        tk.Label(
            statusbar,
            textvariable=self.status_var,
            bg="#171d27",
            fg="#9eabba",
        ).pack(side="left")

        tk.Label(
            statusbar,
            text="ASCII Studio • Python",
            bg="#171d27",
            fg="#657184",
        ).pack(side="right")

    @staticmethod
    def _button(parent, text, command, primary=False, compact=False):
        background = "#34c99b" if primary else "#242d3a"
        foreground = "#092019" if primary else "#e8edf5"

        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground="#45d8aa" if primary else "#303b4a",
            activeforeground=foreground,
            relief="flat",
            bd=0,
            padx=13 if not compact else 9,
            pady=9 if not compact else 7,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Выберите изображение или видео",
            filetypes=self.IMAGE_FILETYPES,
        )
        if not path:
            return

        self._stop_video()
        self.source_path = Path(path)

        if self.source_path.suffix.lower() in self.VIDEO_EXTENSIONS:
            self._open_video()
            return

        try:
            with Image.open(path) as image:
                self.source_image = ImageOps.exif_transpose(image).convert("RGB")

            self.status_var.set(f"Изображение: {self.source_path.name}")
            self._schedule_render(immediate=True)
        except Exception as exc:
            messagebox.showerror("Ошибка открытия", f"Не удалось открыть изображение:\n{exc}")

    def _open_video(self):
        if cv2 is None:
            messagebox.showerror(
                "Не установлен OpenCV",
                "Для работы с видео установите зависимости командой:\n"
                "python -m pip install -r requirements.txt",
            )
            return

        capture = cv2.VideoCapture(str(self.source_path))
        if not capture.isOpened():
            capture.release()
            messagebox.showerror("Ошибка открытия", "Не удалось открыть видеофайл.")
            return

        self.video_capture = capture
        self.video_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        self.video_fps = fps if fps and fps > 0 else 30.0
        self.video_frame_index = 0

        self.video_progress.configure(to=max(1, self.video_frame_count - 1))
        self.status_var.set(f"Видео: {self.source_path.name}")
        self._read_video_frame(0)

    def _read_video_frame(self, index=None):
        if self.video_capture is None:
            return False

        if index is not None:
            self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))

        ok, frame = self.video_capture.read()
        if not ok:
            return False

        self.video_frame_index = max(
            0,
            int(self.video_capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1,
        )
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self.source_image = Image.fromarray(rgb)

        self.video_progress.set(self.video_frame_index)
        self._schedule_render(immediate=True)
        return True

    def play_video(self):
        if self.video_capture is None or self.video_running:
            return

        self.video_stop_event.clear()
        self.video_running = True
        self.video_thread = threading.Thread(
            target=self._video_loop,
            daemon=True,
        )
        self.video_thread.start()

    def _video_loop(self):
        frame_duration = 1.0 / self.video_fps
        next_frame_time = time.perf_counter()

        while not self.video_stop_event.is_set():
            if self.video_capture is None:
                break

            ok, frame = self.video_capture.read()
            if not ok:
                break

            frame_index = max(
                0,
                int(self.video_capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1,
            )
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)

            try:
                self.root.after(
                    0,
                    lambda current=image, number=frame_index: self._accept_video_frame(
                        current, number
                    ),
                )
            except tk.TclError:
                break

            next_frame_time += frame_duration
            wait_time = next_frame_time - time.perf_counter()

            if wait_time > 0:
                self.video_stop_event.wait(wait_time)
            else:
                next_frame_time = time.perf_counter()

        try:
            self.root.after(0, self._video_finished)
        except tk.TclError:
            pass

    def _accept_video_frame(self, image, frame_index):
        if not self.video_running:
            return

        self.source_image = image
        self.video_frame_index = frame_index
        self.video_progress.set(frame_index)
        self._schedule_render(immediate=True)

    def _video_finished(self):
        self.video_running = False

    def pause_video(self):
        self._stop_video_thread()

    def restart_video(self):
        if self.video_capture is None:
            return

        self._stop_video_thread()
        if self._read_video_frame(0):
            self.status_var.set(f"Видео: {self.source_path.name}")

    def seek_video(self, value):
        if self.video_capture is None or self.video_running:
            return

        try:
            frame_index = int(float(value))
        except (TypeError, ValueError):
            return

        self._read_video_frame(frame_index)

    def _stop_video_thread(self):
        self.video_stop_event.set()
        self.video_running = False

    def _stop_video(self):
        self._stop_video_thread()
        if self.video_capture is not None:
            self.video_capture.release()
            self.video_capture = None

    def _charset(self):
        chars = self.CHARACTER_SETS.get(
            self.charset_var.get(),
            self.CHARACTER_SETS["Стандартный"],
        )
        return chars[::-1] if self.invert_var.get() else chars

    def _render_ascii(self, image):
        width = max(20, min(240, int(self.width_var.get())))
        aspect_ratio = image.height / max(1, image.width)
        height = max(1, int(width * aspect_ratio * 0.48))

        resized = image.resize(
            (width, height),
            Image.Resampling.BILINEAR,
        ).convert("RGB")
        grayscale = ImageOps.grayscale(resized)

        gray_pixels = grayscale.load()
        source_pixels = resized.load()
        chars = self._charset()
        char_count = len(chars)
        cell_width = self.CELL_WIDTH
        cell_height = self.CELL_HEIGHT

        result_width = width * cell_width
        result_height = height * cell_height
        output = Image.new(
            "RGB",
            (result_width, result_height),
            self.BACKGROUND,
        )
        output_pixels = output.load()
        rows = []

        if self.color_var.get():
            for y in range(height):
                row = []
                cell_y = y * cell_height

                for x in range(width):
                    brightness = gray_pixels[x, y]
                    index = min(char_count - 1, brightness * char_count // 256)
                    char = chars[index]
                    row.append(char)

                    mask = self._glyph_mask(
                        char,
                        self.FONT_SIZE,
                        cell_width,
                        cell_height,
                    )
                    mask_pixels = mask.load()
                    color = source_pixels[x, y]
                    cell_x = x * cell_width

                    for mask_y in range(cell_height):
                        output_y = cell_y + mask_y

                        for mask_x in range(cell_width):
                            alpha = mask_pixels[mask_x, mask_y]
                            if alpha == 0:
                                continue

                            output_pixels[cell_x + mask_x, output_y] = (
                                (self.BACKGROUND[0] * (255 - alpha) + color[0] * alpha) // 255,
                                (self.BACKGROUND[1] * (255 - alpha) + color[1] * alpha) // 255,
                                (self.BACKGROUND[2] * (255 - alpha) + color[2] * alpha) // 255,
                            )

                rows.append("".join(row))
        else:
            for y in range(height):
                row = []
                cell_y = y * cell_height

                for x in range(width):
                    brightness = gray_pixels[x, y]
                    index = min(char_count - 1, brightness * char_count // 256)
                    char = chars[index]
                    row.append(char)

                    mask = self._glyph_mask(
                        char,
                        self.FONT_SIZE,
                        cell_width,
                        cell_height,
                    )
                    mask_pixels = mask.load()
                    cell_x = x * cell_width

                    for mask_y in range(cell_height):
                        output_y = cell_y + mask_y

                        for mask_x in range(cell_width):
                            alpha = mask_pixels[mask_x, mask_y]
                            if alpha == 0:
                                continue

                            output_pixels[cell_x + mask_x, output_y] = (
                                (self.BACKGROUND[0] * (255 - alpha) + self.LIGHT_TEXT[0] * alpha) // 255,
                                (self.BACKGROUND[1] * (255 - alpha) + self.LIGHT_TEXT[1] * alpha) // 255,
                                (self.BACKGROUND[2] * (255 - alpha) + self.LIGHT_TEXT[2] * alpha) // 255,
                            )

                rows.append("".join(row))

        return output, "\n".join(rows)

    def _schedule_render(self, immediate=False):
        self.width_label.configure(text=str(self.width_var.get()))

        if self.source_image is None:
            return

        self.render_generation += 1
        generation = self.render_generation

        if self.render_after_id is not None:
            try:
                self.root.after_cancel(self.render_after_id)
            except tk.TclError:
                pass
            self.render_after_id = None

        delay = 0 if immediate else 120
        self.render_after_id = self.root.after(
            delay,
            lambda current=generation: self._start_render(current),
        )

    def _start_render(self, generation):
        self.render_after_id = None
        image = self.source_image.copy()

        settings = (
            int(self.width_var.get()),
            self.charset_var.get(),
            bool(self.color_var.get()),
            bool(self.invert_var.get()),
        )

        thread = threading.Thread(
            target=self._render_in_background,
            args=(image, settings, generation),
            daemon=True,
        )
        thread.start()

    def _render_in_background(self, image, settings, generation):
        try:
            output, text = self._render_ascii(image, settings)
            self.root.after(
                0,
                lambda: self._apply_render_result(
                    generation,
                    output,
                    text,
                    image.size,
                ),
            )
        except Exception as exc:
            self.root.after(
                0,
                lambda error=str(exc), current=generation: self._show_render_error(
                    current, error
                ),
            )

    def _render_ascii(self, image, settings=None):
        if settings is None:
            settings = (
                int(self.width_var.get()),
                self.charset_var.get(),
                bool(self.color_var.get()),
                bool(self.invert_var.get()),
            )

        width, charset_name, keep_color, invert = settings
        width = max(20, min(240, width))
        aspect_ratio = image.height / max(1, image.width)
        height = max(1, int(width * aspect_ratio * 0.48))

        resized = image.resize((width, height), Image.Resampling.BILINEAR).convert("RGB")
        grayscale = ImageOps.grayscale(resized)
        gray_pixels = grayscale.load()
        source_pixels = resized.load()

        chars = self.CHARACTER_SETS.get(
            charset_name,
            self.CHARACTER_SETS["Стандартный"],
        )
        if invert:
            chars = chars[::-1]

        cell_width = self.CELL_WIDTH
        cell_height = self.CELL_HEIGHT
        background = self.BACKGROUND
        foreground = None if keep_color else self.LIGHT_TEXT

        output = Image.new(
            "RGB",
            (width * cell_width, height * cell_height),
            background,
        )
        output_pixels = output.load()
        rows = []
        char_count = len(chars)

        masks = {
            char: self._glyph_mask(char, self.FONT_SIZE, cell_width, cell_height).load()
            for char in set(chars)
        }

        for y in range(height):
            row = []
            cell_y = y * cell_height

            for x in range(width):
                brightness = gray_pixels[x, y]
                char_index = min(char_count - 1, brightness * char_count // 256)
                char = chars[char_index]
                row.append(char)

                mask_pixels = masks[char]
                color = source_pixels[x, y] if foreground is None else foreground
                cell_x = x * cell_width

                for mask_y in range(cell_height):
                    output_y = cell_y + mask_y

                    for mask_x in range(cell_width):
                        alpha = mask_pixels[mask_x, mask_y]
                        if alpha:
                            output_pixels[cell_x + mask_x, output_y] = (
                                (background[0] * (255 - alpha) + color[0] * alpha) // 255,
                                (background[1] * (255 - alpha) + color[1] * alpha) // 255,
                                (background[2] * (255 - alpha) + color[2] * alpha) // 255,
                            )

            rows.append("".join(row))

        return output, "\n".join(rows)

    def _apply_render_result(self, generation, output, text, source_size):
        if generation != self.render_generation:
            return

        self.output_image = output
        self.ascii_text = text
        lines = text.splitlines()
        line_count = len(lines)
        char_width = len(lines[0]) if lines else 0

        self.dimensions_label.configure(
            text=f"{char_width} × {line_count} символов • исходник {source_size[0]} × {source_size[1]}"
        )
        self._draw_preview()

    def _show_render_error(self, generation, error):
        if generation == self.render_generation:
            self.status_var.set(f"Ошибка обработки: {error}")

    def _draw_preview(self):
        if self.output_image is None or not hasattr(self, "canvas"):
            return

        canvas_width = max(1, self.canvas.winfo_width())
        canvas_height = max(1, self.canvas.winfo_height())
        max_width = max(1, int(canvas_width * self.zoom))
        max_height = max(1, int(canvas_height * self.zoom))

        preview = self.output_image.copy()
        preview.thumbnail((max_width, max_height), Image.Resampling.NEAREST)

        self.preview_photo = ImageTk.PhotoImage(preview)
        self.canvas.delete("all")
        self.canvas.create_image(
            canvas_width // 2,
            canvas_height // 2,
            image=self.preview_photo,
            anchor="center",
        )

    def set_zoom(self, value):
        self.zoom = float(value)
        self.zoom_label.configure(text=f"{int(self.zoom * 100)}%")
        self._draw_preview()

    def export_image(self):
        if self.output_image is None:
            messagebox.showinfo("Нет результата", "Сначала откройте изображение или видео.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg")],
            initialfile="ascii_art.png",
        )
        if not path:
            return

        try:
            image = self.output_image
            if Path(path).suffix.lower() in {".jpg", ".jpeg"}:
                image.convert("RGB").save(path, quality=95)
            else:
                image.save(path)

            self.status_var.set(f"Сохранено: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))

    def export_text(self):
        if not self.ascii_text:
            messagebox.showinfo("Нет результата", "Сначала откройте изображение или видео.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстовый файл", "*.txt"), ("Все файлы", "*.*")],
            initialfile="ascii_art.txt",
        )
        if not path:
            return

        try:
            Path(path).write_text(self.ascii_text, encoding="utf-8")
            self.status_var.set(f"Текст сохранён: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))

    def export_video_frame(self):
        if self.video_capture is None:
            messagebox.showinfo("Нет видео", "Сначала откройте видеофайл.")
            return
        self.export_image()

    def close(self):
        self._stop_video()
        self.root.destroy()


def main():
    root = tk.Tk()
    AsciiStudio(root)
    root.mainloop()


if __name__ == "__main__":
    main()