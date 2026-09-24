// Standalone simulator; also used by containerized batch jobs.
#include "../src/runner.h"

int main(int argc, char **argv) { return feynman::main_entry(argc, argv); }
