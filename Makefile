# Producer-Consumer (OSC Project 4) - Makefile
#   make          C програмыг хөрвүүлнэ (./pc)
#   make test     бүх туршилт (unit + tests/cases.csv) → tests/results.md
#   make ui       Tkinter UI-г ажиллуулна
#   make run      номын жишээ: ./pc 10 2 3
#   make clean    хөрвүүлсэн файлуудыг устгана

CC      = gcc
CFLAGS  ?= -Wall -Wextra -O2
LDFLAGS += -pthread
PYTHON  ?= python3

SRC = src/buffer.c src/main.c
HDR = src/buffer.h

.PHONY: all test unit ui run clean

all: pc

pc: $(SRC) $(HDR)
	$(CC) $(CFLAGS) $(SRC) -o $@ $(LDFLAGS)

tests/test_buffer: src/buffer.c tests/test_buffer.c $(HDR)
	$(CC) $(CFLAGS) src/buffer.c tests/test_buffer.c -o $@ $(LDFLAGS)

unit: tests/test_buffer
	./tests/test_buffer

test: pc
	$(PYTHON) tests/run_tests.py

ui: pc
	$(PYTHON) src/gui.py

run: pc
	./pc 10 2 3

clean:
	rm -f pc tests/test_buffer
	rm -rf src/__pycache__ tests/__pycache__
