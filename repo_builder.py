# -*- coding: utf-8 -*-
"""Интерактивный генератор Cydia-репозитория."""
import os
import sys
import io
import json
import tarfile
import hashlib
import bz2
import gzip

# Настройка кодировки вывода для корректного отображения в Windows CMD
try:
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "config.json")
DEBS_DIR = os.path.join(ROOT, "debs")
os.makedirs(DEBS_DIR, exist_ok=True)

# 1. Загрузка существующих настроек (если уже есть)
current = {
    "name": "Sasha Repo",
    "description": "Твики и приложения для iOS 6",
    "url": "https://creepyfaiz.github.io/cydia-repo/",
    "author": "Alexander F."
}

if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
            if isinstance(saved, dict):
                current.update(saved)
    except Exception:
        pass

def prompt(text, default=""):
    try:
        val = input(f"{text} [{default}]: ").strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        print()
        return default

print("========================================")
print("     Настройка Cydia-репозитория        ")
print("========================================")
print("(Нажмите Enter, чтобы оставить значение в скобках)\n")

# Интерактивный опрос
current["name"] = prompt("1. Название репозитория", current["name"])
url_val = prompt("2. Ссылка на сайт/хостинг", current["url"])
current["url"] = url_val.rstrip("/") + "/"
current["description"] = prompt("3. Описание", current["description"])
current["author"] = prompt("4. Имя автора", current["author"])

# Сохраняем обновлённый конфиг
with open(CONFIG_FILE, "w", encoding="utf-8") as f:
    json.dump(current, f, ensure_ascii=False, indent=2)

print("\n[+] Настройки сохранены в config.json")
print("----------------------------------------")
print("Сканирование папки debs/...")

# 2. Чтение control из .deb
def parse_deb(deb_path):
    with open(deb_path, "rb") as f:
        if f.read(8) != b"!<arch>\n":
            return None, {}
        while True:
            h = f.read(60)
            if len(h) < 60:
                break
            name = h[:16].strip().decode("ascii", "ignore")
            size = int(h[48:58].strip())
            data = f.read(size)
            if size % 2:
                f.read(1)
            if name.startswith("control.tar"):
                with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
                    for m in tar.getmembers():
                        if m.name in ("control", "./control"):
                            raw = tar.extractfile(m).read().decode("utf-8", "ignore").strip()
                            fields = {}
                            for line in raw.splitlines():
                                if ":" in line and not line.startswith(" "):
                                    k, v = line.split(":", 1)
                                    fields[k.strip()] = v.strip()
                            return raw, fields
    return None, {}

# 3. Обработка всех твиков
entries, html_items = [], []
deb_files = [f for f in sorted(os.listdir(DEBS_DIR)) if f.endswith(".deb")]

if not deb_files:
    print("[!] В папке debs/ пока нет файлов .deb.")
    print("    Положите файлы твиков в папку cydia-repo/debs/ и запустите скрипт снова.")
else:
    for fname in deb_files:
        path = os.path.join(DEBS_DIR, fname)
        data = open(path, "rb").read()
        raw_ctrl, meta = parse_deb(path)
        if not raw_ctrl:
            print(f"[-] Ошибка чтения: {fname}")
            continue

        entries.append(
            f"{raw_ctrl}\nFilename: debs/{fname}\nSize: {len(data)}\n"
            f"MD5sum: {hashlib.md5(data).hexdigest()}\n"
            f"SHA256: {hashlib.sha256(data).hexdigest()}\n"
        )
        tweak_name = meta.get("Name", meta.get("Package", fname))
        tweak_ver = meta.get("Version", "1.0")
        tweak_desc = meta.get("Description", "Нет описания")
        html_items.append({
            "name": tweak_name,
            "version": tweak_ver,
            "desc": tweak_desc,
            "file": f"debs/{fname}"
        })
        print(f"[+] Добавлен твик: {tweak_name} (версия {tweak_ver})")

# 4. Запись индексов Packages, Packages.bz2, Packages.gz
pkg_data = ("\n\n".join(entries) + ("\n" if entries else "")).encode("utf-8")
open(os.path.join(ROOT, "Packages"), "wb").write(pkg_data)
open(os.path.join(ROOT, "Packages.bz2"), "wb").write(bz2.compress(pkg_data))
open(os.path.join(ROOT, "Packages.gz"), "wb").write(gzip.compress(pkg_data))

# 5. Запись Release
release_text = (
    f"Origin: {current['name']}\n"
    f"Label: {current['name']}\n"
    f"Suite: stable\n"
    f"Version: 1.0\n"
    f"Codename: ios\n"
    f"Architectures: iphoneos-arm\n"
    f"Components: main\n"
    f"Description: {current['description']}\n"
)
open(os.path.join(ROOT, "Release"), "w", encoding="utf-8").write(release_text)

# 6. Генерация страницы index.html
cydia_url = f"cydia://url/https://cydia.saurik.com/api/share#?source={current['url']}"
items_html = "".join([
    f'<div class="card"><b>{it["name"]}</b> <span class="ver">{it["version"]}</span>'
    f'<p>{it["desc"]}</p><a class="deb-link" href="{it["file"]}">Скачать .deb</a></div>'
    for it in html_items
]) or '<p class="muted">В репозитории пока нет пакетов. Добавьте файлы в папку debs/.</p>'

html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{current['name']}</title>
  <style>
    body{{margin:0;padding:16px;font:15px/1.4 system-ui,-apple-system,sans-serif;background:#edf0f5;color:#222}}
    .wrap{{max-width:540px;margin:0 auto}}
    h1{{font-size:22px;margin:0 0 6px}}
    p{{margin:0 0 12px;color:#555}}
    .btn{{display:block;padding:12px;text-align:center;background:#007aff;color:#fff;border-radius:10px;text-decoration:none;font-weight:600;margin:14px 0 20px}}
    .card{{background:#fff;border-radius:10px;padding:12px 14px;margin-bottom:10px;border:1px solid #dcdfe6;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
    .ver{{font-size:12px;background:#e5f1ff;color:#007aff;padding:2px 6px;border-radius:6px;float:right}}
    .deb-link{{font-size:13px;color:#007aff;text-decoration:none}}
    .muted{{color:#888;text-align:center;padding:20px 0}}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{current['name']}</h1>
    <p>{current['description']}</p>
    <a class="btn" href="{cydia_url}">Добавить в Cydia</a>
    <h2>Доступные твики ({len(html_items)})</h2>
    {items_html}
  </div>
</body>
</html>"""
open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(html)

print("----------------------------------------")
print(f"[+] Репозиторий успешно собран! Всего твиков: {len(html_items)}")
print(f"[+] Созданы файлы: Release, Packages, Packages.bz2, index.html")

# 7. Запрос на отправку в git (если репозиторий под git)
if os.path.exists(os.path.join(ROOT, ".git")):
    push_answer = prompt("\nОтправить изменения в Git (git push)? (y/n)", "n").lower()
    if push_answer in ('y', 'yes', 'да', 'д'):
        commit_msg = prompt("Текст коммита", "Update repo")
        os.system(f'git add . && git commit -m "{commit_msg}" && git push')
        print("[+] Изменения отправлены на GitHub!")
