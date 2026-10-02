# -*- coding: utf-8 -*-
"""
Лёгкие анимации интерфейса: заставка при запуске, плавное проявление содержимого при переходах,
выезжающие плашки. Эффект ставится только на время анимации (0,15–0,35 с) и сразу снимается, поэтому
в покое на компьютер ничего не нагружает. Встроенный браузер (карта дела) не анимируется — эффекты
прозрачности с ним несовместимы. Выключаются в «Вид → Анимации».
"""
from PySide6.QtCore import (Qt, QElapsedTimer, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QTimer,
                            QEventLoop, QRectF, QPointF, QPoint)
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QLinearGradient
from PySide6.QtWidgets import QWidget, QGraphicsOpacityEffect, QApplication

ENABLED = True
_running = {}          # id(виджета) -> анимация (чтобы не наслаивать)


def _has_webview(w):
    import sys
    mod = sys.modules.get("PySide6.QtWebEngineWidgets")
    if mod is None:                 # встроенный браузер ещё не загружали — значит, его и нет на экране
        return False                # (не загружать его ради проверки: это 0,3 с на запуске)
    QWebEngineView = mod.QWebEngineView
    return isinstance(w, QWebEngineView) or w.findChild(QWebEngineView) is not None


def fade_in(w, ms=180):
    """Плавно проявить содержимое виджета (переход между вкладками, делами, разделами)."""
    if not ENABLED or w is None or not w.isVisible() or w.graphicsEffect() is not None or _has_webview(w):
        return
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", w)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.OutCubic)

    def done():
        _running.pop(id(w), None)
        if w.graphicsEffect() is eff:
            w.setGraphicsEffect(None)
    a.finished.connect(done)
    _running[id(w)] = a
    a.start(QPropertyAnimation.DeleteWhenStopped)


def slide_in(w, dx=0, dy=14, ms=240):
    """Переход: содержимое проявляется и чуть «подъезжает» на место (снизу или сбоку), как в современных
    программах. Сдвиг небольшой (10–20 точек), длится четверть секунды."""
    if not ENABLED or w is None or not w.isVisible() or w.graphicsEffect() is not None or _has_webview(w):
        return
    old = _running.pop(id(w), None)
    if old is not None:
        try:
            old.stop()
        except RuntimeError:
            pass
    end = w.pos()
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    grp = QParallelAnimationGroup(w)
    fa = QPropertyAnimation(eff, b"opacity", grp)
    fa.setDuration(ms)
    fa.setStartValue(0.0)
    fa.setEndValue(1.0)
    fa.setEasingCurve(QEasingCurve.OutCubic)
    ma = QPropertyAnimation(w, b"pos", grp)
    ma.setDuration(ms)
    ma.setStartValue(end + QPoint(dx, dy))
    ma.setEndValue(end)
    ma.setEasingCurve(QEasingCurve.OutCubic)
    grp.addAnimation(fa)
    grp.addAnimation(ma)

    def done():
        _running.pop(id(w), None)
        try:
            if w.graphicsEffect() is eff:
                w.setGraphicsEffect(None)
            if w.pos() != end:
                w.move(end)
        except RuntimeError:
            pass
    grp.finished.connect(done)
    _running[id(w)] = grp
    grp.start(QParallelAnimationGroup.DeleteWhenStopped)


def pop_in(win, dy=10, ms=200):
    """Окно (диалог, меню) появляется мягко: проявляется и слегка «всплывает» на место."""
    if not ENABLED or win is None:
        return
    end = win.pos()
    win.setWindowOpacity(0.0)
    grp = QParallelAnimationGroup(win)
    fa = QPropertyAnimation(win, b"windowOpacity", grp)
    fa.setDuration(ms)
    fa.setStartValue(0.0)
    fa.setEndValue(1.0)
    fa.setEasingCurve(QEasingCurve.OutCubic)
    grp.addAnimation(fa)
    if dy:
        ma = QPropertyAnimation(win, b"pos", grp)
        ma.setDuration(ms)
        ma.setStartValue(end + QPoint(0, dy))
        ma.setEndValue(end)
        ma.setEasingCurve(QEasingCurve.OutCubic)
        grp.addAnimation(ma)

    def done():
        _running.pop(id(win), None)
        try:
            win.setWindowOpacity(1.0)
        except RuntimeError:
            pass
    grp.finished.connect(done)
    _running[id(win)] = grp
    grp.start(QParallelAnimationGroup.DeleteWhenStopped)
    # страховка: окно ни при каких условиях не остаётся прозрачным
    QTimer.singleShot(ms + 400, lambda: _safe_opaque(win))


def _safe_opaque(win):
    try:
        if win.windowOpacity() < 1.0 and id(win) not in _running:
            win.setWindowOpacity(1.0)
    except RuntimeError:
        pass


def slide_down(w, ms=240):
    """Показать плашку, «выезжая» сверху (анимация высоты)."""
    if not ENABLED:
        w.show()
        return
    w.setMaximumHeight(0)
    w.show()
    target = max(w.sizeHint().height(), 30)
    a = QPropertyAnimation(w, b"maximumHeight", w)
    a.setDuration(ms)
    a.setStartValue(0)
    a.setEndValue(target)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.finished.connect(lambda: w.setMaximumHeight(16777215))
    _running[id(w)] = a
    a.start(QPropertyAnimation.DeleteWhenStopped)


def window_fade(win, start=0.0, end=1.0, ms=220, then=None):
    """Проявить / скрыть окно целиком (прозрачность окна — это делает сама Windows, почти бесплатно)."""
    if not ENABLED:
        win.setWindowOpacity(end)
        if then:
            then()
        return None
    win.setWindowOpacity(start)
    a = QPropertyAnimation(win, b"windowOpacity", win)
    a.setDuration(ms)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.OutCubic if end > start else QEasingCurve.InCubic)
    if then:
        a.finished.connect(then)
    _running[id(win)] = a
    a.finished.connect(lambda: _running.pop(id(win), None))
    a.start(QPropertyAnimation.DeleteWhenStopped)
    return a


def wait(ms):
    """Дать анимации поиграть, не блокируя окно (используется только при запуске)."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Splash(QWidget):
    """Заставка при запуске: иконка, название и бегущая полоска, пока открывается главное окно."""

    def __init__(self, pixmap, name, version, dark=False):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(360, 250)
        self.name, self.version, self.dark = name, version, dark
        self.pix = pixmap if isinstance(pixmap, QPixmap) else QPixmap(pixmap)
        self.phase = 0.0
        self.progress = 0.0            # полоска заполняется слева направо, а не «бегает»
        self.held = False
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        scr = QApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)

    def _tick(self):
        t = min(1.0, self.clock.elapsed() / 220.0)
        self.phase = t
        self.progress = 0.9 * (1 - (1 - t) ** 3)          # плавное замедление к концу
        self.update()

    def start(self):
        self.clock.start()
        self.show()
        self.timer.start()
        window_fade(self, 0.0, 1.0, 260)
        QApplication.processEvents()

    def hold(self):
        """Замереть перед тяжёлой работой (сборка главного окна): неподвижная картинка не выглядит
        «подвисшей», а бегущая полоска, остановившаяся на полпути, — выглядит."""
        self.timer.stop()
        self.progress, self.phase = 0.9, 1.0
        self.held = True
        self.repaint()
        QApplication.processEvents()

    def finish(self, main_window):
        """Главное окно сначала полностью отрисовывается (ещё невидимым), потом проявляется, а заставка тает."""
        self.timer.stop()
        self.progress = 1.0
        self.repaint()
        QApplication.processEvents()
        main_window.repaint()
        QApplication.processEvents()
        window_fade(main_window, 0.0, 1.0, 280)
        window_fade(self, self.windowOpacity(), 0.0, 220, then=self.close)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        bg, fg, sub = (("#1c1c1e", "#f2f2f7", "#98989f") if self.dark else ("#ffffff", "#1c1c1e", "#8e8e93"))
        for i in range(6, 0, -1):                         # мягкая тень
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 5))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 22 + i, 22 + i)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(r, 22, 22)
        # иконка с лёгким «дыханием»
        s = 80 + 8 * (1 - (1 - self.phase) ** 3)            # иконка мягко «вырастает» при появлении
        if not self.pix.isNull():
            p.drawPixmap(QRectF(r.center().x() - s / 2, r.top() + 30 + (88 - s) / 2, s, s), self.pix,
                         QRectF(self.pix.rect()))
        f = QFont(self.font())
        f.setPointSize(17)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(fg))
        p.drawText(QRectF(r.left(), r.top() + 126, r.width(), 32), Qt.AlignCenter, self.name)
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(sub))
        p.drawText(QRectF(r.left(), r.top() + 156, r.width(), 20), Qt.AlignCenter, f"версия {self.version}")
        # полоска загрузки
        track = QRectF(r.center().x() - 70, r.bottom() - 36, 140, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(118, 118, 128, 50))
        p.drawRoundedRect(track, 2, 2)
        if self.progress > 0:
            seg = QRectF(track.left(), track.top(), track.width() * self.progress, 4)
            grad = QLinearGradient(QPointF(seg.left(), 0), QPointF(seg.right(), 0))
            grad.setColorAt(0, QColor(0, 122, 255, 140))
            grad.setColorAt(1, QColor(0, 122, 255, 255))
            p.setBrush(grad)
            p.drawRoundedRect(seg, 2, 2)
        p.end()
