# Хэрэглэгчийн гарын авлага (Manual)

Producer–Consumer Problem · F.CSM302 Бие даалт 1

Энэ гарын авлагыг дагаж, шинэ Linux компьютер дээр програмыг суулгах, ажиллуулах, UI ашиглах, туршилтыг дахин хийх боломжтой.

---

## 1. Шаардлагатай орчин

| Хэрэгсэл | Хувилбар | Шалгах команд |
|---|---|---|
| Linux (Ubuntu, Debian гэх мэт) | Ubuntu 22.04+ дээр туршсан | `cat /etc/os-release` |
| GCC (C11, pthread) | 11+ | `gcc --version` |
| make | дурын | `make --version` |
| Python 3 | 3.10+ | `python3 --version` |
| Tkinter | Python-той тохирох | `python3 -c "import tkinter"` |

Суулгах (нэг удаа):

```bash
sudo apt update
sudo apt install build-essential python3 python3-tk git
```

> **macOS/Windows:** Програм Linux-ийн POSIX unnamed semaphore (`sem_init`)-ийг ашигладаг. macOS дээр `sem_init` дэмжигддэггүй тул ажиллахгүй. Windows дээр **WSL (Ubuntu)** суулгаж ашиглана уу.

## 2. Татах ба хөрвүүлэх

```bash
git clone <REPO_URL>
cd The-Producer-Consumer-Problem
make
```

Амжилттай бол төслийн хавтсанд `pc` гэсэн програм үүснэ. `make` байхгүй бол:

```bash
gcc -Wall -pthread src/buffer.c src/main.c -o pc
```

## 3. Командын мөрөөс ажиллуулах (номын шаардлага)

```
./pc <sleep_sec> <producers> <consumers> [buffer_size] [prod_ms] [cons_ms]
```

Жишээ:

```bash
./pc 10 2 3                # номын жишээ: 10 сек, 2 producer, 3 consumer, 5 нүд
./pc 10 3 1 5 100 1000     # producer хурдан → буфер дүүрнэ
./pc 10 1 3 5 1000 100     # consumer хурдан → буфер хоосорно
```

Гаралт:

```
Тохиргоо: sleep=10s producers=2 consumers=3 buffer=5 prod_ms=1000 cons_ms=1000
producer 2 produced 276671478
consumer 2 consumed 276671478
...
Дүн: produced=21 consumed=21 buffer-д үлдсэн~0
```

`main` нь `sleep_sec` секунд унтаад програмыг дуусгана (номын Figure 7.15).

### Алдааны мессежүүд

| Оролт | Мессеж |
|---|---|
| `./pc` | `Хэрэглээ: pc [-j] <sleep_sec> ...` |
| `./pc abc 2 3` | `Алдаа: sleep_sec = "abc" бүхэл тоо биш байна.` |
| `./pc 10 0 3` | `Алдаа: producers = 0, зөвшөөрөгдөх муж [1..32].` |
| `./pc 10 2 3 100` | `Алдаа: buffer_size = 100, зөвшөөрөгдөх муж [1..64].` |

Алдаатай үед програм exit code **1** буцаана.

## 4. UI ашиглах

```bash
make ui          # эсвэл: python3 src/gui.py
```

![UI ерөнхий харагдах байдал](images/ui_overview.png)

### 4.1 Тохиргоо (зүүн хэсэг)

| Талбар | Тайлбар |
|---|---|
| Бэлэн хувилбар | 6 бэлэн сценари: номын жишээ, тэнцүү хурд, producer давамгай, consumer давамгай, 1 нүд, 16 нүд |
| Буферийн хэмжээ, Producer тоо, Consumer тоо, Хугацаа | Утгыг шууд бичих эсвэл сумаар өөрчилнө. Муж нь хажууд нь бичигдсэн |
| Producer / Consumer хурд | Санамсаргүй sleep-ийн дээд хязгаар. **Ажиллаж байхад ч** өөрчилж болно. Програм руу шууд илгээгдэнэ |

Товчнууд:
- **▶ Эхлүүлэх**: оролтыг шалгаад `./pc -j ...`-г ажиллуулна.
- **■ Зогсоох**: ажиллаж буй програмыг зогсооно.
- **↺ Reset**: зогсоож, бүх тохиргоог анхны утгад нь буцаана.
- **Лог хадгалах**: ажиллагааны бүх event-ийг `.jsonl` файлд хадгална.
- **Зөв эсэхийг шалгах**: `tests/check_log.py`-г одоогийн лог дээр ажиллуулж PASS/FAIL харуулна.

### 4.2 Дүрслэл (баруун хэсэг)

| Хэсэг | Юу харуулах вэ |
|---|---|
| Producer / Consumer thread-үүд | Thread бүр нэг хайрцаг. **Цагаан** = sleep, **ногоон/улбар** = яг одоо produce/consume хийлээ, **улаан** = `sem_wait` дээр **хүлээж** байна. Доор нь хийсэн үйлдлийн тоо |
| Тойрог буфер | Нүд бүр: индекс, утга (сүүлийн 4 орон), хийсэн producer. Ногоон = дүүрсэн, саарал = хоосон. `▲in` = дараагийн бичих, `▲out` = дараагийн унших байрлал |
| Синхрончлолын объектууд | `empty` (сул нүд), `full` (дүүрсэн нүд). Үргэлж `empty + full = size` |
| Буферийн дүүргэлт | Сүүлийн 20 секундын дүүргэлтийн график. Улаан тасархай шугам = дүүрэн |
| Event лог | C програмаас ирсэн event бүр: `P2 → нүд[3]` (produce), `C1 ← нүд[0]` (consume), `ХҮЛЭЭЖ байна`, `сэрлээ` |

### 4.3 Санал болгох туршилтууд

1. **Номын жишээ** → consumer-ууд ихэвчлэн улаан (буфер хоосон).
2. **Producer давамгай** → буфер 5/5 дүүрч, бүх producer улаан. Дараа нь Consumer хурдыг 50 болгож буфер хоосорч эхлэхийг ажиглана.
3. **1 нүдтэй буфер** → график 0 ↔ 1 хооронд үсэрнэ (P, C заавал ээлжилнэ).
4. Буферийн хэмжээнд `0` бичээд ▶ → алдааны мессеж.

### 4.4 Тоогоор шалгах арга

Дэлгэц дээрх дараах тэгшитгэлүүд үргэлж биелэх ёстой:

- `дүүрсэн нүд = Produced − Consumed`
- `in = Produced mod size`, `out = Consumed mod size`
- Producer-уудын тоолуурын нийлбэр = Produced, consumer-уудынх = Consumed

## 5. Туршилтыг дахин хийх

```bash
make test        # эсвэл: python3 tests/run_tests.py
```

1. Кодыг `-Wall -Wextra -Werror`-той хөрвүүлнэ.
2. Unit тест (`tests/test_buffer.c`) ажиллуулна.
3. `tests/cases.csv`-ийн 27 тохиолдлыг ажиллуулна (~1 минут).
4. Үр дүнг `tests/results.md` хүснэгт, лог-ийг `tests/logs/<ID>.jsonl.gz` болгож хадгална.

Зөвхөн зарим тохиолдол: `python3 tests/run_tests.py B1 C3`

Лог-ийг дахин шалгах: `zcat tests/logs/B1.jsonl.gz | python3 tests/check_log.py`

Шинэ туршилт нэмэх: `tests/cases.csv`-д мөр нэмнэ (файлын эхэнд формат тайлбарласан).

```
E1;Миний туршилт;10 нүд, 5P 5C;3 5 5 10 50 50;pass
```

## 6. JSON event протокол (`./pc -j`)

UI ба тест энэ протоколоор C програмтай харилцана. stdout-д мөр бүр нэг JSON:

| `ev` | Талбарууд | Утга |
|---|---|---|
| `config` | `sleep, producers, consumers, size, prod_ms, cons_ms` | эхлэх тохиргоо |
| `produce` / `consume` | `who, item, slot, count, in, out, buf[]` | mutex **дотор** хэвлэгдэнэ → буферийн бодит төлөв |
| `wait` | `who, reason` (`full` / `empty`) | thread семафор дээр блоклогдлоо |
| `wake` | `who, reason` | блоклогдсон thread сэрлээ |
| `speed` | `prod_ms, cons_ms` | хурд өөрчлөгдлөө |
| `error` | `msg` | буруу stdin команд |
| `end` | `produced, consumed` | `main` унтаж дуусаад гарах үед |

stdin команд (мөр тутам): `prod_ms <0..10000>`, `cons_ms <0..10000>`.

Бүх event-д `t` = програм эхэлснээс хойших миллисекунд.

## 7. Түгээмэл асуудал

| Асуудал | Шийдэл |
|---|---|
| `gcc: command not found` | `sudo apt install build-essential` |
| `No module named 'tkinter'` | `sudo apt install python3-tk` |
| UI: "C програм олдсонгүй" | Төслийн хавтсанд `make` ажиллуулна. Эсвэл `python3 src/gui.py --bin /зам/pc` |
| `expected declaration or statement at end of input` | Файл дутуу хуулагдсан. Copy-paste хийхийн оронд repo-оос `git clone` хийнэ |
| `./pc: No such file or directory` | Хөрвүүлэлт амжилтгүй болсон. Дээрх алдааг уншина |
| 0 мс хурдтай UI удаашрах | Секундэд 100 мянга+ event гардаг тул UI сүүлийнхийг л харуулна. Бүх event лог-д хадгалагдана |
| macOS дээр семафор ажиллахгүй | 1-р хэсгийн тэмдэглэлийг үзнэ үү (WSL эсвэл Linux) |
