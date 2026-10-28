# The Producer–Consumer Problem

**F.CSM302 Үйлдлийн систем · Бие даалт 1 · Сэдэв 12**
**Баг:** `<IV-2-12>`
**Гишүүд:** `<B222270085>`, `<B21091086>`, `<B231940071>`, `<B241940069>`,`<B242270012>`,`<B242270505>`

_Operating System Concepts_ (Silberschatz, Galvin, Gagne, 10th ed., 2018), Chapter 7, Programming Project 4-ийн хэрэгжүүлэлт: **хязгаарлагдмал буфер (bounded buffer)**-ийг семафор ба mutex-ээр синхрончилж, producer/consumer thread-үүдийн ажиллагааг бодит цагийн UI-аар харуулна.

## Зорилго

- Номын шаардлагыг бүрэн хэрэгжүүлэх: тойрог буфер, `empty`/`full` тоолох семафор, `mutex` lock, Pthreads, командын мөрийн 3 параметр.
- Буферийн хэмжээ, producer/consumer-ийн тоо ба **хурдыг** өөрчилж, буферийн төлөв ба **wait / produce / consume** үйл явцыг бодит C програмаас харуулах.
- Зөв ажиллагааг автомат шалгалт (FIFO, хэтрэлтгүй байдал) болон 27 туршилтаар нотлох.

## Quick Start

Linux (Ubuntu 22.04+ дээр туршсан):

```bash
sudo apt install build-essential python3 python3-tk   # нэг удаа
git clone <REPO_URL>
cd The-Producer-Consumer-Problem
make            # ./pc үүснэ
make run        # номын жишээ: ./pc 10 2 3
make ui         # график UI
make test       # бүх туршилт → tests/results.md
```

## Хэрэглээ

```
./pc [-j] <sleep_sec> <producers> <consumers> [buffer_size] [prod_ms] [cons_ms]
```

| Параметр             | Утга                                    | Муж      | Анхдагч |
| -------------------- | --------------------------------------- | -------- | ------- |
| `sleep_sec`          | `main` хэдэн секунд унтаад дуусах       | 1..3600  | —       |
| `producers`          | producer thread-ийн тоо                 | 1..32    | —       |
| `consumers`          | consumer thread-ийн тоо                 | 1..32    | —       |
| `buffer_size`        | буферийн нүдний тоо                     | 1..64    | 5       |
| `prod_ms`, `cons_ms` | санамсаргүй sleep-ийн дээд хязгаар (мс) | 0..10000 | 1000    |
| `-j`                 | үйлдэл бүрийг JSON мөрөөр гаргах (UI-д) |          |         |

Эхний 3 параметр номын шаардлага, үлдсэн нь даалгаврын нэмэлт. Дэлгэрэнгүйг [docs/Manual.md](docs/Manual.md)-ээс үзнэ үү.

## Бүтэц

```
src/
  buffer.h, buffer.c   тойрог буфер, insert_item/remove_item (sem_wait → mutex → sem_post)
  main.c               аргумент шалгах, thread үүсгэх, sleep, JSON event, stdin команд
  gui.py               Tkinter UI: ./pc -j-ийг ажиллуулж, event-үүдийг дүрсэлнэ
tests/
  test_buffer.c        unit тест (FIFO, буруу хэмжээ)
  check_log.py         JSON лог дээр I1–I4 нөхцлийг шалгагч
  cases.csv            27 туршилтын тохиолдол (өгөгдөл)
  run_tests.py         бүгдийг ажиллуулж tests/results.md гаргана
  results.md, logs/    сүүлийн ажиллагааны үр дүн ба лог
docs/
  Manual.md            суулгах, ажиллуулах, UI, алдааны заавар
  images/              screenshot-ууд
Makefile
```

## Туршилтын үр дүн (товч)

27/27 тохиолдол PASS. Үүнд 14 буруу оролт, номын жишээ, захын утга (1 ба 64 нүд, 32+32 thread, 0 мс), стресс (секундэд 100 мянга+ event), хөгжүүлэлтийн явцад олдож засагдсан 2 синхрончлолын алдааны регресс тест орсон. Бүтэн хүснэгт: [tests/results.md](tests/results.md).

## Ашигласан сан, хэрэгсэл, AI

- C11, POSIX Threads (`pthread`), POSIX unnamed semaphore (`semaphore.h`), `stdatomic.h`. Гадны C сан ашиглаагүй.
- Python 3 стандарт сан: `tkinter`, `subprocess`, `json`. Гадны Python сан ашиглаагүй.
- **AI ашиглалт:** Anthropic-ийн **Claude** (claude.ai) AI туслахыг алхам алхмаар заах, кодын эхний хувилбарыг бичих, туршилт зохиоход ашигласан. Багийн гишүүд код бүрийг өөрсдийн компьютер дээр хөрвүүлж, ажиллуулж, screenshot-оор шалгаж, туршилтын үр дүнг гараар тулгасан. Дэлгэрэнгүйг тайлангийн "Хэрэгжилт" хэсэгт тусгасан.

## Ашигласан материал

- A. Silberschatz, P. B. Galvin, G. Gagne. _Operating System Concepts_, 10th ed., Wiley, 2018. §4.4.1 (Pthreads), §7.1.1 (Bounded-Buffer), §7.3 (POSIX Synchronization), Chapter 7 Programming Project 4.
- Linux man-pages: `sem_init(3)`, `sem_wait(3)`, `sem_trywait(3)`, `pthread_create(3)`, `pthread_mutex_lock(3p)`, `flockfile(3)`, `rand_r(3)`, `_exit(2)`.
- Python documentation: `tkinter`, `subprocess`.
