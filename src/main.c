/* main.c - Producer-Consumer (OSC Project 4, Figure 7.15 / 7.16)
 *
 * Хэрэглээ:
 *   ./pc [-j] <sleep_sec> <producers> <consumers> [buffer_size] [prod_ms] [cons_ms]
 *
 *   -j          : JSON горим - үйлдэл бүрийг JSON мөрөөр гаргана (UI-д)
 *
 *   sleep_sec   : main хэдэн секунд унтаад програмыг дуусгах   (1..3600)
 *   producers   : producer thread-ийн тоо                     (1..32)
 *   consumers   : consumer thread-ийн тоо                     (1..32)
 *   buffer_size : буферийн хэмжээ, анхдагч 5                  (1..64)
 *   prod_ms     : producer-ийн хамгийн их sleep (мс), анхдагч 1000 (0..10000)
 *   cons_ms     : consumer-ийн хамгийн их sleep (мс), анхдагч 1000 (0..10000)
 *
 * JSON горимд stdin-ээс мөр тутам команд уншиж, хурдыг ажиллаж байхад нь өөрчилнө:
 *   prod_ms <N>     producer-ийн хурд
 *   cons_ms <N>     consumer-ийн хурд
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include <pthread.h>
#include <stdatomic.h>
#include "buffer.h"

#define MAX_THREADS 32

static int json = 0;
/* control thread өөрчилж, producer/consumer уншдаг тул atomic */
static atomic_int prod_ms = 1000;
static atomic_int cons_ms = 1000;

static atomic_long total_produced = 0;
static atomic_long total_consumed = 0;

/* --- Туслах функцууд ------------------------------------------------ */

/* Тэмдэгт мөрийг бүхэл тоо болгож, [lo, hi] мужид байгааг шалгана. */
static int parse_int(const char *s, const char *name, int lo, int hi, int *out)
{
    char *end;
    errno = 0;
    long v = strtol(s, &end, 10);
    if (errno != 0 || end == s || *end != '\0') {
        fprintf(stderr, "Алдаа: %s = \"%s\" бүхэл тоо биш байна.\n", name, s);
        return -1;
    }
    if (v < lo || v > hi) {
        fprintf(stderr, "Алдаа: %s = %ld, зөвшөөрөгдөх муж [%d..%d].\n",
                name, v, lo, hi);
        return -1;
    }
    *out = (int)v;
    return 0;
}

/* 0..max_ms миллисекунд санамсаргүй унтах */
static void random_sleep(int max_ms, unsigned int *seed)
{
    if (max_ms <= 0) return;
    int ms = rand_r(seed) % (max_ms + 1);
    struct timespec ts = { ms / 1000, (ms % 1000) * 1000000L };
    nanosleep(&ts, NULL);
}

static void usage(const char *prog)
{
    const char *slash = strrchr(prog, '/');   /* бүтэн замыг (хэрэглэгчийн нэр) нуух */
    if (slash) prog = slash + 1;
    fprintf(stderr,
        "Хэрэглээ: %s [-j] <sleep_sec> <producers> <consumers> "
        "[buffer_size] [prod_ms] [cons_ms]\n"
        "Жишээ:    %s 10 2 3\n"
        "          %s 10 2 3 5 500 1500\n", prog, prog, prog);
}

/* --- Thread-үүд (Figure 7.16) --------------------------------------- */

void *producer(void *param)
{
    int id = *(int *)param;
    char name[8];
    snprintf(name, sizeof name, "P%d", id);
    buffer_set_thread_name(name);
    unsigned int seed = (unsigned int)time(NULL) ^ (id * 7919u);
    buffer_item item;

    while (1) {
        random_sleep(prod_ms, &seed);       /* санамсаргүй унтах */
        item = rand_r(&seed);               /* санамсаргүй тоо   */
        if (insert_item(item))
            fprintf(stderr, "producer %d: insert алдаа\n", id);
        else {
            atomic_fetch_add(&total_produced, 1);
            if (!json) printf("producer %d produced %d\n", id, item);
        }
    }
    return NULL;
}

void *consumer(void *param)
{
    int id = *(int *)param;
    char name[8];
    snprintf(name, sizeof name, "C%d", id);
    buffer_set_thread_name(name);
    unsigned int seed = (unsigned int)time(NULL) ^ (id * 104729u);
    buffer_item item;

    while (1) {
        random_sleep(cons_ms, &seed);
        if (remove_item(&item))
            fprintf(stderr, "consumer %d: remove алдаа\n", id);
        else {
            atomic_fetch_add(&total_consumed, 1);
            if (!json) printf("consumer %d consumed %d\n", id, item);
        }
    }
    return NULL;
}

/* --- Алхам 5: UI-аас ирэх команд унших thread ----------------------- */

void *control(void *param)
{
    (void)param;
    char line[128], cmd[32];
    int v;
    while (fgets(line, sizeof line, stdin) != NULL) {
        int ok = sscanf(line, "%31s %d", cmd, &v) == 2 && v >= 0 && v <= 10000;
        flockfile(stdout);
        if (ok && strcmp(cmd, "prod_ms") == 0)
            atomic_store(&prod_ms, v);
        else if (ok && strcmp(cmd, "cons_ms") == 0)
            atomic_store(&cons_ms, v);
        else
            ok = 0;
        if (ok)
            printf("{\"t\":%ld,\"ev\":\"speed\",\"prod_ms\":%d,\"cons_ms\":%d}\n",
                   buffer_now_ms(), atomic_load(&prod_ms), atomic_load(&cons_ms));
        else
            printf("{\"t\":%ld,\"ev\":\"error\",\"msg\":\"буруу команд\"}\n",
                   buffer_now_ms());
        funlockfile(stdout);
    }
    return NULL;   /* stdin хаагдсан - зүгээр л зогсоно */
}

/* --- main (Figure 7.15) --------------------------------------------- */

int main(int argc, char *argv[])
{
    int sleep_sec, n_prod, n_cons, buf_size = BUFFER_SIZE;
    int p_ms = 1000, c_ms = 1000;

    /* 1. Командын мөрийн аргумент авах, шалгах */
    if (argc > 1 && strcmp(argv[1], "-j") == 0) {   /* сонголтот -j */
        json = 1;
        argv++;            /* -j-г алгасаж, үлдсэнийг хуучнаар унших */
        argc--;
    }
    if (argc < 4 || argc > 7) {
        usage(argv[0]);
        return 1;
    }
    if (parse_int(argv[1], "sleep_sec",   1, 3600, &sleep_sec) ||
        parse_int(argv[2], "producers",   1, MAX_THREADS, &n_prod) ||
        parse_int(argv[3], "consumers",   1, MAX_THREADS, &n_cons) ||
        (argc > 4 && parse_int(argv[4], "buffer_size", 1, MAX_BUFFER_SIZE, &buf_size)) ||
        (argc > 5 && parse_int(argv[5], "prod_ms", 0, 10000, &p_ms)) ||
        (argc > 6 && parse_int(argv[6], "cons_ms", 0, 10000, &c_ms))) {
        usage(argv[0]);
        return 1;
    }
    atomic_store(&prod_ms, p_ms);
    atomic_store(&cons_ms, c_ms);

    setvbuf(stdout, NULL, _IOLBF, 0);   /* мөр бүрийг шууд гаргах */
    buffer_set_json(json);
    if (json)
        printf("{\"t\":0,\"ev\":\"config\",\"sleep\":%d,\"producers\":%d,"
               "\"consumers\":%d,\"size\":%d,\"prod_ms\":%d,\"cons_ms\":%d}\n",
               sleep_sec, n_prod, n_cons, buf_size, p_ms, c_ms);
    else
    printf("Тохиргоо: sleep=%ds producers=%d consumers=%d buffer=%d "
           "prod_ms=%d cons_ms=%d\n",
           sleep_sec, n_prod, n_cons, buf_size, p_ms, c_ms);

    /* 2. Буфер эхлүүлэх */
    if (buffer_init(buf_size) != 0) {
        fprintf(stderr, "Алдаа: буфер эхлүүлж чадсангүй.\n");
        return 1;
    }

    /* 3, 4. Producer, consumer thread үүсгэх */
    pthread_t tid[2 * MAX_THREADS];
    int ids[2 * MAX_THREADS];
    for (int i = 0; i < n_prod; i++) {
        ids[i] = i + 1;
        if (pthread_create(&tid[i], NULL, producer, &ids[i]) != 0) {
            fprintf(stderr, "Алдаа: producer %d үүсгэж чадсангүй.\n", i + 1);
            return 1;
        }
    }
    for (int i = 0; i < n_cons; i++) {
        int k = n_prod + i;
        ids[k] = i + 1;
        if (pthread_create(&tid[k], NULL, consumer, &ids[k]) != 0) {
            fprintf(stderr, "Алдаа: consumer %d үүсгэж чадсангүй.\n", i + 1);
            return 1;
        }
    }

    /* UI-аас команд хүлээн авах thread (зөвхөн JSON горимд) */
    if (json) {
        pthread_t ctl;
        if (pthread_create(&ctl, NULL, control, NULL) == 0)
            pthread_detach(ctl);
    }

    /* 5. Унтах */
    sleep(sleep_sec);

    /* 6. Дуусгах
     * stdout-ийг түгжиж, бусад thread хагас мөр бичих боломжгүй болгоно.
     * exit() нь мөн энэ thread-ээс flush хийх тул түгжээ саад болохгүй. */
    flockfile(stdout);
    long p = atomic_load(&total_produced);
    long c = atomic_load(&total_consumed);
    if (json)
        printf("{\"t\":%ld,\"ev\":\"end\",\"produced\":%ld,\"consumed\":%ld}\n",
               buffer_now_ms(), p, c);
    else
    printf("Дүн: produced=%ld consumed=%ld buffer-д үлдсэн~%ld\n", p, c, p - c);
    /* exit() биш _exit(): exit() нь stdin-ийг ч flush хийх гэж оролддог,
     * гэтэл control thread fgets(stdin) дотор түүний түгжээг барьж байгаа тул
     * програм ГАЦНА. Тиймээс stdout-оо өөрсдөө flush хийгээд шууд гарна. */
    fflush(stdout);
    _exit(0);  /* бүх thread хамт дуусна */
}
