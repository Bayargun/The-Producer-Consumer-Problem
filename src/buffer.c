#include <stdio.h>
#include <time.h>
#include <pthread.h>
#include <semaphore.h>
#include "buffer.h"

static buffer_item buffer[MAX_BUFFER_SIZE];
static int size;          
static int in  = 0;       
static int out = 0;       
static int count = 0;     

static sem_t empty;       
static sem_t full;        
static pthread_mutex_t mutex;

static int json = 0;
static struct timespec t0;
static __thread const char *tname = "main";   


void buffer_set_json(int enabled)            { json = enabled; }
void buffer_set_thread_name(const char *n)   { tname = n; }

long buffer_now_ms(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (t.tv_sec - t0.tv_sec) * 1000L + (t.tv_nsec - t0.tv_nsec) / 1000000L;
}

static void emit_state(const char *ev, buffer_item item, int slot)
{
    flockfile(stdout);   /* бүх мөрийг нэг дор бичих - бусад thread хүлээнэ */
    printf("{\"t\":%ld,\"ev\":\"%s\",\"who\":\"%s\",\"item\":%d,\"slot\":%d,"
           "\"count\":%d,\"in\":%d,\"out\":%d,\"buf\":[",
           buffer_now_ms(), ev, tname, item, slot, count, in, out);
    for (int i = 0; i < size; i++) {
        /* i нүд дүүрсэн эсэх: out-оос эхлээд count нүд дүүрсэн */
        int filled = ((i - out + size) % size) < count;
        if (filled) printf("%d", buffer[i]);
        else        printf("null");
        if (i < size - 1) putchar(',');
    }
    printf("]}\n");
    funlockfile(stdout);
}

static void emit_simple(const char *ev, const char *reason)
{
    flockfile(stdout);
    printf("{\"t\":%ld,\"ev\":\"%s\",\"who\":\"%s\",\"reason\":\"%s\"}\n",
           buffer_now_ms(), ev, tname, reason);
    funlockfile(stdout);
}

static int sem_wait_traced(sem_t *s, const char *reason)
{
    if (sem_trywait(s) == 0)          
        return 0;
    if (json) emit_simple("wait", reason);
    if (sem_wait(s) != 0)
        return -1;
    if (json) emit_simple("wake", reason);
    return 0;
}


int buffer_init(int n)
{
    if (n < 1 || n > MAX_BUFFER_SIZE)
        return -1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    size = n;
    in = out = count = 0;
    if (pthread_mutex_init(&mutex, NULL) != 0) return -1;
    if (sem_init(&empty, 0, n) != 0) return -1;   
    if (sem_init(&full,  0, 0) != 0) return -1;   
    return 0;
}

void buffer_destroy(void)
{
    sem_destroy(&empty);
    sem_destroy(&full);
    pthread_mutex_destroy(&mutex);
}

int insert_item(buffer_item item)
{
    if (sem_wait_traced(&empty, "full") != 0)  
        return -1;
    pthread_mutex_lock(&mutex);                

    int slot = in;
    buffer[in] = item;
    in = (in + 1) % size;
    count++;
    if (json) emit_state("produce", item, slot);

    pthread_mutex_unlock(&mutex);
    sem_post(&full);                          
    return 0;
}

int remove_item(buffer_item *item)
{
    if (sem_wait_traced(&full, "empty") != 0)  
        return -1;
    pthread_mutex_lock(&mutex);

    int slot = out;
    *item = buffer[out];
    out = (out + 1) % size;
    count--;
    if (json) emit_state("consume", *item, slot);

    pthread_mutex_unlock(&mutex);
    sem_post(&empty);                          
    return 0;
}