int main() {
    int sum = 0;
    // Bounded for loop with 4 iterations: unrolled under -O2
    for (int i = 0; i < 4; i++) {
        sum = sum + i;
    }
    return sum;
}
