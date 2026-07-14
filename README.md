# Blimp UWB — наземная станция реального дирижабля

Проект принимает координаты **одной** UWB-метки, показывает их на плоской карте
зала и передаёт команды и миссии настоящему автопилоту по двустороннему MAVLink.
SITL, виртуальной «болванки» дирижабля и 3D-сцены в целевой схеме нет.

## Целевая схема

```text
                         +-- UART Node_Frame2 -----------> FC / EKF
единственная UWB T1 -----+
        ^                +-- UWB-радиосеть --> консоль P-A --> USB --> nlink-dump
        |                                                       |
     якоря                                                      +-- UDP :9999
                                                                    --> backend --> браузер

браузер --> backend <--> MAVLink UDP :14550 или serial <--> ELRS Backpack/TX12
                                                          <--> ELRS RX <--> FC
```

- По умолчанию backend пропускает в браузер только UWB tag ID `1`. Другие
  UWB-метки отфильтровываются на сервере, даже если консоль видит их в том же
  кадре. ID настраивается через `--uwb-tag-id` или `BLIMP_UWB_TAG_ID`.
- Отдельного ESP в тракте UWB нет: консоль подключается к наземному компьютеру
  напрямую по USB. **ELRS Backpack остаётся частью MAVLink-радиомоста** и не
  является отдельным UWB-ESP.
- Эта же единственная метка подключается напрямую к UART полётного контроллера:
  `Node_Frame2`, `921600`, `BCN_TYPE=3`, `SERIAL1_PROTOCOL=13`. Номер UART и
  параметры нужно адаптировать под фактический FC; источник курса — компас/IMU,
  а не вторая UWB-метка.
- Backend не подменяет телеметрию данными SITL и не стримит фиктивные setpoint-ы.
  Он загружает маршрут стандартной MAVLink mission-транзакцией и ждёт
  подтверждения автопилота; ARM, DISARM, смена режима и запуск миссии также
  требуют MAVLink ACK.

## Запуск без Docker

Установка из корня репозитория:

```bash
git submodule update --init --recursive
python3 -m venv .venv
source .venv/bin/activate
pip install -e uwb/nlink_py -e uwb/dashboard
```

Шаг с submodule обязателен: без исходников `uwb/extern/nlink_unpack` и
`uwb/extern/protocol_extracter` нативный UWB-парсер и Docker-образ не соберутся.

### Реальный MAVLink через ELRS Backpack / UDP 14550

Настройте Backpack на отправку MAVLink на IP наземного компьютера, порт `14550`.
Затем запустите backend:

```bash
blimp-dashboard \
  --http-port 8000 \
  --udp-port 9999 \
  --anchors uwb/dashboard/anchors.json \
  --uwb-tag-id 1 \
  --mavlink udpin:0.0.0.0:14550 \
  --origin-lat 55.7522 \
  --origin-lon 48.7446 \
  --origin-alt 120.0
```

В другом терминале подключите UWB-консоль:

```bash
nlink-dump \
  --port /dev/ttyCH343USB0 \
  --baud 921600 \
  --udp 127.0.0.1:9999 \
  --quiet
```

Откройте <http://localhost:8000>. MAVLink-соединение считается готовым только
после heartbeat настоящего автопилота; backend автоматически переподключается
после потери канала.

### Реальный MAVLink через serial

Для USB/UART MAVLink укажите serial-устройство и его фактическую скорость:

```bash
blimp-dashboard \
  --anchors uwb/dashboard/anchors.json \
  --uwb-tag-id 1 \
  --mavlink /dev/ttyUSB0 \
  --mavlink-baud 115200 \
  --origin-lat 55.7522 \
  --origin-lon 48.7446 \
  --origin-alt 120.0
```

По возможности используйте стабильные пути `/dev/serial/by-id/...`, чтобы не
перепутать MAVLink и UWB USB-устройства после перезагрузки.

Те же основные настройки доступны через переменные окружения:
`BLIMP_MAVLINK_ENDPOINT`, `BLIMP_MAVLINK_BAUD`, `BLIMP_UWB_TAG_ID`,
`BLIMP_ORIGIN_LAT`, `BLIMP_ORIGIN_LON`, `BLIMP_ORIGIN_ALT`.

## Запуск через Docker Compose

Живой профиль использует UWB-консоль по USB и по умолчанию слушает реальный
MAVLink от Backpack на UDP `14550`:

```bash
git submodule update --init --recursive
cd uwb
docker compose --profile live up --build
```

Основные переменные Compose:

- `UWB_PORT` (по умолчанию `/dev/ttyCH343USB0`) и `UWB_BAUD` (`921600`);
- `BLIMP_UWB_TAG_ID` (по умолчанию `1`);
- `BLIMP_MAVLINK_ENDPOINT` (по умолчанию `udpin:0.0.0.0:14550`) и
  `BLIMP_MAVLINK_BAUD` (`115200`);
- `BLIMP_ORIGIN_LAT`, `BLIMP_ORIGIN_LON`, `BLIMP_ORIGIN_ALT`;
- `BLIMP_SET_ORIGIN_ON_UPLOAD` (по умолчанию `false`).

Для serial MAVLink внутри контейнера передайте устройство как `/dev/mavlink`:

```bash
cd uwb
MAVLINK_SERIAL_DEVICE=/dev/serial/by-id/REPLACE_WITH_REAL_DEVICE \
BLIMP_MAVLINK_ENDPOINT=/dev/mavlink \
BLIMP_MAVLINK_BAUD=115200 \
docker compose --profile live up --build
```

## Origin и координаты

`X` маршрута означает север, `Y` — восток, `Z` — высоту относительно Home в
метрах. `BLIMP_ORIGIN_LAT/LON` используются для пересчёта локальных точек в
широту/долготу. Они должны совпадать с origin, настроенным на реальном борту.

Backend **не меняет origin автопилота по умолчанию**. Флаг
`--set-origin-on-upload` (или `BLIMP_SET_ORIGIN_ON_UPLOAD=true`) явно меняет и
проверяет origin перед каждой загрузкой миссии. Не включайте его, пока реальные
координаты и высота не измерены и не сверены с настройками FC.

Координаты UWB-якорей хранятся в `uwb/dashboard/anchors.json` и редактируются в
панели «Якоря UWB». Они должны совпадать с системой координат в NAssistant.

## Replay — только офлайн-проверка UWB

Replay не имитирует дирижабль и не проверяет MAVLink-управление. Он нужен только
для проверки парсинга, фильтра выбранного tag ID и 2D-интерфейса. В replay-
профиле MAVLink принудительно отключён:

```bash
cd uwb
docker compose --profile replay up --build
```

Без Docker:

```bash
# терминал 1: пустое значение гарантированно отключает MAVLink
BLIMP_MAVLINK_ENDPOINT= blimp-dashboard \
  --anchors uwb/dashboard/anchors.json \
  --uwb-tag-id 1

# терминал 2
nlink-dump \
  --replay uwb/recordings/uwb_live.bin \
  --replay-delay 0.05 \
  --loop \
  --udp 127.0.0.1:9999 \
  --quiet
```

## Безопасная первая проверка на стенде

> **Перед первой проверкой снимите пропеллеры и отключите/снимите моторы от
> ESC. Не проверяйте ARM на собранной силовой установке.**

1. Закрепите дирижабль, оставьте автопилот DISARMED и подайте питание с
   ограничением тока.
2. Запустите UWB и убедитесь, что интерфейс показывает только настроенную метку
   (по умолчанию `T1`), а её координаты соответствуют физическому перемещению.
3. Включите TX12, ELRS и Backpack; дождитесь в интерфейсе MAVLink heartbeat,
   правильного SYS ID, режима, состояния DISARMED и телеметрии. При фиксации
   component ID дополнительно проверьте `/api/mavlink/status`.
4. Загрузите короткую безопасную миссию, не запуская её, и проверьте, что
   автопилот подтвердил загрузку. Сначала отдельно проверьте DISARM; ARM и
   движение допускаются только после завершения стендовой проверки в безопасной
   зоне по процедуре команды.
