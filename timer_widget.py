# -*- coding: utf-8 -*-
"""
Маленькие таймер и секундомер в правом нижнем углу окна.

В строке состояния — кнопка «⏱». Щелчок раскрывает крошечную панель: вкладка «Таймер» (обратный отсчёт:
5, 10, 15, 30, 60 минут или своё время) и «Секундомер» (с кругами). Пока идёт отсчёт, на кнопке видно
оставшееся или прошедшее время — можно закрыть панель и работать дальше. Когда таймер закончился, звучит
сигнал и всплывает окно поверх программы.
"""
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QFrame, QToolButton, QPushButton, QLabel, QVBoxLayout, QHBoxLayout,
                               QTabBar, QStackedWidget, QSpinBox, QListWidget, QApplication, QMessageBox)


def fmt(sec, tenths=False):
    sec = max(0.0, sec)
    h, rest = divmod(int(sec), 3600)
    m, s = divmod(rest, 60)
    out = f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
    if tenths:
        out += f",{int((sec - int(sec)) * 10)}"
    return out


def beep():
    """Три сигнала (Windows) — в отдельном потоке, чтобы окно не замирало; в других системах — один."""
    try:
        import winsound
    except ImportError:
        QApplication.beep()
        return
    import threading

    def ring():
        for _ in range(3):
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                return
            time.sleep(0.35)
    threading.Thread(target=ring, daemon=True).start()


class Countdown:
    """Обратный отсчёт: не зависит от интерфейса, считает по часам компьютера (не сбивается при нагрузке)."""

    def __init__(self):
        self.total = 0.0
        self.end = None          # время окончания, если идёт
        self.left_paused = None  # остаток, если на паузе

    def start(self, seconds=None):
        if seconds is not None:
            self.total = float(seconds)
            self.left_paused = None
        left = self.left_paused if self.left_paused is not None else self.total
        if left <= 0:
            return
        self.end = time.monotonic() + left
        self.left_paused = None

    def pause(self):
        if self.end is not None:
            self.left_paused = max(0.0, self.end - time.monotonic())
            self.end = None

    def reset(self):
        self.end, self.left_paused = None, None

    @property
    def running(self):
        return self.end is not None

    @property
    def active(self):
        return self.running or self.left_paused is not None

    def left(self):
        if self.end is not None:
            return max(0.0, self.end - time.monotonic())
        return self.left_paused if self.left_paused is not None else self.total


class Stopwatch:
    def __init__(self):
        self.acc = 0.0
        self.since = None
        self.laps = []

    def start(self):
        if self.since is None:
            self.since = time.monotonic()

    def pause(self):
        if self.since is not None:
            self.acc += time.monotonic() - self.since
            self.since = None

    def reset(self):
        self.acc, self.since, self.laps = 0.0, None, []

    def lap(self):
        self.laps.append(self.elapsed())

    @property
    def running(self):
        return self.since is not None

    def elapsed(self):
        return self.acc + (time.monotonic() - self.since if self.since is not None else 0.0)


class TimerPanel(QFrame):
    """Всплывающая панель над кнопкой."""
    finished = Signal()

    PRESETS = (5, 10, 15, 30, 60)

    def __init__(self, owner):
        super().__init__(owner.window(), Qt.Popup | Qt.FramelessWindowHint)
        self.owner = owner
        self.cd, self.sw = owner.cd, owner.sw
        self.setObjectName("timerpanel")
        self.setFixedWidth(250)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 12)
        v.setSpacing(8)
        self.seg = QTabBar()
        self.seg.setObjectName("docseg")
        self.seg.setDrawBase(False)
        self.seg.setExpanding(True)
        self.seg.addTab("Таймер")
        self.seg.addTab("Секундомер")
        v.addWidget(self.seg)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        self.seg.currentChanged.connect(self.stack.setCurrentIndex)

        # --- таймер
        t = QWidget()
        tv = QVBoxLayout(t)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(6)
        self.t_big = QLabel("00:00")
        self.t_big.setObjectName("timerbig")
        self.t_big.setAlignment(Qt.AlignCenter)
        tv.addWidget(self.t_big)
        pr = QHBoxLayout()
        pr.setSpacing(3)
        for m in self.PRESETS:
            b = QPushButton(f"{m}")
            b.setObjectName("compact")
            b.setToolTip(f"Запустить на {m} мин")
            b.setFixedWidth(40)
            b.clicked.connect(lambda _=False, m=m: self.start_timer(m * 60))
            pr.addWidget(b)
        tv.addLayout(pr)
        cr = QHBoxLayout()
        cr.addWidget(QLabel("Своё:"))
        self.t_min = QSpinBox()
        self.t_min.setRange(0, 600)
        self.t_min.setValue(20)
        self.t_min.setSuffix(" мин")
        cr.addWidget(self.t_min, 1)
        self.t_sec = QSpinBox()
        self.t_sec.setRange(0, 59)
        self.t_sec.setSuffix(" с")
        cr.addWidget(self.t_sec)
        tv.addLayout(cr)
        br = QHBoxLayout()
        self.t_go = QPushButton("Старт")
        self.t_go.setObjectName("primary")
        self.t_go.clicked.connect(self.toggle_timer)
        self.t_reset = QPushButton("Сброс")
        self.t_reset.clicked.connect(self.reset_timer)
        br.addWidget(self.t_go, 1)
        br.addWidget(self.t_reset)
        tv.addLayout(br)
        self.stack.addWidget(t)

        # --- секундомер
        s = QWidget()
        sv = QVBoxLayout(s)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(6)
        self.s_big = QLabel("00:00,0")
        self.s_big.setObjectName("timerbig")
        self.s_big.setAlignment(Qt.AlignCenter)
        sv.addWidget(self.s_big)
        self.laps = QListWidget()
        self.laps.setFixedHeight(80)
        sv.addWidget(self.laps)
        sr = QHBoxLayout()
        self.s_go = QPushButton("Старт")
        self.s_go.setObjectName("primary")
        self.s_go.clicked.connect(self.toggle_sw)
        self.s_lap = QPushButton("Круг")
        self.s_lap.clicked.connect(self.lap)
        self.s_reset = QPushButton("Сброс")
        self.s_reset.clicked.connect(self.reset_sw)
        sr.addWidget(self.s_go, 1)
        sr.addWidget(self.s_lap)
        sr.addWidget(self.s_reset)
        sv.addLayout(sr)
        self.stack.addWidget(s)
        self.update_view()

    # таймер
    def start_timer(self, seconds):
        self.cd.start(seconds)
        self.owner.tick()

    def toggle_timer(self):
        if self.cd.running:
            self.cd.pause()
        elif self.cd.left_paused is not None:
            self.cd.start()
        else:
            sec = self.t_min.value() * 60 + self.t_sec.value()
            if sec:
                self.cd.start(sec)
        self.owner.tick()

    def reset_timer(self):
        self.cd.reset()
        self.cd.total = 0
        self.owner.tick()

    # секундомер
    def toggle_sw(self):
        self.sw.pause() if self.sw.running else self.sw.start()
        self.owner.tick()

    def lap(self):
        if self.sw.running:
            self.sw.lap()
            self.owner.tick()

    def reset_sw(self):
        self.sw.reset()
        self.owner.tick()

    def update_view(self):
        self.t_big.setText(fmt(self.cd.left()))
        self.t_go.setText("Пауза" if self.cd.running else ("Продолжить" if self.cd.left_paused is not None else "Старт"))
        self.s_big.setText(fmt(self.sw.elapsed(), tenths=True))
        self.s_go.setText("Пауза" if self.sw.running else ("Продолжить" if self.sw.elapsed() else "Старт"))
        if self.laps.count() != len(self.sw.laps):
            self.laps.clear()
            prev = 0.0
            for i, t in enumerate(self.sw.laps, 1):
                self.laps.insertItem(0, f"Круг {i}:  {fmt(t - prev, True)}   (всего {fmt(t, True)})")
                prev = t


class TimerButton(QToolButton):
    """Кнопка «⏱» в строке состояния; во время отсчёта показывает время."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("timerbtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        self.setToolTip("Таймер и секундомер")
        self.cd, self.sw = Countdown(), Stopwatch()
        self.panel = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.clicked.connect(self.show_panel)
        self.tick()

    def show_panel(self):
        if self.panel is None:
            self.panel = TimerPanel(self)
        self.panel.update_view()
        self.panel.adjustSize()
        g = self.mapToGlobal(self.rect().topRight())
        self.panel.move(g.x() - self.panel.width(), g.y() - self.panel.height() - 6)
        self.panel.show()
        self.timer.start()

    def tick(self):
        if self.cd.running and self.cd.left() <= 0:
            self.cd.reset()
            self.cd.total = 0
            self.done()
        parts = []
        if self.cd.active:
            parts.append(("⏳ " if self.cd.running else "⏸ ") + fmt(self.cd.left()))
        if self.sw.running or self.sw.elapsed():
            parts.append(("⏱ " if self.sw.running else "⏸ ") + fmt(self.sw.elapsed()))
        self.setText("   ".join(parts) if parts else "⏱")
        if self.panel is not None and self.panel.isVisible():
            self.panel.update_view()
        busy = self.cd.running or self.sw.running or (self.panel is not None and self.panel.isVisible())
        if busy and not self.timer.isActive():
            self.timer.start()
        elif not busy and self.timer.isActive():
            self.timer.stop()

    def done(self):
        beep()
        w = self.window()
        box = QMessageBox(w)
        box.setWindowTitle("Таймер")
        box.setText("⏰  Время вышло!")
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        box.setWindowModality(Qt.NonModal)
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.show()
        try:
            w.raise_()
            w.activateWindow()
        except Exception:
            pass
