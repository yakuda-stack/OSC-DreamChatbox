"""
core/ai_translator.py - translating with an AI (v1.6.5)

Five services, all behind core/translators.py's Translator interface:

    Local AI       Ollama on your own PC (HTTP API, 127.0.0.1:11434)
    Claude Code    claude -p "<prompt>" --model haiku
    Gemini CLI     gemini -m flash -p "<prompt>" --output-format json
    ChatGPT        codex exec -m <model> -   (prompt on stdin, Codex CLI)
    Custom AI      your own command or curl call, {prompt} = the request

The three online ones use the vendor's own command-line program, so the
login is the one you already have (Claude / Google / ChatGPT account) -
no API key has to be typed in here. The UI offers an install button
and a login button that open a terminal.

Settings live in the normal config (stt_ai_* keys, see DEFAULTS); the
window hands its config over once with use_config(), so every caller of
translate_with_fallback() gets the AI settings without passing them on.

Everything here BLOCKS for a few seconds -> worker threads only.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from core.osinfo import IS_WINDOWS, subprocess_flags

METHOD_OLLAMA = "ai_ollama"
METHOD_CLAUDE = "ai_claude"
METHOD_GEMINI = "ai_gemini"
METHOD_CHATGPT = "ai_chatgpt"
METHOD_AI_CUSTOM = "ai_custom"

CLI_METHODS = (METHOD_CLAUDE, METHOD_GEMINI, METHOD_CHATGPT)
AI_METHODS = (METHOD_OLLAMA,) + CLI_METHODS + (METHOD_AI_CUSTOM,)

#: dropdown entries, appended to core/translators.METHODS
LABELS = [
    ("Local AI – Ollama (offline, own PC)", METHOD_OLLAMA),
    ("Claude Code (AI, Claude login)", METHOD_CLAUDE),
    ("Gemini CLI (AI, Google login)", METHOD_GEMINI),
    ("ChatGPT – Codex CLI (AI, ChatGPT login)", METHOD_CHATGPT),
    ("Custom AI (own command / API)", METHOD_AI_CUSTOM),
]

BINARIES = {METHOD_CLAUDE: "claude", METHOD_GEMINI: "gemini",
            METHOD_CHATGPT: "codex", METHOD_OLLAMA: "ollama"}
NPM_PACKAGES = {METHOD_CLAUDE: "@anthropic-ai/claude-code",
                METHOD_GEMINI: "@google/gemini-cli",
                METHOD_CHATGPT: "@openai/codex"}
LOGIN_COMMANDS = {METHOD_CLAUDE: ["claude"], METHOD_GEMINI: ["gemini"],
                  METHOD_CHATGPT: ["codex", "login"]}
#: where the install button puts npm packages - no sudo needed
NPM_PREFIX = Path.home() / ".local"
CLAUDE_INSTALLER = "curl -fsSL https://claude.ai/install.sh | bash"
CLAUDE_INSTALLER_WIN = "irm https://claude.ai/install.ps1 | iex"
OLLAMA_SCRIPT = "curl -fsSL https://ollama.com/install.sh | sh"
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
OLLAMA_LIBRARY_URL = "https://ollama.com/library"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

#: model suggestions - the dropdown is editable, any other name works.
#: Short names (haiku / flash / pro) always point at the newest model.
MODELS = {
    # small, multilingual, fast enough next to VRChat on one GPU
    METHOD_OLLAMA: ["gemma3:4b", "qwen3:4b", "llama3.2:3b",
                    "gemma3:12b", "aya-expanse:8b"],
    METHOD_CLAUDE: ["haiku", "sonnet", "opus"],
    METHOD_GEMINI: ["flash", "flash-lite", "pro"],
    # luna = fast (ideal for short chat lines), terra / sol = stronger
    METHOD_CHATGPT: ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
}
MODEL_KEYS = {m: f"stt_{m}_model" for m in AI_METHODS}

DEFAULTS = {
    "stt_ai_ollama_model": "gemma3:4b",
    "stt_ai_claude_model": "haiku",
    "stt_ai_gemini_model": "flash",
    "stt_ai_chatgpt_model": "gpt-5.6-luna",
    "stt_ai_custom_model": "",
    "stt_ai_ollama_url": "",       # "" = http://127.0.0.1:11434
    "stt_ai_custom_cmd": "",
}

#: a chat line has to arrive while the conversation is still going
TIMEOUT = 60
OLLAMA_TIMEOUT = 90      # the first request loads the model into VRAM

CUSTOM_EXAMPLE = (
    "# Example: any OpenAI-compatible server (LM Studio, llama.cpp,\n"
    "# vLLM, Ollama, ...). {prompt} = the finished request, {model} =\n"
    "# the model field below. A plain command works too, e.g.\n"
    "#   ollama run {model} {prompt}\n"
    "# response: choices[0].message.content\n"
    "curl http://localhost:1234/v1/chat/completions \\\n"
    "  -H \"Content-Type: application/json\" \\\n"
    "  -d '{\"model\": \"{model}\", \"messages\": [{\"role\": \"user\", "
    "\"content\": \"{prompt}\"}]}'\n")

_NAMES = {"de": "German", "en": "English", "fr": "French",
          "es": "Spanish", "it": "Italian", "pt": "Portuguese",
          "pt-br": "Brazilian Portuguese", "nl": "Dutch", "pl": "Polish",
          "ru": "Russian", "uk": "Ukrainian", "tr": "Turkish",
          "ja": "Japanese", "ko": "Korean", "zh": "Chinese (Simplified)",
          "zh-cn": "Chinese (Simplified)", "zh-tw": "Chinese (Traditional)",
          "ar": "Arabic", "sv": "Swedish", "cs": "Czech", "fi": "Finnish",
          "da": "Danish", "no": "Norwegian", "hu": "Hungarian",
          "el": "Greek", "hi": "Hindi", "id": "Indonesian", "th": "Thai",
          "vi": "Vietnamese"}

_CFG: dict = {}


class AIError(Exception):
    pass


def is_ai(method: str) -> bool:
    return method in AI_METHODS


def use_config(cfg: dict):
    """The window's config dict (kept by reference, so changes apply
    live)."""
    global _CFG
    _CFG = cfg if isinstance(cfg, dict) else {}


def setting(key: str) -> str:
    val = _CFG.get(key)
    if isinstance(val, str) and val.strip():
        return val.strip()
    return DEFAULTS.get(key, "")


def model_of(method: str) -> str:
    key = MODEL_KEYS.get(method)
    return setting(key) if key else ""


# ----------------------------------------------------------- programs
def find_binary(name: str) -> str | None:
    """PATH first, then the places the install buttons use - started
    from the app menu, ~/.local/bin is often missing from PATH."""
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    if IS_WINDOWS:
        folders = [Path(os.environ.get("APPDATA", home)) / "npm",
                   home / ".local" / "bin",
                   Path(os.environ.get("LOCALAPPDATA", home))
                   / "Programs" / "Ollama"]
        names = [f"{name}.cmd", f"{name}.exe", name]
    else:
        folders = [NPM_PREFIX / "bin", home / ".npm-global" / "bin",
                   Path("/usr/local/bin")]
        names = [name]
    for folder in folders:
        for n in names:
            p = folder / n
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


def installed(method: str) -> bool:
    binary = BINARIES.get(method)
    return binary is not None and find_binary(binary) is not None


_LOGIN_FILES = {METHOD_CLAUDE: [".claude/.credentials.json"],
                METHOD_GEMINI: [".gemini/oauth_creds.json"],
                METHOD_CHATGPT: [".codex/auth.json"]}
_LOGIN_ENV = {METHOD_CLAUDE: ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
                              "ANTHROPIC_AUTH_TOKEN"],
              METHOD_GEMINI: ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
              METHOD_CHATGPT: ["OPENAI_API_KEY"]}
_LOGIN_HINTS = ("/login", "invalid api key", "not logged in",
                "please log in", "please login", "codex login",
                "authentication required", "native binary not installed")


def logged_in(method: str) -> bool | None:
    """True = logged in, False = not, None = cannot tell (Claude on
    macOS/Windows and Codex may keep the login in the keyring)."""
    if any(os.environ.get(v) for v in _LOGIN_ENV.get(method, [])):
        return True
    if any((Path.home() / f).is_file() for f in _LOGIN_FILES.get(method, [])):
        return True
    if method == METHOD_GEMINI:
        g = Path.home() / ".gemini"
        try:
            if "GEMINI_API_KEY" in (g / ".env").read_text(encoding="utf-8"):
                return True
        except OSError:
            pass
        try:
            text = (g / "settings.json").read_text(encoding="utf-8")
            if "selectedType" in text or "selectedAuthType" in text:
                return True
        except OSError:
            pass
        return False
    return None if (method == METHOD_CHATGPT or IS_WINDOWS) else False


def _distro_ids() -> list[str]:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return []
    ids = []
    for line in text.splitlines():
        k, _, v = line.partition("=")
        if k in ("ID", "ID_LIKE"):
            ids += v.strip().strip('"').lower().split()
    return ids


def _gpu_vendor() -> str:
    found = set()
    for vendor in Path("/sys/class/drm").glob("card*/device/vendor"):
        try:
            v = vendor.read_text().strip().lower()
        except OSError:
            continue
        found.add({"0x10de": "nvidia", "0x1002": "amd"}.get(v, ""))
    return "nvidia" if "nvidia" in found else "amd" if "amd" in found else ""


def install_command(method: str) -> str | None:
    """Shell command for the install button (runs in a terminal, so
    sudo can ask there). None = no command - open the download page."""
    if method == METHOD_OLLAMA:
        if IS_WINDOWS:
            return None
        ids = _distro_ids()
        if any(i.startswith(n) for i in ids
               for n in ("arch", "cachyos", "endeavouros", "manjaro")):
            pkg = {"nvidia": "ollama-cuda", "amd": "ollama-rocm"}.get(
                _gpu_vendor(), "ollama")
            return (f"sudo pacman -S --needed {pkg} && "
                    f"sudo systemctl enable --now ollama")
        return OLLAMA_SCRIPT     # sets the service up by itself
    if method == METHOD_CLAUDE:
        if IS_WINDOWS:
            return f'powershell -NoExit -Command "{CLAUDE_INSTALLER_WIN}"'
        return CLAUDE_INSTALLER
    pkg = NPM_PACKAGES.get(method)
    if not pkg:
        return None
    if IS_WINDOWS:
        return f"npm install -g {pkg}"
    return f"npm install -g --prefix ~/.local {pkg}"


def needs_npm(method: str) -> bool:
    return method in (METHOD_GEMINI, METHOD_CHATGPT)


# ------------------------------------------ v1.6.6: install in the app
# Like LinuxVR-ViewShot: the install button runs the steps itself
# (QProcess in the UI) instead of opening a terminal. npm packages go to
# ~/.local (no sudo); if npm itself is missing it is installed first
# through pkexec, which asks for the password in a normal window.
#: (os-release ids, package manager, install argv) - pkexec is put in
#: front by pkexec_install_argv()
_PKG_MANAGERS = [
    (("arch", "cachyos", "endeavouros", "manjaro"), "pacman",
     ["pacman", "-S", "--needed", "--noconfirm"]),
    (("fedora", "nobara", "bazzite", "rhel"), "dnf", ["dnf", "install", "-y"]),
    (("debian", "ubuntu", "linuxmint", "pop"), "apt-get",
     ["apt-get", "install", "-y"]),
    (("opensuse", "suse"), "zypper", ["zypper", "--non-interactive",
                                      "install"]),
]
_PKG_NAMES = {("dnf", "npm"): "nodejs-npm"}


def _pkg_manager(ids=None):
    ids = _distro_ids() if ids is None else ids
    for names, binary, cmd in _PKG_MANAGERS:
        if any(i.startswith(n) for i in ids for n in names):
            return binary, cmd
    for _names, binary, cmd in _PKG_MANAGERS:
        if shutil.which(binary):
            return binary, cmd
    return None


def pkexec_install_argv(package: str, ids=None) -> list[str] | None:
    """["pkexec", "/usr/bin/pacman", "-S", ..., package] or None when
    that cannot work (Windows, no pkexec, rpm-ostree, unknown distro)."""
    if IS_WINDOWS or not shutil.which("pkexec"):
        return None
    if Path("/run/ostree-booted").exists():
        return None
    found = _pkg_manager(ids)
    if found is None:
        return None
    binary, cmd = found
    exe = shutil.which(binary)
    if not exe:
        return None
    return ["pkexec", exe] + cmd[1:] + [_PKG_NAMES.get((binary, package),
                                                       package)]


def npm_install_argv(method: str) -> list[str] | None:
    """npm install into ~/.local (no sudo). --include=optional: without
    it Codex & co. miss their actual program on some npm setups."""
    npm = shutil.which("npm")
    pkg = NPM_PACKAGES.get(method)
    if npm is None or pkg is None:
        return None
    return [npm, "install", "-g", "--prefix", str(NPM_PREFIX),
            "--include=optional", pkg]


def can_install_in_app(method: str) -> bool:
    """True when the install button can do it without a terminal
    (Linux, and npm present or installable through pkexec). Ollama
    needs a system service, so it keeps the terminal."""
    if IS_WINDOWS or method not in CLI_METHODS:
        return False
    if method == METHOD_CLAUDE and shutil.which("curl"):
        return True
    return bool(shutil.which("npm") or pkexec_install_argv("npm"))


def install_steps(method: str) -> list:
    """The steps of the install button, each a function that returns
    an argv list (built only when it runs, because npm may only exist
    after the step before). An argv of None = step not possible."""
    steps = []
    if method == METHOD_CLAUDE and shutil.which("curl"):
        # official installer - own program in ~/.local/bin, no npm
        return [lambda: ["bash", "-c", CLAUDE_INSTALLER]]
    if method in NPM_PACKAGES:
        if not shutil.which("npm"):
            steps.append(lambda: pkexec_install_argv("npm"))
        steps.append(lambda: npm_install_argv(method))
    return steps


def configured(method: str) -> bool:
    """Set up = usable right now: program installed (Ollama: or an own
    server URL), Custom AI: a command entered. Only those are offered
    in the To Text dropdown - like the Main page in LinuxVR-ViewShot."""
    if method == METHOD_AI_CUSTOM:
        return bool(setting("stt_ai_custom_cmd").strip())
    if method == METHOD_OLLAMA:
        return installed(method) or bool(
            (_CFG.get("stt_ai_ollama_url") or "").strip())
    return installed(method)


def run_in_terminal(command: str | list) -> tuple[bool, str]:
    """Opens a terminal window running `command` (a shell string or an
    argv list). The window stays open afterwards so errors can be read.
    Returns (ok, message)."""
    if isinstance(command, list):
        shell = " ".join(shlex.quote(p) for p in command) \
            if not IS_WINDOWS else subprocess.list2cmdline(command)
    else:
        shell = command
    try:
        if IS_WINDOWS:
            subprocess.Popen(f'cmd /c start "" cmd /k {shell}',
                             cwd=str(Path.home()))
            return True, ""
        from core.proclaunch import find_terminal
        prefix = find_terminal()
        if prefix is None:
            return False, ("no terminal found – run it yourself:  "
                           + shell)
        script = (f"{shell}; echo; echo '[finished – press Enter]'; "
                  f"read _")
        # home folder, not the app folder: the AI CLIs treat the start
        # folder as their workspace
        subprocess.Popen(prefix + ["sh", "-c", script],
                         start_new_session=True, cwd=str(Path.home()))
    except OSError as e:
        return False, str(e)
    return True, ""


def login_command(method: str) -> list[str] | None:
    parts = LOGIN_COMMANDS.get(method)
    if not parts:
        return None
    exe = find_binary(parts[0])
    return [exe] + parts[1:] if exe else None


# ------------------------------------------------------------- Ollama
def ollama_url() -> str:
    return (setting("stt_ai_ollama_url") or DEFAULT_OLLAMA_URL).rstrip("/")


def _ollama_request(path, payload=None, timeout=5.0):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        ollama_url() + path, data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST")
    return urllib.request.urlopen(req, timeout=timeout)


def ollama_running(timeout: float = 0.6) -> bool:
    try:
        with _ollama_request("/api/version", timeout=timeout):
            return True
    except Exception:      # noqa: BLE001
        return False


def ollama_models(timeout: float = 1.0) -> list[str]:
    """Installed models ([] when Ollama is not running)."""
    try:
        with _ollama_request("/api/tags", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:      # noqa: BLE001
        return []
    return sorted(m.get("name", "") for m in data.get("models", [])
                  if m.get("name"))


def start_ollama(log_path=None) -> tuple[bool, str]:
    """`ollama serve` in the background, detached from the app."""
    exe = find_binary("ollama")
    if not exe:
        return False, "ollama is not installed"
    out = subprocess.DEVNULL
    handle = None
    try:
        if log_path is not None:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            handle = open(log_path, "wb")
            out = handle
        subprocess.Popen([exe, "serve"], stdout=out,
                         stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL,
                         **subprocess_flags(new_group=True))
    except OSError as e:
        return False, str(e)
    finally:
        if handle is not None:
            handle.close()
    return True, ""


def models_for(method: str) -> list[str]:
    """Dropdown entries; for Ollama the installed models come first."""
    if method == METHOD_OLLAMA:
        have = ollama_models()
        return have + [m for m in MODELS[METHOD_OLLAMA] if m not in have]
    return list(MODELS.get(method, []))


# ------------------------------------------------------------- prompt
def lang_name(code: str) -> str:
    low = (code or "").strip().lower()
    return _NAMES.get(low) or _NAMES.get(low.split("-")[0]) or code


def make_prompt(text: str, source: str, target: str) -> str:
    src = lang_name(source) if source and source != "auto" else ""
    frm = f"from {src} " if src else ""
    return (f"Translate the following VRChat chat message {frm}into "
            f"{lang_name(target)}. Keep the tone, slang, names and "
            "emojis. Reply with the translation ONLY – no "
            "explanation, no quotes, no notes, no Markdown. Answer "
            "immediately: do NOT use any tools, do NOT search the web, "
            "do NOT read files.\n\nMessage:\n" + text)


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def clean_answer(out: str, text: str = "") -> str:
    """Colour codes, <think> blocks and quotes around the answer off."""
    out = _THINK.sub("", _ANSI.sub("", out or "")).strip()
    if len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'“«" \
            and not (text.startswith(out[0])):
        out = out[1:-1].strip()
    if len(out) >= 2 and out[0] in "“„«" \
            and out[-1] in "”“»":
        out = out[1:-1].strip()
    return out


# ---------------------------------------------------------- translate
def _ollama(text, source, target) -> str:
    model = model_of(METHOD_OLLAMA)
    payload = {"model": model, "prompt": make_prompt(text, source, target),
               "stream": False, "keep_alive": "5m",
               "options": {"temperature": 0.2}}
    try:
        with _ollama_request("/api/generate", payload,
                             timeout=OLLAMA_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 404 or "not found" in body.lower():
            raise AIError(f"Ollama: model “{model}” is not "
                          f"downloaded – press “Download "
                          f"model” (ollama pull {model})") from None
        raise AIError(f"Ollama: HTTP {e.code} {body[:160]}") from None
    except urllib.error.URLError as e:
        raise AIError(f"Ollama not reachable at {ollama_url()} – is "
                      f"it running? ({e.reason})") from None
    except TimeoutError:
        raise AIError(f"Ollama took longer than {OLLAMA_TIMEOUT} s") \
            from None
    if data.get("error"):
        raise AIError(f"Ollama: {data['error']}")
    return data.get("response", "")


def build_command(method, prompt, model):
    """(argv, stdin) for the CLI services."""
    if method == METHOD_CLAUDE:
        argv = ["claude", "-p", prompt]
        if model:
            argv += ["--model", model]
        return argv, None
    if method == METHOD_GEMINI:
        argv = ["gemini"] + (["-m", model] if model else [])
        return argv + ["-p", prompt, "--output-format", "json"], None
    if method == METHOD_CHATGPT:
        argv = ["codex", "exec", "--skip-git-repo-check",
                "--sandbox", "read-only",
                "-c", "model_reasoning_effort=low"]
        if model:
            argv += ["-m", model]
        return argv + ["-"], prompt       # "-" = prompt on stdin
    raise AIError(f"unknown AI service {method}")


def _gemini_response(output: str) -> str:
    start = output.find("{")
    try:
        data = json.loads(output[start:]) if start >= 0 else None
    except ValueError:
        return output
    if not isinstance(data, dict):
        return output
    if data.get("error") and not data.get("response"):
        err = data["error"]
        raise AIError("Gemini: " + str(err.get("message")
                                       if isinstance(err, dict) else err))
    return data.get("response") or ""


def _run(argv, stdin, cwd, env, timeout):
    """subprocess.run, but a timeout kills the WHOLE process group -
    Gemini/Codex start children that would otherwise keep running."""
    import signal
    proc = subprocess.Popen(
        argv, stdin=subprocess.PIPE if stdin is not None
        else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", cwd=cwd, env=env,
        **subprocess_flags(new_group=True))
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/T", "/PID",
                                str(proc.pid)], capture_output=True,
                               timeout=10, **subprocess_flags())
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except Exception:      # noqa: BLE001
            proc.kill()
        raise AIError(f"{Path(argv[0]).stem} took longer than "
                      f"{timeout} s") from None
    return proc.returncode, out or "", err or ""


def _cli(method, text, source, target) -> str:
    prompt = make_prompt(text, source, target)
    argv, stdin = build_command(method, prompt, model_of(method))
    exe = find_binary(argv[0])
    if not exe:
        raise AIError(f"{argv[0]} is not installed – press "
                      f"“Install” in the Translation card")
    argv = [exe] + argv[1:]
    name = BINARIES[method]
    # an empty folder as workspace: the AI sees no files of yours
    with tempfile.TemporaryDirectory(prefix="dreamchatbox-ai-") as tmp:
        last_msg = None
        if method == METHOD_CHATGPT:
            # Codex prints its progress on stdout too - have the final
            # answer written to a file instead
            last_msg = Path(tmp) / "answer.txt"
            argv = argv[:2] + ["--output-last-message", str(last_msg)] \
                + argv[2:]
        # Gemini only runs in "trusted" folders without a terminal
        env = dict(os.environ, GEMINI_CLI_TRUST_WORKSPACE="true",
                   NO_COLOR="1")
        if not IS_WINDOWS:
            local_bin = str(NPM_PREFIX / "bin")
            if local_bin not in env.get("PATH", ""):
                env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
        try:
            code, out, err = _run(argv, stdin, tmp, env, TIMEOUT)
        except FileNotFoundError:
            raise AIError(f"{name} not found") from None
        if code != 0:
            lines = _ANSI.sub("", err or out).strip().splitlines()
            msg = lines[-1] if lines else ""
            if any(h in (err + out).lower() for h in _LOGIN_HINTS):
                raise AIError(f"{name}: not logged in – press "
                              f"“Log in” ({msg[:120]})")
            raise AIError(f"{name} exited with {code}"
                          + (f": {msg[:200]}" if msg else ""))
        if last_msg is not None and last_msg.is_file():
            out = last_msg.read_text(encoding="utf-8", errors="replace")
        if method == METHOD_GEMINI:
            out = _gemini_response(out)
    low = (out or "").lower()
    if len(low) < 300 and any(h in low for h in _LOGIN_HINTS):
        raise AIError(f"{name}: not logged in – press “Log "
                      f"in” ({out.strip().splitlines()[0][:120]})")
    return out


def _custom(text, source, target) -> str:
    from core import custom_translator as ct
    snippet = setting("stt_ai_custom_cmd")
    if not snippet:
        raise AIError("Custom AI: no command set")
    snippet = (snippet.replace("{prompt}", "{text}")
               .replace("{model}", model_of(METHOD_AI_CUSTOM)))
    try:
        return ct.translate(snippet, "", make_prompt(text, source, target),
                            source or "auto", target, timeout=TIMEOUT) or ""
    except ct.CustomError as e:
        raise AIError(f"Custom AI: {e}") from None


def translate(method: str, text: str, source: str, target: str) -> str:
    """The translation, or AIError with a readable reason."""
    if method == METHOD_OLLAMA:
        out = _ollama(text, source, target)
    elif method in CLI_METHODS:
        out = _cli(method, text, source, target)
    elif method == METHOD_AI_CUSTOM:
        out = _custom(text, source, target)
    else:
        raise AIError(f"unknown AI service {method}")
    out = clean_answer(out, text)
    if not out:
        raise AIError("the AI answered nothing")
    return out
