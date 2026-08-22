/*
 * dreamfps_shm.h - the one page of memory the layer and the app share.
 *
 * The layer writes, OSC-DreamChatbox reads, and nothing else is
 * exchanged: no socket, no protocol, no ordering problems. One file per
 * process in /dev/shm, named after the uid and the pid, so several games
 * running at once do not fight over it and a crashed game leaves nothing
 * behind but a stale file the reader can identify by its dead pid.
 *
 * The layout is deliberately plain - fixed-width fields, natural
 * alignment, no bitfields, no pointers - because the other end of it is
 * a Python struct.unpack() format string (see core/fpslayer.py) and the
 * two have to agree byte for byte. The _Static_assert below is what
 * keeps them honest.
 */

/* Copyright (C) 2026 yakuda */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef DREAMFPS_SHM_H
#define DREAMFPS_SHM_H

#include <stdint.h>

#define DREAMFPS_MAGIC   0x53504644u   /* "DFPS" little-endian */
#define DREAMFPS_VERSION 1u
#define DREAMFPS_NAME_LEN 64

/*
 * seq is a seqlock: odd while a write is in progress, even when the
 * contents are consistent. The reader takes seq, reads, takes seq again
 * and retries if the two differ or either was odd. That is enough here -
 * writes happen twice a second and are a few dozen bytes.
 */
struct dreamfps_shm {
    uint32_t magic;                    /*  0 */
    uint32_t version;                  /*  4 */
    uint32_t seq;                      /*  8 */
    uint32_t pid;                      /* 12 */
    float    fps;                      /* 16 */
    float    frametime_ms;             /* 20 */
    double   updated;                  /* 24  CLOCK_REALTIME seconds */
    uint64_t frames;                   /* 32  total presents seen */
    char     name[DREAMFPS_NAME_LEN];  /* 40  /proc/self/comm */
};                                     /* 104 */

#if defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L
_Static_assert(sizeof(struct dreamfps_shm) == 104,
               "dreamfps_shm must stay 104 bytes - core/fpslayer.py "
               "unpacks it with '<IIIIffdQ64s'");
#endif

#endif /* DREAMFPS_SHM_H */
