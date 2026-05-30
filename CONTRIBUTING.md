# Контрибьютинг в KaproVPN (desktop)

Спасибо за интерес! Это десктопный клиент: **Python 3.10+ / PySide6** поверх
**Xray-core**, со split-routing по настраиваемому RU-direct-списку.

> Android-клиент живёт в отдельном репозитории. Здесь — только десктоп
> (Windows / macOS / Linux). Общий между ними только
> `kapro_vpn/data/default_sites.json` (источник правды для split-routing).

## Быстрый старт (из исходников)

```bash
git clone https://github.com/fafnirov/KaproVPN.git
cd KaproVPN
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m kapro_vpn.main
```

TUN-режим требует прав администратора/root; HTTP-прокси режим — нет.
Бинарники Xray / tun2socks / hysteria клиент докачивает сам при первом
подключении (с зеркала `kaprovpn.pro/files`, фолбэк — GitHub Releases).

## Тесты

Перед каждым PR прогоняй smoke-набор — он покрывает импорт всех модулей,
генерацию xray-конфига, парсинг подписок, leak-test, сборку GUI и т.д.:

```bash
python -m kapro_vpn.scripts.smoke_test
# На headless-машине (CI) без дисплея:
QT_QPA_PLATFORM=offscreen python -m kapro_vpn.scripts.smoke_test
```

CI гейтит сборку релиза этим же набором — красный smoke = нет билда.

## Сборка инсталлятора (Windows)

```bash
pyinstaller KaproVPN.spec          # -> dist/KaproVPN.exe
pyinstaller KaproVPN-Setup.spec    # -> dist/KaproVPN-Setup.exe (скачивает KaproVPN.exe из релиза при установке)
```

## Структура

- `kapro_vpn/core/` — логика без UI: контроллер подключения, генерация
  xray-конфига, маршруты/TUN, подписки, leak-test, защита от утечек.
- `kapro_vpn/gui/` — PySide6-интерфейс.
- `kapro_vpn/scripts/smoke_test.py` — весь smoke-набор.
- `installer/` — брендированный установщик (тоже PySide6).
- `server-setup/` — скрипты зеркала бинарников на VPS.

## Релиз

1. Внести фикс/фичу.
2. Добавить запись в начало секции Desktop в `CHANGELOG.md` —
   **верхняя запись = тело релиза** на странице Releases.
3. Поднять `__version__` в `kapro_vpn/__init__.py`.
4. Commit → tag `vX.Y.Z` → push тега. CI соберёт билды на 3 ОС
   (после прохождения smoke) и опубликует релиз.

## Договорённости

- Smoke обязан проходить.
- Не коммить абсолютные пути с именем пользователя ОС.
- Пользовательские строки — на русском (основная аудитория), технические
  комментарии — как удобно.
- Лицензия проекта — **GPL-3.0**; вклад принимается на этих же условиях.
