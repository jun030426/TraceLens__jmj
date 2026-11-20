/* Injected with `gcc -include` by the trace runner (never shown to students).
   Unbuffered stdout lets the tracer attribute each printf to the line that produced it. */
#include <stdio.h>
#include <stdlib.h>

__attribute__((constructor)) static void lerny_trace_io(void) {
    const char *out = getenv("LERNY_STDOUT");
    if (out) freopen(out, "w", stdout);
    freopen("/dev/null", "r", stdin);
    setvbuf(stdout, NULL, _IONBF, 0);
}
