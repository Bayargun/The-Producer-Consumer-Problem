#include <stdio.h>
#include <pthread.h>
#include "../src/buffer.h"

#define N 10000

static void *prod(void *p) {
    (void)p;
    for (int i = 1; i <= N; i++) insert_item(i);
    return NULL;
}

static void *cons(void *p) {
    int *errors = p;
    buffer_item x;
    for (int i = 1; i <= N; i++) {
        remove_item(&x);
        if (x != i) (*errors)++;   
    }
    return NULL;
}

int main(void) {
    printf("init(0)  -> %d (хүлээгдэх: -1)\n", buffer_init(0));
    printf("init(65) -> %d (хүлээгдэх: -1)\n", buffer_init(65));

    int sizes[] = {1, 5, 64};
    for (int k = 0; k < 3; k++) {
        int errors = 0;
        buffer_init(sizes[k]);
        pthread_t p, c;
        pthread_create(&p, NULL, prod, NULL);
        pthread_create(&c, NULL, cons, &errors);
        pthread_join(p, NULL);
        pthread_join(c, NULL);
        buffer_destroy();
        printf("size=%-2d  %d item, алдаа=%d  %s\n",
               sizes[k], N, errors, errors ? "FAIL" : "PASS");
    }
    return 0;
}