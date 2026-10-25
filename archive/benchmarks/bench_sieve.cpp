#include <iostream>

int main() {
    int count = 0;
    int is_prime[1000];
    for (int i = 0; i < 1000; i++) {
        is_prime[i] = 1;
    }
    is_prime[0] = 0;
    is_prime[1] = 0;
    for (int p = 2; p * p < 1000; p++) {
        if (is_prime[p] == 1) {
            for (int i = p * p; i < 1000; i += p) {
                is_prime[i] = 0;
            }
        }
    }
    for (int i = 0; i < 1000; i++) {
        if (is_prime[i] == 1) {
            count++;
        }
    }
    std::cout << "Primes count = " << count << std::endl;
    return 0;
}
