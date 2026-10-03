# -*- coding: utf-8 -*-
"""
Максимально надежный автоматический сборщик Cydia-репозитория.
Работает на Windows/macOS/Linux без внешних зависимостей.
"""
import os
import sys
import re
import io
import json
import tarfile
import hashlib
import bz2
import gzip
import subprocess

# Настройка безопасной кодировки вывода для Windows CMD
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.abspath(__file__)) or "."
CONFIG_FILE = os.path.join(ROOT, "config.json")
DEBS_DIR = os.path.join(ROOT, "debs")
os.makedirs(DEBS_DIR, exist_ok=True)

def prompt(text, default=""):
    try:
        val = input(f"{text} [{default}]: " if default else f"{text}: ").strip()
        return val if val else default
    except (EOFError, KeyboardInterrupt):
        print()
        return default

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, cwd=ROOT)

def main():
    print("\n" + "=" * 60)
    print("       АВТОМАТИЧЕСКИЙ СБОРЩИК CYDIA РЕПОЗИТОРИЯ")
    print("=" * 60)
    print("Подсказка:")
    print(" • Все .deb файлы твиков кладите в папку: debs/")
    print(" • Репозиторий на GitHub создавайте ПУСТЫМ (без README)")
    print("=" * 60 + "\n")

    # 1. Загрузка существующих настроек
    config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            config = {}

    # Если в config.json ссылки нет, пробуем подтянуть из git remote
    if not config.get("github_url"):
        try:
            res_url = subprocess.run("git config --get remote.origin.url", shell=True, cwd=ROOT, capture_output=True, text=True)
            remote_val = res_url.stdout.strip()
            if remote_val:
                config["github_url"] = remote_val
                match_init = re.search(r"github\.com[/:]([^/]+)/([^/\.]+)", remote_val)
                if match_init:
                    u, r = match_init.group(1), match_init.group(2)
                    config.setdefault("name", r)
                    config.setdefault("url", f"https://{u}.github.io/{r}/")
        except Exception:
            pass

    reconfigure = False
    if config.get("github_url"):
        print("[+] Найдена сохранённая конфигурация репозитория:")
        print(f"    Репозиторий : {config.get('github_url')}")
        print(f"    Название    : {config.get('name', 'Cydia Repo')}")
        print(f"    Описание    : {config.get('description', 'Твики')}")
        print(f"    Для Cydia   : {config.get('url', '')}\n")
        print("Нажмите [Enter] для быстрой сборки и отправки")
        choice = prompt("или введите 1, чтобы изменить настройки", "enter")
        if choice.strip() == "1":
            reconfigure = True
    else:
        reconfigure = True

    if reconfigure:
        current_gh = config.get("github_url", "")
        print("\nВведите ссылку на ваш репозиторий GitHub:")
        print("Пример: https://github.com/creepyfaiz/testrepo\n")
        github_url = prompt("Ссылка на GitHub", current_gh).strip()
        if not github_url:
            print("[-] Ошибка: ссылка на GitHub не указана.")
            return

        match = re.search(r"github\.com[/:]([^/]+)/([^/\.]+)", github_url)
        if match:
            user, repo_name = match.group(1), match.group(2)
            default_pages_url = f"https://{user}.github.io/{repo_name}/"
        else:
            user, repo_name = "User", "repo"
            default_pages_url = "https://example.github.io/repo/"

        repo_title = prompt("Название репозитория", config.get("name", repo_name))
        repo_desc = prompt("Описание репозитория", config.get("description", "Твики для iOS"))
        pages_url = default_pages_url

        config.update({
            "name": repo_title,
            "description": repo_desc,
            "url": pages_url.rstrip("/") + "/",
            "github_url": github_url
        })

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print("\n[+] Настройки сохранены в config.json!")
    else:
        github_url = config.get("github_url", "")
        match = re.search(r"github\.com[/:]([^/]+)/([^/\.]+)", github_url)
        if match:
            user, repo_name = match.group(1), match.group(2)
        else:
            user, repo_name = "User", "repo"

    # 2. Функция чтения метаданных из .deb
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
                                clean_lines = []
                                for line in raw.splitlines():
                                    line_s = line.rstrip()
                                    if not line_s:
                                        continue
                                    if line_s.startswith(" ") or line_s.startswith("\t"):
                                        clean_lines.append(line_s)
                                    elif ":" in line_s:
                                        k, v = line_s.split(":", 1)
                                        if v.strip():  # игнорируем пустые поля, ломающие Cydia
                                            clean_lines.append(f"{k.strip()}: {v.strip()}")
                                            fields[k.strip()] = v.strip()
                                raw_cleaned = "\n".join(clean_lines)
                                return raw_cleaned, fields
        return None, {}

    # 3. Сканирование папки debs/
    print("\n[1/3] Поиск твиков в папке debs/...")
    entries, html_items = [], []
    debs = [f for f in sorted(os.listdir(DEBS_DIR)) if f.endswith(".deb")]

    if not debs:
        print("  -> В папке debs/ пока нет файлов .deb.")
        print("  -> Создаю основу репозитория (твики можно будет добавить позже).")
    else:
        for fname in debs:
            # Очистка имени файла от пробелов и скобок (Cydia не принимает пробелы в Filename)
            clean_fname = re.sub(r'[\s\(\)\[\]]', '_', fname)
            clean_fname = re.sub(r'_+', '_', clean_fname).replace('_.deb', '.deb')
            if clean_fname != fname:
                old_p = os.path.join(DEBS_DIR, fname)
                new_p = os.path.join(DEBS_DIR, clean_fname)
                try:
                    os.rename(old_p, new_p)
                    fname = clean_fname
                except Exception:
                    pass

            path = os.path.join(DEBS_DIR, fname)
            data = open(path, "rb").read()
            raw_ctrl, meta = parse_deb(path)
            if not raw_ctrl:
                print(f"  [-] Ошибка чтения файла: {fname}")
                continue

            entries.append(
                f"{raw_ctrl}\n"
                f"Filename: ./debs/{fname}\n"
                f"Size: {len(data)}\n"
                f"MD5sum: {hashlib.md5(data).hexdigest()}\n"
                f"SHA1: {hashlib.sha1(data).hexdigest()}\n"
                f"SHA256: {hashlib.sha256(data).hexdigest()}\n"
            )
            html_items.append({
                "name": meta.get("Name", meta.get("Package", fname)),
                "ver": meta.get("Version", "1.0"),
                "desc": meta.get("Description", "Нет описания"),
                "file": f"debs/{fname}"
            })
            print(f"  [+] Добавлен твик: {meta.get('Name', fname)} (версия {meta.get('Version', '1.0')})")

    # 4. Создание файлов для Cydia
    print("\n[2/3] Генерация индексов для Cydia...")
    pkg_data = ("\n\n".join(entries) + ("\n" if entries else "")).encode("utf-8")
    with open(os.path.join(ROOT, "Packages"), "wb") as f:
        f.write(pkg_data)
    with open(os.path.join(ROOT, "Packages.bz2"), "wb") as f:
        f.write(bz2.compress(pkg_data))
    with open(os.path.join(ROOT, "Packages.gz"), "wb") as f:
        f.write(gzip.compress(pkg_data))

    # Файл .nojekyll отключает обработку Jekyll на GitHub Pages
    with open(os.path.join(ROOT, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")

    release_content = (
        f"Origin: {config['name']}\nLabel: {config['name']}\nSuite: stable\n"
        f"Version: 1.0\nCodename: ios\nArchitectures: iphoneos-arm iphoneos-arm64\n"
        f"Components: main\nDescription: {config['description']}\n"
    )
    with open(os.path.join(ROOT, "Release"), "w", encoding="utf-8") as f:
        f.write(release_content)

    cydia_add = f"cydia://url/https://cydia.saurik.com/api/share#?source={config['url']}"
    sileo_add = f"sileo://source/{config['url']}"
    items_card = "".join([
        f'<div style="background:#fff;border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0;box-shadow:0 1px 3px rgba(0,0,0,0.05)">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
        f'<b style="font-size:16px">{x["name"]}</b> <span style="background:#007aff;color:#fff;padding:2px 8px;border-radius:12px;font-size:12px">{x["ver"]}</span></div>'
        f'<p style="color:#555;font-size:14px;margin:6px 0 10px">{x["desc"]}</p>'
        f'<a style="display:inline-block;background:#f0f2f5;color:#007aff;text-decoration:none;font-weight:600;font-size:13px;padding:6px 12px;border-radius:6px" href="{x["file"]}">Скачать .deb</a></div>'
        for x in html_items
    ]) or '<p style="color:#888;text-align:center;padding:20px 0">В репозитории пока нет пакетов. Добавьте файлы в папку debs/.</p>'

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{config['name']}</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;background:#edf0f5;padding:16px;max-width:520px;margin:0 auto;color:#222">
<div style="text-align:center;margin:18px 0 20px">
  <h1 style="margin:0 0 6px;font-size:24px">{config['name']}</h1>
  <p style="color:#666;margin:0;font-size:15px">{config['description']}</p>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
  <a href="{cydia_add}" style="display:block;background:linear-gradient(180deg,#8b5a2b,#654321);color:#fff;padding:12px 6px;text-align:center;text-decoration:none;border-radius:10px;font-weight:bold;font-size:14px">Добавить в Cydia</a>
  <a href="{sileo_add}" style="display:block;background:linear-gradient(180deg,#2997ff,#0071e3);color:#fff;padding:12px 6px;text-align:center;text-decoration:none;border-radius:10px;font-weight:bold;font-size:14px">Добавить в Sileo</a>
</div>

<div style="background:#fff;border:1px solid #ddd;border-radius:10px;padding:14px;margin-bottom:20px;font-size:13px;line-height:1.5;box-shadow:0 1px 3px rgba(0,0,0,0.05)">
  <b>📱 Как добавить в Cydia вручную:</b>
  <ol style="margin:6px 0 0 16px;padding:0">
    <li>Откройте Cydia на iPhone/iPad.</li>
    <li>Перейдите во вкладку <b>Источники</b> (Sources).</li>
    <li>Нажмите <b>Правка</b> (Edit) ➔ <b>Добавить</b> (Add).</li>
    <li>Введите адрес: <br><code style="background:#f4f4f4;padding:2px 6px;border-radius:4px;word-break:break-all;color:#007aff">{config['url']}</code></li>
  </ol>
</div>

<h3 style="margin:20px 0 10px;font-size:18px">Доступные пакеты ({len(html_items)}):</h3>
{items_card}
</body></html>"""
    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print("  [+] Файлы Packages, Packages.bz2, Release и index.html готовы.")

    # 5. Автоматическая отправка в GitHub
    print("\n[3/3] Подготовка и отправка в GitHub...")
    remote_url = github_url.rstrip("/") + ".git" if not github_url.endswith(".git") else github_url

    if not os.path.exists(os.path.join(ROOT, ".git")):
        run_cmd("git init")
        run_cmd("git branch -M main")
        run_cmd(f"git remote add origin {remote_url}")
    else:
        # Обновляем remote URL, если репозиторий уже был инициализирован
        run_cmd(f"git remote set-url origin {remote_url}")

    # Защита от ошибки "Author identity unknown"
    run_cmd('git config user.name "Cydia Builder"')
    run_cmd('git config user.email "cydia@local"')

    run_cmd("git add .")
    run_cmd('git commit -m "Update Cydia repository"')
    
    print("\nВыполняю отправку (git push)...")
    res = run_cmd("git push -u origin main")
    if res.returncode != 0:
        res = run_cmd("git push -u origin main --force")

    print("\n" + "=" * 62)
    if res.returncode == 0:
        print("[+] ВСЕ ФАЙЛЫ УСПЕШНО СОБРАНЫ И ОТПРАВЛЕНЫ НА GITHUB!")
        print("=" * 62)
        print("\n[ШАГ 1] ВКЛЮЧИТЕ GITHUB PAGES (ЕСЛИ ДЕЛАЕТЕ В ПЕРВЫЙ РАЗ):")
        if match:
            print(f"  1. Откройте ссылку:\n     https://github.com/{user}/{repo_name}/settings/pages")
            print("  2. В графе 'Branch' выберите 'main' (папка /root) и нажмите 'Save'.")
            print("  (Через 1-2 минуты сайт и репозиторий заработают!)")

        print("\n[ШАГ 2] КАК ДОБАВИТЬ РЕПОЗИТОРИЙ НА IPHONE / IPAD:")
        print(f"  Адрес вашего репозитория:\n  -> {config['url']}")
        print("\n  Способ А (В один клик через Safari):")
        print(f"    Откройте {config['url']} в браузере Safari на iPhone")
        print("    и нажмите большую кнопку 'Добавить в Cydia' (или Sileo).")
        print("\n  Способ Б (Вручную через Cydia):")
        print("    1. Откройте Cydia -> вкладка 'Источники' (Sources).")
        print("    2. Нажмите 'Правка' (Edit) -> 'Добавить' (Add).")
        print(f"    3. Введите адрес: {config['url']}")
        print("    4. Нажмите 'Добавить источник' и дождитесь обновления.")

        print("\n[КАК ДОБАВЛЯТЬ ИЛИ ОБНОВЛЯТЬ ТВКИ В БУДУЩЕМ]:")
        print("  1. Просто положите новый .deb файл в папку 'debs'.")
        print("  2. Запустите 'start.bat' снова.")
        print("  Скрипт автоматически обновит каталог и отправит изменения в GitHub!")
    else:
        print("[-] Ошибка отправки на GitHub.")
        print("    Возможные причины:")
        print("    1. Требуется авторизоваться в Git (GitHub Sign-in).")
        print("    2. У аккаунта нет прав на запись в этот репозиторий.")
        print("    3. В репозитории уже были другие файлы (он должен быть пустым).")
    print("=" * 62 + "\n")

if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        print(f"\n[-] Произошла непредвиденная ошибка: {err}")
    finally:
        try:
            input("Нажмите Enter для завершения...")
        except Exception:
            pass
