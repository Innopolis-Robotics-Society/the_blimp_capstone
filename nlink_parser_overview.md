# NLink Parser — разбор структуры и план ROS-независимой обёртки

## 1. Что это такое

`nlink_parser` — сторонний **ROS1-пакет (catkin, не ROS2!)** производителя UWB-оборудования
**Nooploop**, подключённый в проект `the_blimp` (ветка `dev_uwb`). Версия 2.1.0, лицензия BSD.

Задача пакета: читать бинарный поток с последовательного порта (USB/UART) от UWB-устройств
LinkTrack / TOFSense, разбирать кадры протокола и публиковать их как типизированные ROS-топики.

Пакет состоит из тонкого ROS-слоя + **трёх git-сабмодулей**:

| Компонент | Язык | Зависит от ROS | Роль |
|-----------|------|:---:|------|
| родительский пакет (`src/linktrack`, `src/tofsense`, …) | C++ | **да** | ROS-ноды, публикация топиков |
| `src/utils/protocol_extracter` | C++ | нет | конечный автомат нарезки потока на кадры |
| `src/utils/nlink_unpack` | C | нет | распаковка конкретных кадров в значения СИ |
| `extern/serial` (wjwwood/serial) | C++ | нет | кроссплатформенный драйвер серийного порта |

Инициализация сабмодулей: `git submodule update --init --recursive`.

---

## 2. Конвейер данных

```
Serial port → NProtocolExtracter → NLinkProtocol (Verify+Unpack) → C-распаковщик → ROS-сообщение → publish
```

Пошагово (на примере ноды `linktrack`):

1. **`src/linktrack/main.cpp`** — `ros::init` → открывает порт через `initSerial` → создаёт
   `NProtocolExtracter` и `linktrack::Init`. Бесконечный цикл @1000 Гц:
   `serial.available()` → `serial.read()` → `protocol_extraction.AddNewData()` → `ros::spinOnce()`.

2. **`NProtocolExtracter`** (сабмодуль) — диспетчер: ищет заголовки зарегистрированных
   протоколов в буфере, режет кадры, проверяет контрольную сумму.

3. **`src/linktrack/init.cpp`** — регистрация. Конструктор `Init` создаёт по объекту-протоколу
   на каждый тип кадра (`AnchorFrame0`, `TagFrame0`, `NodeFrame0..6`) и вешает лямбду-callback.
   Callback лениво создаёт `ros::Publisher`, копирует поля из распакованной C-структуры `g_nlt_*`
   в ROS-сообщение и публикует. Топики вида `nlink_linktrack_nodeframe2`.
   Также подписка на `nlink_linktrack_data_transmission` — обратный канал записи в порт.

4. **`src/linktrack/protocols.h/.cpp`** — классы кадров. Два базовых типа:
   - `NLinkProtocol` — кадр фиксированной длины;
   - `NLinkProtocolVLength` — переменной длины (длина = байты 2–3 кадра, см. `UpdateLength`).

   `UnpackFrameData()` делегирует в C-функцию сабмодуля (`g_nlt_nodeframe2.UnpackData(...)`).

5. **`src/utils/nlink_protocol.cpp`** — мост: `HandleData` → `UnpackFrameData` → callback;
   `Verify` — контроль целостности по сумме байт.

---

## 3. Сабмодуль `protocol_extracter` — stream-парсер

Не зависящая от ROS библиотека из 2 классов.

**`NProtocolBase`** — абстрактный «вид кадра». Хранит `fixed_header_` (сигнатура header +
function_mark), `fixed_tail_` (для NMEA-подобных без явной длины), `is_length_knowable_`,
`fixed_part_size_`. Виртуальные крючки: `UpdateLength()`, `Verify()`, `HandleData()`.

**`NProtocolExtracter`** — диспетчер, вся логика в `AddNewData()`:

1. **Склейка**: к новым байтам приклеивается хвост прошлого вызова (`prev_data_array_`) —
   кадр мог прийти не целиком.
2. **Поиск заголовков**: по всем протоколам ищет все вхождения `fixed_header` → список
   `SortInfo{протокол, позиция}`.
3. **Сортировка** по позиции (при совпадении — по длине).
4. **Извлечение по порядку**: `UpdateLength()` (VLength читает длину из байт 2–3) → проверка
   достаточности данных → `Verify()` (checksum) → `HandleData()` → сдвиг `index_begin`.
5. **Сохранение остатка**: незаконченный хвост уходит в `prev_data_array_` до след. вызова.

Итог — устойчивый к фрагментации потоковый парсер: байты могут приходить как угодно нарезанными.

---

## 4. Сабмодуль `nlink_unpack` — распаковщики кадров (чистый C)

Аппаратно-зависимый слой: бинарный layout протокола → значения в СИ. Полностью на C (может
работать и на микроконтроллере).

**Общая база** (`nlink_typedef.h`, `nlink_utils.h/.c`):
- `nint24_t` / `nuint24_t` — упакованные 24-битные числа (позиции/дальности в 3 байтах);
- `NLINK_ParseInt24()`, `NLINK_VerifyCheckSum()`, `NLink_UpdateCheckSum()`;
- `NLINK_PROTOCOL_LENGTH(X) = X[2] | X[3]<<8` — длина кадра из байт 2–3;
- множители перевода в СИ: voltage /1000, pos /1000 (мм→м), dis /1000, vel /10000,
  angle /100, rssi /-2, eop /100;
- роли: `LINKTRACK_ROLE_NODE / ANCHOR / TAG / CONSOLE / DT_MASTER / DT_SLAVE / MONITOR`.

**Паттерн каждого кадра** (пример `nlink_linktrack_nodeframe2.c`):

```c
#pragma pack(1)
typedef struct { ... } nlt_nodeframe2_raw_t;   // ТОЧНЫЙ бинарный layout с проводов (+ reserved[])
static uint8_t UnpackData(const uint8_t *data, size_t data_length) {
    // 1. проверка header / function_mark / длины / контрольной суммы
    // 2. memcpy сырых байт в packed-структуру g_frame
    // 3. перевод полей в СИ через множители → g_nlt_nodeframe2.result
    // 4. цикл по valid_node_count: malloc узлов, распаковка dis/rssi
}
nlt_nodeframe2_t g_nlt_nodeframe2 = {.fixed_part_size=119, .frame_header=0x55,
                                     .function_mark=0x04, .UnpackData=UnpackData};
```

Ключевая идея — **packed-структура, точно повторяющая байты на проводе** (включая `reserved[]`).
Один `memcpy` накладывает её на буфер, поля приводятся к человеческим единицам. Результат —
в глобальном синглтоне `g_nlt_*`, откуда его читает `init.cpp`.

Каждый кадр идентифицируется парой **`frame_header=0x55` + `function_mark`**
(0x01 = TagFrame0, 0x04 = NodeFrame2 и т.д.).

Типичные кадры позиционирования:
- **TagFrame0** (`0x55 0x01`, фикс. 128 байт) — состояние одного тега: `pos_3d`, `vel_3d`,
  `dis_arr[8]` (дальности до якорей), `quaternion`, `imu_*`, `voltage`.
- **NodeFrame2** (`0x55 0x04`, переменная длина, fixed 119) — состояние тега + список узлов
  с дальностями/RSSI.

---

## 5. Сабмодуль `extern/serial`

Библиотека [wjwwood/serial](https://github.com/wjwwood/serial) — кроссплатформенный C++-драйвер
последовательного порта. К UWB отношения не имеет, просто транспорт. `initSerial()` открывает
порт, `main.cpp` дёргает `serial.available()` / `serial.read()`.

Параметры порта берутся из launch-файла, напр. `linktrack.launch`:
`port_name = /dev/ttyUSB0`, `baud_rate = 921600`.

---

## 6. Полная картина слоёв

```
extern/serial          → сырые байты с USB/UART
        ↓
protocol_extracter     → нарезка потока на кадры (header/length/checksum), устойчиво к фрагментации
        ↓ HandleData()
nlink_protocol (utils) → мост: UnpackFrameData + callback
        ↓
nlink_unpack (C)       → memcpy packed-структуры, перевод в СИ, заполнение g_nlt_*
        ↓
linktrack/init.cpp     → копирует g_nlt_* в ROS-msg и публикует nlink_linktrack_*   ← ЕДИНСТВЕННЫЙ ROS-слой
```

**Вывод:** ROS присутствует только в самом верхнем слое (`main.cpp` + `init.cpp` родительского
пакета). Транспорт (`serial`), нарезка (`protocol_extracter`) и разбор (`nlink_unpack`) от ROS
не зависят вообще.

---

## 7. Можно ли написать чистую (не-ROS) обёртку? — Да

ROS выкидывается целиком, переиспользуются три ROS-независимых сабмодуля. Есть два пути.

### Вариант A. Тонкий C++ без ROS (максимальное переиспользование кода)

Повторить `main.cpp`/`init.cpp` без ROS:

1. Открыть порт через `extern/serial` (та же библиотека).
2. Создать `NProtocolExtracter`, зарегистрировать нужные протоколы (`NLT_ProtocolTagFrame0`
   и т.д. из `protocols.cpp` — их можно взять как есть, они не тянут ROS).
3. Вместо ROS-callback'а из `init.cpp` подставить свой: читать `g_nlt_*.result` и отдавать
   в дашборд (stdout / JSON / сокет / общий буфер).
4. Цикл чтения порта — как в `main.cpp`, но без `ros::spinOnce()`.

Плюсы: используется штатный протестированный парсер один-в-один. Минусы: нужна сборка C++.

### Вариант B. Чистый Python (удобно для дашборда)

Для дашборда Python обычно практичнее. Два под-варианта:

- **B1 — ctypes/pybind поверх `nlink_unpack`**: собрать C-файлы `nlink_unpack` в `.so`, дергать
  `UnpackData` и читать `g_nlt_*` из Python. Нарезку потока (`protocol_extracter`) переписать на
  Python (класс несложный) или тоже собрать в `.so`.
- **B2 — полностью на Python (рекомендуется для дашборда):** переписать логику на `pyserial` +
  `struct`. Протокол полностью документирован в C-структурах:
  - искать заголовок `0x55` + function_mark;
  - для VLength читать длину из байт 2–3 (`data[2] | data[3]<<8`);
  - проверять checksum (сумма байт по модулю 256, последний байт);
  - распаковывать через `struct.unpack('<...')` по тем же layout'ам, что в `*_raw_t`
    (int24 — вручную из 3 байт), делить на те же множители (pos/1000, vel/10000, …).

Плюсы: ноль сборки, легко встроить в web-дашборд (Flask/FastAPI + WebSocket, Dash, Streamlit).
Минусы: layout структур придётся аккуратно перенести (внимание к `reserved[]`-полям и `#pragma
pack(1)` → формат `<` без выравнивания).

### Рекомендация

Для дашборда без ROS — **Вариант B2 (чистый Python)**: минимум зависимостей, максимум гибкости.
Достаточно реализовать один-два кадра, которые реально шлёт железо `the_blimp` (скорее всего
TagFrame0 или NodeFrame2). C-структуры `nlink_unpack/*.c` служат точной спецификацией layout'а.

---

## 8. Открытые вопросы перед реализацией

1. **Язык обёртки**: чистый Python (B2) vs тонкий C++ (A)?
2. **Какой кадр** реально шлёт железо блимпа — TagFrame0 (`0x55 0x01`) или NodeFrame2 (`0x55 0x04`)
   или другой? От этого зависит layout распаковки.
3. **Формат отдачи в дашборд**: локальный web (WebSocket/HTTP), TUI, или запись в файл/БД?
4. **Порт и baud**: `/dev/ttyUSB0 @ 921600` из launch — подтвердить для реального устройства.
</content>
</invoke>
