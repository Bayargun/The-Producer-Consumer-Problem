#ifndef BUFFER_H
#define BUFFER_H

typedef int buffer_item;

#define BUFFER_SIZE     5    
#define MAX_BUFFER_SIZE 64   

int  buffer_init(int size);

void buffer_destroy(void);

int insert_item(buffer_item item);
int remove_item(buffer_item *item);

void buffer_set_json(int enabled);
void buffer_set_thread_name(const char *name);
long buffer_now_ms(void);

#endif