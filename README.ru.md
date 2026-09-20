<p align="center">
  <img src="assets/icon.png" width="128" alt="Логотип ModBridge">
</p>

# ModBridge

<p align="center">
  <a href="README.md">Read in English</a>
</p>

Десктопное приложение для поиска и скачивания модов Minecraft через API [Modrinth](https://modrinth.com),
а также для переноса данных между майнкрафт профилями любого лаунчера. Интерфейс на русском и английском.

## Скриншоты

![Поиск с успешными результатами](assets/screenshots/search.png)
![Перенос профилей перед запуском](assets/screenshots/transfer.png)
![Перенос профилей после успешного переноса](assets/screenshots/transfer_complete.png)

## Скачать

Готовые сборки публикуются на странице [Releases](https://github.com/WoolfinDev/ModBridge/releases):

- Windows: `ModBridge.exe` — скачать и запустить, установка не нужна.
- Linux: `ModBridge` — `chmod +x ModBridge && ./ModBridge`,
  либо `sh packaging/build_linux.sh --install` для ярлыка в меню.

Аккаунт и API-ключ не нужны — приложение использует публичный API Modrinth.

## Возможности

- **Поиск** — проверка списка модов под нужные версию Minecraft и загрузчик
  (`fabric`, `forge`, `neoforge`, `quilt`), скачивание одним кликом.
- **Импорт** — распознавание названий модов из папки с `.jar` (по хэшу Modrinth или метаданным внутри jar).
- **Перенос профилей** — копирование `mods`, `resourcepacks`, `config`, `shaderpacks`, `saves` и др.
  между профилями любого лаунчера (профили Modrinth App находятся автоматически,
  любую другую папку можно выбрать вручную). Моды докачиваются из Modrinth под целевую версию,
  перед переносом создаётся бэкап с кнопкой отката (хранятся последние 5 бэкапов,
  откат удаляет добавленные переносом файлы и восстанавливает перезаписанные).
- **RU/EN** — переключатель языка сверху справа, выбор сохраняется.

## Установка и запуск (из исходников)

Требуется Python 3.10–3.11 (`PySide6==6.5.2` в `requirements.txt`).

Windows:

```bash
pip install -r requirements.txt
python main.py
```

Linux (на Debian 12+ системный pip закрыт, поэтому через venv;
системные библиотеки ниже нужны для *запуска* PySide6):

```bash
sudo apt install python3-venv libgl1 libegl1 libfontconfig1 \
  libxkbcommon-x11-0 libdbus-1-3 libxcb-cursor0  # Debian/Ubuntu

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

## Сборка

Windows (PowerShell, рекомендуется):

```powershell
powershell -ExecutionPolicy Bypass -File packaging/build_windows.ps1
# -> dist/ModBridge.exe
```

Вручную:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name ModBridge `
  --icon assets/icon.ico `
  --add-data "modrinth_app/locales;modrinth_app/locales" `
  --add-data "assets;assets" `
  main.py
```

Linux:

```bash
sh packaging/build_linux.sh            # только собрать -> dist/ModBridge
sh packaging/build_linux.sh --install  # собрать + поставить в ~/.local
```

Переводы лежат в `modrinth_app/locales/` — их обязательно
подключать через `--add-data`, иначе сборка запустится без текстов.

## Куда сохраняются файлы

- Скачанные моды: `mods_<время>-<версия-mc>/` рядом с приложением при запуске из исходников,
  иначе в `Downloads` (под Windows папка выбирается автоматически).
- Настройки: `config.json` рядом с кодом при запуске из исходников,
  иначе `%LOCALAPPDATA%/ModBridge/config.json` (Windows)
  или `~/.local/share/ModBridge/config.json` (Linux). Не коммитится.
- Бэкапы переносов: `.transfer_backups/` (та же логика, что у настроек). Не коммитятся.

## Структура

```
main.py                  # точка входа
modrinth_app/
    app.py               # GUI (PySide6)
    api.py               # клиент Modrinth API
    resolver.py          # сопоставление модов с проектами Modrinth
    jar_metadata.py      # чтение метаданных из .jar
    localization.py      # загрузка переводов
    locales/             # ru.json, en.json
    constants.py         # тема, шрифты, правила переноса
    utils.py             # пути, безопасное скачивание, имена файлов
    _version.py          # единый источник версии приложения
    services/            # перенос, проверка, импорт, бэкапы
packaging/
    build_windows.ps1    # сборка под Windows
    build_linux.sh       # сборка под Linux + установка
    ModBridge.desktop    # ярлык для меню Linux
assets/                  # иконка + глифы интерфейса (коммитятся)
config.json              # настройки пользователя (не коммитится)
.transfer_backups/       # бэкапы переносов (не коммитятся)
```

## Лицензия

MIT — см. [LICENSE](LICENSE).
