import json
import sys
from collections import deque


def main() -> int:
    size = None
    count = 0
    queue = deque()          
    waiting = {}             
    errors = []
    stats = {"produce": 0, "consume": 0, "wait": 0, "wake": 0}

    for lineno, line in enumerate(sys.stdin, 1):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"мөр {lineno}: JSON биш: {line[:60]}")
            continue

        ev = e.get("ev")
        if ev == "config":
            size = e["size"]
            continue
        if ev in stats:
            stats[ev] += 1

        if ev == "produce":
            if e["buf"][e["slot"]] != e["item"]:
                errors.append(f"мөр {lineno}: I4 slot-д item биш утга байна")
            count += 1
            queue.append(e["item"])
        elif ev == "consume":
            if not queue:
                errors.append(f"мөр {lineno}: I3 хоосон буферээс consume")
            else:
                expected = queue.popleft()
                if expected != e["item"]:
                    errors.append(f"мөр {lineno}: I3 FIFO зөрчил "
                                  f"{expected} хүлээсэн, {e['item']} ирсэн")
            count -= 1
        elif ev == "wait":
            waiting[e["who"]] = e["reason"]
        elif ev == "wake":
            waiting.pop(e["who"], None)

        if ev in ("produce", "consume"):
            if not (0 <= e["count"] <= size):
                errors.append(f"мөр {lineno}: I1 count={e['count']} size={size}")
            filled = sum(x is not None for x in e["buf"])
            if filled != e["count"] or count != e["count"]:
                errors.append(f"мөр {lineno}: I2 count={e['count']} "
                              f"дүүрсэн={filled} тооцоолсон={count}")

    if size is None:
        print("АЛДАА: config event олдсонгүй. ./pc -j ... гэж ажиллуулсан уу?")
        return 2

    print(f"size={size}  produce={stats['produce']}  consume={stats['consume']}  "
          f"wait={stats['wait']}  wake={stats['wake']}")
    print(f"Төгсгөлд буферт: {count}  (дуусах үед хүлээж байсан thread: "
          f"{len(waiting)})")
    if errors:
        print(f"FAIL: {len(errors)} зөрчил")
        for err in errors[:10]:
            print("  ", err)
        return 1
    print("PASS: I1-I4 бүх нөхцөл хангагдсан")
    return 0


if __name__ == "__main__":
    sys.exit(main())