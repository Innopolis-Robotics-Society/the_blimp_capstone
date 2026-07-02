# nlink_py — парсер UWB-протокола Nooploop LinkTrack (без ROS)

Python-пакет для чтения бинарного потока NLink с консоли LinkTrack P-A (или тега)
по USB/UART. Разбор потока делает **оригинальный C/C++-код Nooploop** — сабмодули
[`protocol_extracter`](https://github.com/nooploop-dev/protocol_extracter) (нарезка
потока на кадры) и [`nlink_unpack`](https://github.com/nooploop-dev/nlink_unpack)
(распаковка кадров в СИ), собранные в нативный модуль через pybind11. Поверх —
чтение порта (pyserial), JSON-over-UDP паблишер и CLI.

Поддержаны все кадры LinkTrack: `anchorframe0`, `tagframe0`, `nodeframe0`–`nodeframe6`.

## Сборка

Нужны: cmake ≥ 3.18, C/C++-компилятор, Python ≥ 3.9. Сабмодули должны быть
инициализированы:

```bash
git submodule update --init --recursive     # в корне the_blimp
cd uwb/nlink_py
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest                                       # golden-кадры из апстрим-тестов Nooploop
```

## CLI

```bash
# Живой поток с консоли P-A, JSON-lines в stdout + запись сырого потока
nlink-dump --port /dev/ttyUSB0 --baud 921600 --record flight.bin

# Стрим в дашборд по UDP (одна JSON-датаграмма на кадр)
nlink-dump --port /dev/ttyUSB0 --udp 127.0.0.1:9999 --quiet

# Отладка без железа: проигрывание записи
nlink-dump --replay flight.bin
```

Каждый кадр — JSON-объект с полями кадра плюс `frame_type` и `recv_time`
(unix-время приёма). Бинарные payload'ы data-transmission кадров
(`nodeframe0`/`nodeframe6`) кодируются hex-строкой.

## Библиотечный API

```python
from nlink_py import LinkTrackExtractor, SerialReader

extractor = LinkTrackExtractor()
extractor.set_callback(lambda frame_type, frame: print(frame_type, frame["pos_3d"]))
SerialReader("/dev/ttyUSB0", 921600).run(extractor.feed)
```

`frame` — dict, поля повторяют ROS-сообщения `nlink_parser` (`pos_3d`, `dis_arr`,
`nodes[]`, `voltage`, …). Роли узлов: 0=NODE, 1=ANCHOR, 2=TAG, 3=CONSOLE.

## Ограничения

- Распаковщики `nlink_unpack` пишут результат в глобальные синглтоны, поэтому
  `feed()` конвертирует кадр в dict синхронно (внутри вызова). Несколько
  экстракторов в одном процессе допустимы, но кормить их из разных потоков
  одновременно нельзя.
- Кадры AOA и TOFSense не подключены (не используются в проекте).
