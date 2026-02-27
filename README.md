# ⬡ Keystroke Sentinel — Educational Keylogger Simulator

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-41CD52?style=flat-square&logo=qt&logoColor=white)
![pynput](https://img.shields.io/badge/Capture-pynput-FF6B35?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)
![Educational](https://img.shields.io/badge/Purpose-Educational%20Only-red?style=flat-square)

> A fully-featured desktop keylogger simulation built for cybersecurity education. Understand how keystroke logging works, what data gets captured, and how to defend against it.All in a dark, terminal-hacker GUI with real-time visualization.

---

## ⚠️ Disclaimer

**This tool is strictly for educational and research purposes.**  
Run it **only on your own machine** with your own consent.  
All captured data stays **100% local** — nothing is transmitted over any network.  
Deploying keylogger software on any device without explicit consent is a criminal offence under the UK Computer Misuse Act, US CFAA, Pakistan PECA 2016, and most other jurisdictions.

---

## 📸 Preview

![alt text](<Screenshot (166).png>) ![alt text](<Screenshot (165).png>) ![alt text](<Screenshot (164).png>) ![alt text](<Screenshot (163).png>)

---

## ✨ Features

### ◉ Live Capture Tab
- **Animated key bubbles** — every keystroke spawns a glowing, color-coded bubble that fades out
- **Color-coded terminal log** — cyan for letters, green for Enter, red for Backspace, amber for modifiers
- **Live word reconstruction** — words are rebuilt in real time from Space/Enter boundaries
- **Word cloud** — most-typed words scale up visually as frequency increases
- **Real-time charts** — keystrokes/second timeline + category breakdown bar chart (requires pyqtgraph)
- **Heuristic findings panel** — auto-alerts for patterns that look like passwords, emails, or PINs

### ◈ Analysis Tab
- Top 20 most-pressed keys with visual bar charts
- Reconstructed word list with auto-flagging of suspicious entries
- Full session statistics table (total keys, error rate, unique words, timing)
- Key category breakdown with attack-relevance descriptions

### ⌨ Heatmap Tab
- Full keyboard layout rendered with **frequency heatmap** — keys glow from dark blue → cyan → white based on press frequency
- Bigram (2-key sequence) analysis — reveals typing patterns and common character pairs

### ⚠ Risk Tab
- **Credential detection** — automatically identifies possible passwords, emails, PINs, card numbers, and OTPs
- **Behavioural analysis** — error rate, Enter-press frequency, numeric sequences, longest tokens
- **Attack risk matrix** — 7 real-world attack scenarios rated by likelihood and impact
- **Defences & mitigations** — star-rated security controls with explanations

### General
- Dark terminal-hacker aesthetic throughout
- Save session to **JSON**, load a previous session, export raw **TXT** log
- Stat cards: total keys, printable chars, words, backspaces, Enter presses, live keys/sec
- Maximizes on launch, fully resizable
- ESC key stops the listener cleanly

---

## 🚀 Installation

### 1. Clone the repo
```bash
git clone https://github.com/dawood-ayub/keystroke-sentinel.git
cd keystroke-sentinel
```

### 2. Install dependencies
```bash
pip install pynput PyQt5 pyqtgraph
```

> `pyqtgraph` is optional — the app runs without it, but real-time charts won't display.

### 3. Windows
pynput works out of the box. Run as Administrator to capture keystrokes from elevated processes.

### 4. Linux
```bash
# If capture doesn't work:
sudo python keylogge.py
```

---

## ▶️ Running

```bash
python keylogger.py
```

The window opens maximized. Click **▶ START CAPTURE** to begin, **■ STOP** to end.

---

## 🎛️ How to Use

| Action | How |
|---|---|
| Start logging | Click **▶ START CAPTURE** |
| Stop logging | Click **■ STOP** or press **ESC** |
| View live stream | LIVE CAPTURE tab |
| See analysis | ANALYSIS tab |
| Keyboard heatmap | HEATMAP tab |
| Risk findings | RISK tab |
| Save session | **↓ Save JSON** |
| Load previous session | **↑ Load JSON** |
| Export raw log | **↓ Export TXT** |
| Clear everything | **⊘ Clear** |

---


## 🔬 What Gets Captured & Why It Matters

| Key Type | Logged As | What an Attacker Extracts |
|---|---|---|
| Letters / numbers / symbols | Raw character | Direct content — passwords, messages |
| Space | Word boundary | Enables full word reconstruction |
| Enter | `[↵]` | Login submissions, form sends |
| Backspace | `[⌫]` | Corrections — reveals deleted characters |
| Shift / Ctrl / Alt | `[⇧]` `[Ctrl]` | Modifier combos, shortcut detection |
| Timestamp | `HH:MM:SS.ms` | Active hours, typing speed, login time |

### The Password Problem
Even if a password field masks input on screen, a keylogger captures raw keystrokes **before** the application receives them:

```
User types:    p a s s w [⌫][⌫] w o r d 1 2 3 !
Keylog sees:   p-a-s-s-w-[⌫]-[⌫]-w-o-r-d-1-2-3-!
Reconstructed: password123!   ← complete credential captured
```

---

## 🛡️ Defences Covered in the Risk Tab

| Control | Effectiveness |
|---|---|
| Multi-Factor Authentication | ★★★★★ Critical — stolen password alone is useless |
| Password Manager | ★★★★☆ High — auto-fill means no keystrokes on password fields |
| Antivirus / EDR | ★★★★☆ High — detects hook-based signatures |
| Application Allowlisting | ★★★★☆ High — prevents unknown executables from running |
| OS Patching | ★★★☆☆ Medium — closes exploitation vectors |
| Virtual On-Screen Keyboard | ★★☆☆☆ Low-Med — mouse clicks bypass keyboard hooks |

---

## 🔧 Requirements

| Package | Version | Purpose |
|---|---|---|
| Python | 3.8+ | Runtime |
| PyQt5 | 5.15+ | GUI framework |
| pynput | 1.7+ | Keyboard event capture |
| pyqtgraph | 0.13+ | Live charts (optional) |

---

## 🤝 Contributing

Pull requests are welcome. Open an issue first for major changes.

1. Fork the repo
2. `git checkout -b feature/my-feature`
3. `git commit -m 'Add feature'`
4. `git push origin feature/my-feature`
5. Open a pull request

---

<p align="center">Built with Python · PyQt5 · pynput · For Education Only</p>
