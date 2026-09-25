# amr-sim: запуск за 10 минут

Симулятор беспилотной колесной платформы для кейса "Безопасный маршрут". Нужны Python 3.10 или новее и numpy. Сеть при работе не нужна. Описание данных, датчиков и счета: docs/DATA.md.

## 1. Установка

Windows (PowerShell или cmd), в папке распакованного архива:

```
py -3 --version
py -3 -m pip install numpy
py -3 -m amrsim doctor
```

macOS и Linux (через виртуальное окружение: так работает и Homebrew Python, и Python в Ubuntu 24.04):

```
python3 --version
python3 -m venv .venv
. .venv/bin/activate
python -m pip install numpy
python -m amrsim doctor
```

Последняя строка doctor должна быть `doctor: OK`. Дальше в примерах написано `python`: на Windows пишите `py -3`, на macOS и Linux в той же консоли с активированным .venv работает `python` (в новой консоли снова выполните `. .venv/bin/activate`). На Windows можно так же: `py -3 -m venv .venv`, `.venv\Scripts\activate`, затем `python -m pip install numpy`. Если в консоли Windows видны кракозябры, выполните `set PYTHONUTF8=1` (cmd) или `$env:PYTHONUTF8=1` (PowerShell).

## 2. Первый прогон

```
python -m amrsim smoke
python -m amrsim run scenarios/01_clear.json --controller baseline/controller.py --seed 7 --report out/01.json --log out/01.jsonl
python -m amrsim score out/01.json
```

smoke прогоняет базовый контроллер на 01_clear (меньше 20 с). run пишет отчет out/01.json и лог out/01.jsonl, score печатает счет по блокам и пять самых дорогих эпизодов.

## 3. Свой контроллер

Скопируйте baseline/controller.py в свою папку, например team/controller.py, и меняйте. Интерфейс и все поля obs: docs/DATA.md раздел 3.

```
python -m amrsim check team
python -m amrsim run scenarios/02_gnss_shadow.json --controller team/controller.py --seed 1 --report out/02.json --log out/02.jsonl
python -m amrsim score out/02.jsonl
```

check проверяет правила: только стандартная библиотека и numpy, без gc, inspect, ctypes, threading, multiprocessing, concurrent, без импорта amrsim и без доступа к кадрам интерпретатора (полный список: docs/DATA.md раздел 3.3). Нарушение (VIOLATION) означает 0 за кейс. WARNING сам по себе на счет не влияет: это места, которые эксперты посмотрят вручную; `result: OK` значит, что нарушений нет. Но заблокированные попытки добраться до сценария, seed, лога или кода симулятора видны экспертам в поле sandbox_violations отчета даже при `result: OK`, и подтвержденная попытка обойти изоляцию означает 0 за кейс.

Контроллер работает в отдельном процессе с пустой временной рабочей папкой. Он может читать файлы своей папки, писать только в рабочую папку, печатать отладку через print (попадает в конец отчета, поле controller_stderr_tail). Чтение сценариев, запуск процессов и сеть блокируются.

Полезно:
- `--seed N`: другой шум датчиков; официальные прогоны идут на seed, которые вам неизвестны;
- открытые сценарии: 01_clear, 02_gnss_shadow, 03_fog_snow, 04_busy_yard и учебные 01e_clear_easy, 02e_gnss_shadow_easy (в obs есть detections);
- `--cheat`: передает истинную позу в Controller.set_truth (если такой метод есть), в obs ее нет; оракул для сравнения: `python -m amrsim run scenarios/02_gnss_shadow.json --controller baseline/controller.py --cheat`; в рейтинг не идет.

## 4. Прогон нескольких сценариев

```
python -m amrsim batch teams scenarios --seeds 1,2,3 --out out/table.csv
```

teams это папка, в которой лежат папки команд с controller.py (для себя: teams/my/controller.py). После teams можно перечислить несколько папок или файлов сценариев. Итог: out/table.csv (строка на прогон) и out/table_summary.csv. С ключом `--jobs 4` прогоны идут параллельно. Официальные прогоны идут с солью: seed смешан с секретом, поэтому шум в них вам неизвестен.

## 5. Образцы лога и рабочее место оператора

В архиве есть папка samples/ с готовыми файлами прогона базового контроллера на seed 7:

```
samples/01_clear.jsonl    samples/01_clear.json
samples/04_busy_yard.jsonl samples/04_busy_yard.json
```

Рабочее место оператора (обязательная часть кейса, критерий О3 на 15 баллов) строится на этих двух файлах: JSONL дает карту, траекторию, пешеходов и события по тикам, JSON дает счет, миссии и эпизоды штрафов. Образцы нужны, чтобы начать интерфейс до того, как готов свой контроллер; когда он появится, те же файлы получаются своим прогоном с ключами --log и --report. Полное описание всех полей: docs/DATA.md раздел 7. Онлайн-интерфейса у симулятора нет: задание запускается командой python -m amrsim run, а рабочее место читает файлы. Зависимости рабочего места кладите в arm/requirements.txt: в корневом requirements.txt должен остаться только numpy, иначе python -m amrsim check дает VIOLATION и это 0 за кейс.

## 6. Картинка траектории

```
python -m amrsim render out/01.jsonl --png out/01.png
```

Нужен matplotlib (`python -m pip install matplotlib`); без него команда подскажет, как построить график из JSONL (docs/DATA.md раздел 7.1). На картинке: карта, истинная траектория, оценка позы контроллера, пешеходы и эпизоды штрафов.

## 7. Самопроверки пакета

```
python -m amrsim probe-scoring
python -m amrsim probe-determinism
```

probe-scoring проверяет расчет счета на известном логе, probe-determinism: два одинаковых прогона дают одинаковые отчет и лог.

## 8. Если что-то не так

| Сообщение | Что делать |
| --- | --- |
| `amrsim requires Python 3.10 or newer` | поставьте Python 3.10-3.12 с python.org |
| `No module named numpy` или `numpy is not importable in the controller process` | `python -m pip install numpy` тем же python, которым запускаете |
| `externally-managed-environment` при pip install | создайте окружение: `python3 -m venv .venv`, `. .venv/bin/activate`, затем `python -m pip install numpy` (на Debian и Ubuntu сначала `sudo apt install python3-venv`) |
| `controller error at t=...: ... (controller.py:N in step)` | ошибка в вашем коде, строка N |
| `real-time limit of 600 s per scenario exceeded` | контроллер слишком медленный или завис; сценарий не засчитан |
| `amrsim sandbox: ... is not allowed for controllers` | контроллер пытался читать чужие файлы или запускать процессы |
| `scenario not found` | путь к сценарию относительно текущей папки, либо короткое имя: `run 01 ...` |

Официальный счет рассчитывается на инфраструктуре проверки на отдельной копии amrsim (хеш пакета есть в каждом отчете). Правки внутри amrsim у себя на счет не влияют.

## 9. Формат сдачи

Из постановки задачи:

Репозиторий команды в GitVerse: controller.py и соседние модули; requirements.txt (только numpy); APPROACH.md на 15-25 строк (локализация, следование, безопасность, что не сделано); папка results с отчетами score по открытым сценариям; папка arm с рабочим местом оператора и инструкцией запуска (обязательная часть); презентация до 12 слайдов. Защита до 5 минут: подход, результаты на сценариях, демонстрация рабочего места оператора, поведение в сложных условиях, ограничения.

```
team_<name>/
  controller.py       # точка входа, может импортировать соседние модули
  requirements.txt    # только numpy
  APPROACH.md         # 15-25 строк: локализация, следование, безопасность, что не сделано
  results/            # отчеты score по открытым сценариям
  arm/                # рабочее место оператора и README запуска (обязательно)
  tests/              # свои автотесты контроллера (по желанию, критерий Т5)
  scenarios/          # свои сценарии проверки (по желанию, критерий О4)
  presentation.pdf    # до 12 слайдов
```

Правила прогона и оценки:

- Официальные прогоны выполняются на инфраструктуре проверки на отдельной копии симулятора. В каждом отчете есть хеш пакета (package_hash) и хеш файла сценария; результаты, посчитанные на измененном симуляторе, не учитываются. Папка results используется как справочная; официальным считается только счет официального прогона.
- Обход изоляции контроллера (доступ к истинному положению, сценарию, seed или файлам симулятора) означает 0 за кейс. Заблокированные попытки видны экспертам в поле sandbox_violations отчета и в столбце sandbox_violations таблицы batch.
- Нарушение python -m amrsim check (запрещенные импорты, лишние зависимости, доступ к кадрам интерпретатора) означает 0 за кейс.
- Прогон, не засчитанный из-за ошибки контроллера или превышения предела реального времени (10 минут на сценарий), дает 0 по этому сценарию.
- Сценарий, в котором не выполнена ни одна перевозка, дает 0: блоки безопасности, правил движения и честности оценки позы начисляются только при хотя бы одной доставке (в отчете они остаются видны с пометкой not_counted).
- Критерии оценки и их баллы: docs/CRITERIA.md.
