#include "test_header.h"
#define MULTIPLIER 5

int main() {
    int val = 4;
    int sq = square(val);
    int result = sq * MULTIPLIER;
    return result;
}
